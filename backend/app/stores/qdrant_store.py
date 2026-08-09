"""Qdrant 子块存储，密集向量 + BM25 稀疏向量混合检索"""

from typing import List
import uuid as _uuid

import structlog
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import FastEmbedSparse, QdrantVectorStore, RetrievalMode
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import Settings

logger = structlog.get_logger()

_CHILD_NS = _uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


class QdrantStore:
    """child_chunks 集合：密集向量 (bge-large-zh-v1.5, 1024d, COSINE) + BM25 稀疏向量"""

    COLLECTION_NAME = "child_chunks"
    SPARSE_VECTOR_NAME = "sparse"
    DENSE_VECTOR_NAME = ""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: QdrantClient | None = None
        self._dense: HuggingFaceEmbeddings | None = None
        self._sparse: FastEmbedSparse | None = None

    def init(self):
        """初始化 Qdrant 客户端和 embedding 模型"""
        storage = self._settings.storage
        if storage.qdrant_url:
            self._client = QdrantClient(url=storage.qdrant_url)
        else:
            self._client = QdrantClient(path=storage.qdrant_path)

        self._dense = HuggingFaceEmbeddings(model_name=self._settings.embedding.dense_model)
        self._sparse = FastEmbedSparse(model_name=self._settings.embedding.sparse_model)

    def close(self):
        if self._client:
            self._client.close()

    @property
    def client(self) -> QdrantClient:
        if not self._client:
            raise RuntimeError("QdrantStore 还没初始化")
        return self._client

    def collection_exists(self) -> bool:
        return self.client.collection_exists(self.COLLECTION_NAME)

    def create_collection(self):
        """如果集合不存在就创建，建密集和稀疏两个向量索引"""
        if self.collection_exists():
            return
        dim = len(self._dense.embed_query("test"))
        self.client.create_collection(
            collection_name=self.COLLECTION_NAME,
            vectors_config=qmodels.VectorParams(
                size=dim, distance=qmodels.Distance.COSINE
            ),
            sparse_vectors_config={
                self.SPARSE_VECTOR_NAME: qmodels.SparseVectorParams()
            },
        )

    def delete_collection(self):
        if self.collection_exists():
            self.client.delete_collection(self.COLLECTION_NAME)

    def as_vector_store(self) -> QdrantVectorStore:
        """返回 LangChain 兼容的混合检索 vector store"""
        return QdrantVectorStore(
            client=self.client,
            collection_name=self.COLLECTION_NAME,
            embedding=self._dense,
            sparse_embedding=self._sparse,
            retrieval_mode=RetrievalMode.HYBRID,
            sparse_vector_name=self.SPARSE_VECTOR_NAME,
        )

    def add_documents(self, docs: List[Document]):
        """批量写入子块，手动计算密集+稀疏向量，用 uuid5 去重"""
        if not docs:
            return

        if not self.collection_exists():
            self.create_collection()

        texts = [doc.page_content for doc in docs]
        metadatas = [doc.metadata for doc in docs]
        ids = [str(_uuid.uuid5(_CHILD_NS, f"{meta.get('doc_id', '')}:{meta.get('parent_id', '')}:{i}"))
               for i, meta in enumerate(metadatas)]

        dense_vectors = self._dense.embed_documents(texts)
        sparse_vectors = self._sparse.embed_documents(texts)

        points = []
        for i, text in enumerate(texts):
            point = qmodels.PointStruct(
                id=ids[i],
                vector={
                    self.DENSE_VECTOR_NAME: [float(x) for x in dense_vectors[i]],
                    self.SPARSE_VECTOR_NAME: qmodels.SparseVector(
                        values=[float(x) for x in sparse_vectors[i].values],
                        indices=[int(x) for x in sparse_vectors[i].indices],
                    ),
                },
                payload={
                    "page_content": text,
                    "metadata": metadatas[i],
                },
            )
            points.append(point)

        batch_size = 64
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            self.client.upsert(
                collection_name=self.COLLECTION_NAME,
                points=batch,
            )

    def delete_by_doc_id(self, doc_id: str) -> int:
        """删除某个文档的所有子块，返回删除数量。失败抛异常，不静默吞错"""
        if not self.collection_exists():
            return 0
        try:
            scroll, _ = self.client.scroll(
                collection_name=self.COLLECTION_NAME,
                scroll_filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(
                        key="metadata.doc_id", match=qmodels.MatchValue(value=doc_id),
                    )]
                ),
                limit=1_000_000,
            )
        except Exception as e:
            logger.exception("qdrant.child.scroll.error", doc_id=doc_id, error=str(e))
            raise RuntimeError(f"统计 Qdrant 子块失败 doc_id={doc_id}: {e}") from e

        if not scroll:
            logger.info("qdrant.child.noop", doc_id=doc_id, reason="no matching points")
            return 0

        try:
            self.client.delete(
                collection_name=self.COLLECTION_NAME,
                points_selector=qmodels.PointIdsList(points=[p.id for p in scroll]),
            )
        except Exception as e:
            logger.exception("qdrant.child.delete.error", doc_id=doc_id, count=len(scroll))
            raise RuntimeError(f"删除 Qdrant 子块失败 doc_id={doc_id} count={len(scroll)}: {e}") from e

        logger.info("qdrant.child.delete.ok", doc_id=doc_id, count=len(scroll))
        return len(scroll)

    def similarity_search(
        self,
        query: str,
        k: int = 5,
        score_threshold: float = 0.7,
    ) -> List[Document]:
        """混合检索快捷方法"""
        store = self.as_vector_store()
        search_kwargs = {"k": k, "score_threshold": score_threshold}
        return store.similarity_search(query, **search_kwargs)

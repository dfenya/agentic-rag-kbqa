"""长期记忆向量库，Qdrant 里的 long_term_memory 集合"""

from typing import List, Optional

from langchain_huggingface import HuggingFaceEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import Settings


class LongTermMemoryStore:
    """长期记忆的向量索引，复用 Qdrant 客户端和 embedding 模型"""

    COLLECTION_NAME = "long_term_memory"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: QdrantClient | None = None
        self._embeddings: HuggingFaceEmbeddings | None = None

    def init(self, client: QdrantClient, embeddings: HuggingFaceEmbeddings):
        self._client = client
        self._embeddings = embeddings

    def _ensure_collection(self):
        if not self._client.collection_exists(self.COLLECTION_NAME):
            dim = len(self._embeddings.embed_query("test"))
            self._client.create_collection(
                collection_name=self.COLLECTION_NAME,
                vectors_config=qmodels.VectorParams(
                    size=dim, distance=qmodels.Distance.COSINE,
                ),
            )

    def upsert(self, memory_id: str, content: str, payload: dict):
        """写入或更新一条记忆的向量"""
        self._ensure_collection()
        vector = self._embeddings.embed_query(content)
        self._client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=[qmodels.PointStruct(
                id=memory_id,
                vector=vector,
                payload={**payload, "content": content},
            )],
        )

    def delete(self, memory_id: str):
        """删除一条记忆向量，集合不存在则跳过"""
        if not self._client.collection_exists(self.COLLECTION_NAME):
            return
        self._client.delete(
            collection_name=self.COLLECTION_NAME,
            points_selector=qmodels.PointIdsList(points=[memory_id]),
        )

    def search(
        self,
        query: str,
        k: int = 5,
        memory_type: Optional[str] = None,
    ) -> List[dict]:
        """语义搜索，返回 [{id, score, payload}, ...]"""
        if not self._client.collection_exists(self.COLLECTION_NAME):
            return []
        vec = self._embeddings.embed_query(query)
        query_filter = None
        if memory_type:
            query_filter = qmodels.Filter(
                must=[qmodels.FieldCondition(
                    key="type", match=qmodels.MatchValue(value=memory_type)
                )]
            )
        results = self._client.query_points(
            collection_name=self.COLLECTION_NAME,
            query=vec,
            limit=k,
            query_filter=query_filter,
        ).points
        return [
            {"id": r.id, "score": r.score, "payload": r.payload}
            for r in results
        ]

    def delete_collection(self):
        if self._client.collection_exists(self.COLLECTION_NAME):
            self._client.delete_collection(self.COLLECTION_NAME)

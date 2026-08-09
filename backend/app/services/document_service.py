"""文档管理服务"""

from pathlib import Path
from typing import Optional

import structlog

from app.stores.sqlite_store import SqliteStore
from app.stores.qdrant_store import QdrantStore
from app.stores.parent_store import ParentStore
from app.domain.models import Document
from app.domain.enums import DocumentStatus

logger = structlog.get_logger()


class DocumentService:
    """文档的增删改查，删除时保证向量和 SQLite 的一致性"""

    def __init__(self, sqlite: SqliteStore, qdrant: QdrantStore, parent: ParentStore):
        self._db = sqlite
        self._qdrant = qdrant
        self._parent = parent

    def list_documents(
        self,
        *,
        kb_id: Optional[str] = None,
        q: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Document], int]:
        return self._db.docs_list(kb_id=kb_id, q=q, page=page, page_size=page_size)

    def delete(self, doc_id: str) -> bool:
        """删文档：先删 Qdrant 子块和父块，最后删 SQLite。
        任一失败抛异常，不留孤儿数据。
        """
        doc = self._db.doc_by_id(doc_id)
        if not doc:
            logger.info("document.delete.not_found", doc_id=doc_id)
            return False

        child_count = self._qdrant.delete_by_doc_id(doc_id)
        parent_count = self._parent.delete_by_doc_id(doc_id)
        ok = self._db.doc_delete(doc_id)
        if not ok:
            logger.error(
                "document.delete.sqlite_failed",
                doc_id=doc_id,
                child_deleted=child_count,
                parent_deleted=parent_count,
            )
            raise RuntimeError(
                f"SQLite 删除文档失败 doc_id={doc_id} "
                f"(child={child_count} parent={parent_count} 已从 Qdrant 清除)"
            )
        logger.info(
            "document.delete.ok",
            doc_id=doc_id,
            filename=doc.filename,
            child_deleted=child_count,
            parent_deleted=parent_count,
        )
        return True

    def retry(self, doc_id: str) -> Optional[Document]:
        """重试处理失败的文档：从已保存的 .md 文件重新分块入库"""
        doc = self._db.doc_by_id(doc_id)
        if not doc or doc.status != DocumentStatus.ERROR.value:
            return None

        import structlog
        from app.ingestion.chunker import DocumentChunker
        from app.ingestion.dedup import compute_file_sha256
        from app.core.config import get_settings

        logger = structlog.get_logger()
        settings = get_settings()
        upload_dir = Path(settings.storage.upload_dir)
        md_path = upload_dir / f"{doc_id}.md"

        if not md_path.exists():
            self._db.doc_update(doc_id, error="Markdown 文件丢失，无法重试")
            return self._db.doc_by_id(doc_id)

        try:
            self._qdrant.delete_by_doc_id(doc_id)
            self._parent.delete_by_doc_id(doc_id)

            chunker = DocumentChunker(
                min_parent_size=settings.rag.min_parent_size,
                max_parent_size=settings.rag.max_parent_size,
                child_chunk_size=settings.rag.child_chunk_size,
                child_chunk_overlap=settings.rag.child_chunk_overlap,
            )

            source_name = Path(doc.filename).with_suffix(".pdf").name if doc.filename.endswith(".pdf") else doc.filename
            sha = doc.sha256
            parent_pairs, child_docs = chunker.chunk_file(
                md_path, doc_id, source_name, sha256=sha,
                kb_id=doc.kb_id,
            )

            self._parent.save_many(parent_pairs)
            self._qdrant.add_documents(child_docs)

            self._db.doc_update(
                doc_id,
                status=DocumentStatus.READY.value,
                parent_count=len(parent_pairs),
                child_count=len(child_docs),
                error=None,
            )
            logger.info("document.retry.success", doc_id=doc_id)
        except Exception as e:
            logger.exception("document.retry.error", doc_id=doc_id)
            self._db.doc_update(doc_id, error=str(e))

        return self._db.doc_by_id(doc_id)

from pathlib import Path
from typing import Optional

import structlog

from app.core.config import Settings
from app.stores.sqlite_store import SqliteStore
from app.stores.qdrant_store import QdrantStore
from app.stores.parent_store import ParentStore
from app.domain.models import Document
from app.domain.enums import DocumentStatus

logger = structlog.get_logger()


class DocumentService:

    def __init__(self, sqlite: SqliteStore, qdrant: QdrantStore, parent: ParentStore, settings: Settings):
        self._db = sqlite
        self._qdrant = qdrant
        self._parent = parent
        self._upload_dir = Path(settings.storage.upload_dir)
        self._md_dir = Path(settings.storage.markdown_dir)
        self._chunks_dir = Path(settings.storage.chunks_dir)

    def list_documents(
        self, user_id: str,
        *,
        kb_id: Optional[str] = None,
        q: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Document], int]:
        if kb_id:
            kb = self._db.kb_by_id(kb_id)
            if not kb or kb.user_id != user_id:
                return [], 0
            return self._db.docs_list(kb_id=kb_id, q=q, page=page, page_size=page_size)
        # 不带 kb_id 时只返回该用户的文档
        return self._db.docs_list_by_user(user_id, q=q, page=page, page_size=page_size)

    def _remove_files(self, doc_id: str, kb_id: str | None = None):
        dirs = [self._upload_dir, self._md_dir, self._chunks_dir]
        if kb_id:
            dirs = [d / kb_id for d in dirs]
        for d in dirs:
            for f in d.glob(f"{doc_id}.*"):
                f.unlink(missing_ok=True)

    def delete(self, user_id: str, doc_id: str) -> bool:
        doc = self._db.doc_by_id(doc_id)
        if not doc:
            return False
        if doc.kb_id:
            kb = self._db.kb_by_id(doc.kb_id)
            if not kb or kb.user_id != user_id:
                return False

        child_count = self._qdrant.delete_by_doc_id(doc_id)
        parent_count = self._parent.delete_by_doc_id(doc_id)
        self._remove_files(doc_id, kb_id=doc.kb_id)

        ok = self._db.doc_delete(doc_id)
        if not ok:
            raise RuntimeError(
                f"SQLite 删除文档失败 doc_id={doc_id} "
                f"(child={child_count} parent={parent_count} 已从 Qdrant 清除)"
            )
        logger.info("document.delete.ok", doc_id=doc_id, filename=doc.filename,
                     child_deleted=child_count, parent_deleted=parent_count)
        return True

    def retry(self, user_id: str, doc_id: str) -> Optional[Document]:
        doc = self._db.doc_by_id(doc_id)
        if not doc or doc.status != DocumentStatus.ERROR.value:
            return None
        if doc.kb_id:
            kb = self._db.kb_by_id(doc.kb_id)
            if not kb or kb.user_id != user_id:
                return None

        from app.ingestion.chunker import DocumentChunker
        from app.core.config import get_settings

        settings = get_settings()
        kb_dir = self._md_dir / doc.kb_id if doc.kb_id else self._md_dir
        md_path = kb_dir / f"{doc_id}.md"
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

            source_name = f"{Path(doc.filename).stem}.pdf" if doc.filename.endswith(".pdf") else doc.filename
            parent_pairs, child_docs = chunker.chunk_file(
                md_path, doc_id, source_name, sha256=doc.sha256,
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

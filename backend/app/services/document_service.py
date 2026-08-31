from pathlib import Path
from typing import Optional

import structlog

from app.core.config import Settings
from app.stores.sqlite_store import SqliteStore
from app.stores.qdrant_store import QdrantStore
from app.stores.parent_store import ParentStore
from app.domain.models import Document
from app.domain.enums import DocumentStatus
from app.core.paths import kb_storage_folder

logger = structlog.get_logger()


class DocumentService:

    def __init__(self, sqlite: SqliteStore, qdrant: QdrantStore, parent: ParentStore, settings: Settings):
        self._db = sqlite
        self._qdrant = qdrant
        self._parent = parent
        self._upload_dir = Path(settings.storage.upload_dir)
        self._md_dir = Path(settings.storage.markdown_dir)
        self._chunks_dir = Path(settings.storage.chunks_dir)
        self._settings = settings

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
        folder = None
        if kb_id:
            kb = self._db.kb_by_id(kb_id)
            folder = kb_storage_folder(kb.name, kb_id) if kb else kb_id
        dirs = [self._upload_dir, self._md_dir, self._chunks_dir]
        if folder:
            dirs = [d / folder for d in dirs]
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
        else:
            # 历史孤儿文档没有可验证的用户归属，不能允许任意登录用户删除。
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

    async def retry(self, user_id: str, doc_id: str) -> Optional[Document]:
        doc = self._db.doc_by_id(doc_id)
        if not doc or doc.status != DocumentStatus.ERROR.value:
            return None
        if doc.kb_id:
            kb = self._db.kb_by_id(doc.kb_id)
            if not kb or kb.user_id != user_id:
                return None
        else:
            return None

        from app.ingestion.pipeline import IngestionPipeline

        pipeline = IngestionPipeline(
            settings=self._settings,
            sqlite=self._db,
            qdrant=self._qdrant,
            parent=self._parent,
            kb_id=doc.kb_id,
        )
        await pipeline.retry_document(doc)
        return self._db.doc_by_id(doc_id)

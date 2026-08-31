from typing import Dict, List

from app.domain.enums import DocumentStatus


class ParentStore:
    """父块存储，底层走 SQLite"""

    def __init__(self, sqlite):
        self._db = sqlite

    def save_many(self, parents: List) -> None:
        if parents:
            self._db.parent_save_many(parents)

    def load_content_many(self, parent_ids: List[str], kb_id: str | None = None) -> List[Dict]:
        return self._db.parent_load_many(parent_ids, kb_id=kb_id)

    def delete_by_doc_id(self, doc_id: str) -> int:
        return self._db.parent_delete_by_doc_id(doc_id)

    def is_document_published(self, doc_id: str) -> bool:
        doc = self._db.doc_by_id(doc_id)
        return bool(doc and doc.status == DocumentStatus.READY.value)

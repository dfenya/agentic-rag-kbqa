from typing import Dict, List


class ParentStore:
    """父块存储，底层走 SQLite"""

    def __init__(self, sqlite):
        self._db = sqlite

    def save_many(self, parents: List) -> None:
        if parents:
            self._db.parent_save_many(parents)

    def load_content_many(self, parent_ids: List[str]) -> List[Dict]:
        return self._db.parent_load_many(parent_ids)

    def delete_by_doc_id(self, doc_id: str) -> int:
        return self._db.parent_delete_by_doc_id(doc_id)

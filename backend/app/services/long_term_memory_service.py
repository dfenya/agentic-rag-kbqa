import json
from typing import Optional
import structlog

from app.stores.sqlite_store import SqliteStore
from app.stores.long_term_memory_store import LongTermMemoryStore
from app.domain.models import LongTermMemory

logger = structlog.get_logger()


class LongTermMemoryService:

    def __init__(self, sqlite: SqliteStore, long_term_memory_store: LongTermMemoryStore):
        self._db = sqlite
        self._store = long_term_memory_store

    def list_memories(self, user_id: str, *, mem_type: Optional[str] = None, q: Optional[str] = None) -> list[LongTermMemory]:
        return self._db.mem_list(user_id, mem_type=mem_type, q=q)

    def update(self, user_id: str, mem_id: str, **kwargs) -> Optional[LongTermMemory]:
        mem = self._db.mem_by_id(mem_id)
        if not mem or mem.user_id != user_id:
            return None
        mem = self._db.mem_update(mem_id, **kwargs)
        if mem and "content" in kwargs:
            try:
                self._store.upsert(mem.id, mem.content, {
                    "type": mem.type,
                    "keywords": json.loads(mem.keywords_json or "[]"),
                    "importance": mem.importance,
                })
            except Exception as e:
                logger.warning("long_term_memory.service.update_vector.fail", mem_id=mem_id, error=str(e))
        return mem

    def delete(self, user_id: str, mem_id: str) -> bool:
        mem = self._db.mem_by_id(mem_id)
        if not mem or mem.user_id != user_id:
            return False
        ok = self._db.mem_delete(mem_id)
        try:
            self._store.delete(mem_id)
        except Exception as e:
            logger.warning("long_term_memory.service.delete_vector.fail", mem_id=mem_id, error=str(e))
        return ok

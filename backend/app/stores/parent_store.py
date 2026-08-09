"""父块存储，只存 Qdrant payload 不建向量索引"""

import re
import uuid as _uuid
from typing import Dict, List

import structlog
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

logger = structlog.get_logger()

_PARENT_NS = _uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _to_uuid(s: str) -> str:
    """把语义 ID（如 doc_id:p0）转成确定性 UUID"""
    return str(_uuid.uuid5(_PARENT_NS, s))


class ParentStore:
    """父块的 Qdrant payload 存储，不建向量索引，只存文本"""

    COLLECTION_NAME = "parent_chunks"

    def __init__(self, client: QdrantClient):
        self._client = client

    def _ensure_collection(self):
        if not self._client.collection_exists(self.COLLECTION_NAME):
            self._client.create_collection(collection_name=self.COLLECTION_NAME)

    def collection_exists(self) -> bool:
        return self._client.collection_exists(self.COLLECTION_NAME)

    def save(self, parent_id: str, content: str, metadata: Dict) -> None:
        self._ensure_collection()
        clean_id = parent_id.replace(".json", "").strip()
        self._client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=[qmodels.PointStruct(
                id=_to_uuid(clean_id),
                vector={},
                payload={"content": content, "metadata": metadata, "_parent_id": clean_id},
            )],
        )

    def save_many(self, parents: List) -> None:
        """批量写入 (parent_id, Document) 元组列表"""
        if not parents:
            return
        self._ensure_collection()
        points = []
        for parent_id, doc in parents:
            clean_id = parent_id.replace(".json", "").strip()
            points.append(qmodels.PointStruct(
                id=_to_uuid(clean_id),
                vector={},
                payload={"content": doc.page_content, "metadata": doc.metadata, "_parent_id": clean_id},
            ))
        self._client.upsert(collection_name=self.COLLECTION_NAME, points=points)

    def load_content(self, parent_id: str) -> Dict:
        clean_id = parent_id.replace(".json", "").strip()
        records = self._client.retrieve(
            collection_name=self.COLLECTION_NAME, ids=[_to_uuid(clean_id)], with_payload=True,
        )
        if not records:
            raise ValueError(f"Parent chunk '{clean_id}' 不存在")
        p = records[0].payload or {}
        return {"content": p.get("content", ""), "parent_id": clean_id, "metadata": p.get("metadata", {})}

    @staticmethod
    def _get_sort_key(id_str: str) -> int:
        """按 parent_N 里的 N 排序"""
        match = re.search(r'_parent_(\d+)$', id_str)
        return int(match.group(1)) if match else 0

    def load_content_many(self, parent_ids: List[str]) -> List[Dict]:
        """批量加载父块，按编号排序返回"""
        if not parent_ids:
            return []
        clean_ids = list(set(pid.replace(".json", "").strip() for pid in parent_ids))
        uuid_ids = [_to_uuid(pid) for pid in clean_ids]
        records = self._client.retrieve(
            collection_name=self.COLLECTION_NAME, ids=uuid_ids, with_payload=True,
        )
        by_parent_id = {}
        for r in records:
            if r.payload:
                pid = r.payload.get("_parent_id", "")
                by_parent_id[pid] = r.payload
        results = []
        for pid in sorted(clean_ids, key=self._get_sort_key):
            p = by_parent_id.get(pid)
            if p:
                results.append({"content": p.get("content", ""), "parent_id": pid, "metadata": p.get("metadata", {})})
        return results

    def delete_by_doc_id(self, doc_id: str) -> int:
        """删除某个文档的所有父块，失败抛异常"""
        if not self.collection_exists():
            return 0
        try:
            points = self._client.scroll(
                collection_name=self.COLLECTION_NAME,
                scroll_filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(
                        key="metadata.doc_id", match=qmodels.MatchValue(value=doc_id),
                    )]
                ),
                limit=1_000_000,
            )[0]
        except Exception as e:
            logger.exception("qdrant.parent.scroll.error", doc_id=doc_id, error=str(e))
            raise RuntimeError(f"统计 Qdrant 父块失败 doc_id={doc_id}: {e}") from e

        if not points:
            logger.info("qdrant.parent.noop", doc_id=doc_id, reason="no matching points")
            return 0

        try:
            self._client.delete(
                collection_name=self.COLLECTION_NAME,
                points_selector=qmodels.PointIdsList(points=[p.id for p in points]),
            )
        except Exception as e:
            logger.exception("qdrant.parent.delete.error", doc_id=doc_id, count=len(points))
            raise RuntimeError(f"删除 Qdrant 父块失败 doc_id={doc_id} count={len(points)}: {e}") from e

        logger.info("qdrant.parent.delete.ok", doc_id=doc_id, count=len(points))
        return len(points)

    def clear(self):
        """清空整个父块集合"""
        if self.collection_exists():
            self._client.delete_collection(self.COLLECTION_NAME)

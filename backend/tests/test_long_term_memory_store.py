import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.stores.long_term_memory_store import LongTermMemoryStore
from app.stores.sqlite_store import SqliteStore


class _FakeEmbeddings:
    def embed_query(self, _query):
        return [0.1, 0.2, 0.3]


class _FakeQdrantClient:
    def __init__(self):
        self.query_kwargs = None
        self.payload_kwargs = None

    def collection_exists(self, _collection_name):
        return True

    def query_points(self, **kwargs):
        self.query_kwargs = kwargs
        return SimpleNamespace(points=[])

    def set_payload(self, **kwargs):
        self.payload_kwargs = kwargs


class LongTermMemoryVectorStoreTests(unittest.TestCase):
    def setUp(self):
        self.client = _FakeQdrantClient()
        self.store = LongTermMemoryStore.__new__(LongTermMemoryStore)
        self.store._client = self.client
        self.store._embeddings = _FakeEmbeddings()

    def test_search_filters_before_vector_recall(self):
        self.store.search(
            "Python后端",
            memory_type="user_preference",
            user_id="user-1",
            conversation_id="conv-1",
        )

        query_filter = self.client.query_kwargs["query_filter"]
        conditions = {
            condition.key: condition.match.value
            for condition in query_filter.must
        }
        self.assertEqual(conditions, {
            "type": "user_preference",
            "user_id": "user-1",
            "conversation_id": "conv-1",
        })

    def test_scope_migration_only_updates_payload(self):
        self.store.update_scope_payload(
            "memory-1",
            user_id="user-1",
            conversation_id="conv-1",
        )

        self.assertEqual(self.client.payload_kwargs["points"], ["memory-1"])
        self.assertEqual(self.client.payload_kwargs["payload"], {
            "user_id": "user-1",
            "conversation_id": "conv-1",
        })

    def test_cross_session_recall_only_shares_preferences_and_faq(self):
        self.store.search(
            "回答简短一些",
            user_id="user-1",
            conversation_id="conv-2",
            include_user_wide=True,
        )

        query_filter = self.client.query_kwargs["query_filter"]
        must = {condition.key: condition.match.value for condition in query_filter.must}
        should = {(condition.key, condition.match.value) for condition in query_filter.should}
        self.assertEqual(must, {"user_id": "user-1"})
        self.assertEqual(should, {
            ("conversation_id", "conv-2"),
            ("type", "user_preference"),
            ("type", "faq_pattern"),
        })


class LongTermMemoryEvictionTests(unittest.TestCase):
    def test_eviction_returns_deleted_ids_and_keeps_most_accessed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteStore(str(Path(temp_dir) / "test.db"))
            store.create_all()
            user = store.user_create(
                username="13800000000",
                password_hash="not-used-in-this-test",
            )
            least = store.mem_insert(
                user.id,
                type="user_preference",
                content="低频",
                access_count=1,
            )
            store.mem_insert(
                user.id,
                type="user_preference",
                content="高频",
                access_count=5,
            )
            store.mem_insert(
                user.id,
                type="user_preference",
                content="中频",
                access_count=2,
            )

            deleted_ids = store.mem_delete_least_accessed(user.id, keep=2)

            self.assertEqual(deleted_ids, [least.id])
            self.assertEqual(store.mem_count(user.id), 2)
            store.engine.dispose()


if __name__ == "__main__":
    unittest.main()

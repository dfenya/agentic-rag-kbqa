import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.config import Settings
from app.ingestion.pipeline import IngestionPipeline
from app.stores.parent_store import ParentStore
from app.stores.sqlite_store import SqliteStore


class _FakeQdrant:
    def __init__(self, fail_add=False):
        self.fail_add = fail_add
        self.documents = []
        self.publish_status = None

    def add_documents(self, documents):
        if self.fail_add:
            raise RuntimeError("simulated vector failure")
        self.documents = list(documents)

    def validate_document(self, doc_id, expected_child_count, expected_parent_ids):
        actual = [d for d in self.documents if d.metadata.get("doc_id") == doc_id]
        if len(actual) != expected_child_count:
            raise ValueError("child count mismatch")
        if not {d.metadata.get("parent_id") for d in actual}.issubset(expected_parent_ids):
            raise ValueError("parent reference mismatch")

    def set_publish_status(self, _doc_id, status):
        self.publish_status = status

    def delete_by_doc_id(self, doc_id):
        before = len(self.documents)
        self.documents = [d for d in self.documents if d.metadata.get("doc_id") != doc_id]
        return before - len(self.documents)


class IngestionCheckpointTests(unittest.TestCase):
    def _create_fixture(self, temp_dir, *, fail_add=False):
        settings = Settings()
        settings.storage.sqlite_path = str(Path(temp_dir) / "app.db")
        settings.storage.upload_dir = str(Path(temp_dir) / "uploads")
        settings.storage.markdown_dir = str(Path(temp_dir) / "markdown")
        settings.storage.chunks_dir = str(Path(temp_dir) / "chunks")
        settings.rag.min_parent_size = 10
        settings.rag.max_parent_size = 100
        settings.rag.child_chunk_size = 30
        settings.rag.child_chunk_overlap = 5
        sqlite = SqliteStore(settings.storage.sqlite_path)
        sqlite.create_all()
        user = sqlite.user_create(username="13800000000", password_hash="test")
        kb = sqlite.kb_create("测试库", user.id)
        qdrant = _FakeQdrant(fail_add=fail_add)
        pipeline = IngestionPipeline(settings, sqlite, qdrant, ParentStore(sqlite), kb.id)
        source = Path(temp_dir) / "source.md"
        source.write_text("# 标题\n这是用于治理 checkpoint 测试的正文。" * 8, encoding="utf-8")
        return sqlite, qdrant, pipeline, source

    def test_successful_ingestion_persists_all_governance_checkpoints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sqlite, qdrant, pipeline, source = self._create_fixture(temp_dir)
            result = asyncio.run(pipeline.process_file(str(source), "测试.md"))

            job = sqlite.governance_job_by_document(result["doc_id"])
            stages = [c.stage for c in sqlite.governance_checkpoints(job.id)]
            self.assertEqual(job.status, "published")
            self.assertEqual(job.last_completed_stage, "published")
            self.assertEqual(stages, [
                "received", "deduped", "parsed", "chunked",
                "parents_staged", "vectors_staged", "validated", "published",
            ])
            self.assertEqual(qdrant.publish_status, "active")
            sqlite.engine.dispose()

    def test_failed_vector_write_rolls_back_and_retry_reuses_chunks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sqlite, qdrant, pipeline, source = self._create_fixture(temp_dir, fail_add=True)
            with patch("app.ingestion.pipeline.logger", Mock()):
                failed = asyncio.run(pipeline.process_file(str(source), "测试.md"))
            doc = sqlite.doc_by_id(failed["doc_id"])
            job = sqlite.governance_job_by_document(doc.id)

            self.assertEqual(doc.status, "error")
            self.assertEqual(job.status, "failed")
            self.assertEqual(sqlite.parent_count_by_doc_id(doc.id), 0)

            qdrant.fail_add = False
            recovered = asyncio.run(pipeline.retry_document(doc))
            refreshed_job = sqlite.governance_job_by_document(doc.id)

            self.assertEqual(recovered["status"], "ready")
            self.assertEqual(refreshed_job.status, "published")
            self.assertEqual(refreshed_job.attempt, 2)
            self.assertEqual(qdrant.publish_status, "active")
            sqlite.engine.dispose()


if __name__ == "__main__":
    unittest.main()

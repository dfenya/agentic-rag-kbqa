"""文档摄入管线：去重 → PDF 提取 → 分块 → 写入 Qdrant"""

import structlog
from pathlib import Path
from typing import Callable, Optional

from app.core.config import Settings
from app.stores.sqlite_store import SqliteStore
from app.stores.qdrant_store import QdrantStore
from app.stores.parent_store import ParentStore
from app.ingestion.dedup import check_duplicate, register_document, compute_sha256
from app.ingestion.extractor import pdf_to_markdown
from app.ingestion.chunker import DocumentChunker
from app.domain.enums import DocumentStatus

logger = structlog.get_logger()

ProgressCallback = Callable[[str, float, str, Optional[dict]], None]


class IngestionPipeline:
    """编排单个文件从上传到入库的完整流程"""

    def __init__(self, settings: Settings, sqlite: SqliteStore, qdrant: QdrantStore, parent: ParentStore, kb_id: str | None = None):
        self._settings = settings
        self._sqlite = sqlite
        self._qdrant = qdrant
        self._parent = parent
        self._kb_id = kb_id
        self._chunker = DocumentChunker(
            min_parent_size=settings.rag.min_parent_size,
            max_parent_size=settings.rag.max_parent_size,
            child_chunk_size=settings.rag.child_chunk_size,
            child_chunk_overlap=settings.rag.child_chunk_overlap,
        )
        self._upload_dir = Path(settings.storage.upload_dir)

    async def process_file(
        self,
        filepath: str,
        filename: str,
        *,
        progress: Optional[ProgressCallback] = None,
        llm=None,
    ) -> dict:
        """处理一个上传文件，返回 {doc_id, status, ...}"""
        emit = progress or (lambda p, pc, m, e: None)

        # 阶段 1: 读文件 + 去重
        emit("dedup", 0.0, f"正在检查重复: {filename}")
        raw_bytes = Path(filepath).read_bytes()
        is_dup, existing = check_duplicate(self._sqlite, raw_bytes, filename)
        if is_dup:
            logger.info("ingestion.duplicate", filename=filename, existing=existing.id)
            emit("dedup", 1.0, f"文件重复，已跳过: {filename}", {"duplicate_of": existing.id})
            return {
                "doc_id": None, "filename": filename,
                "status": DocumentStatus.DUPLICATE.value, "duplicate_of": existing.id,
            }

        doc = register_document(self._sqlite, filename, raw_bytes, kb_id=self._kb_id)
        doc_id = doc.id
        emit("dedup", 1.0, "去重通过")

        try:
            # 阶段 2: PDF → Markdown
            emit("extract", 0.0, f"正在提取文本: {filename}")
            suffix = Path(filename).suffix.lower()

            if suffix == ".md":
                md_path = self._upload_dir / f"{doc_id}.md"
                md_path.write_bytes(raw_bytes)
            else:
                pdf_tmp = self._upload_dir / f"{doc_id}.pdf"
                pdf_tmp.write_bytes(raw_bytes)
                md_path = pdf_to_markdown(pdf_tmp, self._upload_dir)
                target = self._upload_dir / f"{doc_id}.md"
                if md_path != target:
                    md_path.rename(target)
                    md_path = target
                pdf_tmp.unlink(missing_ok=True)

            emit("extract", 1.0, "文本提取完成")

            # 阶段 3: 分块
            emit("chunk", 0.0, "正在切分文档...")
            source_name = Path(filename).with_suffix(".pdf").name if suffix == ".pdf" else filename
            sha = compute_sha256(raw_bytes)
            parent_pairs, child_docs = self._chunker.chunk_file(
                md_path, doc_id, source_name, sha, kb_id=self._kb_id)
            emit("chunk", 1.0, f"切分完成: {len(parent_pairs)} 个父块, {len(child_docs)} 个子块",
                 {"parent_count": len(parent_pairs), "child_count": len(child_docs)})

            # 阶段 4: 写入 Qdrant
            emit("store", 0.0, "正在写入向量数据库...")
            self._parent.save_many(parent_pairs)
            self._qdrant.add_documents(child_docs)
            emit("store", 1.0, "写入完成")

            self._sqlite.doc_update(doc_id,
                status=DocumentStatus.READY.value,
                parent_count=len(parent_pairs), child_count=len(child_docs),
            )

            logger.info("ingestion.complete", doc_id=doc_id, filename=filename,
                        parents=len(parent_pairs), children=len(child_docs))
            return {
                "doc_id": doc_id, "filename": filename,
                "status": DocumentStatus.READY.value,
                "parent_count": len(parent_pairs), "child_count": len(child_docs),
            }

        except Exception as e:
            logger.exception("ingestion.error", doc_id=doc_id, filename=filename)
            self._sqlite.doc_update(doc_id, status=DocumentStatus.ERROR.value, error=str(e))
            emit("error", 0.0, f"处理失败: {str(e)}")
            return {"doc_id": doc_id, "filename": filename, "status": DocumentStatus.ERROR.value, "error": str(e)}

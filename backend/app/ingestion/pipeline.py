"""文档摄入管线：去重 → MinerU 解析 → 父子分块 → Qdrant 写入。

中间文件：data/uploads (PDF) / data/markdown (MD) / data/chunks (JSON)。
失败时自动清理所有中间文件。
"""

import asyncio
import json
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
        self._md_dir = Path(settings.storage.markdown_dir)
        self._chunks_dir = Path(settings.storage.chunks_dir)

    def _dirs(self, kb_id: str | None):
        upload = self._upload_dir / kb_id if kb_id else self._upload_dir
        md = self._md_dir / kb_id if kb_id else self._md_dir
        chunks = self._chunks_dir / kb_id if kb_id else self._chunks_dir
        for d in [upload, md, chunks]:
            d.mkdir(parents=True, exist_ok=True)
        return upload, md, chunks

    def _cleanup_files(self, doc_id: str, upload_dir, md_dir, chunks_dir):
        for d in [upload_dir, md_dir, chunks_dir]:
            for f in d.glob(f"{doc_id}.*"):
                f.unlink(missing_ok=True)

    async def process_file(
        self,
        filepath: str,
        filename: str,
        *,
        progress: Optional[ProgressCallback] = None,
    ) -> dict:
        """处理一个上传文件，返回 {doc_id, status, ...}"""
        emit = progress or (lambda p, pc, m, e: None)
        current_phase = ["dedup"]

        # 阶段 1: 读文件 + 去重
        emit("dedup", 0.0, f"正在检查重复: {filename}")
        raw_bytes = Path(filepath).read_bytes()
        is_dup, existing = check_duplicate(self._sqlite, raw_bytes, filename, kb_id=self._kb_id)
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
        await asyncio.sleep(0)

        upload_dir, md_dir, chunks_dir = self._dirs(self._kb_id)

        try:
            suffix = Path(filename).suffix.lower()

            if suffix == ".pdf":
                upload_path = upload_dir / f"{doc_id}.pdf"
                upload_path.write_bytes(raw_bytes)

            # 阶段 2: PDF → Markdown
            current_phase[0] = "extract"
            emit("extract", 0.0, f"MinerU 解析中: {filename}")
            await asyncio.sleep(0)

            target = md_dir / f"{doc_id}.md"
            if suffix == ".md":
                target.write_bytes(raw_bytes)
            else:
                md_path = await pdf_to_markdown(upload_path, md_dir)
                if md_path != target:
                    md_path.rename(target)

            emit("extract", 1.0, "MinerU 解析完成")
            await asyncio.sleep(0)

            # 阶段 3: 分块
            current_phase[0] = "chunk"
            emit("chunk", 0.0, "正在切分文档...")
            await asyncio.sleep(0)
            source_name = f"{Path(filename).stem}.pdf" if suffix == ".pdf" else filename
            sha = compute_sha256(raw_bytes)
            parent_pairs, child_docs = self._chunker.chunk_file(
                target, doc_id, source_name, sha, kb_id=self._kb_id)
            emit("chunk", 1.0, f"切分完成: {len(parent_pairs)} 个父块, {len(child_docs)} 个子块",
                 {"parent_count": len(parent_pairs), "child_count": len(child_docs)})
            await asyncio.sleep(0)

            # 保存 chunk 数据
            chunks_path = chunks_dir / f"{doc_id}.json"
            chunks_path.write_text(json.dumps({
                "parents": [{"id": pid, "content": pdoc.page_content, "metadata": pdoc.metadata}
                            for pid, pdoc in parent_pairs],
                "children": [{"content": c.page_content, "metadata": c.metadata} for c in child_docs],
            }, ensure_ascii=False, indent=2), encoding="utf-8")

            # 阶段 4: 写入 Qdrant
            current_phase[0] = "store"
            emit("store", 0.0, "正在写入向量数据库...")
            await asyncio.sleep(0)
            self._parent.save_many(parent_pairs)
            self._qdrant.add_documents(child_docs)
            emit("store", 1.0, "写入完成")
            await asyncio.sleep(0)

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
            self._sqlite.doc_delete(doc_id)
            self._cleanup_files(doc_id, upload_dir, md_dir, chunks_dir)
            emit(current_phase[0], 1.0, f"处理失败: {str(e)}")
            return {"doc_id": doc_id, "filename": filename, "status": DocumentStatus.ERROR.value, "error": str(e)}

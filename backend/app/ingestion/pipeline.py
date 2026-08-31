"""文档摄入管线：去重 → MinerU 解析 → 父子分块 → Qdrant 写入。

中间文件：data/uploads (PDF) / data/markdown (MD) / data/chunks (JSON)。
失败时回滚向量和父块索引，并保留中间文件供重试。
"""

import asyncio
import hashlib
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
from app.domain.enums import GovernanceJobStatus, GovernanceStage
from app.domain.models import Document
from app.core.paths import kb_storage_folder
from langchain_core.documents import Document as LangChainDocument

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

    def _config_hash(self) -> str:
        data = {
            "dense_model": self._settings.embedding.dense_model,
            "sparse_model": self._settings.embedding.sparse_model,
            "min_parent_size": self._settings.rag.min_parent_size,
            "max_parent_size": self._settings.rag.max_parent_size,
            "child_chunk_size": self._settings.rag.child_chunk_size,
            "child_chunk_overlap": self._settings.rag.child_chunk_overlap,
        }
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _file_hash(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _checkpoint(
        self,
        job,
        stage: GovernanceStage,
        *,
        input_checksum: str = "",
        output_checksum: str = "",
        artifacts: dict | None = None,
    ) -> None:
        self._sqlite.governance_checkpoint(
            job.id,
            job.attempt,
            stage.value,
            input_checksum=input_checksum,
            output_checksum=output_checksum,
            artifacts=artifacts,
        )

    @staticmethod
    def _load_chunks(path: Path) -> tuple[list[tuple], list[LangChainDocument]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        parents = [
            (item["id"], LangChainDocument(
                page_content=item["content"], metadata=item.get("metadata", {})
            ))
            for item in data.get("parents", [])
        ]
        children = [
            LangChainDocument(
                page_content=item["content"], metadata=item.get("metadata", {})
            )
            for item in data.get("children", [])
        ]
        if not parents or not children:
            raise ValueError("chunk checkpoint 为空或不完整")
        return parents, children

    @staticmethod
    def _write_chunks(
        path: Path,
        parent_pairs: list[tuple],
        child_docs: list[LangChainDocument],
    ) -> None:
        path.write_text(json.dumps({
            "parents": [
                {"id": pid, "content": doc.page_content, "metadata": doc.metadata}
                for pid, doc in parent_pairs
            ],
            "children": [
                {"content": doc.page_content, "metadata": doc.metadata}
                for doc in child_docs
            ],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _stage_validate_publish(
        self,
        doc: Document,
        job,
        parent_pairs: list[tuple],
        child_docs: list[LangChainDocument],
        chunks_path: Path,
        emit: ProgressCallback,
        current_phase: list[str],
    ) -> dict:
        parent_ids = {parent_id for parent_id, _ in parent_pairs}
        if not parent_ids or not child_docs:
            raise ValueError("文档没有生成有效父块或子块")
        if any(not child.page_content.strip() for child in child_docs):
            raise ValueError("存在空子块")
        referenced = {str(child.metadata.get("parent_id", "")) for child in child_docs}
        if "" in referenced or not referenced.issubset(parent_ids):
            raise ValueError("子块与父块引用关系不完整")
        for child in child_docs:
            child.metadata["publish_status"] = "staging"

        current_phase[0] = GovernanceStage.PARENTS_STAGED.value
        await asyncio.to_thread(self._parent.save_many, parent_pairs)
        self._checkpoint(
            job,
            GovernanceStage.PARENTS_STAGED,
            output_checksum=str(len(parent_pairs)),
            artifacts={"parent_count": len(parent_pairs)},
        )

        current_phase[0] = GovernanceStage.VECTORS_STAGED.value
        emit("store", 0.25, "正在计算 BGE/BM25 向量并写入 Qdrant 暂存索引...")
        await asyncio.to_thread(self._qdrant.add_documents, child_docs)
        self._checkpoint(
            job,
            GovernanceStage.VECTORS_STAGED,
            output_checksum=str(len(child_docs)),
            artifacts={"child_count": len(child_docs)},
        )

        current_phase[0] = GovernanceStage.VALIDATED.value
        actual_parents = self._sqlite.parent_count_by_doc_id(doc.id)
        if actual_parents != len(parent_pairs):
            raise ValueError(
                f"父块数量不一致: expected={len(parent_pairs)}, actual={actual_parents}"
            )
        await asyncio.to_thread(
            self._qdrant.validate_document,
            doc.id,
            len(child_docs),
            parent_ids,
        )
        self._checkpoint(
            job,
            GovernanceStage.VALIDATED,
            input_checksum=self._file_hash(chunks_path),
            output_checksum=f"parents={len(parent_pairs)};children={len(child_docs)}",
        )

        current_phase[0] = GovernanceStage.PUBLISHED.value
        # 先将结构化主记录设为 READY，再原地发布向量；若后一步失败，统一补偿回滚。
        self._sqlite.doc_update(
            doc.id,
            status=DocumentStatus.READY.value,
            parent_count=len(parent_pairs),
            child_count=len(child_docs),
            error=None,
        )
        await asyncio.to_thread(self._qdrant.set_publish_status, doc.id, "active")
        self._checkpoint(job, GovernanceStage.PUBLISHED)
        self._sqlite.governance_job_update(
            job.id,
            status=GovernanceJobStatus.PUBLISHED.value,
            current_stage=GovernanceStage.PUBLISHED.value,
            error=None,
        )
        emit("store", 1.0, "质量校验通过，知识已发布")
        return {
            "doc_id": doc.id,
            "filename": doc.filename,
            "status": DocumentStatus.READY.value,
            "parent_count": len(parent_pairs),
            "child_count": len(child_docs),
        }

    def _rollback(self, doc_id: str, job, failed_stage: str, error: Exception) -> None:
        self._sqlite.governance_checkpoint(
            job.id,
            job.attempt,
            failed_stage,
            status="failed",
            error=str(error),
        )
        self._sqlite.governance_job_update(
            job.id,
            status=GovernanceJobStatus.ROLLING_BACK.value,
            current_stage=failed_stage,
            error=str(error),
        )
        cleanup_errors = []
        try:
            self._qdrant.delete_by_doc_id(doc_id)
        except Exception as cleanup_error:
            cleanup_errors.append(f"qdrant: {cleanup_error}")
            logger.warning("ingestion.rollback.qdrant.fail", doc_id=doc_id, error=str(cleanup_error))
        try:
            self._parent.delete_by_doc_id(doc_id)
        except Exception as cleanup_error:
            cleanup_errors.append(f"parent: {cleanup_error}")
            logger.warning("ingestion.rollback.parent.fail", doc_id=doc_id, error=str(cleanup_error))
        final_error = str(error)
        if cleanup_errors:
            final_error += " | 补偿未完全成功: " + "; ".join(cleanup_errors)
        self._sqlite.doc_update(
            doc_id,
            status=DocumentStatus.ERROR.value,
            parent_count=0,
            child_count=0,
            error=final_error,
        )
        self._sqlite.governance_job_update(
            job.id,
            # 补偿失败时保持 rolling_back，启动恢复会继续执行幂等清理。
            status=(
                GovernanceJobStatus.ROLLING_BACK.value
                if cleanup_errors else GovernanceJobStatus.FAILED.value
            ),
            error=final_error,
        )

    def _dirs(self, kb_id: str | None):
        if kb_id:
            kb = self._sqlite.kb_by_id(kb_id)
            folder = kb_storage_folder(kb.name, kb_id) if kb else kb_id
        else:
            folder = None
        upload = self._upload_dir / folder if folder else self._upload_dir
        md = self._md_dir / folder if folder else self._md_dir
        chunks = self._chunks_dir / folder if folder else self._chunks_dir
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
        emit = progress or (lambda *args, **kwargs: None)
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
        job = self._sqlite.governance_job_create(doc_id, self._config_hash())
        self._checkpoint(
            job,
            GovernanceStage.RECEIVED,
            input_checksum=compute_sha256(raw_bytes),
            artifacts={"filename": filename, "file_size": len(raw_bytes)},
        )
        self._checkpoint(job, GovernanceStage.DEDUPED, input_checksum=doc.sha256)
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
            self._checkpoint(
                job,
                GovernanceStage.PARSED,
                input_checksum=doc.sha256,
                output_checksum=self._file_hash(target),
                artifacts={"markdown_path": str(target)},
            )
            await asyncio.sleep(0)

            # 阶段 3: 分块
            current_phase[0] = "chunk"
            emit("chunk", 0.0, "正在切分文档...")
            await asyncio.sleep(0)
            source_name = f"{Path(filename).stem}.pdf" if suffix == ".pdf" else filename
            sha = compute_sha256(raw_bytes)
            parent_pairs, child_docs = await asyncio.to_thread(
                self._chunker.chunk_file,
                target, doc_id, source_name, sha, self._kb_id,
            )
            emit("chunk", 1.0, f"切分完成: {len(parent_pairs)} 个父块, {len(child_docs)} 个子块",
                 {"parent_count": len(parent_pairs), "child_count": len(child_docs)})
            await asyncio.sleep(0)

            chunks_path = chunks_dir / f"{doc_id}.json"
            self._write_chunks(chunks_path, parent_pairs, child_docs)
            self._checkpoint(
                job,
                GovernanceStage.CHUNKED,
                input_checksum=self._file_hash(target),
                output_checksum=self._file_hash(chunks_path),
                artifacts={"chunks_path": str(chunks_path)},
            )

            # 阶段 4: 写入 Qdrant
            current_phase[0] = "store"
            emit("store", 0.0, "正在写入向量数据库...")
            await asyncio.sleep(0)
            result = await self._stage_validate_publish(
                doc, job, parent_pairs, child_docs, chunks_path, emit, current_phase
            )

            logger.info("ingestion.complete", doc_id=doc_id, filename=filename,
                        parents=len(parent_pairs), children=len(child_docs))
            return result

        except Exception as e:
            logger.exception("ingestion.error", doc_id=doc_id, filename=filename)
            self._rollback(doc_id, job, current_phase[0], e)
            emit(current_phase[0], 1.0, f"处理失败: {str(e)}")
            return {"doc_id": doc_id, "filename": filename, "status": DocumentStatus.ERROR.value, "error": str(e)}

    async def retry_document(
        self,
        doc: Document,
        *,
        progress: Optional[ProgressCallback] = None,
    ) -> dict:
        """按 checkpoint 重试：配置未变化时优先复用 chunk 产物。"""
        emit = progress or (lambda *args, **kwargs: None)
        current_phase = ["resume"]
        upload_dir, md_dir, chunks_dir = self._dirs(doc.kb_id)
        md_path = md_dir / f"{doc.id}.md"
        chunks_path = chunks_dir / f"{doc.id}.json"
        job = self._sqlite.governance_job_by_document(doc.id)
        old_config_hash = job.config_hash if job else ""
        if job is None:
            job = self._sqlite.governance_job_create(doc.id, self._config_hash())
        else:
            job = self._sqlite.governance_begin_retry(job.id, self._config_hash())

        self._sqlite.doc_update(doc.id, status=DocumentStatus.PROCESSING.value, error=None)
        try:
            await asyncio.to_thread(self._qdrant.delete_by_doc_id, doc.id)
            await asyncio.to_thread(self._parent.delete_by_doc_id, doc.id)

            if not md_path.exists():
                pdf_path = upload_dir / f"{doc.id}.pdf"
                if not pdf_path.exists():
                    raise FileNotFoundError("原文件和 Markdown 均不存在，无法恢复")
                current_phase[0] = GovernanceStage.PARSED.value
                parsed = await pdf_to_markdown(pdf_path, md_dir)
                if parsed != md_path:
                    parsed.replace(md_path)
                self._checkpoint(
                    job,
                    GovernanceStage.PARSED,
                    input_checksum=doc.sha256,
                    output_checksum=self._file_hash(md_path),
                    artifacts={"markdown_path": str(md_path)},
                )

            reusable_chunks = (
                chunks_path.exists()
                and old_config_hash == self._config_hash()
                and job.last_completed_stage in {
                    GovernanceStage.CHUNKED.value,
                    GovernanceStage.PARENTS_STAGED.value,
                    GovernanceStage.VECTORS_STAGED.value,
                    GovernanceStage.VALIDATED.value,
                    GovernanceStage.PUBLISHED.value,
                }
            )
            current_phase[0] = GovernanceStage.CHUNKED.value
            if reusable_chunks:
                parent_pairs, child_docs = self._load_chunks(chunks_path)
                emit("chunk", 1.0, "已从 checkpoint 复用分块产物")
            else:
                source_name = (
                    f"{Path(doc.filename).stem}.pdf"
                    if doc.filename.lower().endswith(".pdf") else doc.filename
                )
                parent_pairs, child_docs = await asyncio.to_thread(
                    self._chunker.chunk_file,
                    md_path, doc.id, source_name, doc.sha256, doc.kb_id,
                )
                self._write_chunks(chunks_path, parent_pairs, child_docs)
            self._checkpoint(
                job,
                GovernanceStage.CHUNKED,
                input_checksum=self._file_hash(md_path),
                output_checksum=self._file_hash(chunks_path),
                artifacts={"chunks_path": str(chunks_path)},
            )
            return await self._stage_validate_publish(
                doc, job, parent_pairs, child_docs, chunks_path, emit, current_phase
            )
        except Exception as exc:
            logger.exception("ingestion.retry.error", doc_id=doc.id)
            self._rollback(doc.id, job, current_phase[0], exc)
            return {
                "doc_id": doc.id,
                "filename": doc.filename,
                "status": DocumentStatus.ERROR.value,
                "error": str(exc),
            }

"""文档上传，带 SSE 进度推送"""

import asyncio
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.v1.deps import get_container, get_current_user
from app.domain.schemas import UploadResponse, UploadTaskInfo
from app.ingestion.pipeline import IngestionPipeline
from app.core.paths import safe_filename

router = APIRouter(tags=["uploads"])


@dataclass
class _UploadEntry:
    tasks: list[UploadTaskInfo]
    created_at: float
    user_id: str
    temp_paths: list[str | None]


_upload_tasks: dict[str, _UploadEntry] = {}
_UPLOAD_TASK_TTL = 1800


def _purge_stale_uploads():
    """清理超过 30 分钟的已完成上传任务"""
    now = time.time()
    stale = [
        uid for uid, entry in _upload_tasks.items()
        if now - entry.created_at > _UPLOAD_TASK_TTL
        and all(t.status not in ("pending", "processing") for t in entry.tasks)
    ]
    for uid in stale:
        del _upload_tasks[uid]


@router.post("/documents", response_model=UploadResponse)
async def upload_documents(
    files: list[UploadFile],
    request: Request,
    kb_id: str | None = None,
    user_id: str = Depends(get_current_user),
):
    """上传文档到知识库"""
    container = get_container(request)
    settings = container.settings
    if not kb_id:
        raise HTTPException(status_code=400, detail="请选择目标知识库")
    kb = container.sqlite.kb_by_id(kb_id)
    if not kb or kb.user_id != user_id:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    upload_id = str(uuid.uuid4())
    tasks = []
    temp_paths: list[str | None] = []

    for f in files:
        if not f.filename:
            continue
        filename = safe_filename(f.filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in settings.upload.allowed_extensions:
            tasks.append(UploadTaskInfo(
                filename=filename, status="error",
                error=f"不支持的文件格式: {suffix}",
            ))
            temp_paths.append(None)
            continue

        content = await f.read()
        if len(content) > settings.upload.max_size_mb * 1024 * 1024:
            tasks.append(UploadTaskInfo(
                filename=filename, status="error",
                error=f"文件过大 (>{settings.upload.max_size_mb}MB)",
            ))
            temp_paths.append(None)
            continue

        # 上传时先做 SHA256 去重，重复文件直接返回终态
        import hashlib
        sha = hashlib.sha256(content).hexdigest()
        existing = container.sqlite.doc_by_sha256(sha, kb_id=kb_id)
        if existing:
            tasks.append(UploadTaskInfo(
                filename=filename, status="duplicate",
                duplicate_of=existing.id, phase="dedup", percent=1.0,
            ))
            temp_paths.append(None)
            continue

        tmp = Path(tempfile.gettempdir()) / f"kb_upload_{uuid.uuid4().hex}_{filename}"
        tmp.write_bytes(content)

        tasks.append(UploadTaskInfo(filename=filename, status="pending"))
        temp_paths.append(str(tmp))

    if tasks:
        _purge_stale_uploads()
        entry = _UploadEntry(
            tasks=tasks,
            created_at=time.time(),
            user_id=user_id,
            temp_paths=temp_paths,
        )
        _upload_tasks[upload_id] = entry
        asyncio.create_task(_process_uploads(upload_id, entry, container, kb_id))

    return UploadResponse(upload_id=upload_id, tasks=tasks)


async def _process_uploads(upload_id: str, entry: _UploadEntry, container, kb_id: str | None = None):
    """后台处理上传文件"""
    settings = container.settings
    pipeline = IngestionPipeline(
        settings=settings,
        sqlite=container.sqlite,
        qdrant=container.qdrant,
        parent=container.parent,
        kb_id=kb_id,
    )

    semaphore = container.ingestion_semaphore or asyncio.Semaphore(1)
    async with semaphore:
        for index, task in enumerate(entry.tasks):
            if task.status != "pending":
                continue
            task.status = "processing"

            filepath = entry.temp_paths[index]
            if not filepath or not Path(filepath).exists():
                task.status = "error"
                task.error = "临时文件丢失"
                continue

            def progress(phase, pct, msg, extra=None):
                task.phase = phase
                task.percent = pct
                if extra:
                    if "duplicate_of" in extra:
                        task.duplicate_of = extra["duplicate_of"]

            try:
                result = await pipeline.process_file(filepath, task.filename, progress=progress)
                task.status = result["status"]
                task.doc_id = result.get("doc_id")
                task.duplicate_of = result.get("duplicate_of")
                task.error = result.get("error")
            except Exception as e:
                task.status = "error"
                task.error = f"处理异常: {str(e)}"
            finally:
                Path(filepath).unlink(missing_ok=True)


@router.get("/uploads/{upload_id}")
async def get_upload_status(upload_id: str, user_id: str = Depends(get_current_user)):
    _purge_stale_uploads()
    entry = _upload_tasks.get(upload_id)
    if not entry or entry.user_id != user_id:
        raise HTTPException(status_code=404, detail="Upload task not found")
    return {"tasks": [t.model_dump() for t in entry.tasks]}


@router.get("/uploads/{upload_id}/events")
async def upload_events(upload_id: str, token: str = "", request: Request = None):
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        from app.services.auth_service import decode_token
        payload = decode_token(token)
        user_id = payload["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    container = get_container(request)
    if not container.auth_service.get_user(user_id):
        raise HTTPException(status_code=401, detail="用户不存在")
    import json

    async def event_gen():
        while True:
            _purge_stale_uploads()
            entry = _upload_tasks.get(upload_id)
            if not entry or entry.user_id != user_id:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Upload task not found'})}\n\n"
                return
            tasks = entry.tasks
            all_done = all(t.status not in ("pending", "processing") for t in tasks)
            for t in tasks:
                yield f"data: {json.dumps(t.model_dump(), default=str)}\n\n"
            if all_done:
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break
            await asyncio.sleep(0.2)

    return StreamingResponse(event_gen(), media_type="text/event-stream")

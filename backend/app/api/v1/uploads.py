"""文档上传，带 SSE 进度推送"""

import asyncio
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.v1.deps import get_container, get_current_user
from app.domain.schemas import UploadResponse, UploadTaskInfo
from app.ingestion.pipeline import IngestionPipeline

router = APIRouter(tags=["uploads"])

_upload_tasks: dict[str, tuple[list[UploadTaskInfo], float]] = {}
_UPLOAD_TASK_TTL = 1800


def _purge_stale_uploads():
    """清理超过 30 分钟的已完成上传任务"""
    now = time.time()
    stale = [
        uid for uid, (tasks, created_at) in _upload_tasks.items()
        if now - created_at > _UPLOAD_TASK_TTL
        and all(t.status not in ("pending", "processing") for t in tasks)
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

    upload_id = str(uuid.uuid4())
    tasks = []

    for f in files:
        if not f.filename:
            continue
        suffix = Path(f.filename).suffix.lower()
        if suffix not in settings.upload.allowed_extensions:
            tasks.append(UploadTaskInfo(
                filename=f.filename, status="error",
                error=f"不支持的文件格式: {suffix}",
            ))
            continue

        content = await f.read()
        if len(content) > settings.upload.max_size_mb * 1024 * 1024:
            tasks.append(UploadTaskInfo(
                filename=f.filename, status="error",
                error=f"文件过大 (>{settings.upload.max_size_mb}MB)",
            ))
            continue

        tmp = Path(tempfile.gettempdir()) / f"kb_upload_{uuid.uuid4().hex[:8]}_{f.filename}"
        tmp.write_bytes(content)

        tasks.append(UploadTaskInfo(filename=f.filename, status="pending"))

    if tasks:
        _purge_stale_uploads()
        _upload_tasks[upload_id] = (tasks, time.time())
        asyncio.create_task(_process_uploads(upload_id, tasks, container, kb_id))

    return UploadResponse(upload_id=upload_id, tasks=tasks)


async def _process_uploads(upload_id: str, tasks: list[UploadTaskInfo], container, kb_id: str | None = None):
    """后台处理上传文件"""
    settings = container.settings
    pipeline = IngestionPipeline(
        settings=settings,
        sqlite=container.sqlite,
        qdrant=container.qdrant,
        parent=container.parent,
        kb_id=kb_id,
    )

    tmp_dir = Path(tempfile.gettempdir())

    for task in tasks:
        if task.status == "error":
            continue
        task.status = "processing"

        candidates = list(tmp_dir.glob(f"kb_upload_*_{task.filename}"))
        if not candidates:
            task.status = "error"
            task.error = "临时文件丢失"
            continue

        filepath = str(candidates[0])

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

        Path(filepath).unlink(missing_ok=True)


@router.get("/uploads/{upload_id}")
async def get_upload_status(upload_id: str, user_id: str = Depends(get_current_user)):
    _purge_stale_uploads()
    entry = _upload_tasks.get(upload_id)
    tasks = entry[0] if entry else []
    return {"tasks": [t.model_dump() for t in tasks]}


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
            tasks = entry[0] if entry else []
            if not tasks:
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break
            all_done = all(t.status not in ("pending", "processing") for t in tasks)
            for t in tasks:
                yield f"data: {json.dumps(t.model_dump(), default=str)}\n\n"
            if all_done:
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break
            await asyncio.sleep(0.2)

    return StreamingResponse(event_gen(), media_type="text/event-stream")

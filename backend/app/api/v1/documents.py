from fastapi import APIRouter, Request, HTTPException, Depends
from app.api.v1.deps import get_container, get_current_user
from app.domain.schemas import DocumentResponse, DocumentListResponse
import json

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("")
async def list_documents(
    kb_id: str | None = None, q: str | None = None,
    page: int = 1, page_size: int = 50,
    request: Request = None, user_id: str = Depends(get_current_user),
):
    container = get_container(request)
    items, total = container.document_service.list_documents(
        user_id, kb_id=kb_id, q=q, page=page, page_size=page_size)
    return DocumentListResponse(
        items=[DocumentResponse(
            id=d.id, filename=d.filename, kb_id=d.kb_id, status=d.status,
            file_size=d.file_size, parent_count=d.parent_count,
            child_count=d.child_count, error=d.error, created_at=d.created_at,
        ) for d in items],
        total=total)


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: str, request: Request, user_id: str = Depends(get_current_user)):
    container = get_container(request)
    ok = container.document_service.delete(user_id, doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Document not found")


@router.post("/{doc_id}/retry")
async def retry_document(doc_id: str, request: Request, user_id: str = Depends(get_current_user)):
    container = get_container(request)
    doc = await container.document_service.retry(user_id, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found or not in error state")
    return DocumentResponse(
        id=doc.id, filename=doc.filename, kb_id=doc.kb_id, status=doc.status,
        file_size=doc.file_size, parent_count=doc.parent_count,
        child_count=doc.child_count, error=doc.error, created_at=doc.created_at)


@router.get("/{doc_id}/governance")
async def get_document_governance(
    doc_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    """查看文档知识治理任务及每次 attempt 的阶段 checkpoint。"""
    container = get_container(request)
    doc = container.sqlite.doc_by_id(doc_id)
    if not doc or not doc.kb_id:
        raise HTTPException(status_code=404, detail="Document not found")
    kb = container.sqlite.kb_by_id(doc.kb_id)
    if not kb or kb.user_id != user_id:
        raise HTTPException(status_code=404, detail="Document not found")
    job = container.sqlite.governance_job_by_document(doc_id)
    if not job:
        return {"document_id": doc_id, "job": None, "checkpoints": []}
    checkpoints = container.sqlite.governance_checkpoints(job.id)
    return {
        "document_id": doc_id,
        "job": {
            "id": job.id,
            "status": job.status,
            "current_stage": job.current_stage,
            "last_completed_stage": job.last_completed_stage,
            "attempt": job.attempt,
            "config_hash": job.config_hash,
            "artifacts": json.loads(job.artifacts_json or "{}"),
            "error": job.error,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        },
        "checkpoints": [
            {
                "attempt": item.attempt,
                "stage": item.stage,
                "status": item.status,
                "input_checksum": item.input_checksum,
                "output_checksum": item.output_checksum,
                "artifacts": json.loads(item.artifacts_json or "{}"),
                "error": item.error,
                "started_at": item.started_at,
                "completed_at": item.completed_at,
            }
            for item in checkpoints
        ],
    }

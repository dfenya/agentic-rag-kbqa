"""知识库的增删"""

from fastapi import APIRouter, Request, HTTPException

from app.api.v1.deps import get_container
from app.domain.schemas import KBCreateRequest, KBResponse

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.post("", status_code=201, response_model=KBResponse)
async def create_kb(body: KBCreateRequest, request: Request):
    container = get_container(request)
    kb = container.sqlite.kb_create(name=body.name, description=body.description)
    return KBResponse(
        id=kb.id, name=kb.name, description=kb.description,
        document_count=0, created_at=kb.created_at,
    )


@router.get("")
async def list_kbs(request: Request):
    container = get_container(request)
    kbs = container.sqlite.kb_list()
    result = []
    for kb in kbs:
        docs, total = container.sqlite.docs_list(kb_id=kb.id)
        result.append(KBResponse(
            id=kb.id, name=kb.name, description=kb.description,
            document_count=total, created_at=kb.created_at,
        ))
    return result


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(kb_id: str, request: Request):
    """删除知识库及其下所有文档，逐文档清理向量和 SQLite"""
    import structlog
    log = structlog.get_logger()
    container = get_container(request)

    if container.sqlite.kb_by_id(kb_id) is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    docs, _ = container.sqlite.docs_list(kb_id=kb_id, page=1, page_size=100_000)
    deleted_doc_ids = []
    for doc in docs:
        ok = container.document_service.delete(doc.id)
        if not ok:
            log.error("kb.delete.doc_missing_midway", kb_id=kb_id, doc_id=doc.id)
            raise HTTPException(
                status_code=500,
                detail=f"删除知识库中途丢失文档记录 doc_id={doc.id}",
            )
        deleted_doc_ids.append(doc.id)

    ok = container.sqlite.kb_delete(kb_id)
    if not ok:
        log.error("kb.delete.sqlite_failed", kb_id=kb_id, docs_deleted=len(deleted_doc_ids))
        raise HTTPException(
            status_code=500,
            detail=f"删除知识库失败 kb_id={kb_id} (已删除 {len(deleted_doc_ids)} 个文档的向量和记录)",
        )
    log.info("kb.delete.ok", kb_id=kb_id, doc_count=len(deleted_doc_ids))

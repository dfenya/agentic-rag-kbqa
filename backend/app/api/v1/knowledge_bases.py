from fastapi import APIRouter, Request, HTTPException, Depends

from app.api.v1.deps import get_container, get_current_user
from app.domain.schemas import KBCreateRequest, KBResponse

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.post("", status_code=201, response_model=KBResponse)
async def create_kb(body: KBCreateRequest, request: Request, user_id: str = Depends(get_current_user)):
    container = get_container(request)
    kb = container.sqlite.kb_create(name=body.name, user_id=user_id, description=body.description)
    return KBResponse(
        id=kb.id, name=kb.name, description=kb.description,
        document_count=0, created_at=kb.created_at,
    )


@router.get("")
async def list_kbs(request: Request, user_id: str = Depends(get_current_user)):
    container = get_container(request)
    kbs = container.sqlite.kb_list(user_id)
    result = []
    for kb in kbs:
        docs, total = container.sqlite.docs_list(kb_id=kb.id)
        result.append(KBResponse(
            id=kb.id, name=kb.name, description=kb.description,
            document_count=total, created_at=kb.created_at,
        ))
    return result


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(kb_id: str, request: Request, user_id: str = Depends(get_current_user)):
    import structlog
    log = structlog.get_logger()
    container = get_container(request)

    kb = container.sqlite.kb_by_id(kb_id)
    if kb is None or kb.user_id != user_id:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    docs, _ = container.sqlite.docs_list(kb_id=kb_id, page=1, page_size=100_000)
    for doc in docs:
        container.document_service.delete(user_id, doc.id)

    ok = container.sqlite.kb_delete(kb_id)
    if not ok:
        raise HTTPException(status_code=500, detail=f"删除知识库失败 kb_id={kb_id}")

"""长期记忆管理"""

import json
from fastapi import APIRouter, Request, HTTPException

from app.api.v1.deps import get_container
from app.domain.schemas import LongTermMemoryResponse, LongTermMemoryUpdateRequest

router = APIRouter(prefix="/memories", tags=["memories"])


@router.get("")
async def list_memories(type: str | None = None, q: str | None = None, request: Request = None):
    container = get_container(request)
    mems = container.long_term_memory_service.list_memories(mem_type=type, q=q)
    # 查所有涉及到的会话标题
    conv_ids = {m.source_conversation_id for m in mems if m.source_conversation_id}
    conv_titles = {}
    for cid in conv_ids:
        conv = container.conversation_service.get(cid)
        if conv:
            conv_titles[cid] = conv.title or cid[:8]
    return [
        LongTermMemoryResponse(
            id=m.id, type=m.type, content=m.content,
            keywords=json.loads(m.keywords_json or "[]"),
            importance=m.importance, access_count=m.access_count,
            source_conversation_id=m.source_conversation_id,
            conversation_title=conv_titles.get(m.source_conversation_id) if m.source_conversation_id else None,
            created_at=m.created_at, updated_at=m.updated_at,
        ) for m in mems
    ]


@router.patch("/{mem_id}")
async def update_memory(mem_id: str, body: LongTermMemoryUpdateRequest, request: Request):
    container = get_container(request)
    mem = container.long_term_memory_service.update(
        mem_id, **(body.model_dump(exclude_none=True)),
    )
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    return LongTermMemoryResponse(
        id=mem.id, type=mem.type, content=mem.content,
        keywords=json.loads(mem.keywords_json or "[]"),
        importance=mem.importance, access_count=mem.access_count,
        created_at=mem.created_at, updated_at=mem.updated_at,
    )


@router.delete("/{mem_id}", status_code=204)
async def delete_memory(mem_id: str, request: Request):
    container = get_container(request)
    ok = container.long_term_memory_service.delete(mem_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")

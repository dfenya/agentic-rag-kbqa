import json
from fastapi import APIRouter, Depends, Request, HTTPException
from app.api.v1.deps import get_container, get_current_user
from app.domain.schemas import (
    ConversationCreateRequest, ConversationResponse, ConversationUpdateRequest, MessageResponse)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", status_code=201)
async def create_conversation(body: ConversationCreateRequest, request: Request, user_id: str = Depends(get_current_user)):
    container = get_container(request)
    conv = container.conversation_service.create(user_id, title=body.title or "新对话", model=body.model or "")
    return ConversationResponse(id=conv.id, title=conv.title, model=conv.model,
        message_count=conv.message_count, last_message_preview=conv.last_message_preview,
        created_at=conv.created_at, updated_at=conv.updated_at)


@router.get("")
async def list_conversations(q: str | None = None, request: Request = None, user_id: str = Depends(get_current_user)):
    container = get_container(request)
    convs = container.conversation_service.list_conversations(user_id, q=q)
    return {"items": [
        ConversationResponse(id=c.id, title=c.title, model=c.model,
            message_count=c.message_count, last_message_preview=c.last_message_preview,
            created_at=c.created_at, updated_at=c.updated_at) for c in convs
    ], "total": len(convs)}


@router.get("/{conv_id}/messages")
async def get_messages(conv_id: str, request: Request, user_id: str = Depends(get_current_user)):
    container = get_container(request)
    if not container.conversation_service.get(user_id, conv_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = container.conversation_service.get_messages(user_id, conv_id)
    result = []
    for m in msgs:
        flow_steps = None
        if m.flow_steps_json:
            try:
                flow_steps = json.loads(m.flow_steps_json)
            except (json.JSONDecodeError, TypeError):
                flow_steps = None
        result.append(MessageResponse(id=m.id, role=m.role, content=m.content,
            sources_json=m.sources_json, flow_steps=flow_steps, created_at=m.created_at))
    return result


@router.patch("/{conv_id}")
async def update_conversation(conv_id: str, body: ConversationUpdateRequest, request: Request, user_id: str = Depends(get_current_user)):
    container = get_container(request)
    conv = container.conversation_service.update(user_id, conv_id, **(body.model_dump(exclude_none=True)))
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationResponse(id=conv.id, title=conv.title, model=conv.model,
        message_count=conv.message_count, last_message_preview=conv.last_message_preview,
        created_at=conv.created_at, updated_at=conv.updated_at)


@router.delete("/{conv_id}", status_code=204)
async def delete_conversation(conv_id: str, request: Request, user_id: str = Depends(get_current_user)):
    container = get_container(request)
    ok = container.conversation_service.delete(user_id, conv_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")

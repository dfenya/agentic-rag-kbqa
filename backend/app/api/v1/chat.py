from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.v1.deps import get_container, get_current_user
from app.domain.schemas import ChatRequest, ChatResumeRequest

router = APIRouter(prefix="/chat", tags=["chat"])


def _validate_chat_scope(container, user_id: str, conversation_id: str | None, kb_id: str | None):
    if conversation_id and not container.conversation_service.get(user_id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    if kb_id:
        kb = container.sqlite.kb_by_id(kb_id)
        if not kb or kb.user_id != user_id:
            raise HTTPException(status_code=404, detail="Knowledge base not found")


@router.post("/stream")
async def chat_stream(body: ChatRequest, request: Request, user_id: str = Depends(get_current_user)):
    container = get_container(request)
    _validate_chat_scope(container, user_id, body.conversation_id, body.kb_id)
    chat_service = container.chat_service
    return StreamingResponse(
        chat_service.stream_chat(
            message=body.message,
            conversation_id=body.conversation_id,
            kb_id=body.kb_id,
            user_id=user_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/resume")
async def chat_resume(body: ChatResumeRequest, request: Request, user_id: str = Depends(get_current_user)):
    container = get_container(request)
    _validate_chat_scope(container, user_id, body.conversation_id, body.kb_id)
    chat_service = container.chat_service
    return StreamingResponse(
        chat_service.stream_chat(
            message=body.reply,
            conversation_id=body.conversation_id,
            kb_id=body.kb_id,
            user_id=user_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )

"""对话端点：SSE 流式输出和中断恢复"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.v1.deps import get_container
from app.domain.schemas import ChatRequest, ChatResumeRequest
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/stream")
async def chat_stream(body: ChatRequest, request: Request):
    """流式对话，SSE 推送"""
    container = get_container(request)
    chat_service = ChatService(container)

    return StreamingResponse(
        chat_service.stream_chat(
            message=body.message,
            conversation_id=body.conversation_id,
            kb_id=body.kb_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/resume")
async def chat_resume(body: ChatResumeRequest, request: Request):
    """澄清中断后恢复对话"""
    container = get_container(request)
    chat_service = ChatService(container)

    return StreamingResponse(
        chat_service.stream_chat(
            message=body.reply,
            conversation_id=body.conversation_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

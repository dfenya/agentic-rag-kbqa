"""把所有 v1 路由聚合到 /api/v1 下"""

from fastapi import APIRouter

from app.api.v1.system import router as system_router
from app.api.v1.chat import router as chat_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.documents import router as documents_router
from app.api.v1.uploads import router as uploads_router
from app.api.v1.knowledge_bases import router as kb_router
from app.api.v1.memories import router as memories_router
from app.api.v1.settings import router as settings_router

v1_router = APIRouter()

v1_router.include_router(system_router)
v1_router.include_router(chat_router)
v1_router.include_router(conversations_router)
v1_router.include_router(documents_router)
v1_router.include_router(uploads_router)
v1_router.include_router(kb_router)
v1_router.include_router(memories_router)
v1_router.include_router(settings_router)

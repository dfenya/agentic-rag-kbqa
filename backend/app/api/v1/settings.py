"""设置和模型列表"""

import httpx
from fastapi import APIRouter, Request

from app.core.config import get_settings, save_user_settings

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def get_settings_api(request: Request):
    """返回当前运行时设置"""
    settings = get_settings()
    return {
        "llm": {
            "model": settings.llm.model,
            "temperature": settings.llm.temperature,
            "num_ctx": settings.llm.num_ctx,
            "ollama_base_url": settings.llm.ollama_base_url,
        },
        "rag": {
            "top_k": settings.rag.top_k,
            "score_threshold": settings.rag.score_threshold,
        },
        "memory": {
            "enabled": settings.long_term_memory.enabled,
            "top_k": settings.long_term_memory.top_k,
        },
    }


@router.put("/settings")
async def update_settings(body: dict):
    """保存用户设置到 JSON，重启后依然生效"""
    save_user_settings(body)
    return {"ok": True}


@router.get("/models")
async def list_models():
    """代理 Ollama 的 /api/tags"""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.llm.ollama_base_url}/api/tags")
            data = resp.json()
            return [
                {
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "modified_at": m.get("modified_at", ""),
                }
                for m in data.get("models", [])
            ]
    except Exception:
        return []


@router.get("/models/current")
async def current_model():
    settings = get_settings()
    return {"model": settings.llm.model}

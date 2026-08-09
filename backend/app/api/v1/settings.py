import httpx
from fastapi import APIRouter, Request, Depends

from app.core.config import get_settings, save_user_settings
from app.api.v1.deps import get_current_user

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def get_settings_api(user_id: str = Depends(get_current_user)):
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
        "dark_mode": getattr(settings, 'dark_mode', False),
    }


@router.put("/settings")
async def update_settings(body: dict, user_id: str = Depends(get_current_user)):
    save_user_settings(body, user_id)
    return {"ok": True}


@router.get("/models")
async def list_models(user_id: str = Depends(get_current_user)):
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.llm.ollama_base_url}/api/tags")
            data = resp.json()
            return [
                {"name": m.get("name", ""), "size": m.get("size", 0), "modified_at": m.get("modified_at", "")}
                for m in data.get("models", [])
            ]
    except Exception:
        return []


@router.get("/models/current")
async def current_model(user_id: str = Depends(get_current_user)):
    settings = get_settings()
    return {"model": settings.llm.model}

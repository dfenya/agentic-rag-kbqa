"""健康检查"""

from fastapi import APIRouter, Request

from app.domain.schemas import HealthResponse, ServiceStatus
from app.api.v1.deps import get_container

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request):
    """检查 SQLite、Qdrant、Ollama 的连接状态"""
    container = get_container(request)
    services = container.check_health()
    all_ok = all(v == "ok" or v.startswith("ok ") for v in services.values())
    return HealthResponse(
        status="ok" if all_ok else "degraded",
        version="1.0.0",
        services=ServiceStatus(**services),
    )

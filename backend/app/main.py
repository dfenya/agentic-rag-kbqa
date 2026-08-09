"""FastAPI 应用入口

启动: python run.py  或  uvicorn app.main:app --reload
"""

import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 确保 .env 加载不受当前工作目录影响
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=False)

from app.api.v1.router import v1_router
from app.core.config import get_settings
from app.core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.app.debug)

    # 确保数据目录存在
    Path(settings.storage.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    Path(settings.storage.upload_dir).mkdir(parents=True, exist_ok=True)

    # 初始化依赖注入容器
    from app.core.container import Container
    container = Container(settings)
    await container.init()
    app.state.container = container

    import structlog
    _bg_logger = structlog.get_logger()

    async def _cleanup_loop():
        """定期清理过期会话，每 24 小时跑一次"""
        while True:
            try:
                ttl = settings.app.conversation_ttl_days
                if ttl > 0 and container.sqlite:
                    deleted = container.sqlite.conv_delete_older_than(ttl)
                    if deleted:
                        _bg_logger.info("conversation.cleanup", deleted=deleted, ttl_days=ttl)
            except Exception:
                pass
            await asyncio.sleep(86400)

    cleanup_task = asyncio.create_task(_cleanup_loop())

    yield

    cleanup_task.cancel()
    await container.close()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app.name,
        version="1.0.0",
        lifespan=lifespan,
    )

    if settings.app.env == "dev":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    from app.core.middleware import register_middleware
    register_middleware(app)

    app.include_router(v1_router, prefix=settings.app.api_v1_prefix)
    return app


app = create_app()

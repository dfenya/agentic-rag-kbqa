"""依赖注入容器，管理所有 store/service/RAG 图的创建和生命周期

在 app lifespan 里调 init() 初始化，close() 释放资源。
"""

import asyncio
import threading
from urllib.parse import urlparse

import structlog
from langchain_ollama import ChatOllama

from app.core.config import Settings
from app.stores.sqlite_store import SqliteStore
from app.stores.qdrant_store import QdrantStore
from app.stores.parent_store import ParentStore
from app.stores.long_term_memory_store import LongTermMemoryStore
from app.services.auth_service import AuthService
from app.services.conversation_service import ConversationService
from app.services.document_service import DocumentService
from app.services.long_term_memory_service import LongTermMemoryService

logger = structlog.get_logger()


def _http_client_kwargs(base_url: str) -> dict:
    """访问本机 Ollama 时忽略系统代理，避免 localhost 被错误转发。"""
    hostname = (urlparse(base_url).hostname or "").lower()
    return {"trust_env": False} if hostname in {"localhost", "127.0.0.1", "::1"} else {}


class Container:
    """手动依赖注入容器，启动时 init()，关闭时 close()"""

    def __init__(self, settings: Settings):
        self.settings = settings

        self.sqlite: SqliteStore | None = None
        self.qdrant: QdrantStore | None = None
        self.parent: ParentStore | None = None
        self.long_term_memory_store: LongTermMemoryStore | None = None

        self.auth_service: AuthService | None = None
        self.conversation_service: ConversationService | None = None
        self.document_service: DocumentService | None = None
        self.long_term_memory_service: LongTermMemoryService | None = None
        self.chat_service = None
        self.ingestion_semaphore = None

        self.langfuse_handler = None
        self._graph = None
        self._checkpointer_conn = None
        self._graphs: dict[tuple, object] = {}
        self._checkpointer_conns: list[object] = []
        self._graph_lock = threading.Lock()

    def create_llm(self, settings=None, **overrides) -> ChatOllama:
        settings = settings or self.settings
        base_url = overrides.get("base_url", settings.llm.ollama_base_url)
        llm = ChatOllama(
            model=overrides.get("model", settings.llm.model),
            temperature=overrides.get("temperature", settings.llm.temperature),
            base_url=base_url,
            num_ctx=overrides.get("num_ctx", settings.llm.num_ctx),
            client_kwargs=_http_client_kwargs(base_url),
            async_client_kwargs=_http_client_kwargs(base_url),
        )
        if self.langfuse_handler:
            llm = llm.with_config(callbacks=[self.langfuse_handler])
        return llm

    @property
    def graph(self):
        return self._graph

    def compile_graph(self, kb_id: str | None = None, settings=None):
        """按知识库和关键配置缓存 LangGraph，避免并发请求互相关闭连接。"""
        settings = settings or self.settings
        cache_key = (
            kb_id,
            settings.llm.model,
            settings.llm.temperature,
            settings.llm.ollama_base_url,
            settings.llm.num_ctx,
            settings.rag.top_k,
            settings.rag.score_threshold,
            settings.rag.max_tool_calls,
            settings.rag.max_iterations,
            settings.long_term_memory.enabled,
            settings.long_term_memory.top_k,
        )
        with self._graph_lock:
            graph = self._graphs.get(cache_key)
            if graph is None:
                graph = self._compile_graph(kb_id=kb_id, settings=settings)
                self._graphs[cache_key] = graph
            self._graph = graph
            return graph

    async def init(self):
        """启动时初始化：SQLite → Qdrant → 业务服务 → RAG 图"""
        logger.info("container.init.start")
        self.ingestion_semaphore = asyncio.Semaphore(1)

        self.sqlite = SqliteStore(self.settings.storage.sqlite_path)
        self.sqlite.create_all()
        logger.info("container.sqlite.ready")

        self.qdrant = QdrantStore(self.settings)
        self.qdrant.init()
        self.qdrant.create_collection()

        self.parent = ParentStore(self.sqlite)

        # 兼容升级前已成功入库、但尚无 publish_status payload 的向量。
        for document in self.sqlite.docs_by_status("ready"):
            try:
                self.qdrant.set_publish_status(document.id, "active")
            except Exception as e:
                logger.warning(
                    "governance.publish_status_migration.fail",
                    doc_id=document.id,
                    error=str(e),
                )

        # 上次进程异常退出时，processing/rolling_back 任务可能留下暂存数据。
        # 启动阶段做幂等补偿并保留 checkpoint，随后可从中间产物重试。
        for job in self.sqlite.governance_incomplete_jobs():
            try:
                self.qdrant.delete_by_doc_id(job.document_id)
                self.parent.delete_by_doc_id(job.document_id)
                self.sqlite.doc_update(
                    job.document_id,
                    status="error",
                    parent_count=0,
                    child_count=0,
                    error="上次知识治理任务异常中断，暂存索引已回滚，可重试",
                )
                self.sqlite.governance_job_update(
                    job.id,
                    status="failed",
                    current_stage="rollback",
                    error="process interrupted",
                )
            except Exception as e:
                logger.error(
                    "governance.startup_recovery.fail",
                    doc_id=job.document_id,
                    error=str(e),
                )

        self.long_term_memory_store = LongTermMemoryStore(self.settings)
        self.long_term_memory_store.init(self.qdrant.client, self.qdrant._dense)

        # 兼容旧版本向量：旧 payload 没有 user_id/conversation_id，升级后会被
        # Qdrant 的范围过滤排除。启动时只补 metadata，不重新计算 embedding。
        migrated = 0
        for memory in self.sqlite.mem_all_records():
            try:
                self.long_term_memory_store.update_scope_payload(
                    memory.id,
                    user_id=memory.user_id,
                    conversation_id=memory.source_conversation_id or "",
                )
                migrated += 1
            except Exception as e:
                logger.warning(
                    "long_term_memory.scope_migration.fail",
                    memory_id=memory.id,
                    error=str(e),
                )
        if migrated:
            logger.info("long_term_memory.scope_migration.done", count=migrated)

        logger.info("container.stores.ready")

        if (
            self.settings.app.env == "prod"
            and self.settings.auth.jwt_secret == "change-me-in-production-use-env-var"
        ):
            raise RuntimeError("生产环境必须通过 AUTH_JWT_SECRET 配置 JWT 密钥")
        self.auth_service = AuthService(self.sqlite, self.settings)
        self.conversation_service = ConversationService(self.sqlite)
        self.document_service = DocumentService(self.sqlite, self.qdrant, self.parent, self.settings)
        self.long_term_memory_service = LongTermMemoryService(self.sqlite, self.long_term_memory_store)
        from app.services.chat_service import ChatService
        self.chat_service = ChatService(self)

        logger.info("container.services.ready")

        from dotenv import load_dotenv
        load_dotenv(".env.dev")
        import os
        if os.getenv("LANGFUSE_ENABLED", "").lower() in ("true", "1"):
            from langfuse.langchain import CallbackHandler
            self.langfuse_handler = CallbackHandler()
            logger.info("container.langfuse.ready")

        # RAG 图需要 Ollama 在线才能编译
        try:
            self.compile_graph()
            logger.info("container.graph.ready")
        except Exception as e:
            logger.warning("container.graph.unavailable", error=str(e))

        logger.info("container.init.done")

    def _compile_graph(self, kb_id: str | None = None, settings=None):
        from app.rag.tools import ToolFactory
        from app.rag.graph import create_agent_graph

        settings = settings or self.settings
        llm = self.create_llm(settings=settings)

        collection = self.qdrant.as_vector_store()
        tools = ToolFactory(
            collection=collection,
            parent_store=self.parent,
            top_k=settings.rag.top_k,
            score_threshold=settings.rag.score_threshold,
            kb_id=kb_id,
        ).create_tools()

        checkpointer_path = self.settings.storage.sqlite_path.replace(".db", "_checkpoints.db")

        self._graph = create_agent_graph(
            llm=llm,
            tools_list=tools,
            long_term_memory_store=self.long_term_memory_store,
            sqlite_store=self.sqlite,
            settings=settings,
            checkpointer_path=checkpointer_path,
        )
        self._checkpointer_conn = getattr(self._graph, '_checkpointer_conn', None)
        if self._checkpointer_conn is not None:
            self._checkpointer_conns.append(self._checkpointer_conn)
        return self._graph

    async def close(self):
        """关闭时释放数据库连接等资源"""
        logger.info("container.close.start")
        for conn in self._checkpointer_conns:
            try:
                conn.close()
            except Exception:
                pass
        self._checkpointer_conns.clear()
        self._graphs.clear()
        if self.qdrant:
            self.qdrant.close()
        logger.info("container.close.done")

    def check_health(self) -> dict:
        """检查各依赖的健康状态，返回 {sqlite, qdrant, ollama} 状态字典"""
        result = {"qdrant": "unknown", "ollama": "unknown", "sqlite": "unknown"}

        try:
            from sqlalchemy import text as sa_text
            self.sqlite.session().execute(sa_text("SELECT 1"))
            result["sqlite"] = "ok"
        except Exception as e:
            result["sqlite"] = f"error: {e}"

        try:
            if self.qdrant and self.qdrant.collection_exists():
                result["qdrant"] = "ok"
            elif self.qdrant:
                result["qdrant"] = "ok (collection pending)"
            else:
                result["qdrant"] = "uninitialized"
        except Exception as e:
            result["qdrant"] = f"error: {e}"

        try:
            import httpx
            resp = httpx.get(
                f"{self.settings.llm.ollama_base_url}/api/tags",
                timeout=5,
                **_http_client_kwargs(self.settings.llm.ollama_base_url),
            )
            if resp.status_code == 200:
                result["ollama"] = "ok"
            else:
                result["ollama"] = f"status {resp.status_code}"
        except Exception as e:
            result["ollama"] = f"unavailable: {e}"

        return result

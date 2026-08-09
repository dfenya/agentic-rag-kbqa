"""依赖注入容器，管理所有 store/service/RAG 图的创建和生命周期

在 app lifespan 里调 init() 初始化，close() 释放资源。
"""

import structlog
from langchain_ollama import ChatOllama

from app.core.config import Settings
from app.stores.sqlite_store import SqliteStore
from app.stores.qdrant_store import QdrantStore
from app.stores.parent_store import ParentStore
from app.stores.long_term_memory_store import LongTermMemoryStore
from app.services.conversation_service import ConversationService
from app.services.document_service import DocumentService
from app.services.long_term_memory_service import LongTermMemoryService

logger = structlog.get_logger()


class Container:
    """手动依赖注入容器，启动时 init()，关闭时 close()"""

    def __init__(self, settings: Settings):
        self.settings = settings

        self.sqlite: SqliteStore | None = None
        self.qdrant: QdrantStore | None = None
        self.parent: ParentStore | None = None
        self.long_term_memory_store: LongTermMemoryStore | None = None

        self.conversation_service: ConversationService | None = None
        self.document_service: DocumentService | None = None
        self.long_term_memory_service: LongTermMemoryService | None = None

        self._graph = None
        self._checkpointer_conn = None

    def create_llm(self, **overrides) -> ChatOllama:
        """创建 ChatOllama 实例，所有 LLM 调用都从这里走"""
        return ChatOllama(
            model=overrides.get("model", self.settings.llm.model),
            temperature=overrides.get("temperature", self.settings.llm.temperature),
            base_url=overrides.get("base_url", self.settings.llm.ollama_base_url),
            num_ctx=overrides.get("num_ctx", self.settings.llm.num_ctx),
        )

    @property
    def graph(self):
        return self._graph

    def compile_graph(self, kb_id: str | None = None):
        """编译/重编译 LangGraph agent 图，按知识库隔离检索"""
        self._compile_graph(kb_id=kb_id)
        return self._graph

    async def init(self):
        """启动时初始化：SQLite → Qdrant → 业务服务 → RAG 图"""
        logger.info("container.init.start")

        self.sqlite = SqliteStore(self.settings.storage.sqlite_path)
        self.sqlite.create_all()
        logger.info("container.sqlite.ready")

        self.qdrant = QdrantStore(self.settings)
        self.qdrant.init()
        self.qdrant.create_collection()

        self.parent = ParentStore(self.qdrant.client)

        self.long_term_memory_store = LongTermMemoryStore(self.settings)
        self.long_term_memory_store.init(self.qdrant.client, self.qdrant._dense)

        logger.info("container.stores.ready")

        self.conversation_service = ConversationService(self.sqlite)
        self.document_service = DocumentService(self.sqlite, self.qdrant, self.parent)
        self.long_term_memory_service = LongTermMemoryService(self.sqlite, self.long_term_memory_store)

        logger.info("container.services.ready")

        # RAG 图需要 Ollama 在线才能编译
        try:
            self._compile_graph()
            logger.info("container.graph.ready")
        except Exception as e:
            logger.warning("container.graph.unavailable", error=str(e))

        logger.info("container.init.done")

    def _compile_graph(self, kb_id: str | None = None):
        from app.rag.tools import ToolFactory
        from app.rag.graph import create_agent_graph

        llm = self.create_llm()

        collection = self.qdrant.as_vector_store()
        tools = ToolFactory(
            collection=collection,
            parent_store=self.parent,
            top_k=self.settings.rag.top_k,
            score_threshold=self.settings.rag.score_threshold,
            kb_id=kb_id,
        ).create_tools()

        checkpointer_path = self.settings.storage.sqlite_path.replace(".db", "_checkpoints.db")

        self._graph = create_agent_graph(
            llm=llm,
            tools_list=tools,
            long_term_memory_store=self.long_term_memory_store,
            sqlite_store=self.sqlite,
            checkpointer_path=checkpointer_path,
            old_checkpointer_conn=self._checkpointer_conn,
        )
        self._checkpointer_conn = getattr(self._graph, '_checkpointer_conn', None)

    async def close(self):
        """关闭时释放数据库连接等资源"""
        logger.info("container.close.start")
        if self._checkpointer_conn:
            try:
                self._checkpointer_conn.close()
            except Exception:
                pass
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
            resp = httpx.get(f"{self.settings.llm.ollama_base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                result["ollama"] = "ok"
            else:
                result["ollama"] = f"status {resp.status_code}"
        except Exception as e:
            result["ollama"] = f"unavailable: {e}"

        return result

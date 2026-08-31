"""RAG agent 的 LangChain 工具。

改编自 project/rag_agent/tools.py。
主要变更：
  - 父块存储从 Qdrant payload 读取（而非 MongoDB）
  - search_child_chunks 通过 kb_id 支持知识库级别隔离
  - 用构造函数注入替代全局导入
"""

from typing import List, Optional

from langchain_core.tools import tool
from langchain_qdrant import QdrantVectorStore
from qdrant_client.http import models as qmodels

from app.stores.parent_store import ParentStore


class ToolFactory:
    """创建绑定到当前 Qdrant 和父块存储的 LangChain 工具。"""

    def __init__(
        self,
        collection: QdrantVectorStore,
        parent_store: ParentStore,
        top_k: int = 5,
        score_threshold: float = 0.7,
        kb_id: Optional[str] = None,
    ):
        self.collection = collection
        self.parent_store = parent_store
        self.top_k = top_k
        self.score_threshold = score_threshold
        self.kb_id = kb_id

    # ── 工具实现 ──

    def _search_child_chunks(self, query: str, limit=None) -> str:
        """通过混合检索搜索最相关的文档子块。

        Args:
            query: 检索查询字符串，建议使用文档中的专业术语。
            limit: 最大结果数（默认：配置的 top_k）。
        """
        # 清洗 limit 参数：LLM 可能传入 dict（如 {"default": 5}）或 None
        if isinstance(limit, dict):
            limit = limit.get("default") or limit.get("value") or list(limit.values())[0] if limit else None
        try:
            k = int(limit) if limit is not None else self.top_k
        except (ValueError, TypeError):
            k = self.top_k
        try:
            # 构造检索参数，可选附带知识库过滤
            search_kwargs = {"k": k, "score_threshold": self.score_threshold}
            filter_conditions = []
            filter_conditions.append(
                qmodels.FieldCondition(
                    key="metadata.publish_status",
                    match=qmodels.MatchValue(value="active"),
                )
            )
            if self.kb_id:
                filter_conditions.append(
                    qmodels.FieldCondition(
                        key="metadata.kb_id",
                        match=qmodels.MatchValue(value=self.kb_id),
                    )
                )
            if filter_conditions:
                search_kwargs["filter"] = qmodels.Filter(must=filter_conditions)

            results = self.collection.similarity_search(query, **search_kwargs)
            # Qdrant 是最终一致的外部存储；即使补偿清理暂时失败，也必须由
            # SQLite 发布清单做第二道校验，禁止 ERROR/staging 文档进入回答。
            results = [
                doc for doc in results
                if self.parent_store.is_document_published(
                    str(doc.metadata.get("doc_id", ""))
                )
            ]
            if not results:
                return "NO_RELEVANT_CHUNKS"

            return "\n\n".join([
                f"Parent ID: {doc.metadata.get('parent_id', '')}\n"
                f"来源文档: {doc.metadata.get('source', '')}\n"
                f"内容: {doc.page_content.strip()}"
                for doc in results
            ])
        except Exception as e:
            return f"RETRIEVAL_ERROR: {str(e)}"

    def _retrieve_parent_chunks(self, parent_ids=None) -> str:
        """一次性获取多个完整的父块。

        Args:
            parent_ids: 父块 ID 列表（字符串或列表）。
        """
        try:
            # 清洗参数：LLM 可能传入各种格式
            if parent_ids is None:
                return "NO_PARENT_DOCUMENTS"
            if isinstance(parent_ids, str):
                ids = [parent_ids]
            elif isinstance(parent_ids, dict):
                # LLM 可能传入 {"parent_ids": [...], ...} 或 {"default": [...]}
                raw = parent_ids.get("parent_ids") or parent_ids.get("parent_id") or parent_ids.get("ids") or parent_ids.get("default") or []
                ids = [raw] if isinstance(raw, str) else list(raw) if raw else []
            elif isinstance(parent_ids, (list, tuple)):
                ids = list(parent_ids)
            else:
                ids = [str(parent_ids)]
            if not ids:
                return "NO_PARENT_DOCUMENTS"
            raw_parents = self.parent_store.load_content_many(
                ids, kb_id=self.kb_id
            )
            if not raw_parents:
                return "NO_PARENT_DOCUMENTS"
            return "\n\n".join([
                f"Parent ID: {doc.get('parent_id', 'n/a')}\n"
                f"来源文档: {doc.get('metadata', {}).get('source', 'unknown')}\n"
                f"完整内容: {doc.get('content', '').strip()}"
                for doc in raw_parents
            ])
        except Exception as e:
            return f"PARENT_RETRIEVAL_ERROR: {str(e)}"

    # ── 公共工厂 ──

    def create_tools(self) -> List:
        """返回供 agent 图使用的 LangChain 工具对象。"""
        search_tool = tool("search_child_chunks")(self._search_child_chunks)
        retrieve_tool = tool("retrieve_parent_chunks")(self._retrieve_parent_chunks)
        return [search_tool, retrieve_tool]

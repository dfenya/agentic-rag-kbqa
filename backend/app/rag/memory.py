"""长期记忆的加载和存储逻辑

load_long_term_memories：每轮对话开始时调用，把相关的长期记忆注入 state.long_term_memory_context
store_long_term_memories：每轮对话结束时调用，从对话中提取新的记忆并写入

注意：这里只处理「长期记忆」（跨对话持久化的用户偏好/FAQ/历史摘要，存 Qdrant+SQLite）。
「短期/工作记忆」即当前对话上下文（messages 序列），由 LangGraph SqliteSaver 持久化，
不在本模块处理。
"""

import json
from typing import List, Optional

import structlog

from app.core.config import Settings, get_settings
from app.stores.sqlite_store import SqliteStore
from app.stores.long_term_memory_store import LongTermMemoryStore
from app.rag.retry import retry_invoke
from app.domain.enums import LongTermMemoryType


logger = structlog.get_logger()


# ── 加载 ──


def load_long_term_memories(
    query: str,
    *,
    long_term_memory_store: LongTermMemoryStore,
    sqlite: SqliteStore,
    settings: Settings,
) -> str:
    """根据用户当前提问搜索相关的长期记忆，返回一段上下文文本

    搜到的片段由调用方写入 state.long_term_memory_context，供 rewrite/orchestrator/
    aggregate 节点参考用户偏好和历史。短期/工作记忆（当前对话上下文）不在此处理。
    """
    if not settings.long_term_memory.enabled:
        return ""

    try:
        results = long_term_memory_store.search(query, k=settings.long_term_memory.top_k)
        if not results:
            return ""

        # 从 SQLite 取完整记录，按 重要性×访问次数 排序
        mem_ids = [r["id"] for r in results]
        all_memories = {m.id: m for m in sqlite.mem_all()}
        relevant = [all_memories[mid] for mid in mem_ids if mid in all_memories]
        if not relevant:
            return ""

        relevant.sort(key=lambda m: m.importance * m.access_count, reverse=True)

        lines = ["## 长期记忆（仅作个性化参考，不代表知识库事实依据）"]
        for m in relevant[:5]:
            type_label = {
                LongTermMemoryType.USER_PREFERENCE.value: "[用户偏好]",
                LongTermMemoryType.FAQ_PATTERN.value: "[高频问题]",
                LongTermMemoryType.CONVERSATION_SUMMARY.value: "[历史对话]",
            }.get(m.type, "[记忆]")
            lines.append(f"{type_label} {m.content}")

            # 原子递增访问计数，避免并发竞态
            sqlite.mem_increment_access(m.id)

        return "\n".join(lines)

    except Exception as e:
        logger.warning("long_term_memory.load.error", error=str(e))
        return ""


# ── 存储 ──


def store_long_term_memories(
    conversation_text: str,
    *,
    llm,
    long_term_memory_store: LongTermMemoryStore,
    sqlite: SqliteStore,
    settings: Settings,
    conversation_id: str = "",
) -> int:
    """从一轮对话中提取记忆候选，去重后写入。

    规则：
    - conversation_summary：同一会话始终更新同一条记录（覆盖为最新、最完整的摘要）
    - faq_pattern：系统自动生成（同类摘要被命中 3+ 次自动升级），不由 LLM 直接产生
    - user_preference：相似内容合并，严格按 prompt 规则，宁缺勿滥

    返回新创建/更新的记忆条数。
    """
    if not settings.long_term_memory.enabled:
        return 0

    try:
        from app.rag.schemas import LongTermMemoryExtraction
        from app.rag.prompts.legal import MEMORY_EXTRACTION_PROMPT
        from langchain_core.messages import SystemMessage, HumanMessage

        llm_structured = llm.with_config(temperature=0).with_structured_output(LongTermMemoryExtraction)
        result: LongTermMemoryExtraction = retry_invoke(
            llm_structured.invoke,
            [SystemMessage(content=MEMORY_EXTRACTION_PROMPT.format(conversation=conversation_text)),
             HumanMessage(content="请提取对话中的长期记忆。")],
        )

        # 预加载全量记忆，避免循环内重复查询
        all_mems = sqlite.mem_all()

        created = 0
        for item in result.items:
            item_type = item.type.value if hasattr(item.type, "value") else str(item.type)

            # ── conversation_summary：同一会话始终覆盖更新 ──
            if item_type == LongTermMemoryType.CONVERSATION_SUMMARY.value and conversation_id:
                existing_summary = next(
                    (m for m in all_mems
                     if m.source_conversation_id == conversation_id
                     and m.type == LongTermMemoryType.CONVERSATION_SUMMARY.value),
                    None,
                )
                if existing_summary:
                    # 覆盖为最新摘要（覆盖整个会话迄今的内容）
                    sqlite.mem_update(
                        existing_summary.id,
                        content=item.content,
                        access_count=existing_summary.access_count + 1,
                        keywords_json=json.dumps(item.keywords, ensure_ascii=False),
                    )
                    long_term_memory_store.upsert(existing_summary.id, item.content, {
                        "type": item_type,
                        "keywords": item.keywords,
                        "importance": existing_summary.importance,
                    })
                    created += 1
                    continue
                # 不存在则走下面的新建逻辑

            # ── user_preference：相似内容合并 + FAQ 自动升级 ──
            existing = long_term_memory_store.search(item.content, k=1)
            if existing and existing[0]["score"] >= settings.long_term_memory.merge_threshold:
                mem_id = existing[0]["id"]
                existing_mem = next((m for m in all_mems if m.id == mem_id), None)
                if existing_mem:
                    new_count = existing_mem.access_count + 1
                    new_content = (
                        item.content
                        if len(item.content) > len(existing_mem.content)
                        else existing_mem.content
                    )
                    new_type = existing_mem.type
                    if new_count >= 3 and existing_mem.type == LongTermMemoryType.CONVERSATION_SUMMARY.value:
                        new_type = LongTermMemoryType.FAQ_PATTERN.value
                        logger.info("long_term_memory.promote_faq", mem_id=mem_id, hits=new_count)

                    sqlite.mem_update(
                        mem_id,
                        content=new_content,
                        type=new_type,
                        importance=min(1.0, existing_mem.importance + 0.05),
                        access_count=new_count,
                        keywords_json=json.dumps(item.keywords, ensure_ascii=False),
                    )
                    long_term_memory_store.upsert(mem_id, new_content, {
                        "type": new_type,
                        "keywords": item.keywords,
                        "importance": min(1.0, existing_mem.importance + 0.05),
                    })
                    created += 1
                    continue

            # ── 全新记忆：直接插入 ──
            mem = sqlite.mem_insert(
                type=item_type,
                content=item.content,
                keywords_json=json.dumps(item.keywords, ensure_ascii=False),
                importance=0.5,
                access_count=1,
                source_conversation_id=conversation_id or None,
            )
            long_term_memory_store.upsert(mem.id, item.content, {
                "type": item_type,
                "keywords": item.keywords,
                "importance": 0.5,
            })
            created += 1

        # LRU 淘汰：超过最大条数就删掉访问最少的
        total = sqlite.mem_count()
        if total > settings.long_term_memory.max_records:
            deleted = sqlite.mem_delete_least_accessed(settings.long_term_memory.max_records)
            logger.info("long_term_memory.evicted", deleted=deleted)

        return created

    except Exception as e:
        logger.warning("long_term_memory.store.error", error=str(e))
        return 0

"""长期记忆的加载和存储逻辑

load_long_term_memories：每轮对话开始时调用，把相关的长期记忆注入 state.long_term_memory_context
store_long_term_memories：每轮对话结束时调用，从对话中提取新的记忆并写入

注意：这里只处理「长期记忆」（跨对话持久化的用户偏好/FAQ/历史摘要，存 Qdrant+SQLite）。
「短期/工作记忆」即当前对话上下文（messages 序列），由 LangGraph SqliteSaver 持久化，
不在本模块处理。
"""

import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import structlog

from app.core.config import Settings, get_settings
from app.stores.sqlite_store import SqliteStore
from app.stores.long_term_memory_store import LongTermMemoryStore
from app.rag.retry import retry_invoke
from app.domain.enums import LongTermMemoryType


logger = structlog.get_logger()

# 按记忆类型的初始重要性：摘要参考性最弱，FAQ 可信度最高
_TYPE_INITIAL_IMPORTANCE = {
    LongTermMemoryType.CONVERSATION_SUMMARY.value: 0.3,
    LongTermMemoryType.USER_PREFERENCE.value: 0.6,
    LongTermMemoryType.FAQ_PATTERN.value: 0.8,
}

# recency 衰减权重
_RECENCY_WEIGHTS = [
    (timedelta(days=1), 1.3),       # 24 小时内
    (timedelta(days=7), 1.1),       # 一周内
    (timedelta(days=30), 1.0),      # 一月内
    (None, 0.85),                   # 更早
]


# ── 加载 ──


def load_long_term_memories(
    query: str,
    *,
    long_term_memory_store: LongTermMemoryStore,
    sqlite: SqliteStore,
    settings: Settings,
    conversation_id: str = "",
) -> str:
    """根据用户当前提问搜索相关的长期记忆，返回一段上下文文本

    搜到的片段由调用方写入 state.long_term_memory_context，供 rewrite/orchestrator/
    aggregate 节点参考用户偏好和历史。短期/工作记忆（当前对话上下文）不在此处理。

    如果指定了 conversation_id，则只加载该会话的记忆（会话级隔离），
    不指定则加载全局记忆（兼容旧行为）。
    """
    if not settings.long_term_memory.enabled:
        return ""

    try:
        results = long_term_memory_store.search(query, k=settings.long_term_memory.top_k)
        if not results:
            return ""

        # 从 SQLite 取完整记录，按 conversation_id 过滤后按 重要性×访问次数 排序
        mem_ids = [r["id"] for r in results]
        all_memories = {
            m.id: m for m in sqlite.mem_list_by_ids(mem_ids, conversation_id=conversation_id or None)
        }
        relevant = [all_memories[mid] for mid in mem_ids if mid in all_memories]
        if not relevant:
            return ""

        now = datetime.now(timezone.utc)
        def _recency_weight(m) -> float:
            age = now - (m.created_at.replace(tzinfo=timezone.utc) if m.created_at.tzinfo is None else m.created_at)
            for threshold, weight in _RECENCY_WEIGHTS:
                if threshold is None or age <= threshold:
                    return weight
            return 1.0  # fallback

        # 融合打分：importance × recency，access_count 作为 tiebreaker
        relevant.sort(key=lambda m: (m.importance * _recency_weight(m), m.access_count), reverse=True)

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
                    new_importance = min(1.0, existing_mem.importance + 0.05)
                    if new_count >= 3 and existing_mem.type == LongTermMemoryType.CONVERSATION_SUMMARY.value:
                        new_type = LongTermMemoryType.FAQ_PATTERN.value
                        new_importance = max(new_importance, _TYPE_INITIAL_IMPORTANCE[LongTermMemoryType.FAQ_PATTERN.value])
                        logger.info("long_term_memory.promote_faq", mem_id=mem_id, hits=new_count)

                    sqlite.mem_update(
                        mem_id,
                        content=new_content,
                        type=new_type,
                        importance=new_importance,
                        access_count=new_count,
                        keywords_json=json.dumps(item.keywords, ensure_ascii=False),
                    )
                    long_term_memory_store.upsert(mem_id, new_content, {
                        "type": new_type,
                        "keywords": item.keywords,
                        "importance": new_importance,
                    })
                    created += 1
                    continue

            # ── 全新记忆：直接插入 ──
            init_importance = _TYPE_INITIAL_IMPORTANCE.get(item_type, 0.5)
            mem = sqlite.mem_insert(
                type=item_type,
                content=item.content,
                keywords_json=json.dumps(item.keywords, ensure_ascii=False),
                importance=init_importance,
                access_count=1,
                source_conversation_id=conversation_id or None,
            )
            long_term_memory_store.upsert(mem.id, item.content, {
                "type": item_type,
                "keywords": item.keywords,
                "importance": init_importance,
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

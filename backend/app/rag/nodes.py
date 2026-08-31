"""LangGraph 节点函数 —— 通用 Agentic RAG 工作流的每一步

节点清单：
  主图：load_long_term_memory → summarize_history → rewrite_query → request_clarification
       → agent(子图) → aggregate_answers
  子图：orchestrator → tools → should_compress → compress → orchestrator（循环）
       → fallback_response → collect_answer

记忆层级：
  短期/工作记忆 = 当前对话上下文（messages，由 SqliteSaver 持久化）
  长期记忆 = 跨对话的用户偏好/FAQ/历史摘要，每轮语义检索后注入 long_term_memory_context
"""

from typing import Literal, Set

from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    RemoveMessage,
    AIMessage,
    ToolMessage,
)
from langgraph.types import Command

from app.rag.graph_state import State, AgentState
from app.rag.schemas import QueryAnalysis
from app.rag.prompts.legal import (
    CONVERSATION_SUMMARY_PROMPT,
    REWRITE_QUERY_PROMPT,
    ORCHESTRATOR_PROMPT,
    FALLBACK_RESPONSE_PROMPT,
    CONTEXT_COMPRESSION_PROMPT,
    AGGREGATION_PROMPT,
)
from app.rag.memory import load_long_term_memories
from app.rag.retry import retry_invoke
from app.rag.token_utils import estimate_tokens
from app.core.config import get_settings


# ── 长期记忆加载 ──


def load_long_term_memory_node(state: State, long_term_memory_store, sqlite_store, settings=None):
    """每轮对话开始前，从长期记忆中语义检索相关片段，注入到 long_term_memory_context

    会话摘要按 conversation_id 隔离；用户偏好和 FAQ 在同一用户内跨会话共享。
    """
    settings = settings or get_settings()
    conv_id = state.get("conversation_id", "")
    last_msg = state["messages"][-1] if state["messages"] else None
    if not last_msg:
        return {"long_term_memory_context": ""}

    query = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
    ctx = load_long_term_memories(
        query,
        long_term_memory_store=long_term_memory_store,
        sqlite=sqlite_store,
        settings=settings,
        conversation_id=conv_id,
        user_id=state.get("user_id", ""),
    )
    return {"long_term_memory_context": ctx}


# ── 对话摘要 ──


def summarize_history(state: State, llm):
    """把对话历史压缩成几句话的摘要，省 token"""
    if len(state["messages"]) < 4:
        return {"conversation_summary": ""}

    relevant = [
        msg for msg in state["messages"][:-1]
        if isinstance(msg, (HumanMessage, AIMessage)) and not getattr(msg, "tool_calls", None)
    ]
    if not relevant:
        return {"conversation_summary": ""}

    conversation = "对话历史:\n"
    for msg in relevant[-6:]:
        role = "用户" if isinstance(msg, HumanMessage) else "助手"
        conversation += f"{role}: {msg.content}\n"

    summary_resp = retry_invoke(
        llm.with_config(temperature=0.2).invoke,
        [SystemMessage(content=CONVERSATION_SUMMARY_PROMPT),
         HumanMessage(content=conversation)],
    )
    return {"conversation_summary": summary_resp.content, "agent_answers": [{"__reset__": True}]}


# ── 查询重写 ──


def rewrite_query(state: State, llm):
    """分析用户的提问，拆成子问题或请求澄清"""
    last_message = state["messages"][-1]
    conv_summary = state.get("conversation_summary", "")
    ltm_ctx = state.get("long_term_memory_context", "")

    kb_name = state.get("kb_name", "")
    context = ""
    if kb_name:
        context += f"## 当前知识库\n你正在检索的知识库名称是「{kb_name}」。请确保生成的查询与知识库内容相关。\n\n"
    if ltm_ctx.strip():
        context += f"## 长期记忆（用户偏好/历史摘要，仅供参考）\n{ltm_ctx}\n\n"
    if conv_summary.strip():
        context += f"## 对话上下文\n{conv_summary}\n"
    context += f"## 用户当前提问\n{last_message.content}\n"

    llm_structured = llm.with_config(temperature=0.1).with_structured_output(QueryAnalysis)
    response = retry_invoke(
        llm_structured.invoke,
        [SystemMessage(content=REWRITE_QUERY_PROMPT),
         HumanMessage(content=context)],
    )

    if response.questions and response.is_clear:
        delete_all = [
            RemoveMessage(id=m.id)
            for m in state["messages"]
            if not isinstance(m, SystemMessage)
        ]
        return {
            "questionIsClear": True,
            "messages": delete_all,
            "originalQuery": last_message.content,
            "rewrittenQuestions": response.questions,
        }

    clarification = (
        response.clarification_needed
        if response.clarification_needed and len(response.clarification_needed.strip()) > 10
        else "我需要更多信息来理解您的问题，请问您能补充一些具体情况吗？"
    )
    return {
        "questionIsClear": False,
        "messages": [AIMessage(content=clarification)],
        "originalQuery": last_message.content,
        # 图在 request_clarification 节点执行前中断，因此必须在这里计数。
        "clarification_count": state.get("clarification_count", 0) + 1,
    }


def request_clarification(state: State):
    """占位——图在执行此节点前中断，等待用户补充信息。"""
    return {}


# ── Agent 子图节点 ──


def orchestrator(state: AgentState, llm_with_tools, settings=None):
    """Agent 大脑：决定搜索、回溯父块、还是直接回答"""
    ctx_summary = state.get("context_summary", "").strip()
    sys_msg = SystemMessage(content=ORCHESTRATOR_PROMPT)

    summary_injection = (
        [HumanMessage(content=f"[此前研究的压缩上下文]\n\n{ctx_summary}")]
        if ctx_summary else []
    )

    # ── 注入长期记忆（用户身份/偏好/历史），让检索关键词更贴合用户背景 ──
    ltm_ctx = state.get("long_term_memory_context", "").strip()
    memory_injection = (
        [HumanMessage(content=f"[用户画像与历史记忆]\n{ltm_ctx}\n"
                              f"（仅供理解用户意图、调整检索关键词方向，不作为事实依据）")]
        if ltm_ctx else []
    )
    summary_injection = memory_injection + summary_injection

    # ── 调用 LLM 前预检 token 数，超限则跳过 LLM 直接标记需要压缩 ──
    if state.get("messages"):
        all_msgs = [sys_msg] + summary_injection + state["messages"]
        estimated = estimate_tokens(all_msgs)
        settings = settings or get_settings()
        safe_limit = int(settings.llm.num_ctx * 0.75)  # 模型上下文窗口的 75%
        if estimated > safe_limit:
            # 不调 LLM，返回一个虚拟消息，让路由走到 fallback_response 或 collect_answer
            from langchain_core.messages import AIMessage as AIMsg
            dummy = AIMsg(
                content="",
                tool_calls=[],
                response_metadata={"__force_compress__": True},
            )
            return {
                "messages": [dummy],
                "tool_call_count": 0,
                "iteration_count": 1,
            }

    if not state.get("messages"):
        human_msg = HumanMessage(content=state["question"])
        force_search = HumanMessage(
            content="你必须首先调用 'search_child_chunks' 来检索知识库中的相关内容。"
        )
        response = retry_invoke(
            llm_with_tools.invoke,
            [sys_msg] + summary_injection + [human_msg, force_search],
        )
        return {
            "messages": [human_msg, response],
            "tool_call_count": len(response.tool_calls or []),
            "iteration_count": 1,
        }

    response = retry_invoke(
        llm_with_tools.invoke,
        [sys_msg] + summary_injection + state["messages"],
    )
    tool_calls = response.tool_calls if hasattr(response, "tool_calls") else []
    return {
        "messages": [response],
        "tool_call_count": len(tool_calls) if tool_calls else 0,
        "iteration_count": 1,
    }


def fallback_response(state: AgentState, llm, settings=None):
    """熔断兜底：达到最大轮次时强制用已有数据生成回答"""
    seen = set()
    unique_contents = []
    for m in state["messages"]:
        if isinstance(m, ToolMessage) and m.content not in seen:
            content = str(m.content)
            # 每条工具结果最多保留 1500 字符
            if len(content) > 1500:
                content = content[:1500] + "\n…[已截断]"
            unique_contents.append(content)
            seen.add(m.content)

    ctx_summary = state.get("context_summary", "").strip()
    context_parts = []
    if ctx_summary:
        context_parts.append(f"## 压缩研究上下文\n\n{ctx_summary}")
    if unique_contents:
        context_parts.append(
            "## 检索到的知识库数据\n\n"
            + "\n\n".join(f"--- 数据源 {i} ---\n{c}" for i, c in enumerate(unique_contents, 1))
        )
    context_text = "\n\n".join(context_parts) if context_parts else "未能从文档中检索到任何数据。"

    # 安全截断：总 prompt 不能超过 num_ctx 的 60%
    settings = settings or get_settings()
    max_chars = int(settings.llm.num_ctx * 0.6 / 1.5)
    if len(context_text) > max_chars:
        context_text = context_text[:max_chars] + "\n…[内容过长，已截断]"

    prompt = (
        f"用户问题: {state.get('question')}\n\n"
        f"{context_text}\n\n"
        f"指令: 仅使用以上数据提供最佳回答。"
    )
    response = retry_invoke(
        llm.invoke,
        [SystemMessage(content=FALLBACK_RESPONSE_PROMPT),
         HumanMessage(content=prompt)],
    )
    return {"messages": [response]}


# ── 上下文压缩 ──


def should_compress_context(state: AgentState, settings=None) -> Command[Literal["compress_context", "orchestrator"]]:
    """检查 token 是否超标，决定压缩还是继续"""
    settings = settings or get_settings()
    messages = state["messages"]
    new_ids: Set[str] = set()

    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                if tc["name"] == "retrieve_parent_chunks":
                    raw = tc["args"].get("parent_id") or tc["args"].get("parent_ids") or tc["args"].get("ids") or []
                    if isinstance(raw, str):
                        new_ids.add(f"parent::{raw}")
                    else:
                        new_ids.update(f"parent::{r}" for r in raw)
                elif tc["name"] == "search_child_chunks":
                    query = tc["args"].get("query", "")
                    if query:
                        new_ids.add(f"search::{query}")
            break

    updated_ids = state.get("retrieval_keys", set()) | new_ids
    current_tokens = estimate_tokens(messages)
    summary_tokens = estimate_tokens([HumanMessage(content=state.get("context_summary", ""))])
    max_allowed = settings.rag.base_token_threshold + int(summary_tokens * settings.rag.token_growth_factor)

    goto = "compress_context" if current_tokens > max_allowed else "orchestrator"
    return Command(update={"retrieval_keys": updated_ids}, goto=goto)


def compress_context(state: AgentState, llm, settings=None):
    """把冗长的工具调用记录压缩成结构化摘要"""
    messages = state["messages"]
    existing_summary = state.get("context_summary", "").strip()
    if not messages:
        return {}

    conversation_text = f"用户问题: {state.get('question')}\n\n待压缩对话:\n\n"
    if existing_summary:
        conversation_text += f"[先前压缩上下文]\n{existing_summary}\n\n"

    for msg in messages[1:]:
        if isinstance(msg, AIMessage):
            tool_info = ""
            if getattr(msg, "tool_calls", None):
                calls = ", ".join(
                    f"{tc['name']}({tc['args']})" for tc in msg.tool_calls
                )
                tool_info = f" | 工具调用: {calls}"
            conversation_text += f"[助手{tool_info}]\n{msg.content or '(仅工具调用)'}\n\n"
        elif isinstance(msg, ToolMessage):
            name = getattr(msg, "name", "工具")
            content = str(msg.content) if msg.content else "(无结果)"
            # 每个工具结果最多保留 2000 字符，避免压缩输入本身超限
            if len(content) > 2000:
                content = content[:2000] + "\n…[已截断]"
            conversation_text += f"[工具结果 — {name}]\n{content}\n\n"

    # 安全截断：压缩输入总长度不超过 num_ctx * 0.6 个 token（按 1.5 token/char 估算）
    settings = settings or get_settings()
    max_chars = int(settings.llm.num_ctx * 0.6 / 1.5)
    if len(conversation_text) > max_chars:
        conversation_text = conversation_text[:max_chars] + "\n…[输入过长，已截断]"

    summary_resp = retry_invoke(
        llm.invoke,
        [SystemMessage(content=CONTEXT_COMPRESSION_PROMPT),
         HumanMessage(content=conversation_text)],
    )
    new_summary = summary_resp.content

    # 防重复：把已经搜过的查询和取过的父块 id 硬编码在摘要末尾
    retrieved_ids: Set[str] = state.get("retrieval_keys", set())
    if retrieved_ids:
        parent_ids = sorted(r for r in retrieved_ids if r.startswith("parent::"))
        search_queries = sorted(
            r.replace("search::", "") for r in retrieved_ids if r.startswith("search::")
        )
        block = "\n\n---\n**已执行，请勿重复:**\n"
        if parent_ids:
            block += "已回溯的父块:\n" + "\n".join(f"- {p.replace('parent::', '')}" for p in parent_ids) + "\n"
        if search_queries:
            block += "已搜索的关键词:\n" + "\n".join(f"- {q}" for q in search_queries) + "\n"
        new_summary += block

    return {
        "context_summary": new_summary,
        "messages": [RemoveMessage(id=m.id) for m in messages[1:]],
    }


def collect_answer(state: AgentState):
    """子图结束，把最终回答收集起来"""
    last = state["messages"][-1]
    is_valid = isinstance(last, AIMessage) and last.content and not last.tool_calls
    answer = last.content if is_valid else "无法生成回答。"
    return {
        "final_answer": answer,
        "agent_answers": [{
            "index": state["question_index"],
            "question": state["question"],
            "answer": answer,
        }],
    }


# ── 答案汇总 ──


def aggregate_answers(state: State, llm):
    """把并行 agent 的结果合成一份连贯的分析回答"""
    if not state.get("agent_answers"):
        return {"messages": [AIMessage(content="未能生成任何回答。")]}

    sorted_answers = sorted(state["agent_answers"], key=lambda x: x["index"])
    formatted = ""
    for i, ans in enumerate(sorted_answers, start=1):
        formatted += f"\n答案 {i}:\n{ans['answer']}\n"

    # ── 注入长期记忆（用户偏好/历史对话等），让最终回答体现个性化风格 ──
    ltm_ctx = state.get("long_term_memory_context", "").strip()
    user_text = f"用户原始问题: {state['originalQuery']}\n检索到的答案:{formatted}"
    if ltm_ctx:
        user_text = (
            f"{ltm_ctx}\n\n"
            f"（以上长期记忆仅供调整回答风格/语言/详略等个性化呈现使用，"
            f"事实内容必须且只能基于下方检索到的答案）\n\n{user_text}"
        )
    user_msg = HumanMessage(content=user_text)
    synthesis = retry_invoke(
        llm.invoke,
        [SystemMessage(content=AGGREGATION_PROMPT), user_msg],
    )
    return {"messages": [AIMessage(content=synthesis.content)]}

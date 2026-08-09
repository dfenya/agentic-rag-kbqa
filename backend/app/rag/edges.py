"""LangGraph 路由边，决定图在每个分叉点走哪条路"""

from typing import Literal

from langgraph.types import Send

from app.rag.graph_state import State, AgentState
from app.core.config import get_settings


def route_after_rewrite(state: State) -> Literal["request_clarification", "agent"]:
    """查询分析完后：意图不清就追问，清楚就把子问题分发给多个 agent 并行"""
    if not state.get("questionIsClear", False):
        clarification_count = state.get("clarification_count", 0)
        if clarification_count >= 3:
            return [
                Send(
                    "agent",
                    {
                        "question": state["messages"][-1].content if state["messages"] else state.get("originalQuery", ""),
                        "question_index": 0,
                        "messages": [],
                        "long_term_memory_context": state.get("long_term_memory_context", ""),
                    },
                )
            ]
        return "request_clarification"

    ltm_ctx = state.get("long_term_memory_context", "")
    return [
        Send(
            "agent",
            {
                "question": query,
                "question_index": idx,
                "messages": [],
                "long_term_memory_context": ltm_ctx,
            },
        )
        for idx, query in enumerate(state["rewrittenQuestions"])
    ]


def route_after_orchestrator_call(
    state: AgentState,
) -> Literal["tools", "fallback_response", "collect_answer", "compress_context"]:
    """Agent 思考完后：调工具、熔断兜底、收集答案、还是压缩上下文"""
    settings = get_settings()
    iteration = state.get("iteration_count", 0)
    tool_count = state.get("tool_call_count", 0)

    if iteration >= settings.rag.max_iterations or tool_count > settings.rag.max_tool_calls:
        return "fallback_response"

    last = state["messages"][-1]

    if getattr(last, "response_metadata", None) and last.response_metadata.get("__force_compress__"):
        return "compress_context"

    tool_calls = getattr(last, "tool_calls", None) or []
    if not tool_calls:
        return "collect_answer"
    return "tools"

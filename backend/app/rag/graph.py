"""LangGraph 图工厂，编译带记忆和持久化检查点的 RAG agent"""

import sqlite3
from functools import partial

from langgraph.graph import START, END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite import SqliteSaver

from app.rag.graph_state import State, AgentState
from app.rag.nodes import (
    load_long_term_memory_node,
    summarize_history,
    rewrite_query,
    request_clarification,
    orchestrator,
    fallback_response,
    should_compress_context,
    compress_context,
    collect_answer,
    aggregate_answers,
)
from app.rag.edges import route_after_rewrite, route_after_orchestrator_call


def create_agent_graph(
    llm,
    tools_list,
    *,
    long_term_memory_store=None,
    sqlite_store=None,
    settings=None,
    checkpointer_path: str = ":memory:",
    old_checkpointer_conn=None,
):
    if old_checkpointer_conn is not None:
        try:
            old_checkpointer_conn.close()
        except Exception:
            pass

    llm_with_tools = llm.bind_tools(tools_list)
    tool_node = ToolNode(tools_list)

    conn = sqlite3.connect(
        checkpointer_path,
        check_same_thread=False,
        timeout=30,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    checkpointer = SqliteSaver(conn)

    # Agent 子图
    agent_builder = StateGraph(AgentState)
    agent_builder.add_node(
        "orchestrator",
        partial(orchestrator, llm_with_tools=llm_with_tools, settings=settings),
    )
    agent_builder.add_node("tools", tool_node)
    agent_builder.add_node(
        "compress_context", partial(compress_context, llm=llm, settings=settings)
    )
    agent_builder.add_node(
        "fallback_response", partial(fallback_response, llm=llm, settings=settings)
    )
    agent_builder.add_node(
        "should_compress_context", partial(should_compress_context, settings=settings)
    )
    agent_builder.add_node("collect_answer", collect_answer)

    agent_builder.add_edge(START, "orchestrator")
    agent_builder.add_conditional_edges(
        "orchestrator",
        partial(route_after_orchestrator_call, settings=settings),
        {"tools": "tools", "fallback_response": "fallback_response", "collect_answer": "collect_answer", "compress_context": "compress_context"},
    )
    agent_builder.add_edge("tools", "should_compress_context")
    agent_builder.add_edge("compress_context", "orchestrator")
    agent_builder.add_edge("fallback_response", "collect_answer")
    agent_builder.add_edge("collect_answer", END)

    agent_subgraph = agent_builder.compile()

    # 主图
    graph_builder = StateGraph(State)

    if long_term_memory_store and sqlite_store:
        graph_builder.add_node(
            "load_long_term_memory",
            partial(
                load_long_term_memory_node,
                long_term_memory_store=long_term_memory_store,
                sqlite_store=sqlite_store,
                settings=settings,
            ),
        )
    graph_builder.add_node("summarize_history", partial(summarize_history, llm=llm))
    graph_builder.add_node("rewrite_query", partial(rewrite_query, llm=llm))
    graph_builder.add_node("request_clarification", request_clarification)
    graph_builder.add_node("agent", agent_subgraph)
    graph_builder.add_node("aggregate_answers", partial(aggregate_answers, llm=llm))

    if long_term_memory_store and sqlite_store:
        graph_builder.add_edge(START, "load_long_term_memory")
        graph_builder.add_edge("load_long_term_memory", "summarize_history")
    else:
        graph_builder.add_edge(START, "summarize_history")

    graph_builder.add_edge("summarize_history", "rewrite_query")
    graph_builder.add_conditional_edges(
        "rewrite_query",
        route_after_rewrite,
        {"request_clarification": "request_clarification", "agent": "agent"},
    )
    graph_builder.add_edge("request_clarification", "rewrite_query")
    graph_builder.add_edge(["agent"], "aggregate_answers")
    graph_builder.add_edge("aggregate_answers", END)

    agent_graph = graph_builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["request_clarification"],
    )
    agent_graph._checkpointer_conn = conn
    return agent_graph

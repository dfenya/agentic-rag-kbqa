"""对话服务，后台线程跑 LangGraph，通过 asyncio.Queue 桥接到 SSE 流

LangGraph 节点是同步的（Ollama 调用会阻塞），FastAPI 是异步的。
用线程 + asyncio.Queue 桥接两边。
"""

import asyncio
import json
import threading
import time
import uuid
from typing import AsyncGenerator, Optional

import structlog
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk, ToolMessage, SystemMessage

from app.core.config import get_settings
from app.core.container import Container
from app.rag.prompts.legal import PLAIN_LLM_SYSTEM_PROMPT
from app.services.chat_utils import format_sse, extract_sources

logger = structlog.get_logger()

# 系统节点，只在状态栏显示提示，不展示完整输出
SYSTEM_NODES = {"summarize_history", "rewrite_query", "load_long_term_memory"}

NODE_LABELS = {
    "load_long_term_memory": "加载长期记忆",
    "summarize_history": "整理对话历史",
    "rewrite_query": "分析与改写问题",
    "request_clarification": "等待补充信息",
    "agent": "检索知识库",
    "llm": "LLM 生成回答",
    "orchestrator": "Agent 决策",
    "tools": "执行工具",
    "compress_context": "压缩上下文",
    "fallback_response": "生成兜底回答",
    "collect_answer": "收集子答案",
    "aggregate_answers": "答案聚合",
}

# agent 子图内部的节点，对外统一显示为 "agent"
AGENT_INTERNAL_NODES = {"orchestrator", "tools", "compress_context", "fallback_response", "collect_answer"}


class ChatService:
    """执行 RAG 图和纯 LLM 对话，生成 SSE 事件流"""

    def __init__(self, container: Container):
        self._container = container
        self._semaphore = asyncio.Semaphore(4)

    async def stream_chat(
        self,
        message: str,
        *,
        conversation_id: Optional[str] = None,
        kb_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """SSE 事件生成器，给 POST /chat/stream 用"""
        async with self._semaphore:
            queue: asyncio.Queue = asyncio.Queue()
            cancel_event = threading.Event()
            conv_id = conversation_id or str(uuid.uuid4())

            def runner():
                try:
                    # 没选知识库 → 纯 LLM 对话，不走检索和图
                    if not kb_id:
                        self._run_plain_llm(conv_id, message.strip(), queue, cancel_event)
                        return

                    config = {
                        "configurable": {"thread_id": conv_id},
                        "recursion_limit": get_settings().rag.graph_recursion_limit,
                    }

                    graph = self._container.compile_graph(kb_id=kb_id)
                    if graph is None:
                        queue.put_nowait(format_sse("error", message="Graph 未初始化"))
                        queue.put_nowait(format_sse("done"))
                        return

                    self._begin_turn(conv_id, message.strip(), queue)

                    # 如果是从 clarification 中断恢复的，注入用户回复后继续
                    current_state = graph.get_state(config)
                    if current_state.next:
                        graph.update_state(config, {"messages": [HumanMessage(content=message.strip())]})
                        stream_input = None
                    else:
                        stream_input = {"messages": [HumanMessage(content=message.strip())]}

                    prev_node_key = None
                    prev_start_ts = None
                    flow_steps: list[dict] = []
                    current_step: dict | None = None

                    for chunk, metadata in graph.stream(
                        stream_input, config=config, stream_mode="messages"
                    ):
                        if cancel_event.is_set():
                            break
                        node = metadata.get("langgraph_node", "")
                        ns = metadata.get("langgraph_checkpoint_ns", "")

                        # 从 checkpoint namespace 提取子任务 key
                        task_key = None
                        if ns and "agent:" in ns:
                            parts = ns.split(":")
                            if len(parts) >= 2:
                                task_key = parts[1].split("/")[0] if "/" in parts[1] else parts[1]

                        is_internal = node in AGENT_INTERNAL_NODES
                        display_node = "agent" if is_internal else node
                        node_key = f"{display_node}:{task_key}" if (task_key and is_internal) else display_node

                        # 节点切换时发送 flow_end + flow_start
                        if node and node_key != prev_node_key:
                            if current_step is not None:
                                duration_ms = round((time.perf_counter() - current_step["_start_ts"]) * 1000)
                                current_step["duration_ms"] = duration_ms
                                del current_step["_start_ts"]
                                flow_steps.append(current_step)
                                queue.put_nowait(format_sse("flow_end",
                                    stage=current_step["stage"],
                                    task=current_step.get("task"),
                                    duration_ms=duration_ms,
                                ))

                            prev_start_ts = time.perf_counter()
                            prev_node_key = node_key
                            label = NODE_LABELS.get(display_node, display_node)
                            current_step = {
                                "stage": display_node,
                                "label": label,
                                "task": task_key if is_internal else None,
                                "_start_ts": prev_start_ts,
                            }
                            queue.put_nowait(format_sse("flow_start",
                                stage=display_node,
                                label=label,
                                task=task_key if is_internal else None,
                            ))

                            # rewrite_query 结束时发意图分析给前端
                            if display_node == "rewrite_query":
                                try:
                                    st = graph.get_state(config)
                                    vals = st.values
                                    questions = vals.get("rewrittenQuestions", [])
                                    is_clear = vals.get("questionIsClear", False)
                                    original = vals.get("originalQuery", "")
                                    if questions:
                                        queue.put_nowait(format_sse("query_analysis",
                                            questions=list(questions),
                                            is_clear=bool(is_clear),
                                            original_query=original,
                                        ))
                                except Exception:
                                    logger.exception("chat.query_analysis.error")

                        # 消息和工具事件
                        if node in SYSTEM_NODES and isinstance(chunk, AIMessageChunk) and chunk.content:
                            label = {
                                "rewrite_query": "分析与改写问题…",
                                "summarize_history": "整理对话历史…",
                                "load_long_term_memory": "加载长期记忆…",
                            }.get(node, node)
                            queue.put_nowait(format_sse("status", stage=node, label=label))

                        elif hasattr(chunk, "tool_calls") and chunk.tool_calls:
                            for tc in chunk.tool_calls:
                                queue.put_nowait(format_sse("tool",
                                    name=tc.get("name", "unknown"),
                                    args=tc.get("args", {}),
                                    task=task_key,
                                ))

                        elif isinstance(chunk, ToolMessage):
                            result_content = str(chunk.content) if chunk.content else "(无结果)"
                            result_count = result_content.count("Parent ID:")
                            if len(result_content) > 500:
                                result_content = result_content[:500] + "…"
                            queue.put_nowait(format_sse("tool_result",
                                name=getattr(chunk, "name", "tool"),
                                content=result_content,
                                task=task_key,
                                count=result_count,
                            ))

                        elif isinstance(chunk, AIMessageChunk) and chunk.content and node not in SYSTEM_NODES:
                            queue.put_nowait(format_sse("content", delta=chunk.content))

                    # 流结束，收尾最后一个步骤
                    if current_step is not None:
                        duration_ms = round((time.perf_counter() - current_step["_start_ts"]) * 1000)
                        current_step["duration_ms"] = duration_ms
                        del current_step["_start_ts"]
                        flow_steps.append(current_step)
                        queue.put_nowait(format_sse("flow_end",
                            stage=current_step["stage"],
                            task=current_step.get("task"),
                            duration_ms=duration_ms,
                        ))

                    final_state = graph.get_state(config)

                    # 兜底发意图分析（checkpoint 时序可能导致 flow_end 时读不到）
                    try:
                        _vals = final_state.values
                        _questions = _vals.get("rewrittenQuestions", [])
                        logger.info("chat.query_analysis.fallback",
                                    state_keys=list(_vals.keys()),
                                    questions=_questions,
                                    is_clear=_vals.get("questionIsClear"),
                                    original=_vals.get("originalQuery", ""))
                        if _questions:
                            queue.put_nowait(format_sse("query_analysis",
                                questions=list(_questions),
                                is_clear=bool(_vals.get("questionIsClear", False)),
                                original_query=_vals.get("originalQuery", ""),
                            ))
                    except Exception:
                        logger.exception("chat.query_analysis.fallback.error")

                    if final_state.next and "request_clarification" in final_state.next:
                        clarification_text = ""
                        for msg in reversed(final_state.values.get("messages", [])):
                            if isinstance(msg, AIMessage) and msg.content:
                                clarification_text = msg.content
                                break
                        if clarification_text:
                            queue.put_nowait(format_sse("clarification", question=clarification_text))
                    else:
                        # 持久化助手回复到 SQLite
                        try:
                            final_msgs = final_state.values.get("messages", [])
                            assistant_text = ""
                            for msg in reversed(final_msgs):
                                if isinstance(msg, AIMessage) and msg.content and not getattr(msg, 'tool_calls', None):
                                    assistant_text = msg.content
                                    break
                            logger.info("chat.persist.check", conv_id=conv_id,
                                        has_assistant_text=bool(assistant_text),
                                        msg_count=len(final_msgs))
                            if assistant_text:
                                try:
                                    sources = extract_sources(final_msgs)
                                    sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
                                    flow_steps_json = json.dumps(flow_steps, ensure_ascii=False) if flow_steps else None
                                    self._container.conversation_service.add_assistant_message(
                                        conv_id, assistant_text,
                                        sources_json=sources_json,
                                        flow_steps_json=flow_steps_json,
                                    )
                                    logger.info("chat.persist.success", conv_id=conv_id,
                                                sources_count=len(sources),
                                                flow_steps_count=len(flow_steps))
                                except Exception as e:
                                    logger.exception("chat.persist.error", conv_id=conv_id, error=str(e))

                                self._extract_memories(message.strip(), assistant_text, conv_id)
                        except Exception:
                            pass

                    queue.put_nowait(format_sse("done", conversation_id=conv_id))

                except Exception as e:
                    logger.exception("chat.stream.error")
                    queue.put_nowait(format_sse("error", message=str(e)))
                    queue.put_nowait(format_sse("done"))

            thread = threading.Thread(target=runner, daemon=True)
            thread.start()

            try:
                while True:
                    event_str = await queue.get()
                    yield event_str
                    if json.loads(event_str.lstrip("data: ").strip()).get("type") == "done":
                        break
            except asyncio.CancelledError:
                # 客户端断开（切会话、刷新页面）：后台线程继续跑完 LLM，
                # 完整回答会持久化到 DB，用户切回来时从 loadMessages 加载
                logger.info("chat.stream.client_disconnected", conv_id=conv_id)
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except Exception:
                        pass

    def _run_plain_llm(self, conv_id: str, user_msg: str, queue: asyncio.Queue, cancel_event: threading.Event) -> None:
        """纯 LLM 对话：不走 LangGraph，直接调 Ollama 流式生成"""
        settings = get_settings()

        self._begin_turn(conv_id, user_msg, queue)

        queue.put_nowait(format_sse("status", stage="llm", label="生成回答…"))
        queue.put_nowait(format_sse("flow_start", stage="llm", label="LLM 生成回答"))

        flow_steps: list[dict] = []

        # 读最近 8 条历史消息做多轮对话上下文
        history_items = self._container.conversation_service.get_messages(conv_id)

        # 加载相关长期记忆，注入系统提示
        from app.rag.memory import load_long_term_memories
        memory_context = load_long_term_memories(
            query=user_msg,
            long_term_memory_store=self._container.long_term_memory_store,
            sqlite=self._container.sqlite,
            settings=settings,
        )
        system_text = PLAIN_LLM_SYSTEM_PROMPT
        if memory_context:
            system_text = f"{PLAIN_LLM_SYSTEM_PROMPT.rstrip()}\n\n{memory_context}"

        msgs: list = [SystemMessage(content=system_text)]
        if history_items:
            for m in history_items[-9:-1] if len(history_items) > 9 else history_items[:-1]:
                if m.role == "user":
                    msgs.append(HumanMessage(content=m.content))
                elif m.role == "assistant":
                    msgs.append(AIMessage(content=m.content))
        msgs.append(HumanMessage(content=user_msg))

        start_ts = time.perf_counter()
        llm = self._container.create_llm()

        assistant_text = ""
        try:
            for chunk in llm.stream(msgs):
                if cancel_event.is_set():
                    break
                delta = ""
                if isinstance(chunk, AIMessageChunk):
                    delta = chunk.content or ""
                elif isinstance(chunk, str):
                    delta = chunk
                if delta:
                    assistant_text += delta
                    queue.put_nowait(format_sse("content", delta=delta))
        except Exception as e:
            logger.exception("chat.plain.llm.error")
            queue.put_nowait(format_sse("error", message=f"LLM 生成失败: {e}"))
            queue.put_nowait(format_sse("done"))
            return

        duration_ms = round((time.perf_counter() - start_ts) * 1000)
        queue.put_nowait(format_sse("flow_end", stage="llm", duration_ms=duration_ms))

        flow_steps.append({
            "stage": "llm",
            "label": "LLM 生成回答",
            "duration_ms": duration_ms,
        })

        if assistant_text:
            try:
                flow_steps_json = json.dumps(flow_steps, ensure_ascii=False) if flow_steps else None
                self._container.conversation_service.add_assistant_message(
                    conv_id, assistant_text,
                    sources_json=None,
                    flow_steps_json=flow_steps_json,
                )
                logger.info("chat.plain.persist.success", conv_id=conv_id,
                            flow_steps_count=len(flow_steps))
            except Exception:
                logger.exception("chat.plain.persist.assistant.error", conv_id=conv_id)

            self._extract_memories(user_msg, assistant_text, conv_id, llm=llm)

        queue.put_nowait(format_sse("done", conversation_id=conv_id))

    def _begin_turn(self, conv_id: str, user_msg: str, queue: asyncio.Queue) -> None:
        """每轮对话开始前的公共步骤"""
        self._container.conversation_service.get_or_create(
            conv_id,
            first_message=user_msg,
            model=self._container.settings.llm.model,
        )
        conv = self._container.conversation_service.get(conv_id)
        if conv and conv.message_count == 0 and user_msg:
            self._container.conversation_service.update(
                conv_id, title=user_msg[:50].replace("\n", " ")
            )
        try:
            self._container.conversation_service.add_user_message(conv_id, user_msg)
        except Exception:
            logger.exception("chat.persist.user_msg.error", conv_id=conv_id)
        queue.put_nowait(format_sse("session", conversation_id=conv_id))

    def _extract_memories(self, user_msg: str, assistant_text: str, conv_id: str, llm=None) -> None:
        """从本轮对话中提取长期记忆"""
        from app.rag.memory import store_long_term_memories

        try:
            if llm is None:
                llm = self._container.create_llm()
            conversation_text = f"用户: {user_msg}\n助手: {assistant_text}"
            created = store_long_term_memories(
                conversation_text=conversation_text,
                llm=llm,
                long_term_memory_store=self._container.long_term_memory_store,
                sqlite=self._container.sqlite,
                settings=get_settings(),
                conversation_id=conv_id,
            )
            if created:
                logger.info("long_term_memory.extracted", count=created)
        except Exception:
            logger.exception("long_term_memory.extract.error")

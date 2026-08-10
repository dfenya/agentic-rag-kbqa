"""LangGraph 状态定义，主图 State + 子图 AgentState"""

from typing import Annotated, List, Set
import operator

from langgraph.graph import MessagesState


def accumulate_or_reset(existing: List[dict], new: List[dict]) -> List[dict]:
    """累加子 agent 答案，收到 __reset__ 信号时清空"""
    if new and any(item.get("__reset__") for item in new):
        return []
    return existing + new


def set_union(a: Set[str], b: Set[str]) -> Set[str]:
    return a | b


class State(MessagesState):
    """全局工作流状态。messages 由 SqliteSaver 持久化，是短期/工作记忆"""

    questionIsClear: bool = False
    conversation_summary: str = ""
    originalQuery: str = ""
    rewrittenQuestions: List[str] = []
    agent_answers: Annotated[List[dict], accumulate_or_reset] = []

    # 长期记忆：每轮从 Qdrant+SQLite 语义检索的用户偏好/FAQ/历史摘要
    long_term_memory_context: str = ""
    conversation_id: str = ""

    # 用户 ID，多租户隔离
    user_id: str = ""

    # 知识库名称，传给改写节点做上下文
    kb_name: str = ""

    # 澄清计数器，防无限循环
    clarification_count: int = 0


class AgentState(MessagesState):
    """单个子 agent 的隔离状态，多 agent 并行互不干扰"""

    question: str = ""
    question_index: int = 0
    context_summary: str = ""
    long_term_memory_context: str = ""
    retrieval_keys: Annotated[Set[str], set_union] = set()
    final_answer: str = ""
    agent_answers: List[dict] = []
    tool_call_count: Annotated[int, operator.add] = 0
    iteration_count: Annotated[int, operator.add] = 0

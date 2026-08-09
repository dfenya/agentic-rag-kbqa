"""LangGraph 中 LLM 结构化输出的 Pydantic 模型"""

from typing import List
from pydantic import BaseModel, Field

from app.domain.enums import LongTermMemoryType


class QueryAnalysis(BaseModel):
    """用户提问的意图分析结果"""

    is_clear: bool = Field(description="用户的提问是否清晰可回答")
    questions: List[str] = Field(description="重写后的独立子问题列表，最多3个")
    clarification_needed: str = Field(description="如果不清晰，需要追问的内容")


class LongTermMemoryItem(BaseModel):
    """从对话中提取的一条长期记忆"""

    type: LongTermMemoryType = Field(description="记忆类型（枚举：user_preference | faq_pattern | conversation_summary）")
    content: str = Field(description="记忆内容，控制在50个中文字以内")
    keywords: List[str] = Field(description="3-5个搜索关键词")
    is_new_signal: bool = Field(description="是否是新出现的模式")


class LongTermMemoryExtraction(BaseModel):
    """一次对话提取的记忆候选列表"""

    items: List[LongTermMemoryItem] = Field(description="0-3条可提取的记忆，没有则为空列表")

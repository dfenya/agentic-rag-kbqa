"""对话服务的工具函数"""

import json

from langchain_core.messages import ToolMessage


def format_sse(event_type: str, **kwargs) -> str:
    """拼接 SSE 事件字符串"""
    payload = {"type": event_type, **kwargs}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def extract_sources(messages) -> list[dict]:
    """从工具消息里解析文档引用来源，去重后返回 [{source, parent_id}]"""
    sources: list[dict] = []
    seen: set[str] = set()
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = str(msg.content) if msg.content else ""
        for block in content.split("\n\n"):
            parent_id = ""
            source = ""
            for line in block.split("\n"):
                if line.startswith("Parent ID:"):
                    parent_id = line[len("Parent ID:"):].strip()
                elif line.startswith("来源文档:"):
                    source = line[len("来源文档:"):].strip()
            if parent_id and parent_id not in seen:
                seen.add(parent_id)
                sources.append({"source": source, "parent_id": parent_id})
    return sources

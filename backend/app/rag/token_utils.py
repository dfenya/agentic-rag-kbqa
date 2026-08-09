"""Token 估算工具 —— 支持 tiktoken（优先）和字符数回退"""

# 模块加载时尝试导入 tiktoken
try:
    import tiktoken
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False


def estimate_tokens(messages: list) -> int:
    """估算消息列表的 token 数，中文自动应用修正系数"""
    if _TIKTOKEN_AVAILABLE:
        return _estimate_with_tiktoken(messages)
    return _estimate_with_charcount(messages)


def _estimate_with_tiktoken(messages: list) -> int:
    try:
        enc = tiktoken.encoding_for_model("gpt-4")
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    total = 0
    for msg in messages:
        content = str(getattr(msg, "content", "")) if hasattr(msg, "content") else str(msg)
        if not content:
            continue
        raw = len(enc.encode(content))
        # 中文字符占比 > 30% 时应用 1.8× 修正系数
        chinese_chars = sum(1 for c in content if '一' <= c <= '鿿')
        if chinese_chars > len(content) * 0.3:
            raw = int(raw * 1.8)
        total += raw
    return total


def _estimate_with_charcount(messages: list) -> int:
    total = 0
    for msg in messages:
        content = str(getattr(msg, "content", "")) if hasattr(msg, "content") else str(msg)
        chinese = sum(1 for c in content if '一' <= c <= '鿿')
        other = len(content) - chinese
        total += int(chinese * 1.8 + other * 0.3)
    return total

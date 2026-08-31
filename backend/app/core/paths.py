"""用户可控名称到本地存储路径的安全映射。"""

import re
from pathlib import Path


_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(filename: str) -> str:
    """去掉客户端路径和 Windows 非法字符，保留可读扩展名。"""
    basename = Path(filename.replace("\\", "/")).name
    cleaned = _INVALID_WINDOWS_CHARS.sub("_", basename).strip(". ")
    return (cleaned or "upload")[:240]


def kb_storage_folder(kb_name: str, kb_id: str) -> str:
    """知识库名只作可读前缀，UUID 才是目录身份。"""
    safe_name = _INVALID_WINDOWS_CHARS.sub("_", kb_name).strip(". ")
    return f"{(safe_name or 'kb')[:80]}_{kb_id}"

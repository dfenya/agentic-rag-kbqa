"""SHA-256 内容去重，同一份文件换名上传能被识别出来"""

import hashlib
from pathlib import Path
from typing import Optional

from app.stores.sqlite_store import SqliteStore
from app.domain.models import Document


def compute_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def compute_file_sha256(filepath: str | Path) -> str:
    return hashlib.sha256(Path(filepath).read_bytes()).hexdigest()


def check_duplicate(
    db: SqliteStore,
    content: bytes,
    filename: str,
    kb_id: str | None = None,
) -> tuple[bool, Optional[Document]]:
    """检查同 KB 内是否已存在相同内容的文件，返回 (是否重复, 已有文档)"""
    sha = compute_sha256(content)
    existing = db.doc_by_sha256(sha, kb_id=kb_id)
    if existing:
        return True, existing
    return False, None


def register_document(
    db: SqliteStore,
    filename: str,
    content: bytes,
    file_size: int = 0,
    kb_id: str | None = None,
) -> Document:
    """在注册表插入新文档记录，状态为 processing"""
    sha = compute_sha256(content)
    return db.doc_insert(
        filename=filename,
        file_size=file_size or len(content),
        sha256=sha,
        status="processing",
        kb_id=kb_id,
    )

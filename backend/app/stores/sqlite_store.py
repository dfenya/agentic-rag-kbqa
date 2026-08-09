"""SQLite 数据访问层，所有结构化数据的读写都走这里"""

import json
from pathlib import Path
from typing import Sequence

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.domain.models import (
    Base,
    Conversation,
    Document,
    KnowledgeBase,
    LongTermMemory,
    Message,
    Setting,
    User,
)
from app.domain.enums import DocumentStatus, LongTermMemoryType


class SqliteStore:
    """SQLite 操作入口，提供各表的增删改查方法"""

    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def _set_wal(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def create_all(self):
        Base.metadata.create_all(self.engine)

    def drop_all(self):
        Base.metadata.drop_all(self.engine)

    def session(self) -> Session:
        return self.SessionLocal()

    # ── 用户 ──

    def user_create(self, **kwargs) -> User:
        with self.session() as s:
            u = User(**kwargs)
            s.add(u)
            s.commit()
            s.refresh(u)
            return u

    def user_by_username(self, username: str) -> User | None:
        with self.session() as s:
            return s.query(User).filter_by(username=username).first()

    def user_by_id(self, user_id: str) -> User | None:
        with self.session() as s:
            return s.query(User).filter_by(id=user_id).first()

    # ── 文档 ──

    def doc_by_sha256(self, sha256: str, kb_id: str | None = None) -> Document | None:
        with self.session() as s:
            q = s.query(Document).filter_by(sha256=sha256)
            if kb_id is not None:
                q = q.filter_by(kb_id=kb_id)
            return q.first()

    def doc_by_id(self, doc_id: str) -> Document | None:
        with self.session() as s:
            return s.query(Document).filter_by(id=doc_id).first()

    def doc_insert(self, **kwargs) -> Document:
        with self.session() as s:
            doc = Document(**kwargs)
            s.add(doc)
            s.commit()
            s.refresh(doc)
            return doc

    def doc_update(self, doc_id: str, **kwargs) -> Document | None:
        with self.session() as s:
            doc = s.query(Document).filter_by(id=doc_id).first()
            if doc:
                for k, v in kwargs.items():
                    setattr(doc, k, v)
                s.commit()
                s.refresh(doc)
            return doc

    def doc_delete(self, doc_id: str) -> bool:
        with self.session() as s:
            doc = s.query(Document).filter_by(id=doc_id).first()
            if doc:
                s.delete(doc)
                s.commit()
                return True
            return False

    def docs_list(
        self, *, kb_id: str | None = None,
        q: str | None = None, page: int = 1, page_size: int = 50,
    ) -> tuple[list[Document], int]:
        with self.session() as s:
            query = s.query(Document)
            if kb_id is not None:
                query = query.filter_by(kb_id=kb_id)
            if q:
                query = query.filter(Document.filename.contains(q))
            total = query.count()
            items = query.order_by(Document.created_at.desc()) \
                         .offset((page - 1) * page_size) \
                         .limit(page_size).all()
            return items, total

    # ── 知识库 ──

    def kb_create(self, name: str, user_id: str, description: str | None = None) -> KnowledgeBase:
        with self.session() as s:
            kb = KnowledgeBase(name=name, user_id=user_id, description=description)
            s.add(kb)
            s.commit()
            s.refresh(kb)
            return kb

    def kb_list(self, user_id: str) -> list[KnowledgeBase]:
        with self.session() as s:
            return s.query(KnowledgeBase).filter_by(user_id=user_id).order_by(KnowledgeBase.created_at.desc()).all()

    def kb_by_id(self, kb_id: str) -> KnowledgeBase | None:
        with self.session() as s:
            return s.query(KnowledgeBase).filter_by(id=kb_id).first()

    def kb_delete(self, kb_id: str) -> bool:
        with self.session() as s:
            kb = s.query(KnowledgeBase).filter_by(id=kb_id).first()
            if kb:
                s.delete(kb)
                s.commit()
                return True
            return False

    # ── 会话 ──

    def conv_create(self, user_id: str, **kwargs) -> Conversation:
        with self.session() as s:
            conv = Conversation(user_id=user_id, **kwargs)
            s.add(conv)
            s.commit()
            s.refresh(conv)
            return conv

    def conv_list(self, user_id: str, *, q: str | None = None) -> list[Conversation]:
        with self.session() as s:
            query = s.query(Conversation).filter_by(user_id=user_id)
            if q:
                query = query.filter(Conversation.title.contains(q))
            return query.order_by(Conversation.updated_at.desc()).limit(50).all()

    def conv_by_id(self, conv_id: str) -> Conversation | None:
        with self.session() as s:
            return s.query(Conversation).filter_by(id=conv_id).first()

    def conv_update(self, conv_id: str, **kwargs) -> Conversation | None:
        with self.session() as s:
            conv = s.query(Conversation).filter_by(id=conv_id).first()
            if conv:
                for k, v in kwargs.items():
                    setattr(conv, k, v)
                s.commit()
                s.refresh(conv)
            return conv

    def conv_delete(self, conv_id: str) -> bool:
        with self.session() as s:
            conv = s.query(Conversation).filter_by(id=conv_id).first()
            if conv:
                s.delete(conv)
                s.commit()
                return True
            return False

    def conv_delete_older_than(self, days: int) -> int:
        """删除 N 天前的旧会话，消息级联删除"""
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with self.session() as s:
            count = s.query(Conversation).filter(
                Conversation.updated_at < cutoff
            ).delete(synchronize_session=False)
            s.commit()
            return count

    # ── 消息 ──

    def msg_create(self, **kwargs) -> Message:
        with self.session() as s:
            msg = Message(**kwargs)
            s.add(msg)
            s.commit()
            s.refresh(msg)
            return msg

    def msgs_by_conv(self, conv_id: str) -> list[Message]:
        with self.session() as s:
            return s.query(Message) \
                    .filter_by(conversation_id=conv_id) \
                    .order_by(Message.created_at.asc()).all()

    # ── 长期记忆 ──

    def mem_insert(self, user_id: str, **kwargs) -> LongTermMemory:
        with self.session() as s:
            mem = LongTermMemory(user_id=user_id, **kwargs)
            s.add(mem)
            s.commit()
            s.refresh(mem)
            return mem

    def mem_increment_access(self, mem_id: str) -> None:
        """原子递增 access_count，避免读-改-写竞态"""
        with self.session() as s:
            s.query(LongTermMemory).filter_by(id=mem_id).update(
                {LongTermMemory.access_count: LongTermMemory.access_count + 1},
                synchronize_session=False,
            )
            s.commit()

    def mem_by_id(self, mem_id: str) -> LongTermMemory | None:
        with self.session() as s:
            return s.query(LongTermMemory).filter_by(id=mem_id).first()

    def mem_update(self, mem_id: str, **kwargs) -> LongTermMemory | None:
        with self.session() as s:
            mem = s.query(LongTermMemory).filter_by(id=mem_id).first()
            if mem:
                for k, v in kwargs.items():
                    setattr(mem, k, v)
                s.commit()
                s.refresh(mem)
            return mem

    def mem_delete(self, mem_id: str) -> bool:
        with self.session() as s:
            mem = s.query(LongTermMemory).filter_by(id=mem_id).first()
            if mem:
                s.delete(mem)
                s.commit()
                return True
            return False

    def mem_list(
        self, user_id: str, *, mem_type: str | None = None, q: str | None = None,
        limit: int = 100,
    ) -> list[LongTermMemory]:
        with self.session() as s:
            query = s.query(LongTermMemory).filter_by(user_id=user_id)
            if mem_type:
                query = query.filter_by(type=mem_type)
            if q:
                query = query.filter(LongTermMemory.content.contains(q))
            return query.order_by(LongTermMemory.updated_at.desc()).limit(limit).all()

    def mem_all(self, user_id: str) -> list[LongTermMemory]:
        with self.session() as s:
            return s.query(LongTermMemory).filter_by(user_id=user_id).all()

    def mem_list_by_ids(
        self,
        mem_ids: list[str],
        conversation_id: str | None = None,
    ) -> list[LongTermMemory]:
        """按 ID 列表取记忆，可选按会话隔离过滤"""
        with self.session() as s:
            q = s.query(LongTermMemory).filter(LongTermMemory.id.in_(mem_ids))
            if conversation_id:
                q = q.filter(LongTermMemory.source_conversation_id == conversation_id)
            return q.all()

    def mem_count(self, user_id: str) -> int:
        with self.session() as s:
            return s.query(LongTermMemory).filter_by(user_id=user_id).count()

    def mem_delete_least_accessed(self, user_id: str, keep: int) -> int:
        """LRU 淘汰：保留访问最多的 keep 条，删掉其余的"""
        with self.session() as s:
            to_keep = s.query(LongTermMemory).filter_by(user_id=user_id).order_by(LongTermMemory.access_count.desc()).limit(keep).all()
            keep_ids = {m.id for m in to_keep}
            deleted = s.query(LongTermMemory).filter(LongTermMemory.user_id == user_id, ~LongTermMemory.id.in_(keep_ids)).delete(
                synchronize_session=False
            )
            s.commit()
            return deleted

    # ── 设置 ──

    def setting_get(self, key: str, user_id: str) -> dict | None:
        with self.session() as s:
            row = s.query(Setting).filter_by(key=key, user_id=user_id).first()
            return json.loads(row.value_json) if row else None

    def setting_set(self, key: str, value: dict, user_id: str):
        with self.session() as s:
            row = s.query(Setting).filter_by(key=key, user_id=user_id).first()
            if row:
                row.value_json = json.dumps(value, ensure_ascii=False)
            else:
                s.add(Setting(key=key, user_id=user_id, value_json=json.dumps(value, ensure_ascii=False)))
            s.commit()

    def setting_all(self, user_id: str) -> dict:
        with self.session() as s:
            rows = s.query(Setting).filter_by(user_id=user_id).all()
            return {r.key: json.loads(r.value_json) for r in rows}

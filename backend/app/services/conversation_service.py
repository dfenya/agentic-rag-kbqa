"""对话和消息的业务逻辑"""

import uuid
from typing import Optional

from app.stores.sqlite_store import SqliteStore
from app.domain.models import Conversation, Message


class ConversationService:
    """对话与消息的增删改查"""

    def __init__(self, sqlite: SqliteStore):
        self._db = sqlite

    def create(self, title: str = "新对话", model: str = "") -> Conversation:
        return self._db.conv_create(
            id=str(uuid.uuid4()),
            title=title,
            model=model,
        )

    def get_or_create(self, conv_id: Optional[str], *, first_message: str = "", model: str = "") -> Conversation:
        if conv_id:
            conv = self._db.conv_by_id(conv_id)
            if conv:
                return conv
        title = first_message[:50].replace("\n", " ") if first_message else "新对话"
        return self._db.conv_create(
            id=conv_id or str(uuid.uuid4()),
            title=title,
            model=model,
        )

    def add_user_message(self, conv_id: str, content: str) -> Message:
        """立即写用户消息到 DB，导航离开不丢数据。同时更新侧边栏预览"""
        msg = self._db.msg_create(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            role="user",
            content=content,
        )
        conv = self._db.conv_by_id(conv_id)
        current_count = conv.message_count if conv else 0
        self._db.conv_update(
            conv_id,
            message_count=current_count + 1,
            last_message_preview=content[:200],
        )
        return msg

    def add_assistant_message(
        self, conv_id: str, content: str,
        sources_json: Optional[str] = None,
        flow_steps_json: Optional[str] = None,
    ) -> Message:
        """流结束后写助手回复到 DB"""
        msg = self._db.msg_create(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            role="assistant",
            content=content,
            sources_json=sources_json,
            flow_steps_json=flow_steps_json,
        )
        conv = self._db.conv_by_id(conv_id)
        current_count = conv.message_count if conv else 0
        self._db.conv_update(
            conv_id,
            message_count=current_count + 1,
            last_message_preview=content[:200],
        )
        return msg

    def list_conversations(self, q: Optional[str] = None) -> list[Conversation]:
        return self._db.conv_list(q=q)

    def get(self, conv_id: str) -> Optional[Conversation]:
        return self._db.conv_by_id(conv_id)

    def update(self, conv_id: str, **kwargs) -> Optional[Conversation]:
        return self._db.conv_update(conv_id, **kwargs)

    def delete(self, conv_id: str) -> bool:
        return self._db.conv_delete(conv_id)

    def get_messages(self, conv_id: str) -> list[Message]:
        return self._db.msgs_by_conv(conv_id)

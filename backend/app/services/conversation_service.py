import uuid
from typing import Optional

from app.stores.sqlite_store import SqliteStore
from app.domain.models import Conversation, Message


class ConversationService:

    def __init__(self, sqlite: SqliteStore):
        self._db = sqlite

    def create(self, user_id: str, title: str = "新对话", model: str = "") -> Conversation:
        return self._db.conv_create(user_id,
            id=str(uuid.uuid4()), title=title, model=model)

    def get_or_create(self, user_id: str, conv_id: Optional[str], *, first_message: str = "", model: str = "") -> Conversation:
        if conv_id:
            conv = self._db.conv_by_id(conv_id)
            if conv:
                if conv.user_id != user_id:
                    raise PermissionError("Conversation does not belong to current user")
                return conv
        title = first_message[:50].replace("\n", " ") if first_message else "新对话"
        return self._db.conv_create(user_id,
            id=conv_id or str(uuid.uuid4()), title=title, model=model)

    def add_user_message(self, conv_id: str, content: str) -> Message:
        msg = self._db.msg_create(
            id=str(uuid.uuid4()), conversation_id=conv_id, role="user", content=content)
        conv = self._db.conv_by_id(conv_id)
        current_count = conv.message_count if conv else 0
        self._db.conv_update(conv_id,
            message_count=current_count + 1, last_message_preview=content[:200])
        return msg

    def add_assistant_message(self, conv_id: str, content: str,
                              sources_json: Optional[str] = None,
                              flow_steps_json: Optional[str] = None) -> Message:
        msg = self._db.msg_create(
            id=str(uuid.uuid4()), conversation_id=conv_id, role="assistant",
            content=content, sources_json=sources_json, flow_steps_json=flow_steps_json)
        conv = self._db.conv_by_id(conv_id)
        current_count = conv.message_count if conv else 0
        self._db.conv_update(conv_id,
            message_count=current_count + 1, last_message_preview=content[:200])
        return msg

    def list_conversations(self, user_id: str, q: Optional[str] = None) -> list[Conversation]:
        return self._db.conv_list(user_id, q=q)

    def get(self, user_id: str, conv_id: str) -> Optional[Conversation]:
        conv = self._db.conv_by_id(conv_id)
        return conv if conv and conv.user_id == user_id else None

    def update(self, user_id: str, conv_id: str, **kwargs) -> Optional[Conversation]:
        conv = self._db.conv_by_id(conv_id)
        if not conv or conv.user_id != user_id:
            return None
        return self._db.conv_update(conv_id, **kwargs)

    def delete(self, user_id: str, conv_id: str) -> bool:
        conv = self._db.conv_by_id(conv_id)
        if not conv or conv.user_id != user_id:
            return False
        return self._db.conv_delete(conv_id)

    def get_messages(self, user_id: str, conv_id: str) -> list[Message]:
        conv = self._db.conv_by_id(conv_id)
        if not conv or conv.user_id != user_id:
            return []
        return self._db.msgs_by_conv(conv_id)

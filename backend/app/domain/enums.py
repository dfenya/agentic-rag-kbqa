"""领域枚举"""

from enum import StrEnum


class DocumentStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    DUPLICATE = "duplicate"
    ERROR = "error"


class LongTermMemoryType(StrEnum):
    USER_PREFERENCE = "user_preference"
    FAQ_PATTERN = "faq_pattern"
    CONVERSATION_SUMMARY = "conversation_summary"

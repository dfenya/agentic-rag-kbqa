"""领域枚举"""

from enum import StrEnum


class DocumentStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    DUPLICATE = "duplicate"
    ERROR = "error"
    DELETING = "deleting"


class GovernanceStage(StrEnum):
    RECEIVED = "received"
    DEDUPED = "deduped"
    PARSED = "parsed"
    CHUNKED = "chunked"
    PARENTS_STAGED = "parents_staged"
    VECTORS_STAGED = "vectors_staged"
    VALIDATED = "validated"
    PUBLISHED = "published"


class GovernanceJobStatus(StrEnum):
    PROCESSING = "processing"
    ROLLING_BACK = "rolling_back"
    FAILED = "failed"
    PUBLISHED = "published"


class LongTermMemoryType(StrEnum):
    USER_PREFERENCE = "user_preference"
    FAQ_PATTERN = "faq_pattern"
    CONVERSATION_SUMMARY = "conversation_summary"

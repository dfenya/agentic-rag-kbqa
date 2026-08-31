"""Pydantic 模型：API 请求和响应的数据结构"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServiceStatus(BaseModel):
    qdrant: str = "unknown"
    ollama: str = "unknown"
    sqlite: str = "unknown"


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    services: ServiceStatus = Field(default_factory=ServiceStatus)


class KBCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("知识库名称不能为空")
        return value


class KBResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    document_count: int = 0
    created_at: datetime


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=20_000)
    kb_id: str | None = None
    model: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class ChatResumeRequest(BaseModel):
    conversation_id: str
    reply: str = Field(min_length=1, max_length=20_000)
    kb_id: str


class DocumentResponse(BaseModel):
    id: str
    filename: str
    kb_id: str | None = None
    status: str
    file_size: int = 0
    parent_count: int = 0
    child_count: int = 0
    error: str | None = None
    created_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


class UploadTaskInfo(BaseModel):
    doc_id: str | None = None
    filename: str
    status: str
    phase: str | None = None
    percent: float = 0.0
    duplicate_of: str | None = None
    error: str | None = None


class UploadResponse(BaseModel):
    upload_id: str
    tasks: list[UploadTaskInfo]


class ConversationResponse(BaseModel):
    id: str
    title: str
    model: str = ""
    message_count: int = 0
    last_message_preview: str | None = None
    created_at: datetime
    updated_at: datetime


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    model: str | None = Field(default=None, max_length=200)


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)


class FlowStep(BaseModel):
    stage: str
    label: str
    task: str | None = None
    duration_ms: int | None = None


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    sources_json: str | None = None
    flow_steps: list[FlowStep] | None = None
    created_at: datetime


class LongTermMemoryResponse(BaseModel):
    id: str
    type: str
    content: str
    keywords: list[str] = Field(default_factory=list)
    importance: float = 0.5
    access_count: int = 0
    source_conversation_id: str | None = None
    conversation_title: str | None = None
    created_at: datetime
    updated_at: datetime


class LongTermMemoryUpdateRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=10_000)
    importance: float | None = Field(default=None, ge=0.0, le=1.0)


class LLMSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str | None = Field(default=None, min_length=1, max_length=200)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    num_ctx: int | None = Field(default=None, ge=1024, le=262_144)
    ollama_base_url: str | None = Field(
        default=None, min_length=8, max_length=2048, pattern=r"^https?://"
    )


class RAGSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top_k: int | None = Field(default=None, ge=1, le=100)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class MemorySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    top_k: int | None = Field(default=None, ge=1, le=100)


class AppSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    llm: LLMSettingsUpdate | None = None
    rag: RAGSettingsUpdate | None = None
    memory: MemorySettingsUpdate | None = None
    dark_mode: bool | None = None

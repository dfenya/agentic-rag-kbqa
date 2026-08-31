"""应用配置，从环境变量和 .env 文件加载"""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 用户通过 Web 界面修改的设置保存在这里
_USER_SETTINGS_PATH = _BASE_DIR / "data" / "settings.json"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_")
    name: str = "Agentic RAG 知识库"
    env: Literal["dev", "prod"] = "dev"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    conversation_ttl_days: int = 90


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SERVER_")
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STORAGE_")
    qdrant_path: str = str(_BASE_DIR / "qdrant_db")
    qdrant_url: str = ""
    sqlite_path: str = str(_BASE_DIR / "data" / "app.db")
    upload_dir: str = str(_BASE_DIR / "data" / "uploads")
    markdown_dir: str = str(_BASE_DIR / "data" / "markdown")
    chunks_dir: str = str(_BASE_DIR / "data" / "chunks")


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMBEDDING_")
    dense_model: str = "../local_model_cache/AI-ModelScope/bge-large-zh-v1___5"
    sparse_model: str = "Qdrant/bm25"
    device: str = "cpu"


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_")
    ollama_base_url: str = "http://localhost:11434"
    model: str = Field(default="qwen3:4b-instruct-2507-q4_K_M", min_length=1, max_length=200)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    num_ctx: int = Field(default=8192, ge=1024, le=262_144)


class RAGSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_")
    child_chunk_size: int = 500
    child_chunk_overlap: int = 100
    min_parent_size: int = 600
    max_parent_size: int = 4000
    top_k: int = Field(default=3, ge=1, le=100)
    score_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    max_tool_calls: int = 4
    max_iterations: int = 5
    graph_recursion_limit: int = 50
    base_token_threshold: int = 1200
    token_growth_factor: float = 0.9

    @model_validator(mode="after")
    def validate_chunk_sizes(self):
        if self.min_parent_size <= 0 or self.max_parent_size < self.min_parent_size:
            raise ValueError("父块大小必须满足 0 < min_parent_size <= max_parent_size")
        if self.child_chunk_size <= 0 or not 0 <= self.child_chunk_overlap < self.child_chunk_size:
            raise ValueError("子块重叠必须满足 0 <= overlap < chunk_size")
        return self


class LongTermMemorySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LONG_TERM_MEMORY_")
    enabled: bool = True
    top_k: int = Field(default=5, ge=1, le=100)
    merge_threshold: float = Field(default=0.88, ge=0.0, le=1.0)
    extraction_per_turn: int = 3
    max_records: int = 1000


class ObservabilitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LANGFUSE_")
    enabled: bool = False
    public_key: str = ""
    secret_key: str = ""
    host: str = "https://cloud.langfuse.com"


class UploadSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UPLOAD_")
    max_size_mb: int = 50
    allowed_extensions: list[str] = [".pdf", ".md"]


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_")
    jwt_secret: str = "change-me-in-production-use-env-var"
    token_expire_hours: int = 72


class Settings(BaseSettings):
    """所有配置项聚合在一起"""

    model_config = SettingsConfigDict(
        env_file=(str(_BASE_DIR / ".env.dev"), str(_BASE_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app: AppSettings = Field(default_factory=AppSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    rag: RAGSettings = Field(default_factory=RAGSettings)
    long_term_memory: LongTermMemorySettings = Field(default_factory=LongTermMemorySettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    upload: UploadSettings = Field(default_factory=UploadSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    dark_mode: bool = False


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _apply_user_settings(_settings)
        _settings = Settings.model_validate(_settings.model_dump())
    return _settings


def get_user_settings(user_id: str) -> Settings:
    """返回当前用户的独立配置快照，不修改进程级默认配置。"""
    settings = Settings.model_validate(get_settings().model_dump())
    if user_id:
        _apply_user_settings_from_file(settings, user_id)
    return Settings.model_validate(settings.model_dump())


def _apply_user_settings(settings: Settings) -> None:
    """把 settings.json 里的用户设置覆盖到运行时配置上"""
    path = _USER_SETTINGS_PATH
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _merge_settings(settings, data)
    except Exception:
        pass


def _merge_settings(settings: Settings, data: dict) -> None:
    """把用户设置字典合并到 Settings 对象上"""
    if "llm" in data:
        llm_data = data["llm"]
        if "model" in llm_data:
            settings.llm.model = llm_data["model"]
        if "temperature" in llm_data:
            settings.llm.temperature = float(llm_data["temperature"])
        if "num_ctx" in llm_data:
            settings.llm.num_ctx = int(llm_data["num_ctx"])
        if "ollama_base_url" in llm_data:
            settings.llm.ollama_base_url = llm_data["ollama_base_url"]
    if "rag" in data:
        rag_data = data["rag"]
        if "top_k" in rag_data:
            settings.rag.top_k = int(rag_data["top_k"])
        if "score_threshold" in rag_data:
            settings.rag.score_threshold = float(rag_data["score_threshold"])
    if "memory" in data:
        mem_data = data["memory"]
        if "enabled" in mem_data:
            settings.long_term_memory.enabled = bool(mem_data["enabled"])
        if "top_k" in mem_data:
            settings.long_term_memory.top_k = int(mem_data["top_k"])
    if "dark_mode" in data:
        settings.dark_mode = bool(data["dark_mode"])


def _user_settings_path(user_id: str) -> Path:
    return _USER_SETTINGS_PATH.parent / f"settings_{user_id}.json"

def _apply_user_settings_from_file(settings: object, user_id: str) -> None:
    path = _user_settings_path(user_id)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _merge_settings(settings, data)
    except Exception:
        pass

def save_user_settings(data: dict, user_id: str = "") -> None:
    """保存设置；个人设置不能污染进程级默认配置。"""
    path = _user_settings_path(user_id) if user_id else _USER_SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if not user_id and _settings is not None:
        _merge_settings(_settings, data)

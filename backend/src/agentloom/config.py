"""Pydantic-validated project configuration and local secret loading."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class StrictModel(BaseModel):
    """Reject misspelled or obsolete configuration keys."""

    model_config = ConfigDict(extra="forbid")


class ServerConfig(StrictModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1)
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173"])


class DatabaseConfig(StrictModel):
    app_path: Path = Path(".agentloom/app.sqlite")
    checkpoint_path: Path = Path(".agentloom/checkpoints.sqlite")


class ModelConfig(StrictModel):
    provider: Literal["fake", "openai_compatible", "anthropic"] = "fake"
    model: str = "scripted-tool-model"
    api_key_env: str = "MODEL_API_KEY"
    base_url_env: str = "MODEL_BASE_URL"
    context_window: int = Field(default=32768, gt=0)
    max_output_tokens: int = Field(default=4096, gt=0)
    temperature: float | None = Field(default=0.0, ge=0.0, le=2.0)
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=2, ge=0)


class ModelsConfig(StrictModel):
    default: ModelConfig = Field(default_factory=ModelConfig)


class RuntimeConfig(StrictModel):
    max_running_runs: int = Field(default=2, ge=1)
    max_pending_runs: int = Field(default=8, ge=1)
    max_model_attempts_per_run: int = Field(default=24, ge=1)
    max_tool_executions_per_run: int = Field(default=40, ge=1)
    max_subagents_per_run: int = Field(default=4, ge=0)
    max_running_subagents: int = Field(default=2, ge=0)
    subagent_timeout_seconds: float = Field(default=120.0, gt=0)

    @model_validator(mode="after")
    def validate_subagent_capacity(self):
        if self.max_running_subagents > self.max_subagents_per_run:
            raise ValueError("max_running_subagents 不能大于 max_subagents_per_run")
        return self


class SandboxConfig(StrictModel):
    image: str = "agentloom-python:v1"
    network: Literal["none"] = "none"
    timeout_seconds: int = Field(default=60, ge=1)
    memory_mb: int = Field(default=512, ge=64)
    cpu_limit: float = Field(default=1.0, gt=0)
    pids_limit: int = Field(default=64, ge=16)
    tmpfs_mb: int = Field(default=64, ge=16)
    output_max_bytes: int = Field(default=20000, ge=1024)


class SkillsConfig(StrictModel):
    directory: Path = Path("./skills")
    max_active_per_agent: int = Field(default=1, ge=0, le=1)


class ContextConfig(StrictModel):
    compaction_fraction: float = Field(default=0.70, gt=0.0, lt=1.0)
    tool_preview_bytes: int = Field(default=8192, ge=256)


class McpConfig(StrictModel):
    """首版只连接仓库内受信任的只读 reference_library stdio Server。"""

    enabled: bool = False
    reference_library_script: Path = Path("./mcp_servers/reference_library/server.py")
    startup_timeout_seconds: float = Field(default=10.0, gt=0)
    call_timeout_seconds: float = Field(default=10.0, gt=0)


class TracingConfig(StrictModel):
    external_enabled: bool = False


class AppConfig(StrictModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)

    def resolve_path(self, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value


class ConfigurationError(RuntimeError):
    """A live provider is selected but its local secret/config is incomplete."""


def _config_path() -> Path:
    configured = os.getenv("AGENTLOOM_CONFIG", "config.yaml")
    path = Path(configured)
    return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache(maxsize=1)
def load_config() -> AppConfig:
    """Load root .env without overriding process env, then validate YAML."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    path = _config_path()
    if not path.exists():
        path = PROJECT_ROOT / "config.example.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(raw)


def require_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"缺少环境变量 {name}；请在项目根目录 .env 中填写")
    return value

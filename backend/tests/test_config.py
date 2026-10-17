from pathlib import Path

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from agentloom.config import PROJECT_ROOT, AppConfig, ConfigurationError, ModelConfig
from agentloom.models.factory import create_chat_model
from agentloom.models.fake import OfflineChatModel
from agentloom.tools import get_builtin_tools


def test_example_config_is_complete_and_fake_is_offline() -> None:
    import yaml

    raw = yaml.safe_load((PROJECT_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    config = AppConfig.model_validate(raw)

    assert config.models.default.provider == "fake"
    assert isinstance(create_chat_model(config.models.default), OfflineChatModel)
    assert config.resolve_path(config.database.app_path) == PROJECT_ROOT / ".agentloom/app.sqlite"


def test_live_model_requires_named_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_AGENTLOOM_KEY", raising=False)
    config = ModelConfig(
        provider="openai_compatible",
        model="test-model",
        api_key_env="TEST_AGENTLOOM_KEY",
    )

    with pytest.raises(ConfigurationError, match="TEST_AGENTLOOM_KEY"):
        create_chat_model(config)


def test_live_model_is_built_from_named_environment_without_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_AGENTLOOM_KEY", "test-only-key")
    monkeypatch.setenv("TEST_AGENTLOOM_BASE", "https://example.invalid/v1")
    config = ModelConfig(
        provider="openai_compatible",
        model="test-model",
        api_key_env="TEST_AGENTLOOM_KEY",
        base_url_env="TEST_AGENTLOOM_BASE",
    )

    model = create_chat_model(config)

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "test-model"
    assert str(model.openai_api_base).rstrip("/") == "https://example.invalid/v1"


def test_anthropic_model_is_built_from_named_environment_without_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "test-only-key")
    monkeypatch.setenv("TEST_ANTHROPIC_BASE", "https://example.invalid")
    config = ModelConfig(
        provider="anthropic",
        model="claude-test",
        api_key_env="TEST_ANTHROPIC_KEY",
        base_url_env="TEST_ANTHROPIC_BASE",
        max_output_tokens=123,
        temperature=None,
        timeout_seconds=9,
        max_retries=1,
    )

    model = create_chat_model(config)

    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-test"
    assert model.max_tokens == 123
    assert model.temperature is None
    assert model.anthropic_api_url == "https://example.invalid"
    assert model.default_request_timeout == 9
    assert model.max_retries == 1
    bound = model.bind_tools(get_builtin_tools())
    assert [tool["name"] for tool in bound.kwargs["tools"]] == [
        "add",
        "lookup_note",
        "list_dir",
        "read_file",
        "write_file",
        "replace_file",
        "present_files",
        "bash",
        "list_skills",
        "load_skill",
        "task",
        "remember_preference",
    ]


def test_anthropic_model_requires_its_named_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_ANTHROPIC_KEY", raising=False)
    config = ModelConfig(
        provider="anthropic",
        model="claude-test",
        api_key_env="TEST_ANTHROPIC_KEY",
    )

    with pytest.raises(ConfigurationError, match="TEST_ANTHROPIC_KEY"):
        create_chat_model(config)


def test_config_examples_exist_and_local_files_are_ignored() -> None:
    ignored = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "config.yaml" in ignored and ".env" in ignored
    assert Path(PROJECT_ROOT / "config.example.yaml").exists()
    assert Path(PROJECT_ROOT / ".env.example").exists()

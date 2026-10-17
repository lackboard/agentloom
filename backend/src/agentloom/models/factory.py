"""Create the configured offline, OpenAI-compatible, or Anthropic chat model."""

import os

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from agentloom.config import ModelConfig, load_config, require_environment
from agentloom.models.fake import OfflineChatModel


def create_chat_model(config: ModelConfig | None = None) -> BaseChatModel:
    selected = config or load_config().models.default
    if selected.provider == "fake":
        return OfflineChatModel()

    api_key = require_environment(selected.api_key_env)
    base_url = os.getenv(selected.base_url_env, "").strip() or None
    if selected.provider == "anthropic":
        return ChatAnthropic(
            model_name=selected.model,
            api_key=api_key,
            base_url=base_url,
            temperature=selected.temperature,
            max_tokens_to_sample=selected.max_output_tokens,
            timeout=selected.timeout_seconds,
            max_retries=selected.max_retries,
        )

    return ChatOpenAI(
        model=selected.model,
        api_key=api_key,
        base_url=base_url,
        temperature=selected.temperature,
        max_tokens=selected.max_output_tokens,
        timeout=selected.timeout_seconds,
        max_retries=selected.max_retries,
        stream_usage=base_url is None,
    )

from typing import Any

from backend.common.types import Settings
from backend.infrastructure.ai.anthropic_client import AnthropicMessagesClient
from backend.infrastructure.ai.qwen_client import QwenClient


def create_model_client(
    settings: Settings,
    *,
    provider: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> Any:
    selected = (provider or "openai").strip().lower()
    if selected in {"anthropic", "minimax", "minimax-anthropic"}:
        return AnthropicMessagesClient(settings, api_key=api_key, base_url=base_url, model=model)
    return QwenClient(settings, api_key=api_key, base_url=base_url, model=model)

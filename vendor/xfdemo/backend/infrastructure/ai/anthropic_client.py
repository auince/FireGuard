import base64
from typing import Any

import anthropic

from backend.common.types import ModelDelta, ModelResult, Settings


class AnthropicMessagesClient:
    def __init__(self, settings: Settings, *, api_key: str | None = None, base_url: str | None = None, model: str | None = None) -> None:
        self.settings = settings
        self.api_key = api_key
        self.base_url = base_url
        self.model = model or "MiniMax-M3"
        if not self.api_key:
            raise RuntimeError("缺少 MiniMax/Anthropic API Key，请在 .env 中配置 MINIMAX_API_KEY 或对应模型 API Key")
        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self.client = anthropic.Anthropic(**kwargs)

    def invoke(self, messages: list[dict[str, Any]]) -> ModelResult:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.settings.max_tokens,
            temperature=self.settings.temperature,
            messages=to_anthropic_messages(messages),
        )
        return ModelResult(content=extract_text(response), usage=extract_usage(getattr(response, "usage", None)))

    def stream(self, messages: list[dict[str, Any]]):
        result = self.invoke(messages)
        yield ModelDelta(content=result.content, usage=result.usage)


def to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = "assistant" if message.get("role") == "assistant" else "user"
        blocks = convert_content(message.get("content"))
        if blocks:
            converted.append({"role": role, "content": blocks})
    return converted


def convert_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    blocks: list[dict[str, Any]] = []
    for part in content or []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            text = str(part.get("text") or "")
            if text:
                blocks.append({"type": "text", "text": text})
        elif part.get("type") == "image_url":
            url = ((part.get("image_url") or {}).get("url") or "").strip()
            image_block = image_url_to_block(url)
            if image_block:
                blocks.append(image_block)
    return blocks


def image_url_to_block(url: str) -> dict[str, Any] | None:
    if not url:
        return None
    if url.startswith("data:") and ";base64," in url:
        header, data = url.split(",", 1)
        media_type = header[5:].split(";", 1)[0] or "image/png"
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
    if url.startswith("http://") or url.startswith("https://"):
        return {"type": "image", "source": {"type": "url", "url": url}}
    try:
        with open(url, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
        media_type = "image/png" if url.lower().endswith(".png") else "image/jpeg"
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
    except OSError:
        return None


def extract_text(response: Any) -> str:
    chunks: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", "") == "text":
            chunks.append(getattr(block, "text", "") or "")
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def extract_usage(usage: Any) -> dict[str, int]:
    if not usage:
        return {}
    mapping = {
        "input_tokens": "prompt_tokens",
        "output_tokens": "completion_tokens",
    }
    result: dict[str, int] = {}
    total = 0
    for source, target in mapping.items():
        value = getattr(usage, source, None)
        if isinstance(value, int):
            result[target] = value
            result[source] = value
            total += value
    if total:
        result["total_tokens"] = total
    return result

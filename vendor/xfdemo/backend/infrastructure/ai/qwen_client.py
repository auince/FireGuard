from typing import Any

from openai import OpenAI

from backend.common.types import ModelDelta, ModelResult, Settings

class QwenClient:
    def __init__(self, settings: Settings, *, api_key: str | None = None, base_url: str | None = None, model: str | None = None) -> None:
        self.settings = settings
        self.api_key = api_key or settings.api_key
        self.base_url = base_url or settings.base_url
        self.model = model or settings.model
        if not self.api_key:
            raise RuntimeError("缺少 API Key，请在 .env 中配置模型 API Key")
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _params(self, messages: list[dict[str, Any]], stream: bool) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": self.settings.temperature,
            "top_p": self.settings.top_p,
            "max_tokens": self.settings.max_tokens,
        }
        if any(key in self.base_url for key in ("dashscope", "aliyun", "maas.aliyuncs")):
            params["extra_body"] = {
                "enable_thinking": self.settings.enable_thinking,
                "thinking_budget": self.settings.thinking_budget,
            }
        return params

    def invoke(self, messages: list[dict[str, Any]]) -> ModelResult:
        completion = self.client.chat.completions.create(**self._params(messages, stream=False))
        message = completion.choices[0].message if completion.choices else None
        return ModelResult(
            content=(getattr(message, "content", "") if message else "") or "",
            usage=extract_usage(getattr(completion, "usage", None)),
        )

    def stream(self, messages: list[dict[str, Any]]):
        for chunk in self.client.chat.completions.create(**self._params(messages, stream=True)):
            usage = extract_usage(getattr(chunk, "usage", None))
            if not getattr(chunk, "choices", None):
                if usage:
                    yield ModelDelta(usage=usage)
                continue
            delta = chunk.choices[0].delta
            yield ModelDelta(
                content=getattr(delta, "content", None) or "",
                reasoning_content=getattr(delta, "reasoning_content", None) or "",
                usage=usage,
            )


def extract_usage(usage: Any) -> dict[str, int]:
    if not usage:
        return {}
    fields = ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens")
    if isinstance(usage, dict):
        return {key: usage[key] for key in fields if isinstance(usage.get(key), int)}
    return {key: value for key in fields if isinstance(value := getattr(usage, key, None), int)}

from dataclasses import dataclass
from typing import Any, TypedDict

class InspectionState(TypedDict, total=False):
    query: str
    image: str | None
    task: str
    messages: list[dict[str, Any]]
    report: str
    raw_report: str
    usage: dict[str, int]


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    base_url: str
    model: str
    judge_api_key: str | None
    judge_base_url: str
    judge_model: str
    temperature: float
    top_p: float
    max_tokens: int
    thinking_budget: int
    max_output_chars: int
    max_identical_deltas: int
    enable_thinking: bool
    first_provider: str = "openai"
    judge_provider: str = "openai"
    direction_review_provider: str = "openai"
    direction_review_api_key: str | None = None
    direction_review_base_url: str | None = None
    direction_review_model: str | None = None


@dataclass(frozen=True)
class ModelResult:
    content: str
    usage: dict[str, int]


@dataclass(frozen=True)
class ModelDelta:
    content: str = ""
    reasoning_content: str = ""
    usage: dict[str, int] | None = None

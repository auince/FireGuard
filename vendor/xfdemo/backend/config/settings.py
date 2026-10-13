import os
from pathlib import Path
from typing import Any

from backend.config.paths import PROJECT_ROOT
from backend.common.types import Settings

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False

DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_MODEL = "qwen3-vl-plus"
DEFAULT_MINIMAX_MODEL = "MiniMax-M3"


def load_env() -> None:
    for env_file in (Path.cwd() / ".env", PROJECT_ROOT / ".env", PROJECT_ROOT / "deploy" / ".env"):
        if env_file.exists():
            load_dotenv(env_file, override=False)
    load_dotenv(override=False)


def first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def normalized_provider(value: str | None, default: str = "openai") -> str:
    provider = (value or default or "openai").strip().lower()
    if provider in {"minimax", "anthropic", "minimax-anthropic"}:
        return "anthropic"
    return "openai"


def env_int(name: str, default: str) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return int(default)


def env_float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "y", "on"}


def get_settings() -> Settings:
    load_env()
    first_provider = normalized_provider(first_env("FIRST_VL_PROVIDER", "MODEL_PROVIDER"), "openai")
    judge_provider = normalized_provider(first_env("JUDGE_VL_PROVIDER", "JUDGE_PROVIDER"), "openai")
    direction_provider = normalized_provider(
        first_env("DIRECTION_REVIEW_PROVIDER", "OUTLET_DIRECTION_PROVIDER"),
        judge_provider,
    )

    minimax_api_key = first_env("MINIMAX_API_KEY", "ANTHROPIC_API_KEY")
    minimax_base_url = first_env("MINIMAX_BASE_URL", "ANTHROPIC_BASE_URL")
    minimax_model = first_env("MINIMAX_MODEL", "ANTHROPIC_MODEL") or DEFAULT_MINIMAX_MODEL

    first_api_key = first_env("FIRST_VL_API_KEY", "DASHSCOPE_API_KEY", "ALIYUN_API_KEY", "QWEN_API_KEY", "VLLM_API_KEY")
    first_base_url = first_env("FIRST_VL_API_BASE", "DASHSCOPE_BASE_URL", "ALIYUN_BASE_URL", "QWEN_BASE_URL", "VLLM_API_BASE")
    first_model = first_env("FIRST_VL_MODEL", "DASHSCOPE_MODEL", "ALIYUN_MODEL", "QWEN_MODEL", "MODEL_NAME")
    if first_provider == "anthropic":
        first_api_key = first_env("FIRST_VL_API_KEY", "MINIMAX_API_KEY", "ANTHROPIC_API_KEY")
        first_base_url = first_env("FIRST_VL_API_BASE", "MINIMAX_BASE_URL", "ANTHROPIC_BASE_URL")
        first_model = first_env("FIRST_VL_MODEL", "MINIMAX_MODEL", "ANTHROPIC_MODEL") or DEFAULT_MINIMAX_MODEL

    judge_api_key = first_env("JUDGE_VL_API_KEY", "DASHSCOPE_API_KEY", "ALIYUN_API_KEY", "QWEN_API_KEY", "VLLM_API_KEY")
    judge_base_url = first_env("JUDGE_VL_API_BASE", "DASHSCOPE_BASE_URL", "ALIYUN_BASE_URL", "QWEN_BASE_URL", "VLLM_API_BASE")
    judge_model = first_env("JUDGE_VL_MODEL", "DASHSCOPE_MODEL", "ALIYUN_MODEL", "QWEN_MODEL", "MODEL_NAME")
    if judge_provider == "anthropic":
        judge_api_key = first_env("JUDGE_VL_API_KEY", "MINIMAX_API_KEY", "ANTHROPIC_API_KEY")
        judge_base_url = first_env("JUDGE_VL_API_BASE", "MINIMAX_BASE_URL", "ANTHROPIC_BASE_URL")
        judge_model = first_env("JUDGE_VL_MODEL", "MINIMAX_MODEL", "ANTHROPIC_MODEL") or DEFAULT_MINIMAX_MODEL

    direction_api_key = first_env("DIRECTION_REVIEW_API_KEY", "OUTLET_DIRECTION_API_KEY")
    direction_base_url = first_env("DIRECTION_REVIEW_API_BASE", "OUTLET_DIRECTION_API_BASE")
    direction_model = first_env("DIRECTION_REVIEW_MODEL", "OUTLET_DIRECTION_MODEL")
    if direction_provider == "anthropic":
        direction_api_key = direction_api_key or minimax_api_key
        direction_base_url = direction_base_url or minimax_base_url
        direction_model = direction_model or minimax_model
    else:
        direction_api_key = direction_api_key or judge_api_key
        direction_base_url = direction_base_url or judge_base_url or DEFAULT_BASE_URL
        direction_model = direction_model or judge_model or DEFAULT_MODEL

    return Settings(
        api_key=first_api_key,
        base_url=first_base_url or DEFAULT_BASE_URL,
        model=first_model or DEFAULT_MODEL,
        judge_api_key=judge_api_key,
        judge_base_url=judge_base_url or DEFAULT_BASE_URL,
        judge_model=judge_model or DEFAULT_MODEL,
        temperature=env_float("TEMPERATURE", "0.1"),
        top_p=env_float("TOP_P", "0.8"),
        max_tokens=env_int("MAX_TOKENS", "768"),
        thinking_budget=env_int("THINKING_BUDGET", "4096"),
        max_output_chars=env_int("MAX_OUTPUT_CHARS", "1600"),
        max_identical_deltas=env_int("MAX_IDENTICAL_DELTAS", "3"),
        enable_thinking=env_bool("ENABLE_THINKING", "false"),
        first_provider=first_provider,
        judge_provider=judge_provider,
        direction_review_provider=direction_provider,
        direction_review_api_key=direction_api_key,
        direction_review_base_url=direction_base_url,
        direction_review_model=direction_model,
    )

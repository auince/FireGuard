import base64
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

WHITESPACE_RE = re.compile(r"\s+")
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)

def normalize_image(image: str | None) -> str | None:
    if not image:
        return None
    value = image.strip()
    if not value:
        return None
    if value.startswith(("http://", "https://", "data:")):
        return value
    return f"data:image/jpeg;base64,{value}"

def file_to_data_url(path: Path) -> str | None:
    if not path.exists():
        return None
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"

def normalize_text(text: str) -> str:
    return WHITESPACE_RE.sub("", text or "")


def has_repeated_tail(text: str) -> bool:
    compact = normalize_text(text)
    if len(compact) < 72:
        return False
    max_unit = min(80, len(compact) // 3)
    for unit_len in range(max_unit, 15, -1):
        unit = compact[-unit_len:]
        if unit and compact.endswith(unit * 3):
            return True
    return False


def strip_reasoning(text: str) -> str:
    return THINK_BLOCK_RE.sub("", text or "").strip()


def trim_output(text: str, max_chars: int) -> str:
    candidate = (text or "").strip()
    if not candidate:
        return candidate
    changed = True
    while changed:
        changed = False
        max_unit = min(80, len(candidate) // 3)
        for unit_len in range(max_unit, 15, -1):
            unit = candidate[-unit_len:]
            if unit and candidate.endswith(unit * 3):
                candidate = candidate[: -(2 * unit_len)].rstrip()
                changed = True
                break
    if len(candidate) > max_chars:
        candidate = candidate[:max_chars].rstrip()
    return candidate


def ndjson(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"

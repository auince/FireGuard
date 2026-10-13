from __future__ import annotations

import hashlib
import json
import re
from typing import Any


SCHEMA_VERSION = 1
VERDICT_LABELS = {
    "qualified": "合格",
    "unqualified": "不合格",
    "unknown": "无法判断",
}
VERDICT_CODES = {label: code for code, label in VERDICT_LABELS.items()}
FIELD_LABELS = {
    "verdict": "检测结论",
    "conclusion": "结论说明",
    "regulations": "涉及法律法规",
    "recommendations": "整改建议",
}
EDITABLE_FIELDS = tuple(FIELD_LABELS)
FIELD_LIMITS = {
    "conclusion": 6000,
    "regulations": 6000,
    "recommendations": 6000,
}


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:limit]


def _section_body(lines: list[str], start: int, end: int) -> str:
    return "\n".join(line.rstrip() for line in lines[start:end]).strip()


def parse_report_document(report: str) -> dict[str, Any]:
    """Convert the public three-section report into an editable document."""
    lines = str(report or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    section_positions: dict[str, int] = {}
    verdict_label = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        match = re.match(r"^([一二三])、(.+)$", stripped)
        if not match:
            continue
        numeral, title = match.groups()
        section_positions[numeral] = index
        if numeral == "一":
            verdict_match = re.match(r"^检测结论\s*[：:]?\s*(.*)$", title.strip())
            if verdict_match:
                verdict_label = verdict_match.group(1).strip()

    first = section_positions.get("一", -1)
    second = section_positions.get("二", len(lines))
    third = section_positions.get("三", len(lines))
    conclusion = _section_body(lines, first + 1, second) if first >= 0 else str(report or "").strip()
    regulations = _section_body(lines, second + 1, third) if second < len(lines) else ""
    recommendations = _section_body(lines, third + 1, len(lines)) if third < len(lines) else ""
    conclusion = conclusion or "当前报告未提供可解析的检测结论。"
    regulations = regulations or "该功能建设中"
    recommendations = recommendations or "建议由巡检人员结合现场情况进行人工复核。"

    return normalize_report_document({
        "schemaVersion": SCHEMA_VERSION,
        "verdict": VERDICT_CODES.get(verdict_label, "unknown"),
        "conclusion": conclusion,
        "regulations": regulations,
        "recommendations": recommendations,
    })


def normalize_report_document(document: dict[str, Any] | None) -> dict[str, Any]:
    payload = document or {}
    verdict = str(payload.get("verdict") or "").strip()
    if verdict in VERDICT_CODES:
        verdict = VERDICT_CODES[verdict]
    if verdict not in VERDICT_LABELS:
        raise ValueError("检测结论必须为合格、不合格或无法判断")

    normalized = {
        "schemaVersion": SCHEMA_VERSION,
        "verdict": verdict,
        "conclusion": _clean_text(payload.get("conclusion"), FIELD_LIMITS["conclusion"]),
        "regulations": _clean_text(payload.get("regulations"), FIELD_LIMITS["regulations"]),
        "recommendations": _clean_text(payload.get("recommendations"), FIELD_LIMITS["recommendations"]),
    }
    for field in ("conclusion", "regulations", "recommendations"):
        if not normalized[field]:
            raise ValueError(f"{FIELD_LABELS[field]}不能为空")
    return normalized


def render_report_document(document: dict[str, Any]) -> str:
    normalized = normalize_report_document(document)
    return "\n".join([
        f"一、检测结论：{VERDICT_LABELS[normalized['verdict']]}",
        normalized["conclusion"],
        "",
        "二、涉及法律法规",
        normalized["regulations"],
        "",
        "三、整改建议",
        normalized["recommendations"],
    ])


def changed_report_fields(
    before: dict[str, Any],
    after: dict[str, Any],
) -> list[str]:
    left = normalize_report_document(before)
    right = normalize_report_document(after)
    return [field for field in EDITABLE_FIELDS if left.get(field) != right.get(field)]


def report_document_hash(document: dict[str, Any]) -> str:
    normalized = normalize_report_document(document)
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def default_review_note(
    original: dict[str, Any],
    revised: dict[str, Any],
    changed_fields: list[str],
) -> str:
    original_doc = normalize_report_document(original)
    revised_doc = normalize_report_document(revised)
    if not changed_fields:
        return "人工复核后确认当前报告内容，无需修正。"

    sentences: list[str] = []
    if "verdict" in changed_fields:
        sentences.append(
            f"原模型结论为{VERDICT_LABELS[original_doc['verdict']]}，"
            f"人工复核后修正为{VERDICT_LABELS[revised_doc['verdict']]}"
        )
    other_fields = [
        FIELD_LABELS[field]
        for field in changed_fields
        if field != "verdict"
    ]
    if other_fields:
        prefix = "同步修正" if sentences else "人工复核后修正"
        sentences.append(prefix + "、".join(other_fields))
    return "；".join(sentences).rstrip("。") + "。"

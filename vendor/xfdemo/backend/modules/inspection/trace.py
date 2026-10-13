import time
from typing import Any

from backend.modules.inspection.labels import INTERNAL_LABELS
from backend.modules.inspection.parser import report_fields_for_trace
from backend.modules.inspection.yolo_context import (
    missing_equipment_fallback_labels,
    yolo_has_component_for_defect,
    yolo_labels_for_trace,
)

def trace_stage(name: str, title: str, started: float, status: str = "ok", **details: Any) -> dict[str, Any]:
    duration_ms = int((time.perf_counter() - started) * 1000)
    usage = details.get("usage") or {}
    return {
        "name": name,
        "title": title,
        "status": status,
        "durationMs": duration_ms,
        "throughput": usage_throughput(usage, duration_ms),
        **details,
    }


def normalized_usage(usage: dict[str, Any] | None) -> dict[str, int]:
    payload = usage or {}
    input_tokens = int(payload.get("prompt_tokens") or payload.get("input_tokens") or 0)
    output_tokens = int(payload.get("completion_tokens") or payload.get("output_tokens") or 0)
    total_tokens = int(payload.get("total_tokens") or input_tokens + output_tokens)
    return {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
    }


def usage_throughput(usage: dict[str, Any] | None, duration_ms: int) -> dict[str, float | int]:
    normalized = normalized_usage(usage)
    seconds = max(duration_ms / 1000, 0.001)
    return {
        **normalized,
        "inputTokensPerSecond": round(normalized["inputTokens"] / seconds, 2),
        "outputTokensPerSecond": round(normalized["outputTokens"] / seconds, 2),
    }


def build_trace_summary(raw_report: str, final_report: str, yolo_result: dict[str, Any] | None, stages: list[dict[str, Any]]) -> dict[str, Any]:
    first = report_fields_for_trace(raw_report)
    final = report_fields_for_trace(final_report)
    yolo_labels = yolo_labels_for_trace(yolo_result)
    first_labels = first.get("labels") or []
    final_labels = final.get("labels") or []
    issues: list[dict[str, Any]] = []
    if first.get("verdict") != final.get("verdict") or set(first_labels) != set(final_labels):
        issues.append({"type": "qwen_corrected", "title": "QwenVL \u521d\u68c0\u88ab\u4e8c\u6b21\u590d\u6838\u4fee\u6b63", "detail": "\u521d\u68c0\u7ed3\u8bba\u6216\u6807\u7b7e\u4e0e\u6700\u7ec8\u590d\u6838\u7ed3\u679c\u4e0d\u4e00\u81f4\u3002"})
    final_internal_labels = [label for label in final_labels if label in INTERNAL_LABELS]
    if yolo_labels:
        if (yolo_result or {}).get("modelType") == "component_presence":
            contradicted_missing = [label for label in final_internal_labels if yolo_has_component_for_defect(label, yolo_labels)]
            if contradicted_missing:
                issues.append({"type": "yolo_component_contradiction", "title": "YOLO \u7ec4\u4ef6\u68c0\u51fa\u4e0e\u7f3a\u5931\u7ed3\u8bba\u51b2\u7a81", "detail": "\u8be5\u7ec4\u4ef6\u5728 YOLO \u4e2d\u5df2\u88ab\u68c0\u51fa\uff0c\u9700\u8981\u91cd\u70b9\u590d\u6838\u662f\u5426\u4ecd\u80fd\u5224\u5b9a\u7f3a\u5931\u3002", "labels": contradicted_missing, "components": yolo_labels})
        else:
            extra = [label for label in yolo_labels if label not in final_internal_labels]
            if extra:
                issues.append({"type": "yolo_possible_false_positive", "title": "YOLO \u68c0\u51fa\u672a\u88ab\u6700\u7ec8\u91c7\u7eb3", "detail": "\u53ef\u80fd\u662f YOLO \u8bef\u62a5\uff0c\u4e5f\u53ef\u80fd\u662f\u590d\u6838\u6a21\u578b\u672a\u91c7\u7eb3\u3002", "labels": extra})
    if final_internal_labels:
        fallback_used = missing_equipment_fallback_labels(final_internal_labels, yolo_labels)
        if fallback_used:
            issues.append({"type": "vlm_fallback_used", "title": "\u5927\u6a21\u578b\u515c\u5e95\u5224\u65ad\u6c34\u5e26/\u6c34\u67aa\u7f3a\u5931", "detail": "YOLO \u672a\u68c0\u51fa\u6c34\u5e26/\u6c34\u67aa\u76f8\u5173\u6846\uff0c\u5df2\u7531\u4e8c\u6b21\u590d\u6838\u5927\u6a21\u578b\u6839\u636e\u539f\u56fe\u515c\u5e95\u5224\u65ad\u3002", "labels": fallback_used})
        if (yolo_result or {}).get("modelType") != "component_presence":
            missed = [label for label in final_internal_labels if label not in yolo_labels and label not in fallback_used]
            if missed:
                issues.append({"type": "yolo_possible_miss", "title": "\u6700\u7ec8\u9690\u60a3\u672a\u88ab YOLO \u68c0\u51fa", "detail": "YOLO \u5bf9\u8fd9\u4e9b\u6700\u7ec8\u6807\u7b7e\u6ca1\u6709\u7ed9\u51fa\u5019\u9009\u6846\uff0c\u53ef\u80fd\u9700\u8981\u8865\u6570\u636e\u6216\u8c03\u9608\u503c\u3002", "labels": missed})
    if final.get("verdict") == "\u65e0\u6cd5\u5224\u65ad" or "\u4eba\u5de5\u590d\u6838" in (final_report or ""):
        issues.append({"type": "judge_needs_manual_review", "title": "\u4e8c\u6b21\u590d\u6838\u7f6e\u4fe1\u4e0d\u8db3", "detail": "\u6700\u7ec8\u7ed3\u679c\u5efa\u8bae\u4eba\u5de5\u590d\u6838\uff0c\u8bf4\u660e\u56fe\u50cf\u8bc1\u636e\u6216\u6a21\u578b\u5224\u65ad\u4ecd\u4e0d\u7a33\u5b9a\u3002"})
    if yolo_result and not yolo_result.get("enabled") and not yolo_result.get("skipped"):
        issues.append({"type": "yolo_unavailable", "title": "YOLO \u672a\u542f\u7528\u6216\u4e0d\u53ef\u7528", "detail": str(yolo_result.get("reason") or "\u65e0\u8be6\u7ec6\u539f\u56e0")})
    total_duration_ms = sum(int(stage.get("durationMs") or 0) for stage in stages)
    total_usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
    for stage in stages:
        normalized = normalized_usage(stage.get("usage") or {})
        for key in total_usage:
            total_usage[key] += normalized[key]
    seconds = max(total_duration_ms / 1000, 0.001)
    return {
        "first": first,
        "final": final,
        "yoloLabels": yolo_labels,
        "issues": issues,
        "totalDurationMs": total_duration_ms,
        "stageCount": len(stages),
        "usage": {
            **total_usage,
            "inputTokensPerSecond": round(total_usage["inputTokens"] / seconds, 2),
            "outputTokensPerSecond": round(total_usage["outputTokens"] / seconds, 2),
        },
    }

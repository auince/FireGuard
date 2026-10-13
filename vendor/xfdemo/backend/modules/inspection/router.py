from __future__ import annotations

import os
import time
from dataclasses import asdict
from typing import Any, Callable

from backend.infrastructure.vision.yolo_detector import run_yolo_detection
from backend.modules.inspection.intent import IntentResult


ProgressCallback = Callable[[dict[str, Any]], None]

ROUTE_ORDER = (
    ("internal_components", "indoor_hydrant", "internal_components", "识别室内消火栓组件"),
    ("appearance", "indoor_hydrant", "appearance", "识别室内消火栓箱体"),
    ("outdoor_hydrant", "outdoor_hydrant", "outdoor", "识别室外消火栓"),
    ("fire_extinguisher", "fire_extinguisher", "extinguisher", "识别灭火器与压力指示器"),
)

INDOOR_CORE_LABELS = {"水带", "水枪", "软管", "栓体", "接口", "手轮", "阀门", "控制器"}
INDOOR_STRONG_SINGLE_LABELS = {"水带", "水枪", "软管", "栓体"}
APPEARANCE_LABELS = {"消火栓", "箱门", "中文标识", "操作说明"}

# Component presence may use the detector's 0.20 confidence floor. Device
# routing is intentionally stricter because a wrong branch produces an
# entirely unrelated report.
INDOOR_STRONG_SINGLE_CONF = float(os.getenv("YOLO_ROUTE_INDOOR_SINGLE_CONF", "0.65"))
APPEARANCE_BOX_CONF = float(os.getenv("YOLO_ROUTE_APPEARANCE_BOX_CONF", "0.35"))
OUTDOOR_ROUTE_CONF = float(os.getenv("YOLO_ROUTE_OUTDOOR_CONF", "0.55"))
EXTINGUISHER_ROUTE_CONF = float(os.getenv("YOLO_ROUTE_EXTINGUISHER_CONF", "0.60"))
EXTINGUISHER_PAIR_BODY_CONF = float(os.getenv("YOLO_ROUTE_EXTINGUISHER_PAIR_BODY_CONF", "0.45"))
EXTINGUISHER_PAIR_PRESSURE_CONF = float(os.getenv("YOLO_ROUTE_EXTINGUISHER_PAIR_PRESSURE_CONF", "0.50"))
ROUTE_SCORE_MARGIN = float(os.getenv("YOLO_ROUTE_SCORE_MARGIN", "0.10"))


def _emit(callback: ProgressCallback | None, **payload: Any) -> None:
    if callback:
        callback(payload)


def _detections(result: dict[str, Any]) -> list[dict[str, Any]]:
    return list(result.get("detections") or [])


def _label(item: dict[str, Any]) -> str:
    return str(item.get("label") or item.get("component") or item.get("className") or "").strip()


def _confidence(item: dict[str, Any]) -> float:
    try:
        return float(item.get("confidence") or 0)
    except (TypeError, ValueError):
        return 0.0


def _route_match(task: str, result: dict[str, Any]) -> tuple[bool, float, str]:
    detections = _detections(result)
    labels = {_label(item) for item in detections if _label(item)}
    highest = max((_confidence(item) for item in detections), default=0.0)

    if task == "internal_components":
        core = labels & INDOOR_CORE_LABELS
        strong_single = any(
            _label(item) in INDOOR_STRONG_SINGLE_LABELS
            and _confidence(item) >= INDOOR_STRONG_SINGLE_CONF
            for item in detections
        )
        matched = (len(core) >= 2 and highest >= 0.30) or strong_single
        reason = (
            f"发现 {len(core)} 类室内核心组件，最高置信度 {highest:.2f}"
            if matched
            else f"室内组件证据不足：{len(core)} 类，最高置信度 {highest:.2f}"
        )
        score = min(1.0, len(core) * 0.22 + highest * 0.58)
        return matched, score, reason

    if task == "appearance":
        visible = labels & APPEARANCE_LABELS
        has_box = any(
            _label(item) in {"消火栓", "箱门"}
            and _confidence(item) >= APPEARANCE_BOX_CONF
            for item in detections
        )
        has_identity = "中文标识" in visible or "操作说明" in visible
        matched = (has_box and has_identity) or (len(visible) >= 3 and highest >= 0.40)
        reason = (
            f"发现室内箱体组合证据：{'、'.join(sorted(visible))}"
            if matched
            else f"室内箱体组合证据不足：{'、'.join(sorted(visible)) or '无'}"
        )
        score = min(1.0, len(visible) * 0.20 + highest * 0.45)
        return matched, score, reason

    if task == "outdoor_hydrant":
        candidates = [item for item in detections if _label(item) == "室外消火栓"]
        top = max((_confidence(item) for item in candidates), default=0.0)
        matched = top >= OUTDOOR_ROUTE_CONF
        return matched, top, f"室外消火栓最高置信度 {top:.2f}"

    extinguisher = max(
        (_confidence(item) for item in detections if _label(item) == "灭火器"),
        default=0.0,
    )
    pressure = max(
        (_confidence(item) for item in detections if _label(item) == "灭火器压力指示器"),
        default=0.0,
    )
    paired = (
        extinguisher >= EXTINGUISHER_PAIR_BODY_CONF
        and pressure >= EXTINGUISHER_PAIR_PRESSURE_CONF
    )
    matched = extinguisher >= EXTINGUISHER_ROUTE_CONF or paired
    paired_bonus = 0.12 if paired else 0.0
    score = min(1.0, max(extinguisher, pressure) + paired_bonus)
    return matched, score, f"灭火器 {extinguisher:.2f}，压力指示器 {pressure:.2f}"


def _unknown_intent(evidence: str, source: str = "yolo_router") -> IntentResult:
    return IntentResult(
        inspection_type="unknown",
        confidence=0.0,
        scope_hint="unknown",
        evidence=evidence,
        source=source,
    )


def resolve_yolo_route(
    image: str | None,
    query: str = "",
    explicit_task: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[IntentResult, dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    probes: list[dict[str, Any]] = []

    # The product only uploads an image. Keep these arguments for API
    # compatibility, but never let fixed request text or a fixed task choose
    # the report branch.
    _ = query, explicit_task

    if not image:
        intent = _unknown_intent("未提供图片，无法确认消防设施类型", "no_image")
        return intent, {"enabled": False, "detections": [], "reason": "no image"}, {
            "source": "no_image",
            "latencyMs": 0,
            "probes": probes,
            "selectedTask": "",
            "selectedReason": intent.evidence,
        }

    def run_probe(
        route: tuple[str, str, str, str],
        detail: str,
    ) -> dict[str, Any]:
        task, inspection_type, _scope_hint, label = route
        _emit(
            progress_callback,
            stage="route",
            substage=task,
            status="running",
            label=f"正在{label}",
            detail=detail,
        )
        probe_started = time.perf_counter()
        result = run_yolo_detection(image, task=task)
        duration_ms = int((time.perf_counter() - probe_started) * 1000)
        matched, score, reason = _route_match(task, result)
        probe = {
            "task": task,
            "inspectionType": inspection_type,
            "matched": matched,
            "score": round(score, 4),
            "reason": reason,
            "durationMs": duration_ms,
            "detectionCount": len(_detections(result)),
            "labels": sorted({_label(item) for item in _detections(result) if _label(item)}),
            "result": result,
        }
        probes.append(probe)
        _emit(
            progress_callback,
            stage="route",
            substage=task,
            status="complete",
            label=label.replace("识别", "") + ("已确认" if matched else "未确认"),
            detail=reason,
            durationMs=duration_ms,
            detectionCount=probe["detectionCount"],
        )
        return probe

    def selected_response(
        inspection_type: str,
        probe: dict[str, Any],
        score: float,
        reason: str,
    ) -> tuple[IntentResult, dict[str, Any], dict[str, Any]]:
        task = str(probe["task"])
        scope_hint = {
            "internal_components": "internal_components",
            "appearance": "appearance",
            "outdoor_hydrant": "outdoor",
            "fire_extinguisher": "extinguisher",
        }.get(task, "unknown")
        intent = IntentResult(
            inspection_type=inspection_type,
            confidence=max(0.0, min(score, 1.0)),
            scope_hint=scope_hint,
            evidence=reason,
            source="yolo_router",
        )
        return intent, probe["result"], {
            "source": "yolo_router",
            "latencyMs": int((time.perf_counter() - started) * 1000),
            "probes": probes,
            "selectedTask": task,
            "selectedReason": reason,
        }

    # Run every detector before choosing a branch. This removes the previous
    # indoor-first short circuit.
    for route in ROUTE_ORDER:
        run_probe(
            route,
            "独立提取消防设施类别证据，全部完成后统一比较",
        )

    indoor_probes = [
        probe
        for probe in probes
        if probe["inspectionType"] == "indoor_hydrant" and probe["matched"]
    ]
    candidates: list[dict[str, Any]] = []
    if indoor_probes:
        selected_indoor = max(indoor_probes, key=lambda item: float(item["score"]))
        indoor_score = min(
            1.0,
            float(selected_indoor["score"]) + (0.08 if len(indoor_probes) > 1 else 0.0),
        )
        candidates.append({
            "inspectionType": "indoor_hydrant",
            "score": indoor_score,
            "probe": selected_indoor,
            "reason": "；".join(str(item["reason"]) for item in indoor_probes),
        })

    for inspection_type in ("outdoor_hydrant", "fire_extinguisher"):
        probe = next(
            item
            for item in probes
            if item["inspectionType"] == inspection_type
        )
        if probe["matched"]:
            candidates.append({
                "inspectionType": inspection_type,
                "score": float(probe["score"]),
                "probe": probe,
                "reason": str(probe["reason"]),
            })

    ranked = sorted(candidates, key=lambda item: float(item["score"]), reverse=True)
    if ranked:
        selected = ranked[0]
        if len(ranked) == 1 or (
            float(selected["score"]) - float(ranked[1]["score"]) >= ROUTE_SCORE_MARGIN
        ):
            return selected_response(
                str(selected["inspectionType"]),
                selected["probe"],
                float(selected["score"]),
                str(selected["reason"]),
            )
        reason = (
            f"类别证据冲突：{selected['inspectionType']} {float(selected['score']):.2f}，"
            f"{ranked[1]['inspectionType']} {float(ranked[1]['score']):.2f}"
        )
        source = "yolo_ambiguous"
    else:
        reason = "所有 YOLO 类别证据均未达到设备路由阈值"
        source = "yolo_no_match"

    strongest = max(probes, key=lambda item: float(item["score"]))
    intent = _unknown_intent(reason, source)
    return intent, strongest["result"], {
        "source": source,
        "latencyMs": int((time.perf_counter() - started) * 1000),
        "probes": probes,
        "selectedTask": "",
        "selectedReason": reason,
    }


def route_trace_payload(intent: IntentResult, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        **asdict(intent),
        "displayName": intent.display_name,
        "latencyMs": meta.get("latencyMs", 0),
        "source": meta.get("source", intent.source),
        "selectedTask": meta.get("selectedTask", ""),
        "selectedReason": meta.get("selectedReason", ""),
        "probes": [
            {key: value for key, value in probe.items() if key != "result"}
            for probe in meta.get("probes") or []
        ],
    }

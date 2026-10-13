from typing import Any

from backend.modules.inspection.labels import INTERNAL_LABELS
from backend.modules.inspection.parser import _pick_report_field, report_fields_for_trace, suggestions_from_report

def yolo_labels_for_trace(result: dict[str, Any] | None) -> list[str]:
    labels: list[str] = []
    for item in (result or {}).get("detections") or []:
        label = str(item.get("component") or item.get("label") or item.get("className") or "").strip()
        if label and label not in labels:
            labels.append(label)
    return labels



MISSING_EQUIPMENT_LABELS = {
    "\u5ba4\u5185\u6d88\u706b\u6813\u65e0\u6d88\u9632\u6c34\u5e26",
    "\u5ba4\u5185\u6d88\u706b\u6813\u65e0\u6d88\u9632\u6c34\u67aa",
}

YOLO_COMPONENT_TO_DEFECT_HINTS = {
    "\u624b\u8f6e": ["\u5ba4\u5185\u6d88\u706b\u6813\u624b\u8f6e\u7f3a\u5931"],
    "\u63a5\u53e3": ["\u5ba4\u5185\u6d88\u706b\u6813\u6d88\u9632\u63a5\u53e3\u7f3a\u5931"],
    "\u6813\u4f53": ["\u5ba4\u5185\u6d88\u706b\u6813\u65e0\u7bb1\u4f53"],
    "\u6c34\u5e26": ["\u5ba4\u5185\u6d88\u706b\u6813\u65e0\u6d88\u9632\u6c34\u5e26"],
    "\u6c34\u67aa": ["\u5ba4\u5185\u6d88\u706b\u6813\u65e0\u6d88\u9632\u6c34\u67aa"],
    "\u9600\u95e8": ["\u5ba4\u5185\u6d88\u706b\u6813\u624b\u8f6e\u7f3a\u5931"],
}

DEFECT_TO_REQUIRED_COMPONENTS = {
    defect: component
    for component, defects in YOLO_COMPONENT_TO_DEFECT_HINTS.items()
    for defect in defects
}


def yolo_component_labels(result: dict[str, Any] | None) -> list[str]:
    return yolo_labels_for_trace(result)


def yolo_has_component_for_defect(defect_label: str, yolo_labels: list[str]) -> bool:
    required = DEFECT_TO_REQUIRED_COMPONENTS.get(defect_label)
    return bool(required and required in yolo_labels)


def yolo_detected_components_text(yolo_labels: list[str]) -> str:
    return "\u3001".join(yolo_labels) if yolo_labels else "\u65e0"


def missing_equipment_fallback_labels(final_labels: list[str], yolo_labels: list[str]) -> list[str]:
    return [label for label in final_labels if label in MISSING_EQUIPMENT_LABELS and not yolo_has_component_for_defect(label, yolo_labels)]

def build_missing_equipment_fallback_prompt(judge_scope: str, yolo_result: dict[str, Any] | None) -> str:
    if judge_scope != "internal_components":
        return ""
    yolo_labels = yolo_labels_for_trace(yolo_result)
    missed = [label for label in MISSING_EQUIPMENT_LABELS if not yolo_has_component_for_defect(label, yolo_labels)]
    detail = "\\n".join(f"- {label}" for label in missed) if missed else "- YOLO \u5df2\u7ed9\u51fa\u6c34\u5e26/\u6c34\u67aa\u76f8\u5173\u5019\u9009\u7ebf\u7d22\uff0c\u4ecd\u9700\u56de\u5230\u539f\u56fe\u590d\u6838\u3002"
    return (
        "\\n\\n\u5185\u90e8\u7ec4\u4ef6\u7f3a\u5931\u9879\u515c\u5e95\u590d\u6838\uff08\u5f3a\u7ea6\u675f\uff09\uff1a"
        "\\nYOLO \u662f\u5185\u90e8\u7ec4\u4ef6\u5b58\u5728\u68c0\u6d4b\uff0c\u5df2\u68c0\u51fa\u7ec4\u4ef6\uff1a" + yolo_detected_components_text(yolo_labels) + "\u3002"
        "\\nYOLO \u68c0\u51fa\u6c34\u5e26/\u6c34\u67aa/\u624b\u8f6e/\u63a5\u53e3\u7b49\u7ec4\u4ef6\u65f6\uff0c\u5e94\u4f5c\u4e3a\u6392\u9664\u5bf9\u5e94\u7f3a\u5931\u7c7b\u8bef\u62a5\u7684\u91cd\u8981\u7ebf\u7d22\uff1bYOLO \u672a\u68c0\u51fa\u4e5f\u53ea\u80fd\u8bf4\u660e\u672a\u63d0\u4f9b\u5b9a\u4f4d\u7ebf\u7d22\uff0c\u7edd\u5bf9\u4e0d\u80fd\u4f5c\u4e3a\u7f3a\u5931\u8bc1\u636e\u3002"
        "\\n\u4f60\u5fc5\u987b\u72ec\u7acb\u56de\u5230\u539f\u56fe\u68c0\u67e5\u6c34\u67aa\u548c\u6c34\u5e26\u662f\u5426\u53ef\u89c1\uff0c\u5e76\u4f18\u5148\u6392\u9664\u8bef\u5224\u7f3a\u5931\u3002"
        "\\n\u6d88\u9632\u6c34\u67aa\u53ef\u89c1\u5224\u5b9a\uff1a\u53ea\u8981\u56fe\u4e2d\u6709\u94f6\u8272/\u91d1\u5c5e\u55b7\u5634\u3001\u9525\u5f62\u6216\u7ba1\u72b6\u55b7\u5c04\u5668\u3001\u6302\u5728\u7bb1\u5185\u4fa7\u6216\u652f\u67b6\u4e0a\u7684\u6c34\u67aa\u5f62\u6001\u7269\uff0c\u5c31\u89c6\u4e3a\u6c34\u67aa\u53ef\u89c1\uff1b\u7981\u6b62\u8f93\u51fa\u201c\u5ba4\u5185\u6d88\u706b\u6813\u65e0\u6d88\u9632\u6c34\u67aa\u201d\u3002"
        "\\n\u6d88\u9632\u6c34\u5e26\u53ef\u89c1\u5224\u5b9a\uff1a\u53ea\u8981\u56fe\u4e2d\u6709\u5377\u653e\u3001\u6298\u53e0\u3001\u76d8\u7ed5\u7684\u767d\u8272/\u6d45\u8272\u7ec7\u7269\u6c34\u5e26\uff0c\u5c31\u89c6\u4e3a\u6c34\u5e26\u53ef\u89c1\uff1b\u7981\u6b62\u8f93\u51fa\u201c\u5ba4\u5185\u6d88\u706b\u6813\u65e0\u6d88\u9632\u6c34\u5e26\u201d\u3002"
        "\\n\u53ea\u6709\u5728\u753b\u9762\u5b8c\u6574\u3001\u65e0\u906e\u6321\u3001\u65e0\u88c1\u5207\u3001\u6ca1\u6709\u4efb\u4f55\u7591\u4f3c\u90e8\u4ef6\u5f62\u6001\u65f6\uff0c\u624d\u5141\u8bb8\u8f93\u51fa\u5bf9\u5e94\u7f3a\u5931\u6807\u7b7e\uff1b\u62ff\u4e0d\u51c6\u65f6\u4e0d\u8981\u65b0\u589e\u7f3a\u5931\u6807\u7b7e\uff0c\u5e94\u8bbe\u7f6e needs_manual_review=true\u3002"
        "\\n\u9700\u8981\u515c\u5e95\u590d\u6838\u4f46\u4e0d\u80fd\u76f4\u63a5\u5224\u7f3a\u5931\u7684\u9879\u76ee\uff1a\\n" + detail
    )

YOLO_BACKSTOP_CONFIDENCE = 0.20


def strong_yolo_detections(yolo_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    strong: list[dict[str, Any]] = []
    for item in (yolo_result or {}).get("detections") or []:
        label = str(item.get("component") or item.get("label") or item.get("className") or "").strip()
        if label not in YOLO_COMPONENT_TO_DEFECT_HINTS:
            continue
        try:
            confidence = float(item.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        if confidence < YOLO_BACKSTOP_CONFIDENCE:
            continue
        strong.append({"label": label, "confidence": confidence})
    strong.sort(key=lambda item: item["confidence"], reverse=True)
    return strong



YOLO_COMPONENT_MISSING_DEFECTS = {
    "栓体": "室内消火栓无箱体",
    "水带": "室内消火栓无消防水带",
    "水枪": "室内消火栓无消防水枪",
}


def yolo_presence_veto_labels(final_labels: list[str], yolo_result: dict[str, Any] | None) -> tuple[list[str], list[str], list[str]]:
    strong_components: list[str] = []
    removed: list[str] = []
    for item in strong_yolo_detections(yolo_result):
        component = item["label"]
        if component not in strong_components:
            strong_components.append(component)
        defect = YOLO_COMPONENT_MISSING_DEFECTS.get(component)
        if defect and defect in final_labels and defect not in removed:
            removed.append(defect)
    cleaned = [label for label in final_labels if label not in removed]
    return cleaned, removed, strong_components


DEFECT_VISIBLE_COMPONENT_TEXT = {
    "室内消火栓无箱体": "栓体",
    "室内消火栓无消防水带": "消防水带",
    "室内消火栓无消防水枪": "消防水枪",
}


def _remove_conflicting_missing_phrases(evidence: str, removed: list[str]) -> str:
    text = (evidence or "").strip()
    if not text:
        return ""
    clauses = []
    for raw in text.replace("；", "。").split("。"):
        for part in raw.split(";"):
            part = part.strip(" ，,;；。")
            if part:
                clauses.append(part)
    cleaned: list[str] = []
    removed_components = [DEFECT_VISIBLE_COMPONENT_TEXT.get(label, "") for label in removed]
    for clause in clauses:
        conflict = False
        for component in removed_components:
            if not component:
                continue
            keywords = {component, component.replace("消防", "")}
            if any(word and word in clause for word in keywords) and any(term in clause for term in ("未见", "缺失", "缺少", "无", "看不到")):
                conflict = True
                break
        if not conflict:
            cleaned.append(clause)
    return "。".join(cleaned).strip("。")


def _visible_components_sentence(removed: list[str], components: list[str]) -> str:
    visible = []
    for label in removed:
        name = DEFECT_VISIBLE_COMPONENT_TEXT.get(label)
        if name and name not in visible:
            visible.append(name)
    for component in components[:8]:
        normalized = DEFECT_VISIBLE_COMPONENT_TEXT.get(YOLO_COMPONENT_MISSING_DEFECTS.get(component, ""), component)
        if normalized and normalized not in visible:
            visible.append(normalized)
    component_text = "、".join(visible[:8])
    return f"画面中可见{component_text}等内部组件，相关部件在位，当前未见明确缺失。" if component_text else "画面中相关内部组件可见，当前未见明确缺失。"


def _merge_evidence_with_yolo(evidence: str, removed: list[str], components: list[str]) -> str:
    base = _remove_conflicting_missing_phrases(evidence, removed).rstrip("。；; ")
    visible_note = _visible_components_sentence(removed, components)
    if not base or len(base) > 220:
        return visible_note
    if visible_note.rstrip("。") in base:
        return base + "。"
    return base + "。" + visible_note



def _full_line_field(report: str, field: str) -> str:
    prefix = field + "："
    alt_prefix = field + ":"
    for raw in (report or "").splitlines():
        line = raw.strip()
        if line.startswith(prefix):
            return line.split("：", 1)[1].strip()
        if line.startswith(alt_prefix):
            return line.split(":", 1)[1].strip()
    return ""

def apply_appearance_yolo_backstop(final_report: str, yolo_result: dict[str, Any] | None) -> str:
    # Appearance YOLO provides positive localization evidence only. A missing
    # detection must not override the VLM verdict because it is not proof that
    # the corresponding visual element is absent.
    return final_report


def apply_yolo_backstop(final_report: str, raw_report: str, yolo_result: dict[str, Any] | None) -> str:
    if (yolo_result or {}).get("modelType") == "appearance_presence":
        return apply_appearance_yolo_backstop(final_report, yolo_result)
    if (yolo_result or {}).get("modelType") != "component_presence":
        return final_report
    final_fields = report_fields_for_trace(final_report)
    final_labels = list(final_fields.get("labels") or [])
    suggestions = suggestions_from_report(final_report)
    if not final_labels:
        return final_report

    cleaned_labels, removed_labels, strong_components = yolo_presence_veto_labels(final_labels, yolo_result)
    if not removed_labels:
        return final_report

    scope = _pick_report_field(final_report, "检查范围") or "内部组件"
    evidence = _full_line_field(final_report, "可见依据") or _pick_report_field(final_report, "可见依据") or ""
    verdict = "不合规" if cleaned_labels else "合规"
    evidence = _merge_evidence_with_yolo(evidence, removed_labels, strong_components)
    if verdict == "合规":
        evidence = _visible_components_sentence(removed_labels, strong_components)
    return "\n".join([
        f"检查范围：{scope}",
        f"结论：{verdict}",
        f"可见依据：{evidence}",
        "隐患标签：" + ("；".join(cleaned_labels) if cleaned_labels else "无"),
        "建议项：" + ("；".join(suggestions) if suggestions else "无"),
    ])

from typing import Any

from backend.infrastructure.vision.yolo_detector import format_yolo_for_prompt

from backend.modules.inspection.parser import (
    _pick_report_field,
    detect_task,
    extract_json_object,
    labels_from_report,
    suggestions_from_report,
)
from backend.config.paths import APPEARANCE_REFERENCE_IMAGE, INTERNAL_REFERENCE_IMAGE
from backend.modules.inspection.prompts import (
    AUTO_PROMPT,
    BEND_VERIFY_PROMPT,
    MISSING_EQUIPMENT_VERIFY_PROMPT,
    OPERATION_INSTRUCTION_VERIFY_PROMPT,
    OUTLET_DIRECTION_VERIFY_PROMPT,
    STRICT_JUDGE_PROMPT_TEMPLATE,
    initial_prompt_for_branch,
    judge_extra_for_branch,
    judge_prompt_for_branch,
)
from backend.modules.inspection.utils import file_to_data_url
from backend.modules.inspection.yolo_context import build_missing_equipment_fallback_prompt


def build_messages(
    query: str,
    image: str | None,
    task: str,
    branch_key: str | None = None,
    yolo_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # Keep the established indoor prompt payload byte-for-byte compatible.
    # New branch context is isolated to outdoor hydrant and extinguisher tasks.
    if branch_key in {None, "", "indoor_hydrant"}:
        content_parts: list[dict[str, Any]] = [{
            "type": "text",
            "text": f"{AUTO_PROMPT}\n固定检测任务：{query}",
        }]
        if image:
            content_parts.insert(0, {"type": "image_url", "image_url": {"url": image}})
        return [{"role": "user", "content": content_parts}]

    prompt = initial_prompt_for_branch(branch_key)
    yolo_context = format_yolo_for_prompt(yolo_result) if yolo_result else ""
    routed_scope = {
        "internal_components": "内部组件",
        "appearance": "箱体外观",
        "outdoor_hydrant": "室外消火栓",
        "fire_extinguisher": "灭火器",
    }.get(task, "")
    routing_context = (
        "\n\n目标定位线索（仅用于确认对象和组件位置，不代表异常结论）：\n" + yolo_context
        if yolo_context
        else ""
    )
    if routed_scope:
        routing_context += (
            f"\n本次已由目标检测路由到“{routed_scope}”范围；请只在该范围内分析，"
            "不要自行切换到其他设施分支。"
        )
    content_parts: list[dict[str, Any]] = [{
        "type": "text",
        "text": f"{prompt}{routing_context}\n固定检测任务：{query}",
    }]
    if image:
        content_parts.insert(0, {"type": "image_url", "image_url": {"url": image}})
    return [{"role": "user", "content": content_parts}]


def build_judge_messages(
    query: str,
    image: str,
    raw_report: str,
    task: str,
    yolo_result: dict[str, Any] | None = None,
    branch_key: str | None = None,
) -> list[dict[str, Any]]:
    if branch_key in {"outdoor_hydrant", "fire_extinguisher"}:
        yolo_text = format_yolo_for_prompt(yolo_result)
        prompt = (
            judge_prompt_for_branch(branch_key)
            + "\n固定检测任务：" + query
            + "\n\n首轮巡检输出：\n" + raw_report
            + "\n\nYOLO 目标定位线索：\n" + yolo_text
            + "\n\n请以原图为准完成最终复核。"
        )
        return [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": image}},
            {"type": "text", "text": prompt},
        ]}]

    judge_scope = detect_task(query="", explicit_task=task, report=raw_report)
    if judge_scope == "auto":
        judge_scope = "internal_components" if "\u5185\u90e8" in raw_report else "appearance"
    scope_text = "\u5185\u90e8\u7ec4\u4ef6" if judge_scope == "internal_components" else "\u7bb1\u4f53\u5916\u89c2"
    yolo_text = format_yolo_for_prompt(yolo_result)
    fallback_text = build_missing_equipment_fallback_prompt(judge_scope, yolo_result)
    prompt = (
        judge_prompt_for_branch(branch_key)
        + judge_extra_for_branch(branch_key)
        + "\n\u672c\u6b21\u5efa\u8bae\u590d\u6838\u8303\u56f4\uff1a" + scope_text
        + "\n\u6ce8\u610f\uff1a\u8be5\u8303\u56f4\u53ea\u662f\u9996\u8f6e\u7ed3\u679c\u7684\u5efa\u8bae\uff1b\u5982\u679c\u539f\u56fe\u663e\u793a\u7bb1\u95e8\u5f00\u542f\u6216\u5173\u95ed\u72b6\u6001\u4e0e\u5efa\u8bae\u4e0d\u4e00\u81f4\uff0c\u4f60\u5fc5\u987b\u6309\u539f\u56fe\u91cd\u65b0\u9009\u62e9\u6b63\u786e\u8303\u56f4\u3002"
        + "\n固定检测任务：" + query
        + "\n\n\u9996\u8f6e QwenVL \u5de1\u68c0\u8f93\u51fa\uff1a\n" + raw_report
        + "\n\nYOLO \u8f85\u52a9\u68c0\u6d4b\u7ed3\u679c\uff1a\n" + yolo_text
        + ("\n\n\u5185\u90e8\u7f3a\u5931\u7c7b\u8bef\u62a5\u515c\u5e95\u63d0\u793a\uff1a\n" + fallback_text if fallback_text else "")
        + "\n\n\u7efc\u5408\u8981\u6c42\uff1a\u8bf7\u540c\u65f6\u53c2\u8003\u539f\u56fe\u3001\u9996\u8f6e QwenVL \u8f93\u51fa\u548c YOLO \u8f85\u52a9\u68c0\u6d4b\u7ed3\u679c\u3002YOLO \u53ea\u63d0\u4f9b\u76ee\u6807/\u7ec4\u4ef6\u5b9a\u4f4d\u7ebf\u7d22\uff0c\u4e0d\u662f\u6700\u7ec8\u7ed3\u8bba\uff1b\u5982\u679c YOLO \u4e0e\u539f\u56fe\u53ef\u89c1\u8bc1\u636e\u4e0d\u4e00\u81f4\uff0c\u4ee5\u539f\u56fe\u4e3a\u51c6\uff1bYOLO \u672a\u68c0\u51fa\u4e5f\u4e0d\u80fd\u76f4\u63a5\u5224\u5b9a\u65e0\u9690\u60a3\u3002\u5916\u89c2\u68c0\u6d4b\u65f6\uff0c\u5982\u679c\u539f\u56fe\u548c\u5916\u89c2YOLO\u90fd\u672a\u80fd\u786e\u8ba4\u6d88\u706b\u6813\u7bb1\u3001\u7bb1\u95e8\u6216\u4e2d\u6587\u6d88\u706b\u6813\u6807\u8bc6\u53ef\u89c1\uff0c\u4e0d\u80fd\u8f93\u51fa\u5408\u89c4\uff0c\u5e94\u8f93\u51fa\u65e0\u6cd5\u5224\u65ad\u5e76\u8bf4\u660e\u5f53\u524d\u56fe\u7247\u4e0d\u5177\u5907\u5916\u89c2\u5224\u5b9a\u6761\u4ef6\u3002"
    )
    parts: list[dict[str, Any]] = []
    for ref_desc, reference_path in (
        ("\u5185\u90e8\u7ec4\u4ef6\u5408\u89c4\u53c2\u8003\u56fe", INTERNAL_REFERENCE_IMAGE),
        ("\u7bb1\u4f53\u5916\u89c2\u5408\u89c4\u53c2\u8003\u56fe", APPEARANCE_REFERENCE_IMAGE),
    ):
        reference_url = file_to_data_url(reference_path)
        if reference_url:
            parts.extend([
                {"type": "text", "text": f"{ref_desc}\uff1a\u4ec5\u7528\u4e8e\u7406\u89e3\u5408\u89c4\u72b6\u6001\u7684\u5173\u952e\u53ef\u89c1\u8981\u7d20\uff0c\u4e0d\u4f5c\u4e3a\u4e00\u6bd4\u4e00\u6a21\u677f\u3002"},
                {"type": "image_url", "image_url": {"url": reference_url}},
            ])
    parts.extend([
        {"type": "text", "text": "\u7528\u6237\u5f85\u68c0\u56fe\uff1a"},
        {"type": "image_url", "image_url": {"url": image}},
        {"type": "text", "text": prompt},
    ])
    return [{"role": "user", "content": parts}]


def build_missing_equipment_verify_messages(
    image: str,
    query: str,
    first_report: str,
    current_report: str,
    candidate_labels: list[str] | None = None,
) -> list[dict[str, Any]]:
    candidate_text = "\uff1b".join(candidate_labels or []) if candidate_labels else "\u65e0"
    prompt = (
        MISSING_EQUIPMENT_VERIFY_PROMPT
        + "\n\u7528\u6237\u95ee\u9898\uff1a" + query
        + "\n\u5019\u9009\u7f3a\u5931\u6807\u7b7e\uff1a" + candidate_text
        + "\n\u9996\u8f6e\u62a5\u544a\uff1a\n" + first_report
        + "\n\u5f53\u524d\u5f85\u4fee\u6b63\u62a5\u544a\uff1a\n" + current_report
    )
    parts = [
        {"type": "image_url", "image_url": {"url": image}},
        {"type": "text", "text": prompt},
    ]
    return [{"role": "user", "content": parts}]


def parse_missing_equipment_verify(text: str) -> dict[str, Any] | None:
    data = extract_json_object(text)
    if not data:
        return None
    scene_fully_visible = bool(data.get("scene_fully_visible"))
    main_storage_area_visible = bool(data.get("main_storage_area_visible", scene_fully_visible))
    door_open = bool(data.get("door_open", main_storage_area_visible))
    major_occlusion = bool(data.get("major_occlusion"))
    water_gun_visible = bool(data.get("water_gun_visible"))
    water_hose_visible = bool(data.get("water_hose_visible"))
    sufficient_missing_evidence = door_open and main_storage_area_visible and not major_occlusion
    return {
        "door_open": door_open,
        "main_storage_area_visible": main_storage_area_visible,
        "major_occlusion": major_occlusion,
        "water_gun_visible": water_gun_visible,
        "water_hose_visible": water_hose_visible,
        "water_gun_missing_supported": not water_gun_visible and (
            bool(data.get("water_gun_missing_supported")) or sufficient_missing_evidence
        ),
        "water_hose_missing_supported": not water_hose_visible and (
            bool(data.get("water_hose_missing_supported")) or sufficient_missing_evidence
        ),
        "scene_fully_visible": scene_fully_visible or main_storage_area_visible,
        "evidence": str(data.get("evidence") or "").strip(),
        "confidence": str(data.get("confidence") or "\u4f4e").strip(),
    }


def _strip_missing_equipment_clauses(text: str) -> str:
    clauses: list[str] = []
    for raw in (text or "").replace("\uff1b", "\u3002").split("\u3002"):
        for part in raw.split(";"):
            clause = part.strip(" \uff0c,;\uff1b\u3002")
            if not clause:
                continue
            if ("\u6c34\u67aa" in clause or "\u6c34\u5e26" in clause) and any(term in clause for term in ("\u672a\u89c1", "\u6ca1\u6709", "\u65e0", "\u7f3a\u5931", "\u7f3a\u5c11")):
                continue
            clauses.append(clause)
    return "\u3002".join(dict.fromkeys(clauses)).strip("\u3002")


def _strip_outlet_direction_clauses(text: str) -> str:
    direction_terms = (
        "方向",
        "朝向",
        "轴线",
        "横向",
        "正对",
        "贴墙",
        "平行于",
        "箱门外侧",
    )
    clauses: list[str] = []
    for raw in (text or "").replace("\uff1b", "\u3002").split("\u3002"):
        for part in raw.split(";"):
            clause = part.strip(" \uff0c,;\uff1b\u3002")
            if not clause:
                continue
            if "栓口" in clause and any(term in clause for term in direction_terms):
                continue
            clauses.append(clause)
    return "\u3002".join(dict.fromkeys(clauses)).strip("\u3002")


def apply_missing_equipment_visibility_review(
    report: str,
    verify: dict[str, Any] | None,
    candidate_labels: list[str] | None = None,
) -> str:
    if not verify:
        return report
    scope = _pick_report_field(report, "\u68c0\u67e5\u8303\u56f4") or "\u5185\u90e8\u7ec4\u4ef6"
    evidence = _pick_report_field(report, "\u53ef\u89c1\u4f9d\u636e") or ""
    labels = list(labels_from_report(report))
    suggestions = suggestions_from_report(report)
    removed: list[str] = []
    added: list[str] = []
    missing_water_gun = "\u5ba4\u5185\u6d88\u706b\u6813\u65e0\u6d88\u9632\u6c34\u67aa"
    missing_water_hose = "\u5ba4\u5185\u6d88\u706b\u6813\u65e0\u6d88\u9632\u6c34\u5e26"
    candidate_set = set(candidate_labels or []) | {label for label in labels if label in {missing_water_gun, missing_water_hose}}

    if verify.get("water_gun_visible"):
        if missing_water_gun in labels:
            labels = [label for label in labels if label != missing_water_gun]
            removed.append(missing_water_gun)
    elif verify.get("water_gun_missing_supported") and missing_water_gun in candidate_set and missing_water_gun not in labels:
        labels.append(missing_water_gun)
        added.append(missing_water_gun)

    if verify.get("water_hose_visible"):
        if missing_water_hose in labels:
            labels = [label for label in labels if label != missing_water_hose]
            removed.append(missing_water_hose)
    elif verify.get("water_hose_missing_supported") and missing_water_hose in candidate_set and missing_water_hose not in labels:
        labels.append(missing_water_hose)
        added.append(missing_water_hose)

    if not removed and not added:
        return report

    ordered_labels: list[str] = []
    for label in labels:
        if label not in ordered_labels:
            ordered_labels.append(label)
    labels = ordered_labels

    verify_evidence = verify.get("evidence") or "\u5df2\u5b8c\u6210\u6d88\u9632\u6c34\u67aa/\u6d88\u9632\u6c34\u5e26\u4e13\u9879\u590d\u6838\u3002"
    retained_evidence = _strip_missing_equipment_clauses(evidence)
    evidence_parts = [verify_evidence.strip("\uff1b\u3002 ")]
    if labels and retained_evidence and retained_evidence not in verify_evidence:
        evidence_parts.append(retained_evidence)
    merged_evidence = "\uff1b".join(part for part in evidence_parts if part).strip("\uff1b")
    verdict = "\u4e0d\u5408\u89c4" if labels else "\u5408\u89c4"

    return "\n".join([
        f"\u68c0\u67e5\u8303\u56f4\uff1a{scope}",
        f"\u7ed3\u8bba\uff1a{verdict}",
        f"\u53ef\u89c1\u4f9d\u636e\uff1a{merged_evidence}",
        "\u9690\u60a3\u6807\u7b7e\uff1a" + ("\uff1b".join(labels) if labels else "\u65e0"),
        "\u5efa\u8bae\u9879\uff1a" + ("\uff1b".join(suggestions) if suggestions else "\u65e0"),
    ])


def build_operation_instruction_verify_messages(
    image: str,
    query: str,
    first_report: str,
    current_report: str,
    yolo_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    prompt = (
        OPERATION_INSTRUCTION_VERIFY_PROMPT
        + "\n固定检测任务：" + query
        + "\n当前外观 YOLO 线索：" + format_yolo_for_prompt(yolo_result)
        + "\n首轮报告：\n" + first_report
        + "\n当前待复核报告：\n" + current_report
    )
    return [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": image}},
        {"type": "text", "text": prompt},
    ]}]


def parse_operation_instruction_verify(text: str) -> dict[str, Any] | None:
    data = extract_json_object(text)
    if not data:
        return None
    front_visible = bool(data.get("cabinet_front_sufficiently_visible"))
    panel_visible = bool(data.get("instruction_panel_visible"))
    readable = bool(data.get("instruction_readable"))
    needs_manual = bool(data.get("needs_manual_review"))
    confidence = str(data.get("confidence") or "低").strip()
    missing_supported = (
        front_visible
        and not panel_visible
        and bool(data.get("instruction_missing_supported"))
        and not needs_manual
        and confidence != "低"
    )
    unclear_supported = (
        front_visible
        and panel_visible
        and bool(data.get("instruction_unclear_supported"))
        and not needs_manual
        and confidence != "低"
    )
    return {
        "cabinet_front_sufficiently_visible": front_visible,
        "instruction_panel_visible": panel_visible,
        "instruction_readable": readable,
        "instruction_missing_supported": missing_supported,
        "instruction_unclear_supported": unclear_supported,
        "needs_manual_review": needs_manual,
        "evidence": str(data.get("evidence") or "").strip(),
        "confidence": confidence,
    }


def _strip_operation_instruction_clauses(text: str) -> str:
    instruction_terms = ("操作说明", "操作步骤", "操作方法", "使用说明", "使用方法")
    clauses: list[str] = []
    for raw in (text or "").replace("；", "。").split("。"):
        for part in raw.split(";"):
            clause = part.strip(" ，,;；。")
            if not clause:
                continue
            if any(term in clause for term in instruction_terms):
                continue
            clauses.append(clause)
    return "。".join(dict.fromkeys(clauses)).strip("。")


def apply_operation_instruction_review(report: str, verify: dict[str, Any] | None) -> str:
    if not verify:
        return report
    operation_label = "室内消火栓箱操作说明缺失或不清晰"
    labels = list(labels_from_report(report))
    supported = bool(
        verify.get("instruction_missing_supported")
        or verify.get("instruction_unclear_supported")
    )
    positive_presence = bool(
        verify.get("instruction_panel_visible")
        and verify.get("instruction_readable")
    )
    changed = False
    if supported and operation_label not in labels:
        labels.append(operation_label)
        changed = True
    elif positive_presence and operation_label in labels:
        labels = [label for label in labels if label != operation_label]
        changed = True
    if not changed:
        return report

    scope = _pick_report_field(report, "检查范围") or "箱体外观"
    suggestions = [
        suggestion
        for suggestion in suggestions_from_report(report)
        if suggestion != operation_label
    ]
    retained_evidence = _strip_operation_instruction_clauses(
        _pick_report_field(report, "可见依据") or ""
    )
    instruction_note = str(verify.get("evidence") or "").strip("；。 ")
    if not instruction_note:
        instruction_note = (
            "消火栓箱正面和箱门主要区域清晰可见，未见操作步骤或使用方法说明。"
            if supported
            else "消火栓箱上可见操作说明面板，当前不支持判定操作说明缺失或不清晰。"
        )
    evidence_parts = [
        part for part in (retained_evidence.strip("；。 "), instruction_note)
        if part
    ]
    evidence = "；".join(dict.fromkeys(evidence_parts))
    verdict = "不合规" if labels else "合规"
    return "\n".join([
        f"检查范围：{scope}",
        f"结论：{verdict}",
        f"可见依据：{evidence}",
        "隐患标签：" + ("；".join(labels) if labels else "无"),
        "建议项：" + ("；".join(suggestions) if suggestions else "无"),
    ])


def build_bend_verify_messages(
    image: str,
    query: str,
    first_report: str,
    current_report: str,
) -> list[dict[str, Any]]:
    prompt = (
        BEND_VERIFY_PROMPT
        + "\n固定检测任务：" + query
        + "\n首轮报告：\n" + first_report
        + "\n当前待复核报告：\n" + current_report
    )
    return [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": image}},
        {"type": "text", "text": prompt},
    ]}]


def parse_bend_verify(text: str) -> dict[str, Any] | None:
    data = extract_json_object(text)
    if not data:
        return None
    legacy_schema = "target_reel_hose_visible" not in data and "target_red_supply_hose_visible" in data
    target_visible = bool(data.get("target_reel_hose_visible", data.get("target_red_supply_hose_visible")))
    target_is_reel_hose = bool(data.get("target_is_reel_hose", target_visible if legacy_schema else False))
    flat_fire_hose_excluded = bool(data.get("flat_fire_hose_excluded", target_visible if legacy_schema else False))
    connection_visible = bool(data.get("reel_or_supply_connection_visible", target_visible if legacy_schema else False))
    acute_turn = bool(data.get("abrupt_acute_turn_visible"))
    wall_damage = bool(data.get("wall_flattening_or_closed_crease_visible"))
    identity_confirmed = (
        target_visible
        and target_is_reel_hose
        and flat_fire_hose_excluded
        and connection_visible
    )
    color = str(data.get("target_hose_color") or "无法判断").strip()
    if color not in {"白色", "红色", "黑色", "其他", "无法判断"}:
        color = "无法判断"
    return {
        "target_reel_hose_visible": target_visible,
        "target_hose_color": color,
        "target_is_reel_hose": target_is_reel_hose,
        "flat_fire_hose_excluded": flat_fire_hose_excluded,
        "reel_or_supply_connection_visible": connection_visible,
        "target_identity_confirmed": identity_confirmed,
        "abrupt_acute_turn_visible": acute_turn,
        "wall_flattening_or_closed_crease_visible": wall_damage,
        "severe_bend_supported": (
            bool(data.get("severe_bend_supported"))
            and identity_confirmed
            and acute_turn
            and wall_damage
        ),
        "identity_evidence": str(data.get("identity_evidence") or "").strip(),
        "evidence": str(data.get("evidence") or "").strip(),
        "confidence": str(data.get("confidence") or "低").strip(),
    }


def _strip_bend_clauses(text: str) -> str:
    bend_terms = ("折弯", "弯折", "锐角", "折痕", "压扁", "凹陷", "通水", "受阻")
    clauses: list[str] = []
    for raw in (text or "").replace("；", "。").split("。"):
        clause = raw.strip(" ，,;；。")
        if not clause:
            continue
        if any(term in clause for term in bend_terms) and any(term in clause for term in ("软管", "供水管", "卷盘")):
            continue
        clauses.append(clause)
    return "。".join(dict.fromkeys(clauses)).strip("。")


def _normalize_bend_evidence_color(text: str, target_name: str) -> str:
    normalized = text or ""
    for term in (
        "红色供水软管", "白色供水软管", "黑色供水软管",
        "红色卷盘软管", "白色卷盘软管", "黑色卷盘软管",
        "红色软管", "白色软管", "黑色软管",
    ):
        normalized = normalized.replace(term, target_name)
    return normalized


def apply_bend_review(report: str, verify: dict[str, Any] | None) -> str:
    bend_label = "消防软管卷盘供水管道折弯严重"
    labels = list(labels_from_report(report))
    if not verify:
        return report
    supported = bool(verify.get("severe_bend_supported"))
    if supported:
        if bend_label not in labels:
            labels.append(bend_label)
    else:
        labels = [label for label in labels if label != bend_label]
    scope = _pick_report_field(report, "检查范围") or "内部组件"
    suggestions = suggestions_from_report(report)
    retained = _strip_bend_clauses(_pick_report_field(report, "可见依据") or "")
    color = str(verify.get("target_hose_color") or "无法判断")
    target_name = f"{color}卷盘软管" if color in {"白色", "红色", "黑色"} else "卷盘软管"
    raw_evidence = _normalize_bend_evidence_color(str(verify.get("evidence") or ""), target_name)
    if supported:
        bend_note = raw_evidence or f"{target_name}同一位置可见突兀锐角急转及管壁压扁或闭合折痕。"
    elif not verify.get("target_identity_confirmed"):
        bend_note = "未能稳定确认候选对象属于与卷盘相连的卷盘软管，或无法排除独立宽扁消防水带；不支持据此判定卷盘软管严重折弯。"
    elif verify.get("abrupt_acute_turn_visible") and not verify.get("wall_flattening_or_closed_crease_visible"):
        bend_note = f"{target_name}可见局部急转，但同一位置未见管壁明显收窄、压扁、凹陷或闭合折痕，不支持严重折弯。"
    elif verify.get("wall_flattening_or_closed_crease_visible") and not verify.get("abrupt_acute_turn_visible"):
        bend_note = f"{target_name}局部管壁形态可疑，但未见同一位置存在突兀锐角急转，不支持严重折弯。"
    else:
        bend_note = f"{target_name}呈自然盘绕或平滑转向，未同时发现锐角急转与管壁压扁、凹陷或闭合折痕，不支持严重折弯。"
    evidence = "；".join(dict.fromkeys(part.strip("；。 ") for part in (retained, bend_note) if part.strip("；。 ")))
    verdict = "不合规" if labels else "合规"
    return "\n".join([
        f"检查范围：{scope}",
        f"结论：{verdict}",
        f"可见依据：{evidence}",
        "隐患标签：" + ("；".join(labels) if labels else "无"),
        "建议项：" + ("；".join(suggestions) if suggestions else "无"),
    ])


def build_outlet_direction_verify_messages(
    image: str,
    query: str,
    first_report: str,
    current_report: str,
    yolo_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    prompt = (
        OUTLET_DIRECTION_VERIFY_PROMPT
        + "\n固定检测任务：" + query
        + "\n当前 YOLO 组件线索：" + format_yolo_for_prompt(yolo_result)
        + "\n首轮报告：\n" + first_report
        + "\n当前待复核报告：\n" + current_report
    )
    return [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": image}},
        {"type": "text", "text": prompt},
    ]}]


def parse_outlet_direction_verify(text: str) -> dict[str, Any] | None:
    data = extract_json_object(text)
    if not data:
        return None
    return {
        "cabinet_back_plane_visible": bool(data.get("cabinet_back_plane_visible")),
        "outlet_opening_visible": bool(data.get("outlet_opening_visible")),
        "outlet_axis_relation_to_back_plane": str(
            data.get("outlet_axis_relation_to_back_plane") or "无法判断"
        ).strip(),
        "wrong_direction_supported": bool(data.get("wrong_direction_supported")),
        "needs_manual_review": bool(data.get("needs_manual_review")),
        "evidence": str(data.get("evidence") or "").strip(),
        "confidence": str(data.get("confidence") or "低").strip(),
    }


def apply_outlet_direction_review(report: str, verify: dict[str, Any] | None) -> str:
    if not verify:
        return report
    direction_label = "室内消火栓栓口方向错误"
    labels = list(labels_from_report(report))
    supported = bool(verify.get("wrong_direction_supported"))
    needs_manual = bool(verify.get("needs_manual_review"))
    confidence = str(verify.get("confidence") or "低")
    if supported and not needs_manual and confidence != "低":
        if direction_label not in labels:
            labels.append(direction_label)
    elif direction_label in labels:
        labels = [label for label in labels if label != direction_label]
    else:
        return report
    scope = _pick_report_field(report, "检查范围") or "内部组件"
    suggestions = suggestions_from_report(report)
    existing_evidence = _pick_report_field(report, "可见依据") or ""
    retained_evidence = _strip_outlet_direction_clauses(existing_evidence)
    direction_note = verify.get("evidence") or (
        "栓口轴线沿墙面横向朝左或朝右，未朝向箱门外侧，方向错误证据成立。"
        if supported
        else "栓口方向受拍摄视角影响，当前证据不足，本次未将其作为异常项。"
    )
    evidence_parts = [retained_evidence.strip("；。 ")] if retained_evidence else []
    if supported or needs_manual:
        evidence_parts.append(direction_note.strip("；。 "))
    evidence = "；".join(part for part in evidence_parts if part).strip("；") or direction_note
    verdict = "不合规" if labels else "合规"
    return "\n".join([
        f"检查范围：{scope}",
        f"结论：{verdict}",
        f"可见依据：{evidence}",
        "隐患标签：" + ("；".join(labels) if labels else "无"),
        "建议项：" + ("；".join(suggestions) if suggestions else "无"),
    ])

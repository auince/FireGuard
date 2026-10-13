import json
import re
from typing import Any

from backend.modules.inspection.labels import APPEARANCE_LABELS
from backend.modules.inspection.parser import (
    _pick_report_field,
    extract_json_object,
    labels_from_report,
    normalize_label_list,
    normalize_suggestion_list,
)


def evidence_is_unstable(evidence: str) -> bool:
    text = evidence or ""
    if len(text) > 280:
        return True
    if text.count("、") + text.count("，") + text.count(",") > 14:
        return True
    repeated_terms = ("密封圈", "发黄", "发蓝", "发绿", "发紫", "发黑", "发白")
    return any(text.count(term) >= 4 for term in repeated_terms)


def stable_evidence_or_raw(evidence: str, raw_report: str) -> str:
    if not evidence_is_unstable(evidence):
        return evidence
    raw_evidence = _pick_report_field(raw_report, "可见依据")
    if raw_evidence and not evidence_is_unstable(raw_evidence):
        return raw_evidence
    return ""

NEGATION_TERMS = ("未见", "没有", "无", "缺失", "缺少", "看不到", "未发现", "未识别", "无法看到")


def _has_negated_phrase(text: str, terms: list[str]) -> bool:
    for neg in NEGATION_TERMS:
        for term in terms:
            if not term:
                continue
            pattern = re.escape(neg) + r"[^。；;，,]{0,16}" + re.escape(term)
            if re.search(pattern, text):
                return True
    return False


def evidence_says_component_visible(evidence: str, component: str) -> bool:
    text = evidence or ""
    water_gun = "水枪"
    water_hose = "水带"
    if component == water_gun:
        suspect_terms = ["消防水枪", "水枪", "喷嘴", "喷射器", "枪头", "锥形", "金属喷嘴", "银色金属"]
        if _has_negated_phrase(text, suspect_terms + [component]):
            return False
        visible_terms = ["可见", "看到", "有", "存在", "挂", "位于"]
        if any(term in text for term in suspect_terms) and any(term in text for term in visible_terms):
            return True
    if component == water_hose:
        hose_terms = [component, "消防水带", "白色水带", "织物水带", "盘绕", "卷放"]
        if _has_negated_phrase(text, hose_terms):
            return False
    if component not in text:
        return False
    negative_terms = [
        f"无{component}",
        f"没有{component}",
        f"未见{component}",
        f"缺少{component}",
        f"{component}缺失",
        f"{component}不可见",
    ]
    if any(term in text for term in negative_terms) or _has_negated_phrase(text, [component]):
        return False
    positive_terms = [
        "可见", "看到", "有", "存在", "挂", "放置",
        "盘绕", "卷放", "折叠", "位于", "清晰", "在位",
    ]
    return any(term in text for term in positive_terms)

def remove_contradictory_missing_labels(labels: list[str], evidence: str) -> tuple[list[str], list[str]]:
    cleaned = list(labels)
    removed: list[str] = []
    missing_water_gun = "\u5ba4\u5185\u6d88\u706b\u6813\u65e0\u6d88\u9632\u6c34\u67aa"
    missing_water_hose = "\u5ba4\u5185\u6d88\u706b\u6813\u65e0\u6d88\u9632\u6c34\u5e26"
    if evidence_says_component_visible(evidence, "\u6c34\u67aa") and missing_water_gun in cleaned:
        cleaned = [label for label in cleaned if label != missing_water_gun]
        removed.append(missing_water_gun)
    if evidence_says_component_visible(evidence, "\u6c34\u5e26") and missing_water_hose in cleaned:
        cleaned = [label for label in cleaned if label != missing_water_hose]
        removed.append(missing_water_hose)
    return cleaned, removed


REFERENCE_COMPONENT_GROUPS = {
    "reel": ["\u5377\u76d8", "\u8f6f\u7ba1\u5377\u76d8", "\u76d8\u7ed5", "\u5377\u653e"],
    "valve": ["\u624b\u8f6e", "\u9600\u4f53", "\u6813\u53e3", "\u63a5\u53e3"],
    "hose": ["\u6c34\u5e26", "\u767d\u8272\u7ec7\u7269", "\u6298\u53e0", "\u76d8\u7ed5\u7684\u767d\u8272"],
    "gun": ["\u6c34\u67aa", "\u55b7\u5634", "\u55b7\u5c04\u5668", "\u67aa\u5934", "\u9525\u5f62", "\u94f6\u8272\u91d1\u5c5e"],
}

REFERENCE_NEGATIVE_TERMS = ["\u672a\u89c1", "\u6ca1\u6709", "\u65e0", "\u770b\u4e0d\u5230", "\u7f3a\u5931"]


def has_component_negative_mention(candidate: str, terms: list[str]) -> bool:
    for neg in REFERENCE_NEGATIVE_TERMS:
        for term in terms:
            patterns = (
                neg + term,
                neg + "消防" + term,
                term + "缺失",
                "消防" + term + "缺失",
            )
            if any(pattern in candidate for pattern in patterns):
                return True
    return False


def reference_like_component_visibility(text: str) -> dict[str, bool]:
    candidate = text or ""
    visible: dict[str, bool] = {}
    for group, terms in REFERENCE_COMPONENT_GROUPS.items():
        matched = any(term in candidate for term in terms)
        if not matched:
            visible[group] = False
            continue
        if group in {"reel", "valve"}:
            visible[group] = True
            continue
        negative = has_component_negative_mention(candidate, terms)
        if negative:
            visible[group] = False
            continue
        if group == "hose":
            visible[group] = evidence_says_component_visible(candidate, "??")
            continue
        if group == "gun":
            visible[group] = evidence_says_component_visible(candidate, "??")
            continue
        visible[group] = False
    return visible


def remove_reference_like_missing_labels(labels: list[str], context_text: str) -> tuple[list[str], list[str], dict[str, bool]]:
    cleaned = list(labels)
    removed: list[str] = []
    groups = reference_like_component_visibility(context_text)
    visible_count = sum(1 for value in groups.values() if value)
    missing_water_gun = "\u5ba4\u5185\u6d88\u706b\u6813\u65e0\u6d88\u9632\u6c34\u67aa"
    missing_water_hose = "\u5ba4\u5185\u6d88\u706b\u6813\u65e0\u6d88\u9632\u6c34\u5e26"

    gun_supported = groups.get("gun")
    hose_supported = groups.get("hose")

    if gun_supported and missing_water_gun in cleaned:
        cleaned = [label for label in cleaned if label != missing_water_gun]
        removed.append(missing_water_gun)
    if hose_supported and missing_water_hose in cleaned:
        cleaned = [label for label in cleaned if label != missing_water_hose]
        removed.append(missing_water_hose)
    return cleaned, removed, groups




def remove_glass_door_label(labels: list[str], evidence: str) -> tuple[list[str], bool, str]:
    glass_label = "室内消火栓箱门为玻璃门"
    text = evidence or ""
    glass_terms = ("玻璃门", "透明", "半透明", "透视", "玻璃反光", "玻璃边框", "箱门材质")
    removed = glass_label in labels or any(term in text for term in glass_terms)
    cleaned = [label for label in labels if label != glass_label]
    clauses: list[str] = []
    for raw in text.replace("；", "。").split("。"):
        clause = raw.strip("；。 ，,")
        if not clause:
            continue
        if any(term in clause for term in glass_terms):
            continue
        clauses.append(clause)
    return cleaned, removed, "。".join(clauses).strip("。")


def collect_recommendation_suggestions(*texts: str) -> list[str]:
    suggestions: list[str] = []
    for text in texts:
        suggestions.extend(normalize_suggestion_list(text or ""))
    return list(dict.fromkeys(suggestions))


def text_indicates_closed_transparent_door(text: str) -> bool:
    candidate = (text or "").replace(" ", "")
    open_terms = ("箱门开启", "箱门打开", "门已打开", "门打开", "开门状态", "打开状态", "敞开")
    closed_terms = ("箱门关闭", "箱门闭合", "箱门关上", "门关闭", "门闭合", "门关上", "关闭状态", "闭合状态")
    transparent_terms = ("玻璃", "透明", "半透明", "透过", "隔着")
    explicit_closed = any(term in candidate for term in closed_terms) and any(term in candidate for term in transparent_terms)
    seeing_through = any(term in candidate for term in ("透过玻璃", "隔着玻璃", "透过透明门", "隔着透明门", "透过箱门"))
    if not (explicit_closed or seeing_through):
        return False
    return not any(term in candidate for term in open_terms)


def force_closed_transparent_door_to_appearance(
    scope: str,
    verdict: str,
    labels: list[str],
    evidence: str,
    context_text: str,
) -> tuple[str, str, list[str], str, bool]:
    if not text_indicates_closed_transparent_door(context_text):
        return scope, verdict, labels, evidence, False
    appearance_labels = [label for label in labels if label in APPEARANCE_LABELS]
    verdict = "不合规" if appearance_labels else "合规"
    evidence = (
        "画面显示箱门处于关闭状态，内部器材即使有透视轮廓也不作为内部组件缺失判定依据；"
        "本次按箱体外观进行判定，未见明确外观必要隐患。"
        if not appearance_labels else
        "画面显示箱门处于关闭状态，本次按箱体外观进行判定；外观存在可见异常。"
    )
    return "箱体外观", verdict, appearance_labels, evidence, True


def evidence_supports_wrong_outlet_direction(evidence: str) -> bool:
    text = evidence or ""
    wrong_terms = (
        "左右朝向", "向左", "向右", "朝左", "朝右", "横向", "侧向",
        "未垂直于墙", "不垂直于墙", "未朝向箱门外侧",
    )
    if any(term in text for term in wrong_terms):
        return True
    positive_terms = ("垂直于墙", "朝向箱门外侧", "朝外", "方向正常", "未见方向错误")
    if any(term in text for term in positive_terms):
        return False
    return False


def remove_unsupported_outlet_direction_label(labels: list[str], evidence: str) -> tuple[list[str], bool]:
    direction_label = "室内消火栓栓口方向错误"
    if direction_label in labels and not evidence_supports_wrong_outlet_direction(evidence):
        return [label for label in labels if label != direction_label], True
    return list(labels), False

def evidence_supports_severe_bend(evidence: str) -> bool:
    text = evidence or ""
    negative_patterns = [
        "未见明显", "无明显", "不存在明显", "未见挤压", "未见压扁", "未见变形",
        "自然下垂", "普通弧度", "正常弧度", "正常弯曲", "正常转弯", "正常盘绕", "轻微", "略微",
    ]
    if any(term in text for term in negative_patterns):
        return False

    target_patterns = [
        "卷盘软管", "软管卷盘供水软管", "软管卷盘供水管",
        "消防软管卷盘供水软管", "消防软管卷盘供水管",
        "与卷盘相连", "连接卷盘", "卷盘出口", "卷盘供水侧", "卷盘出水侧",
    ]
    if not any(term in text for term in target_patterns):
        return False

    acute_turn_patterns = [
        "明显锐角折弯", "明显锐角弯折", "锐角折弯", "锐角弯折", "锐角死弯", "死弯",
        "突兀锐角", "锐角急转",
    ]
    wall_damage_patterns = [
        "明显折痕", "折痕明显", "局部折痕",
        "压扁", "明显压扁", "局部管壁凹陷", "管壁凹陷", "局部凹陷", "管体凹陷",
        "挤压变形", "被挤压", "折痕闭合", "管道闭合", "通水路径受阻",
        "通水路径明显受阻", "通水受阻", "近乎闭合", "严重扭曲变形",
    ]
    return (
        any(term in text for term in acute_turn_patterns)
        and any(term in text for term in wall_damage_patterns)
    )


def remove_unsupported_bend_label(labels: list[str], evidence: str) -> tuple[list[str], bool]:
    bend_label = "\u6d88\u9632\u8f6f\u7ba1\u5377\u76d8\u4f9b\u6c34\u7ba1\u9053\u6298\u5f2f\u4e25\u91cd"
    if bend_label in labels and not evidence_supports_severe_bend(evidence):
        return [label for label in labels if label != bend_label], True
    return list(labels), False


def evidence_indicates_non_target(evidence: str) -> bool:
    text = evidence or ""
    target_terms = ["消火栓", "消防栓", "箱门", "箱体", "FIRE HYDRANT"]
    non_target_terms = [
        "未见消火栓", "未见消防栓", "未见消火栓箱", "未见消防栓箱",
        "未见消防栓箱体", "未见消火栓箱体", "无法确认是否存在消火栓",
        "无法确认是消火栓", "无法判断其外观合规性", "无法判断其开启/关闭状态及外观合规性",
        "仅显示墙面", "只显示墙面", "仅显示瓷砖", "只显示瓷砖", "非消火栓", "不是消火栓",
    ]
    if any(term in text for term in non_target_terms):
        return True
    if any(term in text for term in ("未见", "无法确认", "无法判断")) and not any(term in text for term in target_terms):
        return True
    return False



def evidence_supports_valid_hydrant_marking(evidence: str) -> bool:
    text = evidence or ""
    hydrant = "\u6d88\u706b\u6813"
    sign = "\u6807\u8bc6"
    sign_board = "\u6807\u8bc6\u724c"
    content_is = "\u5185\u5bb9\u4e3a"
    red_white_board = "\u7ea2\u5e95\u767d\u5b57\u6807\u8bc6\u724c"
    clear_terms = ("\u6e05\u6670", "\u53ef\u89c1", "\u53ef\u8fa8")
    if hydrant not in text and "FIRE HYDRANT" not in text:
        return False
    # A reviewer may correctly read the literal Chinese marking but then
    # incorrectly reject it because it is not a separate signboard, is on the
    # inside of a transparent door, or is considered too small. Those are not
    # grounds for the "Chinese marking missing/unclear" hazard. Treat explicit
    # visual recognition of the literal text as positive presence evidence.
    positive_marking_patterns = (
        r"(?:\u53ef\u89c1|\u770b\u5230|\u8bc6\u522b\u5230|\u5370\u6709|\u6807\u6709|\u5199\u6709|\u8d34\u6709|\u542b\u6709|\u542b|\u867d\u6709)"
        r"[^。\n]{0,40}[“‘\"]?\u6d88\u706b\u6813[”’\"]?(?:\u4e09\u5b57|\u5b57\u6837|\u6587\u5b57)?",
        r"[“‘\"]\u6d88\u706b\u6813[”’\"](?:\u4e09\u5b57|\u5b57\u6837|\u6587\u5b57)?"
        r"[^。\n]{0,24}(?:\u6e05\u6670|\u53ef\u89c1|\u53ef\u8fa8|\u53ef\u8bc6\u522b)",
    )
    if any(re.search(pattern, text) for pattern in positive_marking_patterns):
        return True
    if content_is in text and hydrant in text and "FIRE HYDRANT" in text:
        return True
    if red_white_board in text and hydrant in text:
        return True
    if sign_board in text and hydrant in text and any(term in text for term in clear_terms):
        return True
    if sign in text and hydrant in text and any(term in text for term in clear_terms):
        return True
    return False


def infer_appearance_labels_from_evidence(scope: str, labels: list[str], evidence: str) -> list[str]:
    if labels or "\u5916\u89c2" not in (scope or ""):
        return list(labels)
    text = evidence or ""
    if evidence_supports_valid_hydrant_marking(text):
        return list(labels)
    has_target = any(term in text for term in ("\u6d88\u706b\u6813", "\u6d88\u9632\u6813", "\u7bb1\u95e8", "\u7bb1\u4f53"))
    unclear_chinese = any(term in text for term in (
        "\u4e2d\u6587\u201c\u6d88\u706b\u6813\u201d\u5b57\u6837", "\u4e2d\u6587\u6d88\u706b\u6813\u5b57\u6837", "\u4e2d\u6587\u6807\u8bc6", "\u6709\u6548\u6807\u8bc6", "\u6807\u8bc6\u724c",
    )) and any(term in text for term in (
        "\u672a\u89c1", "\u672a\u5b8c\u6574\u5448\u73b0", "\u672a\u6e05\u6670", "\u4e0d\u6e05\u6670", "\u6a21\u7cca", "\u4e0d\u53ef\u8fa8", "\u65e0\u6cd5\u786e\u8ba4", "\u65e0\u6e05\u6670\u53ef\u8fa8\u6587\u5b57",
    ))
    missing_chinese = any(term in text for term in (
        "\u672a\u89c1\u4e2d\u6587\u201c\u6d88\u706b\u6813\u201d", "\u672a\u89c1\u4e2d\u6587\u6d88\u706b\u6813", "\u6ca1\u6709\u4e2d\u6587\u201c\u6d88\u706b\u6813\u201d", "\u65e0\u4e2d\u6587\u201c\u6d88\u706b\u6813\u201d",
        "\u672a\u6e05\u6670\u6807\u6ce8\u4e2d\u6587\u201c\u6d88\u706b\u6813\u201d", "\u672a\u6e05\u6670\u6807\u6ce8\u4e2d\u6587\u6d88\u706b\u6813",
    ))
    if has_target and (unclear_chinese or missing_chinese):
        return ["\u5ba4\u5185\u6d88\u706b\u6813\u7bb1\u95e8\u672a\u6e05\u6670\u6807\u6ce8\u4e2d\u6587\u201c\u6d88\u706b\u6813\u201d\u5b57\u6837"]
    return list(labels)


def remove_unsupported_chinese_marking_label(labels: list[str], evidence: str) -> tuple[list[str], bool]:
    chinese_label = "\u5ba4\u5185\u6d88\u706b\u6813\u7bb1\u95e8\u672a\u6e05\u6670\u6807\u6ce8\u4e2d\u6587\u201c\u6d88\u706b\u6813\u201d\u5b57\u6837"
    if chinese_label in labels and evidence_supports_valid_hydrant_marking(evidence):
        return [label for label in labels if label != chinese_label], True
    return list(labels), False


SUPPORTED_SCOPES = {
    "\u7bb1\u4f53\u5916\u89c2",
    "\u5185\u90e8\u7ec4\u4ef6",
    "\u5ba4\u5916\u6d88\u706b\u6813",
    "\u706d\u706b\u5668",
    "\u65e0\u6cd5\u5224\u65ad",
}


def normalize_inspection_scope(scope: str, expected_scope: str = "") -> str:
    expected = (expected_scope or "").strip()
    if expected in SUPPORTED_SCOPES - {"\u65e0\u6cd5\u5224\u65ad"}:
        return expected

    candidate = (scope or "").strip()
    if "\u5ba4\u5916" in candidate and "\u6d88\u706b\u6813" in candidate:
        return "\u5ba4\u5916\u6d88\u706b\u6813"
    if "\u706d\u706b\u5668" in candidate:
        return "\u706d\u706b\u5668"
    if "\u5916\u89c2" in candidate:
        return "\u7bb1\u4f53\u5916\u89c2"
    if "\u5185\u90e8" in candidate:
        return "\u5185\u90e8\u7ec4\u4ef6"
    return candidate if candidate in SUPPORTED_SCOPES else "\u65e0\u6cd5\u5224\u65ad"


def enforce_report_scope(report: str, expected_scope: str) -> str:
    normalized = normalize_inspection_scope("", expected_scope)
    if not report or normalized == "\u65e0\u6cd5\u5224\u65ad":
        return report
    scope_pattern = re.compile(r"(^\s*\u68c0\u67e5\u8303\u56f4\s*[:\uff1a]\s*)[^\n]+", re.MULTILINE)
    if scope_pattern.search(report):
        return scope_pattern.sub(rf"\g<1>{normalized}", report, count=1)
    return f"\u68c0\u67e5\u8303\u56f4\uff1a{normalized}\n{report}".strip()


def format_judge_json(
    reviewed_text: str,
    raw_report: str = "",
    expected_scope: str = "",
) -> str | None:
    data = extract_json_object(reviewed_text)
    if not data:
        return None
    labels = normalize_label_list(data.get("labels"))
    scope = normalize_inspection_scope(str(data.get("scope") or ""), expected_scope)
    verdict = str(data.get("verdict") or "\u65e0\u6cd5\u5224\u65ad").strip()
    if verdict not in {"\u5408\u89c4", "\u4e0d\u5408\u89c4", "\u65e0\u6cd5\u5224\u65ad"}:
        verdict = "\u4e0d\u5408\u89c4" if labels else "\u65e0\u6cd5\u5224\u65ad"
    if labels and verdict == "\u5408\u89c4":
        verdict = "\u4e0d\u5408\u89c4"
    if not labels and verdict == "\u4e0d\u5408\u89c4":
        verdict = "\u65e0\u6cd5\u5224\u65ad"
    evidence = stable_evidence_or_raw(str(data.get("visible_evidence") or "").strip(), raw_report)
    labels = infer_appearance_labels_from_evidence(scope, labels, evidence)
    labels, removed_chinese_marking = remove_unsupported_chinese_marking_label(labels, evidence)
    if labels and verdict == "\u5408\u89c4":
        verdict = "\u4e0d\u5408\u89c4"
    if labels and verdict == "\u65e0\u6cd5\u5224\u65ad":
        verdict = "\u4e0d\u5408\u89c4"
    suggestions = normalize_suggestion_list(data.get("suggestions"))
    suggestions = list(dict.fromkeys(suggestions + collect_recommendation_suggestions(reviewed_text, raw_report)))
    closed_door_context = "\n".join(part for part in [evidence, reviewed_text, raw_report] if part)
    scope, verdict, labels, evidence, forced_closed_door_scope = force_closed_transparent_door_to_appearance(scope, verdict, labels, evidence, closed_door_context)
    labels, removed_glass, evidence = remove_glass_door_label(labels, evidence)
    labels, removed_missing = remove_contradictory_missing_labels(labels, evidence)
    context_text = "\n".join(part for part in [evidence, reviewed_text, raw_report] if part)
    labels, removed_reference_missing, reference_groups = remove_reference_like_missing_labels(labels, context_text)
    labels, removed_bend = remove_unsupported_bend_label(labels, evidence)
    labels, removed_direction = remove_unsupported_outlet_direction_label(labels, evidence)
    if forced_closed_door_scope and not labels:
        verdict = "\u5408\u89c4"
        evidence = evidence or "\u7bb1\u95e8\u5904\u4e8e\u5173\u95ed\u72b6\u6001\uff0c\u672c\u6b21\u6309\u7bb1\u4f53\u5916\u89c2\u8fdb\u884c\u5224\u5b9a\uff0c\u672a\u89c1\u660e\u786e\u5916\u89c2\u5fc5\u8981\u9690\u60a3\u3002"
    elif removed_glass and not labels and not removed_bend:
        verdict = "\u5408\u89c4"
        evidence = evidence or "\u5f53\u524d\u672a\u89c1\u5176\u4ed6\u660e\u786e\u5916\u89c2\u9690\u60a3\u3002"
    if removed_direction and not labels:
        verdict = "\u5408\u89c4"
        evidence = "\u5f53\u524d\u753b\u9762\u672a\u5f62\u6210\u6813\u53e3\u5de6\u53f3\u6a2a\u5411\u671d\u5411\u6216\u672a\u5782\u76f4\u4e8e\u5899\u9762\u7684\u6e05\u6670\u8bc1\u636e\uff0c\u4e0d\u652f\u6301\u5224\u5b9a\u4e3a\u6813\u53e3\u65b9\u5411\u9519\u8bef\u3002"
    elif removed_direction:
        evidence = evidence + "\uff1b\u6813\u53e3\u65b9\u5411\u672a\u5f62\u6210\u6e05\u6670\u9519\u8bef\u8bc1\u636e\uff0c\u5df2\u6392\u9664\u65b9\u5411\u9519\u8bef\u6807\u7b7e\u3002"
    if removed_chinese_marking and not labels:
        verdict = "\u5408\u89c4"
        evidence = "\u7bb1\u95e8\u6b63\u9762\u6216\u5176\u9644\u7740\u6807\u8bc6\u4e0a\u53ef\u6e05\u6670\u8fa8\u8ba4\u4e2d\u6587\u201c\u6d88\u706b\u6813\u201d\u5b57\u6837\uff0c\u5f53\u524d\u4e0d\u652f\u6301\u5224\u5b9a\u4e3a\u4e2d\u6587\u6807\u8bc6\u7f3a\u5931\u6216\u4e0d\u6e05\u6670\u3002"
    elif removed_chinese_marking:
        evidence = evidence + "\uff1b\u7bb1\u95e8\u6b63\u9762\u6216\u5176\u9644\u7740\u6807\u8bc6\u4e0a\u53ef\u6e05\u6670\u8fa8\u8ba4\u4e2d\u6587\u201c\u6d88\u706b\u6813\u201d\u5b57\u6837\uff0c\u5df2\u6392\u9664\u4e2d\u6587\u6807\u8bc6\u7f3a\u5931\u6807\u7b7e\u3002"
    if removed_bend and not labels:
        verdict = "\u5408\u89c4"
        evidence = "\u672a\u89c1\u4f9b\u6c34\u7ba1\u9053\u660e\u663e\u9510\u89d2\u6298\u5f2f\u6216\u6324\u538b\u53d8\u5f62\uff0c\u5f53\u524d\u4e0d\u652f\u6301\u5224\u5b9a\u4e3a\u201c\u6d88\u9632\u8f6f\u7ba1\u5377\u76d8\u4f9b\u6c34\u7ba1\u9053\u6298\u5f2f\u4e25\u91cd\u201d\u3002"
    elif removed_bend:
        evidence = evidence + "\uff1b\u4f9b\u6c34\u7ba1\u9053\u672a\u89c1\u660e\u663e\u9510\u89d2\u6298\u5f2f\u6216\u6324\u538b\u53d8\u5f62\uff0c\u5df2\u6392\u9664\u201c\u6298\u5f2f\u4e25\u91cd\u201d\u6807\u7b7e\u3002"
    if removed_reference_missing and not labels:
        verdict = "\u5408\u89c4"
        visible_parts = []
        if reference_groups.get("reel"):
            visible_parts.append("\u5377\u76d8")
        if reference_groups.get("valve"):
            visible_parts.append("\u624b\u8f6e/\u6813\u53e3")
        if reference_groups.get("hose"):
            visible_parts.append("\u6c34\u5e26")
        if reference_groups.get("gun"):
            visible_parts.append("\u6c34\u67aa\u5f62\u6001\u7269")
        part_text = "\u3001".join(visible_parts) if visible_parts else "\u4e3b\u8981\u5185\u90e8\u7ec4\u4ef6"
        evidence = f"\u56fe\u4e2d\u53ef\u89c1{part_text}\u7b49\u5185\u90e8\u7ec4\u4ef6\uff0c\u672a\u89c1\u6c34\u67aa\u6216\u6c34\u5e26\u7f3a\u5931\u7684\u660e\u786e\u8bc1\u636e\u3002"
    elif removed_reference_missing:
        evidence = evidence + "\uff1b\u56fe\u4e2d\u53ef\u89c1\u4e3b\u8981\u5185\u90e8\u7ec4\u4ef6\uff0c\u672a\u89c1\u5bf9\u5e94\u90e8\u4ef6\u7f3a\u5931\u7684\u660e\u786e\u8bc1\u636e\u3002"
    elif removed_missing and not labels:
        verdict = "\u65e0\u6cd5\u5224\u65ad"
        evidence = "\u56fe\u4e2d\u53ef\u89c1\u7591\u4f3c\u6c34\u67aa\u6216\u6c34\u5e26\u5f62\u6001\u7269\uff0c\u5bf9\u5e94\u7f3a\u5931\u9879\u8bc1\u636e\u4e0d\u8db3\uff0c\u5efa\u8bae\u73b0\u573a\u6838\u9a8c\u3002"
    elif removed_missing:
        evidence = evidence + "\uff1b\u7591\u4f3c\u6c34\u67aa/\u6c34\u5e26\u5f62\u6001\u7269\u53ef\u89c1\uff0c\u5df2\u6392\u9664\u5bf9\u5e94\u7f3a\u5931\u6807\u7b7e\u3002"
    if labels and verdict == "\u5408\u89c4":
        verdict = "\u4e0d\u5408\u89c4"
    if not labels and verdict == "\u4e0d\u5408\u89c4":
        verdict = "\u65e0\u6cd5\u5224\u65ad" if data.get("needs_manual_review") else "\u5408\u89c4"
    if not evidence:
        evidence = "\u8be5\u9879\u9690\u60a3\u5728\u5f53\u524d\u56fe\u7247\u4e2d\u672a\u5f62\u6210\u6e05\u6670\u3001\u53ef\u6838\u9a8c\u7684\u89c6\u89c9\u8bc1\u636e\u3002" if verdict == "\u65e0\u6cd5\u5224\u65ad" else "\u672a\u89c1\u660e\u786e\u9690\u60a3\u3002"
    return "\n".join([
        f"\u68c0\u67e5\u8303\u56f4\uff1a{scope}",
        f"\u7ed3\u8bba\uff1a{verdict}",
        f"\u53ef\u89c1\u4f9d\u636e\uff1a{evidence}",
        "\u9690\u60a3\u6807\u7b7e\uff1a" + ("\uff1b".join(labels) if labels else "\u65e0"),
        "\u5efa\u8bae\u9879\uff1a" + ("\uff1b".join(suggestions) if suggestions else "\u65e0"),
    ])


def guarded_format_judge_json(
    reviewed_text: str,
    raw_report: str,
    expected_scope: str = "",
) -> str | None:
    data = extract_json_object(reviewed_text)
    if not data:
        return None
    first_labels = labels_from_report(raw_report)
    labels = normalize_label_list(data.get("labels"))
    added = [x for x in labels if x not in first_labels]
    confidence = str(data.get("confidence") or "\u4e2d").strip()
    needs_manual = bool(data.get("needs_manual_review")) or confidence == "\u4f4e"

    # Block additions only when the judge itself says confidence is low or manual review is needed.
    if added and (confidence == "低" or needs_manual):
        labels = [x for x in labels if x in first_labels]
        data["labels"] = labels
        data["added_to_first"] = []
        data["verdict"] = "无法判断" if not labels else "不合规"
        data["needs_manual_review"] = True
        data["confidence"] = "低"
        needs_manual = True

    formatted = format_judge_json(
        json.dumps(data, ensure_ascii=False),
        raw_report=raw_report,
        expected_scope=expected_scope,
    )
    return formatted

import json
import re
from typing import Any

from backend.modules.inspection.labels import ALLOWED_LABELS, LABEL_ALIASES, SUGGESTION_LABELS
from backend.modules.inspection.utils import strip_reasoning, trim_output

def detect_task(query: str, explicit_task: str | None = None, report: str | None = None) -> str:
    task = (explicit_task or "").strip().lower()
    if task in {"internal", "internal_components", "内部", "内部组件"}:
        return "internal_components"
    if task in {"appearance", "外观", "箱体外观"}:
        return "appearance"
    report_text = pick_primary_structured_report(report or "")
    text = f"{query or ''}\n{report_text}"
    if any(word in text for word in ("检查范围：内部", "内部组件", "检查内部", "箱内", "水带", "水枪", "手轮", "栓口", "接口", "卷盘")):
        return "internal_components"
    if any(word in text for word in ("检查范围：箱体外观", "外观", "检查外观", "箱门标识", "FIRE HYDRANT", "铭牌", "操作说明", "玻璃门")):
        return "appearance"
    return "auto"

REPORT_SECTION_RE = re.compile(r"\u68c0\u67e5\u8303\u56f4\s*[:\uff1a].*?(?=(?:\n\s*\u68c0\u67e5\u8303\u56f4\s*[:\uff1a])|\Z)", re.DOTALL)


def extract_structured_report_sections(text: str) -> list[str]:
    candidate = strip_reasoning(text or "").strip()
    if not candidate:
        return []
    sections: list[str] = []
    for block in REPORT_SECTION_RE.findall(candidate):
        block = block.strip()
        if "\u7ed3\u8bba" in block and "\u9690\u60a3\u6807\u7b7e" in block:
            sections.append(block)
    return sections


def pick_primary_structured_report(text: str) -> str:
    sections = extract_structured_report_sections(text)
    if sections:
        return sections[0]
    return strip_reasoning(text or "").strip()


def has_structured_report(text: str) -> bool:
    candidate = strip_reasoning(text or "").strip()
    if not candidate:
        return False
    if extract_structured_report_sections(candidate):
        return True
    required = ["\u68c0\u67e5\u8303\u56f4", "\u7ed3\u8bba", "\u9690\u60a3\u6807\u7b7e"]
    return all(token in candidate for token in required)


def sanitize_final_report(text: str) -> str:
    candidate = pick_primary_structured_report(text or "")
    if not candidate:
        return candidate
    allowed_labels = ALLOWED_LABELS
    candidate_suggestions = normalize_suggestion_list(candidate)
    cleaned_lines: list[str] = []
    for raw_line in candidate.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("隐患标签："):
            value = line.split("：", 1)[1].strip().strip("。")
            if value in {"", "无", "无隐患", "无隐患标签"}:
                line = "隐患标签：无"
            else:
                matched = normalize_label_list(value)
                line = "隐患标签：" + ("；".join(dict.fromkeys(matched)) if matched else "无")
        if line.startswith("建议项："):
            value = line.split("：", 1)[1].strip().strip("。")
            if value in {"", "无", "无建议", "无建议项"}:
                line = "建议项：无"
            else:
                matched = normalize_suggestion_list(value)
                line = "建议项：" + ("；".join(matched) if matched else "无")
        if line.startswith("复核说明：") and any(word in line for word in ("首轮", "模型", "误判", "漏判")):
            line = "复核说明：已根据参考图和用户图完成二次复核，最终结果以图像可见证据为准。"
        line = re.sub(r"《[^》]+》[^；。]*", "", line)
        line = re.sub(r"GB\s*\d+[\d.-]*[^；。]*", "", line, flags=re.IGNORECASE)
        line = line.replace("首轮结果与图像证据一致", "二次复核结果与图像证据一致")
        line = line.replace("，本次同时作内部组件判断", "")
        line = line.replace("；本次同时作内部组件判断", "")
        line = line.replace("本次同时作内部组件判断。", "")
        cleaned_lines.append(line.strip())
    return normalize_report_policy("\n".join(cleaned_lines), candidate_suggestions)


def normalize_report_policy(report: str, candidate_suggestions: list[str] | None = None) -> str:
    """Keep legacy model output aligned with the current audit standard.

    Older fine-tuned outputs may still mark nameplate or English-only issues as
    hazards. The active label list removes those from labels; this pass
    preserves them as suggestions and fixes the verdict when no required
    hazard remains. Operation-instruction defects are active appearance labels.
    """
    labels = labels_from_report(report)
    suggestions = list(dict.fromkeys((candidate_suggestions or []) + suggestions_from_report(report)))
    output_lines: list[str] = []
    has_suggestion_line = False
    for raw_line in (report or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("结论：") and not labels:
            current_verdict = line.split("：", 1)[1].strip()
            if current_verdict == "无法判断":
                line = "结论：无法判断"
            elif current_verdict == "不合规" and suggestions:
                line = "结论：合规"
            else:
                line = "结论：" + (current_verdict if current_verdict in {"合规", "不合规", "无法判断"} else "无法判断")
        elif line.startswith("隐患标签："):
            line = "隐患标签：" + ("；".join(labels) if labels else "无")
        elif line.startswith("建议项："):
            has_suggestion_line = True
            line = "建议项：" + ("；".join(suggestions) if suggestions else "无")
        output_lines.append(line)
    if not has_suggestion_line:
        output_lines.append("建议项：" + ("；".join(suggestions) if suggestions else "无"))
    return "\n".join(output_lines)


def extract_json_object(text: str) -> dict[str, Any] | None:
    candidate = strip_reasoning(text or "").strip()
    candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
    candidate = re.sub(r"\s*```$", "", candidate).strip()
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(candidate[start : end + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None

def normalize_label_list(value: Any) -> list[str]:
    allowed = ALLOWED_LABELS
    if isinstance(value, str):
        raw_items = [x.strip() for x in re.split(r"[；;、,，]", value) if x.strip()]
    elif isinstance(value, list):
        raw_items = [str(x).strip() for x in value if str(x).strip()]
    else:
        raw_items = []
    labels: list[str] = []
    for item in raw_items:
        normalized_item = re.sub(r"\s+", "", item).strip("。；;，,")
        for alias, canonical in LABEL_ALIASES.items():
            if alias in normalized_item and canonical not in labels:
                labels.append(canonical)
        for label in allowed:
            if normalized_item == label or label in normalized_item:
                if label not in labels:
                    labels.append(label)
    return labels


def raw_label_items_from_report(text: str) -> list[str]:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(("隐患标签：", "隐患标签:")):
            value = re.split(r"[:：]", stripped, maxsplit=1)[1].strip().strip("。")
            if value in {"", "无", "无隐患", "无隐患标签"}:
                return []
            return [item.strip() for item in re.split(r"[；;、,，]", value) if item.strip()]
    data = extract_json_object(text)
    if not data:
        return []
    value = data.get("labels")
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[；;、,，]", value) if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def has_bend_candidate(*texts: str) -> bool:
    bend_label = "消防软管卷盘供水管道折弯严重"
    target_terms = (
        "卷盘软管", "软管卷盘", "供水软管", "供水管道", "供水管",
        "连接软管", "红色软管", "白色软管", "黑色软管",
    )
    bend_terms = ("折弯", "弯折", "锐角", "折痕", "压扁", "凹陷", "变形", "通水受阻")
    negative_terms = (
        "未见",
        "没有",
        "不存在",
        "无明显",
        "未发现",
        "未观察到",
        "不属于",
        "不能认定",
        "证据不足",
    )
    for text in texts:
        if not text:
            continue
        raw_labels = raw_label_items_from_report(text)
        if bend_label in normalize_label_list(raw_labels):
            return True
        clauses = re.split(r"[\n。；;]", text)
        for clause in clauses:
            if not any(term in clause for term in target_terms):
                continue
            if not any(term in clause for term in bend_terms):
                continue
            if any(term in clause for term in negative_terms):
                continue
            return True
    return False


def normalize_suggestion_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = [x.strip() for x in re.split(r"[；;、,，]", value) if x.strip()]
    elif isinstance(value, list):
        raw_items = [str(x).strip() for x in value if str(x).strip()]
    else:
        raw_items = []
    suggestions: list[str] = []
    negative_terms = ("缺失", "未见", "没有", "无", "模糊", "不清晰", "难以辨认", "未标注", "未采用", "非耐久")
    for item in raw_items:
        for suggestion in SUGGESTION_LABELS:
            if item == suggestion or suggestion in item:
                if suggestion not in suggestions:
                    suggestions.append(suggestion)
        if not any(term in item for term in negative_terms):
            continue
        if "铭牌" in item and "模糊" in item and "室内消火栓箱体铭牌模糊" not in suggestions:
            suggestions.append("室内消火栓箱体铭牌模糊")
        elif "铭牌" in item and "室内消火栓箱体无铭牌" not in suggestions:
            suggestions.append("室内消火栓箱体无铭牌")
        if ("FIRE HYDRANT" in item or "英文" in item) and "室内消火栓箱门英文“FIRE HYDRANT”字样缺失或不清晰" not in suggestions:
            suggestions.append("室内消火栓箱门英文“FIRE HYDRANT”字样缺失或不清晰")
    return suggestions

def labels_from_report(text: str) -> list[str]:
    for line in (text or "").splitlines():
        if line.strip().startswith("隐患标签："):
            return normalize_label_list(line.split("：", 1)[1])
    return []


def suggestions_from_report(text: str) -> list[str]:
    for line in (text or "").splitlines():
        if line.strip().startswith("建议项："):
            return normalize_suggestion_list(line.split("：", 1)[1])
    return []




def _pick_report_field(text: str, name: str) -> str:
    pattern = re.escape(name) + r"\s*[:\uff1a]\s*([^\n;\uff1b]+)"
    match = re.search(pattern, text or "")
    return match.group(1).strip().strip("\u3002\uff1b;") if match else ""


def report_fields_for_trace(text: str) -> dict[str, Any]:
    return {
        "scope": _pick_report_field(text, "\u68c0\u67e5\u8303\u56f4"),
        "verdict": _pick_report_field(text, "\u7ed3\u8bba"),
        "labels": labels_from_report(text),
        "suggestions": suggestions_from_report(text),
        "excerpt": trim_output(strip_reasoning(text or ""), 900),
    }

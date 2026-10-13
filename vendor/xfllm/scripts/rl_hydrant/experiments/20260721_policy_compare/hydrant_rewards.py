from __future__ import annotations

import re
from typing import Any, Iterable


INTERNAL_LABELS = {
    "室内消火栓手轮缺失",
    "室内消火栓栓口方向错误",
    "室内消火栓无消防水带",
    "室内消火栓无消防水枪",
    "室内消火栓消防接口缺失",
    "消防软管卷盘供水管道折弯严重",
    "室内消火栓无箱体",
    "室内消火栓箱锈蚀",
    "室内消火栓箱门缺失",
}

APPEARANCE_LABELS = {
    "室内消火栓箱明显部位未采用耐久性文字或图形标注操作说明",
    "室内消火栓箱门上未标注“消火栓”和英文“FIRE HYDRANT”字样",
    "室内消火栓箱体无铭牌",
    "室内消火栓箱门标识模糊",
    "室内消火栓箱体铭牌模糊",
    "室内消火栓箱门为玻璃门",
    "室内消火栓箱体或箱门被物品遮挡",
}

ALL_LABELS = INTERNAL_LABELS | APPEARANCE_LABELS


def completion_text(completion: Any) -> str:
    """Accept both standard and conversational TRL completion formats."""
    if isinstance(completion, str):
        return completion
    if isinstance(completion, dict):
        return str(completion.get("content", completion.get("text", "")))
    if isinstance(completion, list):
        parts: list[str] = []
        for item in completion:
            if isinstance(item, dict):
                value = item.get("content", item.get("text", ""))
                if isinstance(value, list):
                    parts.extend(str(x.get("text", "")) for x in value if isinstance(x, dict))
                else:
                    parts.append(str(value))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(completion)


def _field(text: str, name: str) -> str:
    match = re.search(rf"(?:^|\n)\s*{re.escape(name)}\s*[:：]\s*([^\n]*)", text)
    return match.group(1).strip() if match else ""


def parse_scope(text: str) -> str:
    value = _field(text, "检查范围")
    if "无法" in value:
        return "unknown"
    if "外观" in value or "箱体" in value:
        return "appearance"
    if "内部" in value or "组件" in value:
        return "internal_components"
    return "unknown"


def parse_verdict(text: str) -> str:
    value = _field(text, "结论")
    if "无法" in value:
        return "无法判断"
    if "不合规" in value:
        return "不合规"
    if "合规" in value:
        return "合规"
    return "unknown"


def parse_labels(text: str) -> set[str]:
    value = _field(text, "隐患标签")
    if not value or value.strip(" 。.；;，,") == "无":
        return set()
    return {label for label in ALL_LABELS if label in value}


def parse_answer(text: str) -> dict[str, Any]:
    return {
        "scope": parse_scope(text),
        "verdict": parse_verdict(text),
        "labels": parse_labels(text),
    }


def _as_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {x.strip(" 。.") for x in re.split(r"[；;]", value) if x.strip(" 。.") and x.strip() != "无"}
    return {str(x).strip(" 。.") for x in value if str(x).strip(" 。.") and str(x).strip() != "无"}


def _weighted_label_score(gold: set[str], pred: set[str]) -> float:
    """Signed F2-like score with explicit false-positive/false-negative costs."""
    if not gold and not pred:
        return 1.0
    if gold == pred:
        return 1.0
    tp = len(gold & pred)
    fp = len(pred - gold)
    fn = len(gold - pred)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f2 = 5 * precision * recall / (4 * precision + recall) if precision + recall else 0.0
    # Missing a true hazard is slightly more costly than adding one false
    # label, while a wrong-label substitution receives both penalties.
    return max(-1.0, f2 - 0.30 * fp - 0.45 * fn)


def outcome_reward(
    completions: Iterable[Any],
    gold_scope: Iterable[str],
    gold_verdict: Iterable[str],
    gold_labels: Iterable[Any],
    **_: Any,
) -> list[float]:
    """Primary task reward; labels dominate, then verdict and inspection scope."""
    rewards: list[float] = []
    for completion, scope, verdict, labels in zip(completions, gold_scope, gold_verdict, gold_labels):
        pred = parse_answer(completion_text(completion))
        gold = _as_set(labels)
        predicted = pred["labels"]

        label_score = _weighted_label_score(gold, predicted)
        scope_score = 1.0 if pred["scope"] == scope else -0.5
        verdict_score = 1.0 if pred["verdict"] == verdict else -0.5

        internally_consistent = (
            (bool(predicted) and pred["verdict"] == "不合规")
            or (not predicted and pred["verdict"] in {"合规", "无法判断"})
        )
        whitelist = INTERNAL_LABELS if pred["scope"] == "internal_components" else APPEARANCE_LABELS
        no_cross_scope_label = predicted <= whitelist if pred["scope"] != "unknown" else not predicted
        consistency_score = 1.0 if internally_consistent and no_cross_scope_label else -0.5

        rewards.append(
            0.60 * label_score
            + 0.20 * verdict_score
            + 0.15 * scope_score
            + 0.05 * consistency_score
        )
    return rewards


def format_reward(completions: Iterable[Any], **_: Any) -> list[float]:
    required = ["检查范围", "结论", "检查过程", "判定依据", "隐患标签"]
    rewards: list[float] = []
    for completion in completions:
        text = completion_text(completion)
        present = sum(bool(re.search(rf"(?:^|\n)\s*{name}\s*[:：]", text)) for name in required)
        valid_scope = parse_scope(text) != "unknown" or "无法确定" in _field(text, "检查范围")
        valid_verdict = parse_verdict(text) != "unknown"
        concise = 80 <= len(text) <= 1800
        rewards.append(0.6 * present / len(required) + 0.15 * valid_scope + 0.15 * valid_verdict + 0.10 * concise)
    return rewards


def evidence_reward(completions: Iterable[Any], **_: Any) -> list[float]:
    """Cheap anti-hallucination proxy; visual truth remains in the outcome labels."""
    rewards: list[float] = []
    for completion in completions:
        text = completion_text(completion)
        pred = parse_answer(text)
        process = re.search(r"检查过程\s*[:：](.*?)(?:\n\s*判定依据\s*[:：]|$)", text, re.S)
        basis = _field(text, "判定依据")
        process_text = process.group(1) if process else ""
        has_visibility_language = any(x in process_text for x in ("可见", "未见", "遮挡", "反光", "模糊", "画面外"))
        labels_supported_in_process = not pred["labels"] or any(
            label in process_text or label[:8] in process_text for label in pred["labels"]
        )
        rewards.append(0.4 * bool(process_text) + 0.2 * bool(basis) + 0.2 * has_visibility_language + 0.2 * labels_supported_in_process)
    return rewards


REWARD_FUNCTIONS = [outcome_reward, format_reward, evidence_reward]
REWARD_WEIGHTS = [0.85, 0.10, 0.05]

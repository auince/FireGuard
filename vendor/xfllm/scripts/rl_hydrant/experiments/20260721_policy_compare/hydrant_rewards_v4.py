from __future__ import annotations

import math
import re
from typing import Any, Iterable

from hydrant_rewards import (
    ALL_LABELS,
    APPEARANCE_LABELS,
    INTERNAL_LABELS,
    _as_set,
    _field,
    completion_text,
    parse_answer,
)


# Support in 20260712_hydrant_rl_expanded_v2/train.jsonl.  Extremely rare
# labels are deliberately not given a large weight: with fewer than ten
# examples, annotation noise is more likely to be amplified than corrected.
LABEL_SUPPORT = {
    "室内消火栓手轮缺失": 194,
    "室内消火栓栓口方向错误": 135,
    "室内消火栓无消防水带": 333,
    "室内消火栓无消防水枪": 358,
    "室内消火栓消防接口缺失": 134,
    "消防软管卷盘供水管道折弯严重": 158,
    "室内消火栓无箱体": 26,
    "室内消火栓箱锈蚀": 19,
    "室内消火栓箱门缺失": 38,
    "室内消火栓箱明显部位未采用耐久性文字或图形标注操作说明": 383,
    "室内消火栓箱门上未标注“消火栓”和英文“FIRE HYDRANT”字样": 377,
    "室内消火栓箱体无铭牌": 130,
    "室内消火栓箱门标识模糊": 39,
    "室内消火栓箱体铭牌模糊": 2,
    "室内消火栓箱门为玻璃门": 27,
    "室内消火栓箱体或箱门被物品遮挡": 304,
}

MEDIAN_SUPPORT = 134.5


def _make_label_weight(count: int) -> float:
    if count < 10:
        return 1.0
    raw = math.sqrt(MEDIAN_SUPPORT / count)
    if count < 20:
        return min(1.25, max(0.75, raw))
    return min(2.0, max(0.75, raw))


LABEL_WEIGHTS = {label: _make_label_weight(count) for label, count in LABEL_SUPPORT.items()}


EVIDENCE_RULES = {
    "室内消火栓手轮缺失": (("手轮",), ("缺失", "未见", "没有", "无手轮")),
    "室内消火栓栓口方向错误": (("栓口",), ("方向错误", "朝向错误", "朝内", "朝后", "不便连接")),
    "室内消火栓无消防水带": (("水带",), ("缺失", "未见", "没有", "无水带")),
    "室内消火栓无消防水枪": (("水枪",), ("缺失", "未见", "没有", "无水枪")),
    "室内消火栓消防接口缺失": (("接口",), ("缺失", "未见", "没有", "无接口")),
    "消防软管卷盘供水管道折弯严重": (("卷盘", "供水管", "软管"), ("折弯", "弯折", "折叠", "扭曲")),
    "室内消火栓无箱体": (("箱体",), ("缺失", "未见", "没有", "无箱体")),
    "室内消火栓箱锈蚀": (("箱", "箱体", "箱门"), ("锈蚀", "生锈", "锈迹")),
    "室内消火栓箱门缺失": (("箱门",), ("缺失", "未见", "没有", "无箱门")),
    "室内消火栓箱明显部位未采用耐久性文字或图形标注操作说明": (
        ("操作说明", "使用说明", "说明"),
        ("未标注", "未见", "缺失", "没有"),
    ),
    "室内消火栓箱门上未标注“消火栓”和英文“FIRE HYDRANT”字样": (
        ("FIRE HYDRANT", "消火栓字样", "中英文标识", "箱门标识"),
        ("未标注", "未见", "缺失", "没有", "不完整"),
    ),
    "室内消火栓箱体无铭牌": (("铭牌",), ("缺失", "未见", "没有", "无铭牌")),
    "室内消火栓箱门标识模糊": (("标识", "字样"), ("模糊", "不清晰", "无法辨认")),
    "室内消火栓箱体铭牌模糊": (("铭牌",), ("模糊", "不清晰", "无法辨认")),
    "室内消火栓箱门为玻璃门": (("箱门", "玻璃门"), ("玻璃", "透明")),
    "室内消火栓箱体或箱门被物品遮挡": (("箱体", "箱门", "物品"), ("遮挡", "遮住", "堆放", "覆盖")),
}


def _weight(labels: set[str]) -> float:
    return sum(LABEL_WEIGHTS.get(label, 1.0) for label in labels)


def _signed_tversky(gold: set[str], pred: set[str]) -> float:
    """Weighted set quality in [-1, 1], with FN slightly costlier than FP."""
    if not gold:
        if not pred:
            return 1.0
        return -min(1.0, 0.50 + 0.10 * _weight(pred))
    if not pred:
        return -0.80

    tp = _weight(gold & pred)
    fp = _weight(pred - gold)
    fn = _weight(gold - pred)
    denominator = tp + 0.45 * fp + 0.55 * fn
    tversky = tp / denominator if denominator else 0.0
    return max(-1.0, min(1.0, 2.0 * tversky - 1.0))


def _has_unparsed_label_text(text: str) -> bool:
    raw = _field(text, "隐患标签").strip(" 。.；;，,")
    return bool(raw and raw != "无" and not parse_answer(text)["labels"])


def label_tversky_reward(
    completions: Iterable[Any],
    gold_labels: Iterable[Any],
    **_: Any,
) -> list[float]:
    rewards: list[float] = []
    for completion, labels in zip(completions, gold_labels):
        text = completion_text(completion)
        if _has_unparsed_label_text(text):
            rewards.append(-1.0)
            continue
        pred = parse_answer(text)["labels"]
        rewards.append(_signed_tversky(_as_set(labels), pred))
    return rewards


def exact_label_reward(
    completions: Iterable[Any],
    gold_labels: Iterable[Any],
    **_: Any,
) -> list[float]:
    rewards: list[float] = []
    for completion, labels in zip(completions, gold_labels):
        text = completion_text(completion)
        exact = not _has_unparsed_label_text(text) and parse_answer(text)["labels"] == _as_set(labels)
        rewards.append(float(exact))
    return rewards


def verdict_reward(
    completions: Iterable[Any],
    gold_verdict: Iterable[str],
    **_: Any,
) -> list[float]:
    rewards: list[float] = []
    for completion, gold in zip(completions, gold_verdict):
        pred = parse_answer(completion_text(completion))["verdict"]
        if pred == gold:
            rewards.append(1.0)
        elif pred in {"unknown", "无法判断"}:
            rewards.append(-0.50)
        else:
            rewards.append(-1.0)
    return rewards


def scope_consistency_reward(
    completions: Iterable[Any],
    gold_scope: Iterable[str],
    **_: Any,
) -> list[float]:
    rewards: list[float] = []
    for completion, gold in zip(completions, gold_scope):
        pred = parse_answer(completion_text(completion))
        scope_score = 1.0 if pred["scope"] == gold else -1.0
        labels = pred["labels"]
        if pred["scope"] == "internal_components":
            labels_in_scope = labels <= INTERNAL_LABELS
        elif pred["scope"] == "appearance":
            labels_in_scope = labels <= APPEARANCE_LABELS
        else:
            labels_in_scope = not labels
        verdict_consistent = (
            (bool(labels) and pred["verdict"] == "不合规")
            or (not labels and pred["verdict"] in {"合规", "无法判断"})
        )
        consistency_score = 1.0 if labels_in_scope and verdict_consistent else -1.0
        rewards.append(0.60 * scope_score + 0.40 * consistency_score)
    return rewards


def _canonical_label_field(text: str) -> bool:
    raw = _field(text, "隐患标签").strip(" 。.；;，,")
    if raw == "无":
        return True
    if not raw:
        return False
    parts = [part.strip(" 。.") for part in re.split(r"[；;]", raw) if part.strip(" 。.")]
    return bool(parts) and all(part in ALL_LABELS for part in parts)


def format_reward(completions: Iterable[Any], **_: Any) -> list[float]:
    required = ["检查范围", "结论", "隐患标签"]
    rewards: list[float] = []
    for completion in completions:
        text = completion_text(completion)
        matches = [re.search(rf"(?:^|\n)\s*{name}\s*[:：]", text) for name in required]
        evidence_match = re.search(r"(?:^|\n)\s*(?:可见证据|检查过程|判定依据)\s*[:：]", text)
        present = (sum(match is not None for match in matches) + bool(evidence_match)) / 4.0
        scope_match, verdict_match, label_match = matches
        compact_order = bool(
            scope_match
            and verdict_match
            and label_match
            and evidence_match
            and scope_match.start() < verdict_match.start() < label_match.start() < evidence_match.start()
        )
        verbose_order = bool(
            scope_match
            and verdict_match
            and label_match
            and evidence_match
            and scope_match.start() < verdict_match.start() < evidence_match.start() < label_match.start()
        )
        ordered = compact_order or verbose_order
        pred = parse_answer(text)
        parseable = pred["scope"] != "unknown" and pred["verdict"] != "unknown"
        canonical = _canonical_label_field(text)
        score = 0.45 * present + 0.15 * ordered + 0.20 * parseable + 0.20 * canonical
        if _field(text, "隐患标签") and not canonical:
            score = -1.0
        rewards.append(max(-1.0, min(1.0, score)))
    return rewards


def _evidence_text(text: str) -> str:
    # Stop before the label field in verbose answers so simply copying the
    # canonical label cannot satisfy the evidence reward.
    match = re.search(
        r"(?:可见证据|判定依据|检查过程)\s*[:：](.*?)(?=\n\s*隐患标签\s*[:：]|\Z)",
        text,
        re.S,
    )
    return match.group(1).strip() if match else ""


def evidence_reward(completions: Iterable[Any], **_: Any) -> list[float]:
    rewards: list[float] = []
    for completion in completions:
        text = completion_text(completion)
        pred = parse_answer(text)
        evidence = _evidence_text(text)
        if not evidence:
            rewards.append(-1.0)
            continue
        if _has_unparsed_label_text(text):
            rewards.append(-1.0)
            continue
        if not pred["labels"]:
            normal_or_uncertain = any(
                cue in evidence
                for cue in ("可见", "完整", "清晰", "无遮挡", "未发现", "无明显", "无法判断", "看不清")
            )
            rewards.append(1.0 if normal_or_uncertain else 0.25)
            continue

        supported = 0
        copy_only = False
        for label in pred["labels"]:
            objects, cues = EVIDENCE_RULES.get(label, ((label,), ()))
            supported += int(any(term in evidence for term in objects) and any(term in evidence for term in cues))
            if label in evidence and len(evidence) <= len(label) + 10:
                copy_only = True
        support_fraction = supported / len(pred["labels"])
        visibility = any(cue in evidence for cue in ("可见", "未见", "遮挡", "反光", "模糊", "画面外", "无法"))
        score = 0.20 + 0.70 * support_fraction + 0.10 * float(visibility)
        if copy_only:
            score -= 0.30
        rewards.append(max(-1.0, min(1.0, score)))
    return rewards


def concise_completion_reward(completions: Iterable[Any], **_: Any) -> list[float]:
    rewards: list[float] = []
    for completion in completions:
        text = completion_text(completion).strip()
        length = len(text)
        evidence = _evidence_text(text)
        if 40 <= length <= 600 and evidence:
            rewards.append(1.0)
        elif 25 <= length <= 900 and evidence:
            rewards.append(0.25)
        else:
            rewards.append(-1.0)
    return rewards


def clean_false_positive_penalty(
    completions: Iterable[Any],
    gold_labels: Iterable[Any],
    **_: Any,
) -> list[float]:
    penalties: list[float] = []
    for completion, labels in zip(completions, gold_labels):
        gold = _as_set(labels)
        text = completion_text(completion)
        pred = parse_answer(text)["labels"]
        if not gold and _has_unparsed_label_text(text):
            penalties.append(-1.0)
        elif not gold and pred:
            penalties.append(-min(1.0, 0.50 + 0.15 * _weight(pred)))
        else:
            penalties.append(0.0)
    return penalties


# Keeping components separate makes every signal visible in W&B.  Positive
# weights sum to 1.0; the final component is an additional safety penalty.
REWARD_FUNCTIONS = [
    label_tversky_reward,
    exact_label_reward,
    verdict_reward,
    scope_consistency_reward,
    format_reward,
    evidence_reward,
    concise_completion_reward,
    clean_false_positive_penalty,
]
REWARD_WEIGHTS = [0.55, 0.10, 0.15, 0.05, 0.05, 0.05, 0.05, 0.10]

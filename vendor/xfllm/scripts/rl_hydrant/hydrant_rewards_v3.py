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


# Counts from the 1,893-row expanded, frozen-eval-excluded training set.
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
LABEL_WEIGHTS = {
    label: min(2.5, max(0.75, math.sqrt(MEDIAN_SUPPORT / max(count, 1))))
    for label, count in LABEL_SUPPORT.items()
}

EVIDENCE_TERMS = {
    "室内消火栓手轮缺失": ("手轮", "缺失"),
    "室内消火栓栓口方向错误": ("栓口", "方向"),
    "室内消火栓无消防水带": ("水带",),
    "室内消火栓无消防水枪": ("水枪",),
    "室内消火栓消防接口缺失": ("接口",),
    "消防软管卷盘供水管道折弯严重": ("卷盘", "折弯"),
    "室内消火栓无箱体": ("箱体",),
    "室内消火栓箱锈蚀": ("锈蚀",),
    "室内消火栓箱门缺失": ("箱门", "缺失"),
    "室内消火栓箱明显部位未采用耐久性文字或图形标注操作说明": ("操作说明",),
    "室内消火栓箱门上未标注“消火栓”和英文“FIRE HYDRANT”字样": ("FIRE HYDRANT", "消火栓"),
    "室内消火栓箱体无铭牌": ("铭牌",),
    "室内消火栓箱门标识模糊": ("标识", "模糊"),
    "室内消火栓箱体铭牌模糊": ("铭牌", "模糊"),
    "室内消火栓箱门为玻璃门": ("玻璃门",),
    "室内消火栓箱体或箱门被物品遮挡": ("遮挡",),
}


def _weight(labels: set[str]) -> float:
    return sum(LABEL_WEIGHTS.get(label, 1.0) for label in labels)


def _label_score(gold: set[str], pred: set[str]) -> float:
    if gold == pred:
        return 1.0
    if not gold:
        # A compliant image with any reported defect is a hard false positive.
        return -min(1.0, 0.65 + 0.15 * _weight(pred))
    if not pred:
        return -0.65

    tp, fp, fn = gold & pred, pred - gold, gold - pred
    tpw, fpw, fnw = _weight(tp), _weight(fp), _weight(fn)
    predw, goldw = max(_weight(pred), 1e-6), max(_weight(gold), 1e-6)
    precision = tpw / predw
    recall = tpw / goldw
    f2 = 5 * precision * recall / (4 * precision + recall) if precision + recall else 0.0
    # Normalize by gold weight so multi-label rows are comparable. A wrong
    # substitution receives both FP and FN penalties.
    score = f2 - 0.30 * fpw / goldw - 0.45 * fnw / goldw
    return max(-1.0, min(1.0, score))


def outcome_reward(
    completions: Iterable[Any],
    gold_scope: Iterable[str],
    gold_verdict: Iterable[str],
    gold_labels: Iterable[Any],
    **_: Any,
) -> list[float]:
    rewards: list[float] = []
    for completion, scope, verdict, labels in zip(completions, gold_scope, gold_verdict, gold_labels):
        pred = parse_answer(completion_text(completion))
        gold = _as_set(labels)
        predicted = pred["labels"]
        label_score = _label_score(gold, predicted)
        scope_score = 1.0 if pred["scope"] == scope else -0.5
        verdict_score = 1.0 if pred["verdict"] == verdict else -0.5
        consistent_verdict = (
            (bool(predicted) and pred["verdict"] == "不合规")
            or (not predicted and pred["verdict"] in {"合规", "无法判断"})
        )
        whitelist = INTERNAL_LABELS if pred["scope"] == "internal_components" else APPEARANCE_LABELS
        same_scope = predicted <= whitelist if pred["scope"] != "unknown" else not predicted
        consistency = 1.0 if consistent_verdict and same_scope else -0.5
        rewards.append(0.72 * label_score + 0.15 * verdict_score + 0.08 * scope_score + 0.05 * consistency)
    return rewards


def format_reward(completions: Iterable[Any], **_: Any) -> list[float]:
    rewards: list[float] = []
    for completion in completions:
        text = completion_text(completion)
        headers = ["检查范围", "结论", "隐患标签"]
        present = sum(bool(re.search(rf"(?:^|\n)\s*{name}\s*[:：]", text)) for name in headers)
        evidence_present = bool(
            re.search(r"(?:^|\n)\s*(?:可见证据|判定依据|检查过程)\s*[:：]", text)
        )
        pred = parse_answer(text)
        valid_scope = pred["scope"] != "unknown" or "无法确定" in _field(text, "检查范围")
        valid_verdict = pred["verdict"] != "unknown"
        label_field = _field(text, "隐患标签").strip(" 。.；;，,")
        invalid_label_text = bool(label_field and label_field != "无" and not pred["labels"])
        concise = 30 <= len(text) <= 1200
        score = (
            0.45 * present / len(headers)
            + 0.15 * evidence_present
            + 0.15 * valid_scope
            + 0.15 * valid_verdict
            + 0.10 * concise
        )
        if invalid_label_text:
            score -= 0.5
        rewards.append(max(-0.5, score))
    return rewards


def evidence_reward(completions: Iterable[Any], **_: Any) -> list[float]:
    rewards: list[float] = []
    for completion in completions:
        text = completion_text(completion)
        pred = parse_answer(text)
        match = re.search(
            r"(?:可见证据|检查过程|判定依据)\s*[:：](.*)$",
            text,
            re.S,
        )
        evidence = match.group(1).strip() if match else ""
        visibility = any(term in evidence for term in ("可见", "未见", "遮挡", "反光", "模糊", "画面外", "无法"))
        if pred["labels"]:
            supported = sum(
                all(term in evidence for term in EVIDENCE_TERMS.get(label, (label,)))
                for label in pred["labels"]
            ) / len(pred["labels"])
        else:
            supported = float(bool(evidence))
        rewards.append(0.5 * bool(evidence) + 0.2 * visibility + 0.3 * supported)
    return rewards


REWARD_FUNCTIONS = [outcome_reward, format_reward, evidence_reward]
REWARD_WEIGHTS = [0.93, 0.05, 0.02]


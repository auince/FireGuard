from __future__ import annotations

from typing import Any, Iterable

import hydrant_rewards_v4 as v4
from hydrant_rewards_v4 import (  # re-export for the training data loader
    ALL_LABELS,
    APPEARANCE_LABELS,
    EVIDENCE_RULES,
    INTERNAL_LABELS,
    LABEL_SUPPORT,
    LABEL_WEIGHTS,
    _as_set,
    _field,
    completion_text,
    parse_answer,
)


# Task rewards.  These are the only positive objectives in v4.1.
label_tversky_reward = v4.label_tversky_reward
exact_label_reward = v4.exact_label_reward
verdict_reward = v4.verdict_reward
clean_false_positive_penalty = v4.clean_false_positive_penalty


def scope_guard_penalty(
    completions: Iterable[Any],
    gold_scope: Iterable[str],
    **_: Any,
) -> list[float]:
    """Return zero for a valid answer and a negative penalty for violations."""
    penalties: list[float] = []
    for completion, gold in zip(completions, gold_scope):
        pred = parse_answer(completion_text(completion))
        labels = pred["labels"]

        wrong_scope = pred["scope"] != gold
        if pred["scope"] == "internal_components":
            cross_scope = not labels <= INTERNAL_LABELS
        elif pred["scope"] == "appearance":
            cross_scope = not labels <= APPEARANCE_LABELS
        else:
            cross_scope = bool(labels)
        verdict_inconsistent = not (
            (bool(labels) and pred["verdict"] == "不合规")
            or (not labels and pred["verdict"] in {"合规", "无法判断"})
        )

        if wrong_scope or cross_scope:
            penalties.append(-1.0)
        elif verdict_inconsistent:
            penalties.append(-0.5)
        else:
            penalties.append(0.0)
    return penalties


def _zero_or_negative(scores: list[float]) -> list[float]:
    """Convert a [roughly -1, 1] quality score to a guard in [-1, 0]."""
    return [max(-1.0, min(0.0, score - 1.0)) for score in scores]


def format_guard_penalty(completions: Iterable[Any], **kwargs: Any) -> list[float]:
    return _zero_or_negative(v4.format_reward(completions, **kwargs))


def evidence_guard_penalty(completions: Iterable[Any], **kwargs: Any) -> list[float]:
    # This remains deliberately low-weight: it verifies textual consistency,
    # not whether the evidence is visually true.
    return _zero_or_negative(v4.evidence_reward(completions, **kwargs))


def concise_guard_penalty(completions: Iterable[Any], **kwargs: Any) -> list[float]:
    return _zero_or_negative(v4.concise_completion_reward(completions, **kwargs))


# Positive task weights sum to 1.0.  Every other function returns 0 for a
# compliant output and becomes negative only when a guard is violated.
REWARD_FUNCTIONS = [
    label_tversky_reward,
    exact_label_reward,
    verdict_reward,
    clean_false_positive_penalty,
    scope_guard_penalty,
    format_guard_penalty,
    evidence_guard_penalty,
    concise_guard_penalty,
]
REWARD_WEIGHTS = [0.65, 0.20, 0.15, 0.10, 0.15, 0.10, 0.05, 0.10]

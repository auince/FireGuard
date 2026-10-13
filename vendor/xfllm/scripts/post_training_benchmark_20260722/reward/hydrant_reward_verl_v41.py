#!/usr/bin/env python3
"""verl adapter for the already validated hydrant reward v4.1."""
from __future__ import annotations

import json
import os
import sys
from typing import Any


REWARD_SOURCE = os.environ.get(
    "HYDRANT_REWARD_SOURCE", "/opt/datasets/fire-inspection/scripts/rl_hydrant"
)
if REWARD_SOURCE not in sys.path:
    sys.path.insert(0, REWARD_SOURCE)

import hydrant_rewards_v41 as reward_v41  # noqa: E402


def compute_score(
    data_source: str,
    solution_str: str,
    ground_truth: str | dict[str, Any],
    extra_info: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, float]:
    if data_source != "hydrant_reward_v41":
        raise ValueError(f"unexpected data_source: {data_source!r}")
    if isinstance(ground_truth, str):
        ground_truth = json.loads(ground_truth)
    kwargs = {
        "completions": [solution_str],
        "gold_scope": [ground_truth["gold_scope"]],
        "gold_verdict": [ground_truth["gold_verdict"]],
        "gold_labels": [ground_truth["gold_labels"]],
    }
    result: dict[str, float] = {}
    total = 0.0
    for function, weight in zip(reward_v41.REWARD_FUNCTIONS, reward_v41.REWARD_WEIGHTS, strict=True):
        raw = float(function(**kwargs)[0])
        weighted = float(weight) * raw
        result[f"raw_{function.__name__}"] = raw
        result[f"weighted_{function.__name__}"] = weighted
        total += weighted
    result["score"] = float(total)
    return result


if __name__ == "__main__":
    compliant = json.dumps(
        {"gold_scope": "appearance", "gold_verdict": "合规", "gold_labels": []},
        ensure_ascii=False,
    )
    answer = "检查范围：箱体外观\n结论：合规\n隐患标签：无\n可见证据：图中未见明确隐患。"
    print(json.dumps(compute_score("hydrant_reward_v41", answer, compliant), ensure_ascii=False, indent=2))

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


MODEL_ORDER = ["base", "pilot10_v1", "checkpoint20", "checkpoint40", "checkpoint60", "checkpoint80", "checkpoint100"]
METRIC_KEYS = [
    "scope_acc",
    "verdict_acc",
    "label_exact_acc",
    "all_exact_acc",
    "label_micro_precision",
    "label_micro_recall",
    "label_micro_f1",
    "label_macro_f1_present",
    "compliant_false_positive_rate",
]


def micro_f1(rows: list[dict[str, Any]]) -> float:
    tp = fp = fn = 0
    for row in rows:
        gold, pred = set(row["gold"]["labels"]), set(row["pred"]["labels"])
        tp += len(gold & pred)
        fp += len(pred - gold)
        fn += len(gold - pred)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def paired_bootstrap(base: list[dict[str, Any]], candidate: list[dict[str, Any]], seed: int = 42) -> dict[str, float]:
    base_by_id = {row["id"]: row for row in base}
    pairs = [(base_by_id[row["id"]], row) for row in candidate if row["id"] in base_by_id]
    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(1000):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        deltas.append(micro_f1([x[1] for x in sample]) - micro_f1([x[0] for x in sample]))
    deltas.sort()
    return {"mean": sum(deltas) / len(deltas), "ci_low": deltas[25], "ci_high": deltas[974]}


def paired_counts(base: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> dict[str, int]:
    base_by_id = {row["id"]: row for row in base}
    counts = {"label_exact_gained": 0, "label_exact_lost": 0, "verdict_gained": 0, "verdict_lost": 0}
    for row in candidate:
        old = base_by_id[row["id"]]
        old_label = set(old["gold"]["labels"]) == set(old["pred"]["labels"])
        new_label = set(row["gold"]["labels"]) == set(row["pred"]["labels"])
        old_verdict = old["gold"]["verdict"] == old["pred"]["verdict"]
        new_verdict = row["gold"]["verdict"] == row["pred"]["verdict"]
        counts["label_exact_gained"] += int(new_label and not old_label)
        counts["label_exact_lost"] += int(old_label and not new_label)
        counts["verdict_gained"] += int(new_verdict and not old_verdict)
        counts["verdict_lost"] += int(old_verdict and not new_verdict)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-dir", required=True)
    args = parser.parse_args()
    root = Path(args.eval_dir)
    models: dict[str, dict[str, Any]] = {}
    for name in MODEL_ORDER:
        path = root / f"{name}.json"
        if path.exists():
            models[name] = json.loads(path.read_text(encoding="utf-8"))
    missing = [name for name in MODEL_ORDER if name not in models]
    if missing:
        raise FileNotFoundError(f"Missing evaluations: {missing}")

    table: dict[str, dict[str, Any]] = {}
    comparisons: dict[str, Any] = {}
    base_rows = models["base"]["all"]["results"]
    for name, payload in models.items():
        table[name] = {}
        for split in ("all", "ultra_strict_pass"):
            metrics = payload[split]["metrics"]
            table[name][split] = {key: metrics[key] for key in METRIC_KEYS}
        if name != "base":
            rows = payload["all"]["results"]
            comparisons[name] = {
                **paired_counts(base_rows, rows),
                "micro_f1_delta": table[name]["all"]["label_micro_f1"] - table["base"]["all"]["label_micro_f1"],
                "micro_f1_paired_bootstrap": paired_bootstrap(base_rows, rows),
            }

    best_name = max(
        MODEL_ORDER,
        key=lambda name: (
            table[name]["ultra_strict_pass"]["label_micro_f1"],
            -table[name]["ultra_strict_pass"]["compliant_false_positive_rate"],
        ),
    )
    best = models[best_name]
    base = models["base"]
    per_label_delta = {}
    for label, values in best["all"]["metrics"]["per_label"].items():
        old = base["all"]["metrics"]["per_label"][label]
        per_label_delta[label] = {
            "base_f1": old["f1"],
            "best_f1": values["f1"],
            "delta": values["f1"] - old["f1"],
            "best_precision": values["precision"],
            "best_recall": values["recall"],
            "gold_support": values["tp"] + values["fn"],
        }

    summary = {
        "best_checkpoint": best_name,
        "selection_rule": "highest ultra_strict_pass label_micro_f1, tie-break lower compliant false-positive rate",
        "metrics": table,
        "paired_vs_base": comparisons,
        "best_per_label_delta": per_label_delta,
    }
    (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 消防栓 Qwen3-VL-4B GRPO 冻结集评测",
        "",
        "## 全量 244 张",
        "",
        "| 模型 | 结论准确率 | 标签 Exact | 标签 Micro-F1 | 标签 Macro-F1 | 合规误报率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in MODEL_ORDER:
        m = table[name]["all"]
        lines.append(
            f"| {name} | {m['verdict_acc']:.1%} | {m['label_exact_acc']:.1%} | {m['label_micro_f1']:.1%} | {m['label_macro_f1_present']:.1%} | {m['compliant_false_positive_rate']:.1%} |"
        )
    lines += [
        "",
        "## 高置信 ultra-strict 148 张",
        "",
        "| 模型 | 结论准确率 | 标签 Exact | 标签 Micro-F1 | 标签 Macro-F1 | 合规误报率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in MODEL_ORDER:
        m = table[name]["ultra_strict_pass"]
        lines.append(
            f"| {name} | {m['verdict_acc']:.1%} | {m['label_exact_acc']:.1%} | {m['label_micro_f1']:.1%} | {m['label_macro_f1_present']:.1%} | {m['compliant_false_positive_rate']:.1%} |"
        )
    lines += ["", f"按预设规则选择的最佳节点：**{best_name}**。", ""]
    (root / "summary_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"best_checkpoint": best_name, "metrics": table[best_name], "vs_base": comparisons.get(best_name)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


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


def paired_bootstrap(
    baseline: list[dict[str, Any]], candidate: list[dict[str, Any]], *, samples: int, seed: int
) -> dict[str, float]:
    base_by_id = {row["id"]: row for row in baseline}
    pairs = [(base_by_id[row["id"]], row) for row in candidate if row["id"] in base_by_id]
    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(samples):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        deltas.append(micro_f1([pair[1] for pair in sample]) - micro_f1([pair[0] for pair in sample]))
    deltas.sort()
    return {
        "mean": sum(deltas) / len(deltas),
        "ci_low": deltas[int(samples * 0.025)],
        "ci_high": deltas[min(samples - 1, int(samples * 0.975))],
    }


def paired_counts(baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> dict[str, int]:
    base_by_id = {row["id"]: row for row in baseline}
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
    parser.add_argument("--names", nargs="+", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    root = Path(args.eval_dir)
    if args.baseline not in args.names:
        raise ValueError("--baseline must be present in --names")
    models: dict[str, dict[str, Any]] = {}
    for name in args.names:
        path = root / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(path)
        models[name] = json.loads(path.read_text(encoding="utf-8"))

    table: dict[str, dict[str, Any]] = {}
    comparisons: dict[str, Any] = {}
    baseline_rows = models[args.baseline]["all"]["results"]
    for name in args.names:
        payload = models[name]
        table[name] = {
            split: {key: payload[split]["metrics"][key] for key in METRIC_KEYS}
            for split in ("all", "ultra_strict_pass")
        }

    for name in args.names:
        if name != args.baseline:
            rows = models[name]["all"]["results"]
            comparisons[name] = {
                **paired_counts(baseline_rows, rows),
                "micro_f1_delta": table[name]["all"]["label_micro_f1"]
                - table[args.baseline]["all"]["label_micro_f1"],
                "micro_f1_paired_bootstrap": paired_bootstrap(
                    baseline_rows, rows, samples=args.bootstrap_samples, seed=args.seed
                ),
            }

    candidates = [name for name in args.names if name.startswith("checkpoint")]
    if not candidates:
        raise ValueError("No checkpoint candidates found; candidate names must start with 'checkpoint'")
    best_name = max(
        candidates,
        key=lambda name: (
            table[name]["ultra_strict_pass"]["label_micro_f1"],
            -table[name]["ultra_strict_pass"]["compliant_false_positive_rate"],
        ),
    )
    best = models[best_name]
    baseline = models[args.baseline]
    per_label_delta = {}
    for label, values in best["all"]["metrics"]["per_label"].items():
        old = baseline["all"]["metrics"]["per_label"][label]
        per_label_delta[label] = {
            "baseline_f1": old["f1"],
            "best_f1": values["f1"],
            "delta": values["f1"] - old["f1"],
            "best_precision": values["precision"],
            "best_recall": values["recall"],
            "gold_support": values["tp"] + values["fn"],
        }

    summary = {
        "baseline": args.baseline,
        "best_checkpoint": best_name,
        "selection_rule": "highest ultra_strict_pass label_micro_f1, tie-break lower compliant false-positive rate",
        "metrics": table,
        "paired_vs_baseline": comparisons,
        "best_per_label_delta": per_label_delta,
    }
    (root / "summary_v3.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = ["# 消防栓 Qwen3-VL-4B GRPO v3 冻结集评测", ""]
    for split, title in (("all", "全量 244 张"), ("ultra_strict_pass", "高置信 ultra-strict 148 张")):
        lines += [
            f"## {title}",
            "",
            "| 模型 | 结论准确率 | 标签 Exact | 标签 Micro-F1 | 标签 Macro-F1 | 合规误报率 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for name in args.names:
            metric = table[name][split]
            lines.append(
                f"| {name} | {metric['verdict_acc']:.1%} | {metric['label_exact_acc']:.1%} | "
                f"{metric['label_micro_f1']:.1%} | {metric['label_macro_f1_present']:.1%} | "
                f"{metric['compliant_false_positive_rate']:.1%} |"
            )
        lines.append("")
    lines += [f"按预设规则选择的最佳节点：**{best_name}**。", ""]
    (root / "summary_v3_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"best_checkpoint": best_name, "metrics": table[best_name], "vs_baseline": comparisons[best_name]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

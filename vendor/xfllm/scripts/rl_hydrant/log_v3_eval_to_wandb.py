#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import wandb


def checkpoint_step(name: str) -> int:
    if name == "base" or name.startswith("v2_init"):
        return 0
    match = re.search(r"(\d+)$", name)
    return int(match.group(1)) if match else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--entity")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--group")
    args = parser.parse_args()

    summary_path = Path(args.summary)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    run = wandb.init(
        project=args.project,
        entity=args.entity,
        name=args.run_name,
        group=args.group,
        job_type="frozen-evaluation",
        config={
            "summary_path": str(summary_path),
            "baseline": summary["baseline"],
            "selection_rule": summary["selection_rule"],
        },
    )
    columns = [
        "name",
        "step",
        "split",
        "verdict_acc",
        "label_exact_acc",
        "label_micro_precision",
        "label_micro_recall",
        "label_micro_f1",
        "label_macro_f1_present",
        "compliant_false_positive_rate",
    ]
    rows = []
    for index, (name, splits) in enumerate(summary["metrics"].items()):
        step = checkpoint_step(name)
        for split, metrics in splits.items():
            rows.append([name, step, split] + [metrics[key] for key in columns[3:]])
        flat = {}
        for split, metrics in splits.items():
            for key in columns[3:]:
                flat[f"frozen/{split}/{key}"] = metrics[key]
        flat["frozen/checkpoint_step"] = step
        flat["frozen/model_index"] = index
        run.log(flat, step=index)

    table = wandb.Table(columns=columns, data=rows)
    run.log({"frozen/checkpoint_comparison": table})
    run.summary["best_checkpoint"] = summary["best_checkpoint"]
    best = summary["metrics"][summary["best_checkpoint"]]
    for split, metrics in best.items():
        for key in columns[3:]:
            run.summary[f"best/{split}/{key}"] = metrics[key]
    run.finish()
    print(run.url)


if __name__ == "__main__":
    main()

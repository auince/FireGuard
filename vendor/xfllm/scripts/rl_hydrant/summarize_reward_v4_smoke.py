#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from datetime import datetime
import json
from pathlib import Path
import re
import statistics
from typing import Any


ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.fmean(values),
        "min": min(values),
        "max": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-log", required=True)
    parser.add_argument("--offline-report", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--wandb-url", required=True)
    args = parser.parse_args()

    text = ANSI.sub("", Path(args.train_log).read_text(encoding="utf-8", errors="replace"))
    steps: list[dict[str, Any]] = []
    for line in text.splitlines():
        marker = "{'loss':"
        position = line.find(marker)
        if position < 0:
            continue
        try:
            parsed = ast.literal_eval(line[position:])
        except (SyntaxError, ValueError):
            continue
        if isinstance(parsed, dict) and "reward" in parsed:
            steps.append(parsed)
    if not steps:
        raise RuntimeError("No per-step metric dictionaries found")

    offline = json.loads(Path(args.offline_report).read_text(encoding="utf-8"))
    keys = sorted({
        key
        for step in steps
        for key, value in step.items()
        if isinstance(value, (int, float))
    })
    aggregate = {
        key: summarize([float(step[key]) for step in steps if key in step])
        for key in keys
    }

    checks = {
        "five_steps_completed": len(steps) == 5,
        "finite_nonzero_gradients": all(
            float(step["grad_norm"]) > 0
            and float(step["grad_norm"]) == float(step["grad_norm"])
            for step in steps
        ),
        "reward_varies_in_every_group": all(float(step["reward_std"]) > 0 for step in steps),
        "no_zero_std_groups": all(float(step["frac_reward_zero_std"]) == 0 for step in steps),
        "no_completion_clipping": all(float(step["completions/clipped_ratio"]) == 0 for step in steps),
        "kl_below_3": all(float(step["kl"]) < 3 for step in steps),
        "offline_assertions_all_passed": offline["assertions_failed"] == 0,
    }

    reward_components = [
        key
        for key in keys
        if key.startswith("rewards/") and key.endswith("/std")
    ]
    saturated_components = [
        key.removesuffix("/std")
        for key in reward_components
        if all(float(step.get(key, 0.0)) == 0.0 for step in steps)
    ]
    warnings: list[str] = []
    saturated_positive_components = [
        component
        for component in saturated_components
        if "guard_penalty" not in component
        and "clean_false_positive_penalty" not in component
    ]
    if saturated_positive_components:
        warnings.append(
            "The following positive reward components had zero within-group standard deviation "
            f"at every smoke step: {', '.join(saturated_positive_components)}"
        )
    entropy_mean = aggregate.get("entropy", {}).get("mean", 0.0)
    if entropy_mean < 0.1:
        warnings.append(
            f"Mean token entropy was only {entropy_mean:.4f}; the SFT policy is highly deterministic."
        )
    unsupported = offline["mutation_summary"]["unsupported_evidence"]["mean"]
    exact = offline["mutation_summary"]["synthetic_exact"]["mean"]
    if exact - unsupported < 0.1:
        warnings.append(
            "Unsupported evidence loses less than 0.1 total reward "
            f"(exact={exact:.4f}, unsupported={unsupported:.4f})."
        )
    wrong_scope = offline["mutation_summary"]["wrong_scope"]["mean"]
    if exact - wrong_scope < 0.15:
        warnings.append(
            "Wrong inspection scope loses less than 0.15 total reward "
            f"(exact={exact:.4f}, wrong_scope={wrong_scope:.4f})."
        )

    status = "pass" if all(checks.values()) and not warnings else (
        "pass_with_warnings" if all(checks.values()) else "fail"
    )
    report = {
        "created_at": datetime.now().astimezone().isoformat(),
        "status": status,
        "wandb_url": args.wandb_url,
        "steps": steps,
        "aggregate": aggregate,
        "checks": checks,
        "warnings": warnings,
        "saturated_reward_components": saturated_components,
        "offline_audit": {
            "dataset_rows_audited": offline["dataset_rows_audited"],
            "assertions_passed": offline["assertions_passed"],
            "assertions_failed": offline["assertions_failed"],
            "reward_sha256": offline["reward_sha256"],
            "mutation_summary": offline["mutation_summary"],
        },
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "validation_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Reward v4 validation summary",
        "",
        f"- Status: **{status}**",
        f"- Created: `{report['created_at']}`",
        f"- W&B: {args.wandb_url}",
        f"- Reward SHA-256: `{offline['reward_sha256']}`",
        f"- Offline audit: `{offline['dataset_rows_audited']} rows`, "
        f"`{offline['assertions_passed']} passed / {offline['assertions_failed']} failed`",
        f"- Smoke test: `{len(steps)} steps`",
        "",
        "## Smoke metrics",
        "",
        "| Metric | Mean | Min | Max |",
        "|---|---:|---:|---:|",
    ]
    for key in [
        "loss",
        "grad_norm",
        "reward",
        "reward_std",
        "frac_reward_zero_std",
        "kl",
        "entropy",
        "completions/mean_length",
        "completions/clipped_ratio",
        "rewards/label_tversky_reward/mean",
        "rewards/exact_label_reward/mean",
        "rewards/verdict_reward/mean",
        "rewards/scope_consistency_reward/mean",
        "rewards/format_reward/mean",
        "rewards/evidence_reward/mean",
        "rewards/concise_completion_reward/mean",
        "rewards/clean_false_positive_penalty/mean",
    ]:
        values = aggregate.get(key)
        if values:
            lines.append(
                f"| {key} | {values['mean']:.4f} | {values['min']:.4f} | {values['max']:.4f} |"
            )
    lines.extend(["", "## Checks", ""])
    lines.extend(
        f"- {'PASS' if passed else 'FAIL'} — `{name}`"
        for name, passed in checks.items()
    )
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in warnings)
    if not warnings:
        lines.append("- None")
    lines.extend([
        "",
        "## Decision",
        "",
        (
            "Reward v4 is executable and supplies non-zero GRPO ranking signal, "
            "but a long pilot should wait until the warning items are reviewed."
            if status == "pass_with_warnings"
            else "See status and checks above."
        ),
    ])
    (output_dir / "VALIDATION_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(
        {
            "status": status,
            "steps": len(steps),
            "warnings": warnings,
            "output_dir": str(output_dir),
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import statistics
from typing import Any

reward = importlib.import_module(os.environ.get("HYDRANT_REWARD_MODULE", "hydrant_rewards_v4"))


def compact(scope: str, verdict: str, labels: list[str], evidence: str) -> str:
    label_text = "；".join(labels) if labels else "无"
    return (
        f"检查范围：{scope}\n"
        f"结论：{verdict}\n"
        f"隐患标签：{label_text}\n"
        f"可见证据：{evidence}"
    )


def verbose(scope: str, verdict: str, labels: list[str], evidence: str) -> str:
    label_text = "；".join(labels) if labels else "无"
    return (
        f"检查范围：{scope}\n\n"
        f"结论：{verdict}\n\n"
        "检查过程：\n"
        f"1. 画面判断：{evidence}\n"
        f"2. 可见正常项：{'未见明显异常。' if not labels else '其余可见组件未见明确异常。'}\n"
        f"3. 可见异常项：{evidence if labels else '未见明确异常项。'}\n"
        "4. 无法判断项：无。\n\n"
        f"判定依据：{evidence}\n\n"
        f"隐患标签：{label_text}。"
    )


def scope_name(scope: str) -> str:
    return "内部组件" if scope == "internal_components" else "箱体外观"


def scope_for_label(label: str) -> str:
    return "internal_components" if label in reward.INTERNAL_LABELS else "appearance"


def opposite_scope(scope: str) -> str:
    return "appearance" if scope == "internal_components" else "internal_components"


def evidence_for(label: str) -> str:
    objects, cues = reward.EVIDENCE_RULES[label]
    return f"图中清晰可见{objects[0]}，{cues[0]}。"


def assistant_text(row: dict[str, Any]) -> str:
    for message in row.get("messages", []):
        if message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        return "\n".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return ""


def normalize_scope(value: str) -> str:
    if value in {"appearance", "箱体外观"}:
        return "appearance"
    if value in {"internal", "internal_components", "内部组件"}:
        return "internal_components"
    return "unknown"


def score(
    completion: str,
    *,
    gold_scope: str,
    gold_verdict: str,
    gold_labels: list[str],
) -> dict[str, float]:
    kwargs = {
        "completions": [completion],
        "gold_scope": [gold_scope],
        "gold_verdict": [gold_verdict],
        "gold_labels": [gold_labels],
    }
    components = {
        fn.__name__: float(fn(**kwargs)[0])
        for fn in reward.REWARD_FUNCTIONS
    }
    total = sum(
        weight * components[fn.__name__]
        for weight, fn in zip(reward.REWARD_WEIGHTS, reward.REWARD_FUNCTIONS)
    )
    return {"total": float(total), **components}


def mutation_examples(
    answer: str,
    gold_scope: str,
    gold_verdict: str,
    gold_labels: list[str],
) -> dict[str, str]:
    scope_text = scope_name(gold_scope)
    labels = list(gold_labels)
    gold_evidence = (
        "；".join(evidence_for(label) for label in labels)
        if labels
        else "图中关键项目清晰可见，未发现明显异常。"
    )
    all_same_scope = (
        reward.INTERNAL_LABELS
        if gold_scope == "internal_components"
        else reward.APPEARANCE_LABELS
    )
    wrong_candidates = sorted(all_same_scope - set(labels))
    wrong_label = wrong_candidates[0] if wrong_candidates else sorted(reward.ALL_LABELS - set(labels))[0]
    empty_verdict = "合规"
    exact_verdict = "不合规" if labels else "合规"
    mutations = {
        "gold_original": answer,
        "synthetic_exact": compact(scope_text, exact_verdict, labels, gold_evidence),
        "wrong_verdict": compact(
            scope_text,
            "合规" if exact_verdict == "不合规" else "不合规",
            labels,
            gold_evidence,
        ),
        "wrong_scope": compact(
            scope_name(opposite_scope(gold_scope)),
            exact_verdict,
            labels,
            gold_evidence,
        ),
        "empty_prediction": compact(
            scope_text,
            empty_verdict,
            [],
            "图中关键项目清晰可见，未发现明显异常。",
        ),
        "fake_label": compact(
            scope_text,
            exact_verdict,
            ["消防栓坏了"],
            "图中设备存在异常。",
        ),
    }
    if labels:
        mutations["drop_one_label"] = compact(
            scope_text,
            "不合规",
            labels[:-1],
            "；".join(evidence_for(label) for label in labels[:-1])
            or "未发现明显异常。",
        )
        mutations["add_wrong_label"] = compact(
            scope_text,
            "不合规",
            labels + [wrong_label],
            gold_evidence + "；" + evidence_for(wrong_label),
        )
        mutations["replace_one_label"] = compact(
            scope_text,
            "不合规",
            labels[:-1] + [wrong_label],
            "；".join(evidence_for(label) for label in labels[:-1] + [wrong_label]),
        )
        mutations["unsupported_evidence"] = compact(
            scope_text,
            "不合规",
            labels,
            "图中设备整体可见。",
        )
    else:
        mutations["clean_false_positive"] = compact(
            scope_text,
            "不合规",
            [wrong_label],
            evidence_for(wrong_label),
        )
    return mutations


def summarize(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "std": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "min": ordered[0],
        "p25": ordered[len(ordered) // 4],
        "median": statistics.median(ordered),
        "p75": ordered[(3 * len(ordered)) // 4],
        "max": ordered[-1],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-jsonl", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    reward_path = Path(reward.__file__).resolve()
    reward_hash = hashlib.sha256(reward_path.read_bytes()).hexdigest()

    cases: list[dict[str, Any]] = []

    clean_exact = compact("箱体外观", "合规", [], "箱门和标识清晰可见，未发现明显异常。")
    for name, text in {
        "clean_exact_compact": clean_exact,
        "clean_exact_verbose": verbose("箱体外观", "合规", [], "箱门和标识清晰可见，未发现明显异常。"),
        "clean_false_positive": compact(
            "箱体外观",
            "不合规",
            ["室内消火栓箱体无铭牌"],
            "图中清晰可见箱体，未见铭牌。",
        ),
        "clean_fake_label": compact("箱体外观", "合规", ["消防栓坏了"], "图中设备存在异常。"),
        "clean_missing_evidence": "检查范围：箱体外观\n结论：合规\n隐患标签：无",
    }.items():
        cases.append(
            {
                "group": "handcrafted",
                "name": name,
                "score": score(
                    text,
                    gold_scope="appearance",
                    gold_verdict="合规",
                    gold_labels=[],
                ),
            }
        )

    for label in sorted(reward.ALL_LABELS):
        scope = scope_for_label(label)
        visible_scope = scope_name(scope)
        evidence = evidence_for(label)
        wrong = next(iter(sorted(
            (reward.INTERNAL_LABELS if scope == "internal_components" else reward.APPEARANCE_LABELS)
            - {label}
        )))
        variants = {
            "exact_compact": compact(visible_scope, "不合规", [label], evidence),
            "exact_verbose": verbose(visible_scope, "不合规", [label], evidence),
            "missed": compact(visible_scope, "合规", [], "未发现明显异常。"),
            "wrong_label": compact(visible_scope, "不合规", [wrong], evidence_for(wrong)),
            "extra_label": compact(
                visible_scope,
                "不合规",
                [label, wrong],
                evidence + "；" + evidence_for(wrong),
            ),
            "wrong_scope": compact(scope_name(opposite_scope(scope)), "不合规", [label], evidence),
            "unsupported_evidence": compact(visible_scope, "不合规", [label], "图中设备整体可见。"),
            "copied_label_only": compact(visible_scope, "不合规", [label], label),
        }
        for variant, text in variants.items():
            cases.append(
                {
                    "group": "per_label",
                    "label": label,
                    "name": variant,
                    "score": score(
                        text,
                        gold_scope=scope,
                        gold_verdict="不合规",
                        gold_labels=[label],
                    ),
                }
            )

    dataset_rows: list[dict[str, Any]] = []
    mutation_scores: dict[str, list[float]] = {}
    component_ranges: dict[str, list[float]] = {}
    with open(args.train_jsonl, encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if args.limit > 0 and index >= args.limit:
                break
            row = json.loads(line)
            answer = assistant_text(row)
            parsed = reward.parse_answer(answer)
            meta = row.get("meta") or {}
            labels = list(meta.get("defect_labels", sorted(parsed["labels"])))
            verdict = meta.get("verdict") or parsed["verdict"]
            scope = normalize_scope(meta.get("task", ""))
            if scope == "unknown":
                scope = parsed["scope"]
            if scope == "unknown":
                continue
            variants = mutation_examples(answer, scope, verdict, labels)
            row_scores: dict[str, float] = {}
            for mutation_name, completion in variants.items():
                scored = score(
                    completion,
                    gold_scope=scope,
                    gold_verdict=verdict,
                    gold_labels=labels,
                )
                row_scores[mutation_name] = scored["total"]
                mutation_scores.setdefault(mutation_name, []).append(scored["total"])
                for component, value in scored.items():
                    component_ranges.setdefault(component, []).append(value)
            dataset_rows.append(
                {
                    "id": row.get("id", f"row_{index}"),
                    "scope": scope,
                    "verdict": verdict,
                    "labels": labels,
                    "scores": row_scores,
                }
            )

    assertions: list[dict[str, Any]] = []

    def check(name: str, condition: bool, details: Any) -> None:
        assertions.append({"name": name, "passed": bool(condition), "details": details})

    handcrafted = {case["name"]: case["score"]["total"] for case in cases if case["group"] == "handcrafted"}
    check(
        "clean_exact_beats_false_positive",
        handcrafted["clean_exact_compact"] > handcrafted["clean_false_positive"],
        handcrafted,
    )
    check(
        "fake_label_is_negative",
        handcrafted["clean_fake_label"] < 0,
        handcrafted["clean_fake_label"],
    )
    check(
        "missing_evidence_is_penalized",
        handcrafted["clean_missing_evidence"] < handcrafted["clean_exact_compact"],
        handcrafted,
    )

    per_label: dict[str, dict[str, float]] = {}
    for case in cases:
        if case["group"] == "per_label":
            per_label.setdefault(case["label"], {})[case["name"]] = case["score"]["total"]
    for label, values in per_label.items():
        check(
            f"{label}:exact_beats_missed",
            min(values["exact_compact"], values["exact_verbose"]) > values["missed"],
            values,
        )
        check(
            f"{label}:exact_beats_wrong",
            min(values["exact_compact"], values["exact_verbose"]) > values["wrong_label"],
            values,
        )
        check(
            f"{label}:evidence_matters",
            values["exact_compact"] > values["unsupported_evidence"],
            values,
        )
        check(
            f"{label}:copy_only_not_full",
            values["copied_label_only"] < values["exact_compact"],
            values,
        )

    for component, values in component_ranges.items():
        check(
            f"{component}:finite_and_bounded",
            all(-1.000001 <= value <= 1.000001 for value in values),
            {"min": min(values), "max": max(values)},
        )

    if mutation_scores:
        summary = {name: summarize(values) for name, values in mutation_scores.items()}
        check(
            "dataset_exact_beats_empty",
            summary["synthetic_exact"]["mean"] > summary["empty_prediction"]["mean"],
            summary,
        )
        check(
            "dataset_exact_beats_wrong_verdict",
            summary["synthetic_exact"]["mean"] > summary["wrong_verdict"]["mean"],
            summary,
        )
        check(
            "dataset_fake_label_negative_on_average",
            summary["fake_label"]["mean"] < 0,
            summary["fake_label"],
        )
    else:
        summary = {}

    report = {
        "created_at": datetime.now().astimezone().isoformat(),
        "reward_module": reward.__name__,
        "reward_file": str(reward_path),
        "reward_sha256": reward_hash,
        "reward_weights": reward.REWARD_WEIGHTS,
        "reward_functions": [fn.__name__ for fn in reward.REWARD_FUNCTIONS],
        "label_weights": reward.LABEL_WEIGHTS,
        "train_jsonl": args.train_jsonl,
        "dataset_rows_audited": len(dataset_rows),
        "dataset_label_cardinality": dict(Counter(len(row["labels"]) for row in dataset_rows)),
        "mutation_summary": summary,
        "assertions": assertions,
        "assertions_passed": sum(item["passed"] for item in assertions),
        "assertions_failed": sum(not item["passed"] for item in assertions),
        "handcrafted_cases": cases,
    }
    (output_dir / "reward_v4_validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "dataset_mutation_scores.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in dataset_rows),
        encoding="utf-8",
    )

    lines = [
        "# Hydrant Reward v4 validation",
        "",
        f"- Created: `{report['created_at']}`",
        f"- Reward SHA-256: `{reward_hash}`",
        f"- Dataset rows audited: `{len(dataset_rows)}`",
        f"- Assertions: `{report['assertions_passed']} passed / {report['assertions_failed']} failed`",
        "",
        "## Mutation reward summary",
        "",
        "| Mutation | Count | Mean | Std | Min | Median | Max |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, values in sorted(summary.items()):
        lines.append(
            f"| {name} | {values['count']} | {values['mean']:.4f} | "
            f"{values['std']:.4f} | {values['min']:.4f} | "
            f"{values['median']:.4f} | {values['max']:.4f} |"
        )
    lines.extend(["", "## Failed assertions", ""])
    failed = [item for item in assertions if not item["passed"]]
    if failed:
        lines.extend(f"- `{item['name']}`: `{item['details']}`" for item in failed)
    else:
        lines.append("- None")
    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(
        {
            "output_dir": str(output_dir),
            "assertions_passed": report["assertions_passed"],
            "assertions_failed": report["assertions_failed"],
            "dataset_rows_audited": len(dataset_rows),
        },
        ensure_ascii=False,
        indent=2,
    ))
    raise SystemExit(1 if report["assertions_failed"] else 0)


if __name__ == "__main__":
    main()

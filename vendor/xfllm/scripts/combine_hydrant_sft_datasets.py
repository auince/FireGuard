#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_INTERNAL_DIR = Path(
    "/opt/datasets/fire-inspection/training_data/202606221711_20260608_indoor_hydrant_internal_components_optimized_reasoned"
)
DEFAULT_APPEARANCE_DIR = Path(
    "/opt/datasets/fire-inspection/training_data/20260624_indoor_hydrant_appearance_compliance_cleaned"
)
DEFAULT_OUTPUT_DIR = Path(
    "/opt/datasets/fire-inspection/training_data/20260624_hydrant_internal_plus_appearance_cleaned"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Combine internal-component and appearance SFT datasets without mixing task prompts."
    )
    p.add_argument("--internal-dir", type=Path, default=DEFAULT_INTERNAL_DIR)
    p.add_argument("--appearance-dir", type=Path, default=DEFAULT_APPEARANCE_DIR)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--input-name", default="all.jsonl")
    p.add_argument("--all-name", default="all.jsonl")
    p.add_argument("--train-name", default="train.jsonl")
    p.add_argument("--val-name", default="val.jsonl")
    p.add_argument("--summary-name", default="summary.json")
    p.add_argument("--report-name", default="cleaning_report.md")
    p.add_argument("--val-ratio", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--id-prefix", default="xf_hydrant_mixed")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: row is not a JSON object")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def image_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_row(
    row: dict[str, Any],
    *,
    task: str,
    source_dataset: Path,
    idx: int,
    id_prefix: str,
) -> dict[str, Any]:
    out = copy.deepcopy(row)
    original_id = out.get("id")
    out["id"] = f"{id_prefix}_{idx:06d}"
    meta = out.setdefault("meta", {})
    meta["task"] = task
    meta["source_dataset"] = str(source_dataset.resolve())
    meta["original_id"] = original_id

    images = out.get("images") or []
    if not images:
        raise ValueError(f"{source_dataset}: row {original_id} has no images")
    image_path = Path(images[0])
    if not image_path.exists():
        raise FileNotFoundError(f"{source_dataset}: row {original_id} missing image: {image_path}")

    actual_hash = image_sha1(image_path)
    recorded_hash = meta.get("image_sha1")
    if recorded_hash and recorded_hash != actual_hash:
        raise ValueError(
            f"{source_dataset}: row {original_id} image hash mismatch: {recorded_hash} != {actual_hash}"
        )
    meta["image_sha1"] = actual_hash
    return out


def row_split_key(row: dict[str, Any]) -> str:
    meta = row.get("meta") or {}
    task = meta.get("task") or "unknown"
    verdict = meta.get("verdict") or "unknown"
    defect_keys = meta.get("defect_keys") or []
    primary = defect_keys[0] if defect_keys else "compliant"
    return f"{task}:{verdict}:{primary}"


def split_by_image_hash(
    rows: list[dict[str, Any]], val_ratio: float, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if val_ratio <= 0:
        return sorted(rows, key=lambda row: row["id"]), []
    if val_ratio >= 1:
        raise ValueError("--val-ratio must be < 1")

    hash_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        hash_groups[row["meta"]["image_sha1"]].append(row)

    strata: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    for group in hash_groups.values():
        key = "|".join(sorted({row_split_key(row) for row in group}))
        strata[key].append(group)

    rng = random.Random(seed)
    train_groups: list[list[dict[str, Any]]] = []
    val_groups: list[list[dict[str, Any]]] = []
    for key in sorted(strata):
        groups = sorted(strata[key], key=lambda group: min(row["id"] for row in group))
        rng.shuffle(groups)
        if len(groups) <= 1:
            val_n = 0
        else:
            val_n = max(1, round(len(groups) * val_ratio))
            val_n = min(val_n, len(groups) - 1)
        val_groups.extend(groups[:val_n])
        train_groups.extend(groups[val_n:])

    train = [row for group in train_groups for row in group]
    val = [row for group in val_groups for row in group]
    return sorted(train, key=lambda row: row["id"]), sorted(val, key=lambda row: row["id"])


def task_counter(rows: list[dict[str, Any]]) -> Counter[str]:
    return Counter((row.get("meta") or {}).get("task") or "unknown" for row in rows)


def verdict_by_task(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counters: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        meta = row.get("meta") or {}
        counters[meta.get("task") or "unknown"][meta.get("verdict") or "unknown"] += 1
    return {task: dict(counter) for task, counter in sorted(counters.items())}


def defect_by_task(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counters: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        meta = row.get("meta") or {}
        task = meta.get("task") or "unknown"
        for label in meta.get("defect_labels") or []:
            counters[task][label] += 1
    return {task: dict(counter) for task, counter in sorted(counters.items())}


def build_summary(
    *,
    args: argparse.Namespace,
    rows: list[dict[str, Any]],
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    internal_source_rows: int,
    appearance_source_rows: int,
    outputs: dict[str, Path],
) -> dict[str, Any]:
    hash_counter = Counter(row["meta"]["image_sha1"] for row in rows)
    duplicate_hash_groups = {h: n for h, n in hash_counter.items() if n > 1}
    cross_task_groups = 0
    for image_hash in duplicate_hash_groups:
        tasks = {row["meta"].get("task") for row in rows if row["meta"]["image_sha1"] == image_hash}
        if len(tasks) > 1:
            cross_task_groups += 1

    train_hashes = {row["meta"]["image_sha1"] for row in train}
    val_hashes = {row["meta"]["image_sha1"] for row in val}

    return {
        "output_dir": str(args.output_dir.resolve()),
        "files": {name: str(path) for name, path in outputs.items()},
        "source_datasets": {
            "internal_components": str(args.internal_dir.resolve()),
            "appearance": str(args.appearance_dir.resolve()),
        },
        "val_ratio": args.val_ratio,
        "seed": args.seed,
        "source_rows": {
            "internal_components": internal_source_rows,
            "appearance": appearance_source_rows,
        },
        "combined_rows": len(rows),
        "train_rows": len(train),
        "val_rows": len(val),
        "unique_image_hashes": len(hash_counter),
        "duplicate_image_hash_groups": len(duplicate_hash_groups),
        "cross_task_duplicate_image_groups": cross_task_groups,
        "train_val_hash_overlap": len(train_hashes & val_hashes),
        "rows_by_task": dict(task_counter(rows)),
        "train_rows_by_task": dict(task_counter(train)),
        "val_rows_by_task": dict(task_counter(val)),
        "verdict_by_task": verdict_by_task(rows),
        "train_verdict_by_task": verdict_by_task(train),
        "val_verdict_by_task": verdict_by_task(val),
        "defect_by_task": defect_by_task(rows),
        "notes": [
            "This is a combined multi-task SFT dataset built on top of the previous internal-component dataset plus the new appearance dataset.",
            "Rows keep their original task-specific prompts; internal-component and appearance labels are not collapsed into one label space.",
            "Train/val is split by image hash group so duplicate images cannot appear across splits.",
        ],
    }


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# 室内消火栓内部组件 + 外观合并训练数据报告",
        "",
        "## 处理结果",
        "",
        f"- 内部组件源样本：{summary['source_rows']['internal_components']}",
        f"- 外观源样本：{summary['source_rows']['appearance']}",
        f"- 合并后样本：{summary['combined_rows']}",
        f"- train={summary['train_rows']}，val={summary['val_rows']}",
        f"- 唯一图片哈希：{summary['unique_image_hashes']}",
        f"- train/val 图片哈希交叉：{summary['train_val_hash_overlap']}",
        "",
        "## 按任务分布",
        "",
        json.dumps(summary["rows_by_task"], ensure_ascii=False, indent=2),
        "",
        "## 按任务结论分布",
        "",
        json.dumps(summary["verdict_by_task"], ensure_ascii=False, indent=2),
        "",
        "## 说明",
        "",
        "1. 这一版是在上一版内部组件数据基础上追加外观数据生成的合并训练集。",
        "2. 内部组件和外观仍保留不同 prompt，避免把两个任务的标签强行混成一个输出空间。",
        "3. 如果只训练外观任务，仍应使用外观专项数据集；如果希望同一个模型同时学两类巡检问题，使用本合并版。",
        "",
    ]
    return "\n".join(lines)


def ensure_outputs(args: argparse.Namespace) -> dict[str, Path]:
    outputs = {
        "all": args.output_dir / args.all_name,
        "train": args.output_dir / args.train_name,
        "val": args.output_dir / args.val_name,
        "summary": args.output_dir / args.summary_name,
        "report": args.output_dir / args.report_name,
    }
    if args.dry_run:
        return outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing = [path for path in outputs.values() if path.exists()]
    if existing and not args.overwrite:
        joined = "\n".join(f"- {path}" for path in existing)
        raise FileExistsError(f"Output files already exist. Use --overwrite to replace:\n{joined}")
    return outputs


def main() -> int:
    args = parse_args()
    internal_rows = read_jsonl(args.internal_dir / args.input_name)
    appearance_rows = read_jsonl(args.appearance_dir / args.input_name)

    rows: list[dict[str, Any]] = []
    idx = 1
    for source_row in internal_rows:
        rows.append(
            normalize_row(
                source_row,
                task="internal_components",
                source_dataset=args.internal_dir,
                idx=idx,
                id_prefix=args.id_prefix,
            )
        )
        idx += 1
    for source_row in appearance_rows:
        rows.append(
            normalize_row(
                source_row,
                task="appearance",
                source_dataset=args.appearance_dir,
                idx=idx,
                id_prefix=args.id_prefix,
            )
        )
        idx += 1

    train, val = split_by_image_hash(rows, args.val_ratio, args.seed)
    outputs = ensure_outputs(args)
    summary = build_summary(
        args=args,
        rows=rows,
        train=train,
        val=val,
        internal_source_rows=len(internal_rows),
        appearance_source_rows=len(appearance_rows),
        outputs=outputs,
    )

    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    write_jsonl(outputs["all"], rows)
    write_jsonl(outputs["train"], train)
    write_jsonl(outputs["val"], val)
    write_json(outputs["summary"], summary)
    outputs["report"].write_text(render_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_TRAIN = "/opt/datasets/fire-inspection/training_data/20260630_hydrant_auto_visible_reasoning_v5_ultra_strict_cleaned/train.jsonl"
DEFAULT_HIGH_CONF = "/opt/datasets/fire-inspection/training_data/20260630_hydrant_auto_visible_reasoning_v5_ultra_strict_cleaned/val.jsonl"
DEFAULT_CANDIDATES = "/opt/datasets/fire-inspection/training_data/20260630_hydrant_auto_visible_reasoning_v5_strict_cleaned/all.jsonl"
DEFAULT_OUTPUT = "/opt/datasets/fire-inspection/training_data/20260711_hydrant_rl_frozen_eval_v1"


def read_jsonl(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def key(row: dict[str, Any]) -> str:
    meta = row.get("meta") or {}
    return meta.get("image_sha1") or (row.get("images") or [""])[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-jsonl", default=DEFAULT_TRAIN)
    parser.add_argument("--high-confidence-jsonl", default=DEFAULT_HIGH_CONF)
    parser.add_argument("--candidate-jsonl", default=DEFAULT_CANDIDATES)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    out = Path(args.output_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Frozen directory already exists and is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)

    train_hashes = {key(row) for row in read_jsonl(args.train_jsonl)}
    high_conf_hashes = {key(row) for row in read_jsonl(args.high_confidence_jsonl)}
    candidates = read_jsonl(args.candidate_jsonl)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in candidates:
        image_key = key(row)
        if not image_key or image_key in train_hashes or image_key in seen:
            continue
        images = row.get("images") or []
        if not images or not Path(images[0]).is_file():
            continue
        copied = dict(row)
        meta = dict(copied.get("meta") or {})
        meta.update(
            {
                "frozen_eval_version": "20260711_hydrant_rl_frozen_eval_v1",
                "frozen_date": str(date.today()),
                "review_tier": "ultra_strict_pass" if image_key in high_conf_hashes else "strict_cleaned_pending_human_signoff",
                "excluded_from_rl_train_by_sha1": True,
            }
        )
        copied["meta"] = meta
        selected.append(copied)
        seen.add(image_key)

    eval_path = out / "eval.jsonl"
    with eval_path.open("w", encoding="utf-8") as handle:
        for row in selected:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    payload = eval_path.read_bytes()
    sha256 = hashlib.sha256(payload).hexdigest()
    verdicts = Counter(row["meta"].get("verdict") for row in selected)
    tasks = Counter(row["meta"].get("task") for row in selected)
    tiers = Counter(row["meta"].get("review_tier") for row in selected)
    labels = Counter(label for row in selected for label in row["meta"].get("defect_labels", []))
    manifest = {
        "version": "20260711_hydrant_rl_frozen_eval_v1",
        "created": str(date.today()),
        "frozen": True,
        "rows": len(selected),
        "sha256": sha256,
        "eval_jsonl": str(eval_path),
        "rl_train_exclusion_source": args.train_jsonl,
        "candidate_source": args.candidate_jsonl,
        "high_confidence_source": args.high_confidence_jsonl,
        "train_sha1_overlap": len(seen & train_hashes),
        "unique_image_keys": len(seen),
        "distribution": {
            "verdict": dict(verdicts),
            "task": dict(tasks),
            "review_tier": dict(tiers),
            "labels": dict(labels),
        },
        "warning": "strict_cleaned_pending_human_signoff rows are frozen for reproducibility but are not represented as manually approved",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "SHA256SUMS").write_text(f"{sha256}  eval.jsonl\n", encoding="utf-8")
    report = [
        "# 冻结评测集 v1",
        "",
        f"- 样本数：{len(selected)}",
        f"- SHA1 与 RL 训练集重叠：{len(seen & train_hashes)}",
        f"- eval.jsonl SHA256：`{sha256}`",
        f"- 高置信 ultra-strict：{tiers.get('ultra_strict_pass', 0)}",
        f"- strict-cleaned 待人工签字：{tiers.get('strict_cleaned_pending_human_signoff', 0)}",
        "",
        "内容已经冻结。任何人工修订必须建立 v2，不允许原地修改 v1。",
    ]
    (out / "README.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

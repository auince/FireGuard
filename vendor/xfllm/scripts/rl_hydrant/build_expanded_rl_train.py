#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_ULTRA = "/opt/datasets/fire-inspection/training_data/20260630_hydrant_auto_visible_reasoning_v5_ultra_strict_cleaned/train.jsonl"
DEFAULT_RULE = "/opt/datasets/fire-inspection/training_data/20260630_hydrant_auto_visible_reasoning_v5_rule_cleaned/all.jsonl"
DEFAULT_FROZEN = "/opt/datasets/fire-inspection/training_data/20260711_hydrant_rl_frozen_eval_v1/eval.jsonl"
DEFAULT_OUTPUT = "/opt/datasets/fire-inspection/training_data/20260712_hydrant_rl_expanded_v2"


def read_jsonl(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def key(row: dict[str, Any]) -> str:
    meta = row.get("meta") or {}
    return meta.get("image_sha1") or (row.get("images") or [""])[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ultra-train", default=DEFAULT_ULTRA)
    parser.add_argument("--rule-cleaned", default=DEFAULT_RULE)
    parser.add_argument("--frozen-eval", default=DEFAULT_FROZEN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    out = Path(args.output_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Output already exists and is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)

    ultra_hashes = {key(row) for row in read_jsonl(args.ultra_train)}
    frozen_hashes = {key(row) for row in read_jsonl(args.frozen_eval)}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    missing_images = 0
    for row in read_jsonl(args.rule_cleaned):
        image_key = key(row)
        images = row.get("images") or []
        if not image_key or image_key in frozen_hashes or image_key in seen:
            continue
        if not images or not Path(images[0]).is_file():
            missing_images += 1
            continue
        copied = dict(row)
        meta = dict(copied.get("meta") or {})
        meta.update(
            {
                "rl_train_version": "20260712_hydrant_rl_expanded_v2",
                "rl_train_tier": "ultra_strict_train" if image_key in ultra_hashes else "rule_cleaned_extra",
                "frozen_eval_excluded_by_sha1": True,
            }
        )
        copied["meta"] = meta
        rows.append(copied)
        seen.add(image_key)

    train_path = out / "train.jsonl"
    with train_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    sha256 = hashlib.sha256(train_path.read_bytes()).hexdigest()
    tiers = Counter(row["meta"]["rl_train_tier"] for row in rows)
    verdicts = Counter(row["meta"].get("verdict") for row in rows)
    tasks = Counter(row["meta"].get("task") for row in rows)
    labels = Counter(label for row in rows for label in row["meta"].get("defect_labels", []))
    manifest = {
        "version": "20260712_hydrant_rl_expanded_v2",
        "created": str(date.today()),
        "rows": len(rows),
        "unique_image_keys": len(seen),
        "frozen_eval_overlap": len(seen & frozen_hashes),
        "missing_images": missing_images,
        "sha256": sha256,
        "train_jsonl": str(train_path),
        "sources": {
            "ultra_train": args.ultra_train,
            "rule_cleaned": args.rule_cleaned,
            "frozen_eval_exclusion": args.frozen_eval,
        },
        "distribution": {
            "tier": dict(tiers),
            "verdict": dict(verdicts),
            "task": dict(tasks),
            "labels": dict(labels),
        },
        "notes": [
            "All 244 frozen-eval image hashes are excluded.",
            "The 566 added rows retain original JSON/box metadata where available.",
            "Training-time class balancing and compliant oversampling are performed by the trainer, not by duplicating this file.",
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "SHA256SUMS").write_text(f"{sha256}  train.jsonl\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

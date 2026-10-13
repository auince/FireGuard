#!/usr/bin/env python3
"""Convert the leakage-safe hydrant split to verl multimodal parquet."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from datasets import Dataset

from build_hydrant_preference_pairs import COMPACT_PROMPT, message_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-rl",
        default="/opt/datasets/fire-inspection/training_data/20260712_hydrant_rl_expanded_v2/train.jsonl",
    )
    parser.add_argument(
        "--preference-train",
        default="/opt/datasets/fire-inspection/training_data/20260722_hydrant_preference_v2_verbose/train.jsonl",
    )
    parser.add_argument(
        "--preference-validation",
        default="/opt/datasets/fire-inspection/training_data/20260722_hydrant_preference_v2_verbose/validation.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        default="/opt/datasets/fire-inspection/training_data/20260722_hydrant_verl_rl_v2_verbose",
    )
    parser.add_argument("--max-image-pixels", type=int, default=131072)
    parser.add_argument("--prompt-style", choices=["source", "compact"], default="source")
    return parser.parse_args()


def read_jsonl(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def preference_sha1s(path: str) -> set[str]:
    return {row["meta"]["image_sha1"] for row in read_jsonl(path)}


def normalize_scope(value: str) -> str:
    if value in {"appearance", "箱体外观"}:
        return "appearance"
    if value in {"internal", "internal_components", "内部组件"}:
        return "internal_components"
    raise ValueError(f"unsupported scope: {value!r}")


def convert_row(
    source: dict[str, Any], split: str, max_image_pixels: int, prompt_style: str
) -> dict[str, Any]:
    meta = source.get("meta") or {}
    images = source.get("images") or []
    if len(images) != 1:
        raise ValueError(f"{source.get('id')}: expected one image")
    if not meta.get("frozen_eval_excluded_by_sha1"):
        raise ValueError(f"{source.get('id')}: row is not certified outside frozen eval")
    scope = normalize_scope(str(meta.get("task") or ""))
    labels = list(dict.fromkeys(meta.get("defect_labels") or []))
    verdict = str(meta.get("verdict") or ("不合规" if labels else "合规"))
    sha1 = str(meta["image_sha1"])
    ground_truth = {
        "gold_scope": scope,
        "gold_verdict": verdict,
        "gold_labels": labels,
    }
    prompt_text = message_text(source, "user") if prompt_style == "source" else COMPACT_PROMPT
    return {
        "data_source": "hydrant_reward_v41",
        # RLHFDataset converts <image> into a multimodal content block.
        "prompt": [{"role": "user", "content": f"<image>\n{prompt_text}"}],
        # qwen_vl_utils.fetch_image accepts this file URI dictionary and applies
        # max_pixels before both HF actor and rollout preprocessing.
        "images": [{"image": f"file://{images[0]}", "max_pixels": max_image_pixels}],
        "ability": "hydrant_multilabel_inspection",
        "reward_model": {"style": "rule", "ground_truth": json.dumps(ground_truth, ensure_ascii=False)},
        "extra_info": {
            "split": split,
            "id": source.get("id"),
            "image_sha1": sha1,
            "scope": scope,
        },
    }


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    truths = [json.loads(row["reward_model"]["ground_truth"]) for row in rows]
    return {
        "rows": len(rows),
        "unique_images": len({row["extra_info"]["image_sha1"] for row in rows}),
        "scopes": dict(Counter(truth["gold_scope"] for truth in truths)),
        "verdicts": dict(Counter(truth["gold_verdict"] for truth in truths)),
        "labels": dict(Counter(label for truth in truths for label in truth["gold_labels"])),
    }


def main() -> None:
    args = parse_args()
    train_sha1 = preference_sha1s(args.preference_train)
    val_sha1 = preference_sha1s(args.preference_validation)
    if train_sha1 & val_sha1:
        raise ValueError("preference train/validation SHA1 overlap")
    source_by_sha1 = {}
    for row in read_jsonl(args.source_rl):
        sha1 = (row.get("meta") or {}).get("image_sha1")
        if sha1 in source_by_sha1:
            raise ValueError(f"duplicate source image_sha1: {sha1}")
        source_by_sha1[sha1] = row
    missing = (train_sha1 | val_sha1) - set(source_by_sha1)
    if missing:
        raise ValueError(f"{len(missing)} preference images are missing from source RL data")

    train = [
        convert_row(source_by_sha1[sha1], "train", args.max_image_pixels, args.prompt_style)
        for sha1 in sorted(train_sha1)
    ]
    validation = [
        convert_row(source_by_sha1[sha1], "validation", args.max_image_pixels, args.prompt_style)
        for sha1 in sorted(val_sha1)
    ]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    Dataset.from_list(train).to_parquet(output_dir / "train.parquet")
    Dataset.from_list(validation).to_parquet(output_dir / "validation.parquet")
    audit = {
        "source_rl": args.source_rl,
        "split_source": "preference image_sha1 split",
        "prompt_style": args.prompt_style,
        "max_image_pixels": args.max_image_pixels,
        "frozen_eval_included": False,
        "train_validation_overlap": 0,
        "train": summary(train),
        "validation": summary(validation),
    }
    (output_dir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

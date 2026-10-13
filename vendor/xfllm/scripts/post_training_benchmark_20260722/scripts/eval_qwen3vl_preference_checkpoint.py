#!/usr/bin/env python3
"""Evaluate a preference LoRA on top of the *merged SFT* Qwen3-VL policy.

Loading the DPO/IPO/SimPO adapter directly on the original base model is
incorrect: the preference adapter was trained relative to the SFT-merged
policy.  This evaluator preserves that composition explicitly.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

HYDRANT_EVAL_DIR = Path("/opt/datasets/fire-inspection/scripts/rl_hydrant")
sys.path.insert(0, str(HYDRANT_EVAL_DIR))
from eval_checkpoint_batched import evaluate, extended_metrics, load_rows  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/opt/models/qwen3-vl-4b")
    parser.add_argument(
        "--sft-adapter",
        default=(
            "/opt/xfagent/artifacts/trl/qwen3vl4b_hydrant_sft_grpo_v41_full_20260717/"
            "sft_model/checkpoint-400"
        ),
    )
    parser.add_argument("--preference-adapter", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--eval-jsonl",
        default=(
            "/opt/datasets/fire-inspection/training_data/"
            "20260711_hydrant_rl_frozen_eval_v1/eval.jsonl"
        ),
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    rows = load_rows(args.eval_jsonl)
    if args.limit > 0:
        rows = rows[: args.limit]

    processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    base = Qwen3VLForConditionalGeneration.from_pretrained(
        args.model,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation="sdpa",
    )
    sft_policy = PeftModel.from_pretrained(base, args.sft_adapter, is_trainable=False).merge_and_unload()
    model = PeftModel.from_pretrained(sft_policy, args.preference_adapter, is_trainable=False)

    results = evaluate(
        model,
        processor,
        rows,
        batch_size=args.batch_size,
        max_new_tokens=args.max_new_tokens,
        compact_prompt=True,
    )
    high_conf = [row for row in results if row["review_tier"] == "ultra_strict_pass"]
    payload = {
        "name": args.name,
        "model": args.model,
        "sft_adapter": args.sft_adapter,
        "preference_adapter": args.preference_adapter,
        "eval_jsonl": args.eval_jsonl,
        "all": {"metrics": extended_metrics(results), "results": results},
        "ultra_strict_pass": {
            "metrics": extended_metrics(high_conf),
            "rows": len(high_conf),
        },
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{args.name}.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "name": args.name,
                "all": payload["all"]["metrics"],
                "ultra": payload["ultra_strict_pass"]["metrics"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

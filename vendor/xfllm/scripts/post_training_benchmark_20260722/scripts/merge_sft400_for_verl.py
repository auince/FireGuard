#!/usr/bin/env python3
"""Merge the selected SFT LoRA into Qwen3-VL for verl/vLLM training."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="/opt/models/qwen3-vl-4b")
    parser.add_argument(
        "--adapter",
        default=(
            "/opt/xfagent/artifacts/trl/qwen3vl4b_hydrant_sft_grpo_v41_full_20260717/"
            "sft_model/checkpoint-400"
        ),
    )
    parser.add_argument(
        "--output",
        default=(
            "/opt/xfagent/artifacts/post_training_benchmark/qwen3vl_hydrant_20260722/"
            "sft400_merged_hf"
        ),
    )
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    base = Qwen3VLForConditionalGeneration.from_pretrained(
        args.base,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        device_map="cpu",
        attn_implementation="sdpa",
    )
    merged = PeftModel.from_pretrained(base, args.adapter, is_trainable=False).merge_and_unload()
    merged.save_pretrained(output, safe_serialization=True, max_shard_size="4GB")
    AutoProcessor.from_pretrained(args.base, trust_remote_code=True).save_pretrained(output)
    manifest = {
        "base": args.base,
        "adapter": args.adapter,
        "output": args.output,
        "dtype": "bfloat16",
        "purpose": "verl PPO/GRPO actor, reference and critic initialization",
    }
    (output / "merge_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

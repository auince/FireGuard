#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
from eval_qwen3vl_hydrant_lora_20260629 import (  # noqa: E402
    get_gold_text,
    parse_answer,
    run_one,
    score_results,
)


def load_stratified(path: str, per_group: int, seed: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            gold = parse_answer(get_gold_text(row))
            groups[(gold["scope"], gold["verdict"])].append(row)
    rng = random.Random(seed)
    selected: list[dict[str, Any]] = []
    for key in sorted(groups):
        rng.shuffle(groups[key])
        selected.extend(groups[key][:per_group])
    rng.shuffle(selected)
    return selected


def evaluate(model, processor, rows: list[dict[str, Any]], max_new_tokens: int) -> dict[str, Any]:
    results = []
    model.eval()
    for index, row in enumerate(rows, 1):
        gold = parse_answer(get_gold_text(row))
        error = None
        try:
            text = run_one(model, processor, row, max_new_tokens)
        except Exception as exc:  # keep the complete evaluation report
            text = ""
            error = repr(exc)
        pred = parse_answer(text)
        record = {"id": row.get("id"), "gold": gold, "pred": pred}
        if error:
            record["error"] = error
        results.append(record)
        print(f"{index}/{len(rows)} {row.get('id')} scope={gold['scope'] == pred['scope']} verdict={gold['verdict'] == pred['verdict']} labels={set(gold['labels']) == set(pred['labels'])}", flush=True)
    return {"metrics": score_results(results), "results": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/opt/models/qwen3-vl-4b")
    parser.add_argument("--adapter", required=True)
    parser.add_argument(
        "--eval-jsonl",
        default="/opt/datasets/fire-inspection/training_data/20260630_hydrant_auto_visible_reasoning_v5_ultra_strict_cleaned/val.jsonl",
    )
    parser.add_argument("--output", default="/opt/xfagent/artifacts/trl/hydrant_qwen3vl4b_grpo_pilot10_ab.json")
    parser.add_argument("--per-group", type=int, default=5)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20260711)
    args = parser.parse_args()

    rows = load_stratified(args.eval_jsonl, args.per_group, args.seed)
    processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        args.model,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation="sdpa",
    )
    print("Evaluating base model", flush=True)
    base = evaluate(model, processor, rows, args.max_new_tokens)

    gc.collect()
    torch.cuda.empty_cache()
    print("Evaluating GRPO adapter", flush=True)
    adapted_model = PeftModel.from_pretrained(model, args.adapter)
    adapted = evaluate(adapted_model, processor, rows, args.max_new_tokens)

    payload = {
        "model": args.model,
        "adapter": args.adapter,
        "eval_jsonl": args.eval_jsonl,
        "selection": {"per_group": args.per_group, "seed": args.seed, "rows": len(rows)},
        "base": base,
        "grpo": adapted,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"base": base["metrics"], "grpo": adapted["metrics"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

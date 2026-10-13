#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from PIL import Image
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
from eval_qwen3vl_hydrant_lora_20260629 import (  # noqa: E402
    ALL_LABELS,
    clean_messages,
    get_gold_text,
    parse_answer,
    score_results,
)

COMPACT_PROMPT = """你是消防设施巡检助手。只根据图片中清晰可见的内容检查室内消火栓，不得把遮挡、反光、模糊或画面外的项目推测为异常。

检查范围只能选：内部组件、箱体外观、无法确定。
内部组件标签只能选：室内消火栓手轮缺失；室内消火栓栓口方向错误；室内消火栓无消防水带；室内消火栓无消防水枪；室内消火栓消防接口缺失；消防软管卷盘供水管道折弯严重；室内消火栓无箱体；室内消火栓箱锈蚀；室内消火栓箱门缺失。
箱体外观标签只能选：室内消火栓箱明显部位未采用耐久性文字或图形标注操作说明；室内消火栓箱门上未标注“消火栓”和英文“FIRE HYDRANT”字样；室内消火栓箱体无铭牌；室内消火栓箱门标识模糊；室内消火栓箱体铭牌模糊；室内消火栓箱门为玻璃门；室内消火栓箱体或箱门被物品遮挡。

有隐患标签则结论为“不合规”，无隐患标签则为“合规”；证据不足时写“无法判断”。不要输出思维链。请在 220 个中文词以内，严格按以下顺序输出：
检查范围：...
结论：...
隐患标签：多个用“；”分隔，无则写“无”
可见证据：用 1 至 3 句说明可见依据和看不清的项目。""".strip()


def load_rows(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def open_image(path: str) -> Image.Image:
    image = Image.open(path).convert("RGB")
    max_area = 131_072
    area = image.width * image.height
    if area > max_area:
        scale = (max_area / float(area)) ** 0.5
        size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        image = image.resize(size, Image.Resampling.LANCZOS)
    return image


def extended_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = score_results(results)
    tp = fp = fn = 0
    per_label: dict[str, dict[str, int | float]] = {}
    for label in ALL_LABELS:
        ltp = sum(label in row["gold"]["labels"] and label in row["pred"]["labels"] for row in results)
        lfp = sum(label not in row["gold"]["labels"] and label in row["pred"]["labels"] for row in results)
        lfn = sum(label in row["gold"]["labels"] and label not in row["pred"]["labels"] for row in results)
        precision = ltp / (ltp + lfp) if ltp + lfp else 0.0
        recall = ltp / (ltp + lfn) if ltp + lfn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_label[label] = {"tp": ltp, "fp": lfp, "fn": lfn, "precision": precision, "recall": recall, "f1": f1}
        tp += ltp
        fp += lfp
        fn += lfn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    micro_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    present = [v["f1"] for v in per_label.values() if v["tp"] + v["fn"] > 0]
    compliant = [row for row in results if not row["gold"]["labels"]]
    metrics.update(
        {
            "label_micro_precision": precision,
            "label_micro_recall": recall,
            "label_micro_f1": micro_f1,
            "label_macro_f1_present": sum(present) / len(present) if present else 0.0,
            "compliant_false_positive_rate": (
                sum(bool(row["pred"]["labels"]) for row in compliant) / len(compliant) if compliant else 0.0
            ),
            "per_label": per_label,
        }
    )
    return metrics


def prompt_messages(row: dict[str, Any], compact_prompt: bool) -> list[dict[str, Any]]:
    messages = clean_messages(row["messages"], generation=True)
    if not compact_prompt:
        return messages
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = COMPACT_PROMPT
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    item["text"] = COMPACT_PROMPT
                    break
            else:
                content.append({"type": "text", "text": COMPACT_PROMPT})
        break
    return messages


def evaluate(
    model,
    processor,
    rows: list[dict[str, Any]],
    batch_size: int,
    max_new_tokens: int,
    compact_prompt: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    model.eval()
    processor.tokenizer.padding_side = "left"
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        images = [open_image(row["images"][0]) for row in batch]
        prompts = [
            processor.apply_chat_template(
                prompt_messages(row, compact_prompt), tokenize=False, add_generation_prompt=True
            )
            for row in batch
        ]
        inputs = processor(
            text=prompts,
            images=images,
            return_tensors="pt",
            padding=True,
            add_special_tokens=False,
        )
        inputs = {key: value.to(model.device) if hasattr(value, "to") else value for key, value in inputs.items()}
        with torch.inference_mode():
            output = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                num_beams=1,
                temperature=None,
                top_p=None,
                use_cache=True,
            )
        generated = output[:, inputs["input_ids"].shape[1] :]
        texts = processor.batch_decode(generated, skip_special_tokens=True, clean_up_tokenization_spaces=False)
        for row, text in zip(batch, texts):
            results.append(
                {
                    "id": row.get("id"),
                    "review_tier": (row.get("meta") or {}).get("review_tier"),
                    "image": row["images"][0],
                    "gold": parse_answer(get_gold_text(row)),
                    "pred": parse_answer(text.strip()),
                }
            )
        print(f"{min(start + len(batch), len(rows))}/{len(rows)}", flush=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/opt/models/qwen3-vl-4b")
    parser.add_argument("--adapter")
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--eval-jsonl",
        default="/opt/datasets/fire-inspection/training_data/20260711_hydrant_rl_frozen_eval_v1/eval.jsonl",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--compact-prompt", action="store_true")
    args = parser.parse_args()

    rows = load_rows(args.eval_jsonl)
    if args.limit > 0:
        rows = rows[: args.limit]
    processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        args.model,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation="sdpa",
    )
    if args.adapter:
        model = PeftModel.from_pretrained(model, args.adapter)
    results = evaluate(model, processor, rows, args.batch_size, args.max_new_tokens, args.compact_prompt)
    high_conf = [row for row in results if row["review_tier"] == "ultra_strict_pass"]
    payload = {
        "name": args.name,
        "model": args.model,
        "adapter": args.adapter,
        "eval_jsonl": args.eval_jsonl,
        "compact_prompt": args.compact_prompt,
        "all": {"metrics": extended_metrics(results), "results": results},
        "ultra_strict_pass": {"metrics": extended_metrics(high_conf), "rows": len(high_conf)},
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{args.name}.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"name": args.name, "all": payload["all"]["metrics"], "ultra": payload["ultra_strict_pass"]["metrics"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import os
import re
from pathlib import Path
from typing import Any

import torch
from PIL import Image
from peft import PeftModel
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

INTERNAL_LABELS = [
    "室内消火栓手轮缺失",
    "室内消火栓栓口方向错误",
    "室内消火栓无消防水带",
    "室内消火栓无消防水枪",
    "室内消火栓消防接口缺失",
    "消防软管卷盘供水管道折弯严重",
    "室内消火栓无箱体",
    "室内消火栓箱锈蚀",
    "室内消火栓箱门缺失",
]
APPEARANCE_LABELS = [
    "室内消火栓箱明显部位未采用耐久性文字或图形标注操作说明",
    "室内消火栓箱门上未标注“消火栓”和英文“FIRE HYDRANT”字样",
    "室内消火栓箱体无铭牌",
    "室内消火栓箱门标识模糊",
    "室内消火栓箱体铭牌模糊",
    "室内消火栓箱门为玻璃门",
    "室内消火栓箱体或箱门被物品遮挡",
]
ALL_LABELS = INTERNAL_LABELS + APPEARANCE_LABELS


def clean_messages(messages: list[dict[str, Any]], *, generation: bool) -> list[dict[str, Any]]:
    if generation:
        messages = [m for m in messages if m.get("role") != "assistant"]
    cleaned = []
    for msg in messages:
        content = []
        for item in msg.get("content", []):
            if isinstance(item, dict):
                content.append({k: v for k, v in item.items() if v is not None})
            else:
                content.append(item)
        cleaned.append({"role": msg.get("role"), "content": content})
    return cleaned


def get_gold_text(row: dict[str, Any]) -> str:
    for msg in row.get("messages", []):
        if msg.get("role") == "assistant":
            parts = msg.get("content", [])
            if isinstance(parts, str):
                return parts
            return "\n".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
    return ""


def field_after(text: str, name: str) -> str:
    m = re.search(rf"{re.escape(name)}\s*[:：]\s*(.*)", text)
    return m.group(1).strip() if m else ""


def parse_scope(text: str) -> str:
    val = field_after(text, "检查范围")
    if "无法" in val:
        return "unknown"
    if "外观" in val or "箱体" in val:
        return "appearance"
    if "内部" in val or "组件" in val:
        return "internal"
    # Fallback from whole answer.
    head = text[:200]
    if "箱体外观" in head or "箱门" in head:
        return "appearance"
    if "内部组件" in head or "手轮" in head or "水带" in head:
        return "internal"
    return "unknown"


def parse_verdict(text: str) -> str:
    val = field_after(text, "结论")
    if "无法" in val:
        return "unknown"
    if "不合规" in val:
        return "non_compliant"
    if "合规" in val:
        return "compliant"
    # order matters: 不合规 contains 合规
    if "不合规" in text:
        return "non_compliant"
    if "合规" in text:
        return "compliant"
    return "unknown"


def parse_labels(text: str) -> list[str]:
    line = field_after(text, "隐患标签")
    if not line:
        line = text
    if "无" == line.strip(" 。.；;，,"):
        return []
    found = []
    for label in ALL_LABELS:
        if label in line or label in text:
            found.append(label)
    return found


def parse_answer(text: str) -> dict[str, Any]:
    return {
        "scope": parse_scope(text),
        "verdict": parse_verdict(text),
        "labels": parse_labels(text),
        "text": text,
    }


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def score_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results)
    scope_ok = sum(r["gold"]["scope"] == r["pred"]["scope"] for r in results)
    verdict_ok = sum(r["gold"]["verdict"] == r["pred"]["verdict"] for r in results)
    labels_ok = sum(set(r["gold"]["labels"]) == set(r["pred"]["labels"]) for r in results)
    all_ok = sum(
        r["gold"]["scope"] == r["pred"]["scope"]
        and r["gold"]["verdict"] == r["pred"]["verdict"]
        and set(r["gold"]["labels"]) == set(r["pred"]["labels"])
        for r in results
    )

    gold_pos = [r for r in results if r["gold"]["labels"]]
    gold_neg = [r for r in results if not r["gold"]["labels"]]
    tp = sum(bool(r["gold"]["labels"]) and bool(r["pred"]["labels"]) for r in results)
    fp = sum((not r["gold"]["labels"]) and bool(r["pred"]["labels"]) for r in results)
    fn = sum(bool(r["gold"]["labels"]) and (not r["pred"]["labels"]) for r in results)
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = safe_div(2 * precision * recall, precision + recall)

    by_task = {}
    for task in ["internal", "appearance", "unknown"]:
        subset = [r for r in results if r["gold"]["scope"] == task]
        if not subset:
            continue
        by_task[task] = {
            "rows": len(subset),
            "scope_acc": safe_div(sum(r["gold"]["scope"] == r["pred"]["scope"] for r in subset), len(subset)),
            "verdict_acc": safe_div(sum(r["gold"]["verdict"] == r["pred"]["verdict"] for r in subset), len(subset)),
            "label_exact_acc": safe_div(sum(set(r["gold"]["labels"]) == set(r["pred"]["labels"]) for r in subset), len(subset)),
        }

    return {
        "rows": n,
        "scope_acc": safe_div(scope_ok, n),
        "verdict_acc": safe_div(verdict_ok, n),
        "label_exact_acc": safe_div(labels_ok, n),
        "all_exact_acc": safe_div(all_ok, n),
        "positive_detection": {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn},
        "gold_positive_rows": len(gold_pos),
        "gold_negative_rows": len(gold_neg),
        "by_task": by_task,
    }


def load_rows(path: str, limit: int, offset: int) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < offset:
                continue
            if len(rows) >= limit:
                break
            rows.append(json.loads(line))
    return rows


def run_one(model, processor, row: dict[str, Any], max_new_tokens: int) -> str:
    image_path = row["images"][0]
    img = Image.open(image_path).convert("RGB")
    max_area = 131072
    area = img.width * img.height
    if area > max_area:
        scale = (max_area / float(area)) ** 0.5
        new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
    msgs = clean_messages(row["messages"], generation=True)
    text = processor.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=[img], max_pixels=262144, return_tensors="pt", padding=True)
    inputs = {k: (v.to(model.device) if hasattr(v, "to") else v) for k, v in inputs.items()}
    with torch.inference_mode():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            num_beams=1,
            temperature=None,
            top_p=None,
            use_cache=True,
        )
    gen = out[:, inputs["input_ids"].shape[1]:]
    return processor.batch_decode(gen, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0].strip()


def evaluate_adapter(args: argparse.Namespace, adapter: str, name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    print(f"[eval] loading base: {args.base_model}", flush=True)
    processor = AutoProcessor.from_pretrained(args.base_model, trust_remote_code=True)
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        args.base_model,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation="eager",
    )
    print(f"[eval] loading adapter: {adapter}", flush=True)
    model = PeftModel.from_pretrained(model, adapter)
    model.eval()

    results = []
    for idx, row in enumerate(rows, 1):
        gold_text = get_gold_text(row)
        gold = parse_answer(gold_text)
        try:
            pred_text = run_one(model, processor, row, args.max_new_tokens)
            error = None
        except Exception as exc:
            pred_text = ""
            error = repr(exc)
            print(f"[eval] error {name} row {idx}: {error}", flush=True)
        pred = parse_answer(pred_text)
        rec = {
            "id": row.get("id", f"row_{idx}"),
            "task": gold["scope"],
            "image": row["images"][0],
            "gold": gold,
            "pred": pred,
            "ok": {
                "scope": gold["scope"] == pred["scope"],
                "verdict": gold["verdict"] == pred["verdict"],
                "labels": set(gold["labels"]) == set(pred["labels"]),
            },
        }
        if error:
            rec["error"] = error
        results.append(rec)
        print(f"[eval] {name} {idx}/{len(rows)} {rec['id']} scope={rec['ok']['scope']} verdict={rec['ok']['verdict']} labels={rec['ok']['labels']}", flush=True)

    payload = {"name": name, "adapter": adapter, "results": results, "metrics": score_results(results)}
    out_file = Path(args.output_dir) / f"{name}.json"
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return payload


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-model", default="/opt/models/Qwen3-VL-8B-Instruct")
    p.add_argument("--eval-jsonl", default="/opt/datasets/fire-inspection/training_data/20260627_hydrant_auto_visible_reasoning_v3/val.jsonl")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--adapter", action="append", required=True, help="name=path")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=75)
    p.add_argument("--max-new-tokens", type=int, default=700)
    args = p.parse_args()

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    rows = load_rows(args.eval_jsonl, args.limit, args.offset)
    models = []
    for spec in args.adapter:
        if "=" in spec:
            name, path = spec.split("=", 1)
        else:
            path = spec
            name = Path(path).name
        models.append(evaluate_adapter(args, path, name, rows))
    summary = {
        "eval_jsonl": args.eval_jsonl,
        "rows": len(rows),
        "offset": args.offset,
        "prompt_mode": "v3_auto_scope_visible_reasoning",
        "base_model": args.base_model,
        "models": models,
    }
    Path(args.output_dir, "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# v5 checkpoint 评测", "", f"样本：{args.eval_jsonl}", f"数量：{len(rows)}", ""]
    lines.append("| 模型 | 范围准确率 | 结论准确率 | 标签完全正确 | 全部正确 | 正例F1 | TP/FP/FN |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for m in models:
        mt = m["metrics"]
        pd = mt["positive_detection"]
        lines.append(
            f"| {m['name']} | {mt['scope_acc']:.1%} | {mt['verdict_acc']:.1%} | {mt['label_exact_acc']:.1%} | {mt['all_exact_acc']:.1%} | {pd['f1']:.1%} | {pd['tp']}/{pd['fp']}/{pd['fn']} |"
        )
    Path(args.output_dir, "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"output_dir": args.output_dir, "models": [{"name": m["name"], "metrics": m["metrics"]} for m in models]}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

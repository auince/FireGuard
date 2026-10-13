#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_INPUT_DIR = Path(
    "/opt/datasets/fire-inspection/training_data/20260624_hydrant_internal_plus_appearance_cleaned"
)
DEFAULT_OUTPUT_DIR = Path(
    "/opt/datasets/fire-inspection/training_data/20260624_hydrant_internal_plus_appearance_prompt_v2"
)

PROMPT_VERSION = "v2_single_turn_visible_evidence"

TASK_CONFIG = {
    "internal_components": {
        "scope": "室内消火栓箱体内部组件",
        "checklist": "箱体、箱门、手轮、栓口方向、消防水带、消防水枪、消防接口、消防软管卷盘供水管道及可见锈蚀或缺失状态。",
    },
    "appearance": {
        "scope": "室内消火栓箱体外观",
        "checklist": "箱体和箱门外观、箱门上的“消火栓”和英文“FIRE HYDRANT”标识、操作说明、铭牌、箱门材质及遮挡情况。",
    },
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Rewrite mixed hydrant SFT data with a stricter prompt v2 for fine-tuning."
    )
    p.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--all-name", default="all.jsonl")
    p.add_argument("--train-name", default="train.jsonl")
    p.add_argument("--val-name", default="val.jsonl")
    p.add_argument("--summary-name", default="summary.json")
    p.add_argument("--design-name", default="prompt_design.md")
    p.add_argument("--id-prefix", default="xf_hydrant_prompt_v2")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_sentence(value: str) -> str:
    text = normalize_text(value).strip("。；; \n\t")
    return f"{text}。" if text else ""


def normalize_label_list(labels: list[str]) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()
    for label in labels:
        item = normalize_text(label).strip("。；; \n\t")
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    return "；".join(cleaned) if cleaned else "无"


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


def assistant_text(row: dict[str, Any]) -> str:
    for msg in row.get("messages") or []:
        if msg.get("role") != "assistant":
            continue
        for item in msg.get("content") or []:
            if item.get("type") == "text":
                return normalize_text(item.get("text"))
    return ""


def extract_field(text: str, field: str) -> str:
    pattern = rf"^{re.escape(field)}：(.+)$"
    for line in text.splitlines():
        match = re.match(pattern, line.strip())
        if match:
            return normalize_text(match.group(1))
    return ""


def build_prompt(task: str) -> str:
    if task not in TASK_CONFIG:
        raise ValueError(f"unsupported task: {task}")
    config = TASK_CONFIG[task]
    return (
        "你是消防巡检助手。根据图片完成一次室内消火栓巡检判定。\n"
        f"检查范围：{config['scope']}。\n"
        f"检查重点：{config['checklist']}\n"
        "判定规则：\n"
        "1. 只依据图片中清晰可见的内容。\n"
        "2. 不推测被遮挡、反光、画面外或看不清的部件。\n"
        "3. 只判断本次检查范围内的项目，其他问题不要写入隐患标签。\n"
        "4. 可见依据只写短事实，不输出长思维链。\n"
        "输出格式固定为三行：\n"
        "结论：合规/不合规\n"
        "可见依据：一句话说明直接可见的合规要素或异常。\n"
        "隐患标签：多个隐患用“；”分隔；无隐患写“无”。\n"
    )


def build_answer(row: dict[str, Any]) -> str:
    meta = row.get("meta") or {}
    source_answer = assistant_text(row)
    verdict = normalize_text(meta.get("verdict")) or extract_field(source_answer, "结论") or "不合规"
    evidence = extract_field(source_answer, "可见依据")
    if not evidence:
        if verdict == "合规":
            evidence = "未见本次检查范围内的明确异常"
        else:
            labels = meta.get("defect_labels") or []
            evidence = "可见" + "、".join(labels) if labels else "可见本次检查范围内存在异常"
    labels = normalize_label_list(meta.get("defect_labels") or [])
    return (
        f"结论：{verdict}\n"
        f"可见依据：{normalize_sentence(evidence)}\n"
        f"隐患标签：{labels}。"
    )


def transform_row(row: dict[str, Any], new_id: str) -> dict[str, Any]:
    meta = dict(row.get("meta") or {})
    task = meta.get("task")
    if task not in TASK_CONFIG:
        raise ValueError(f"{row.get('id')}: missing or unsupported meta.task: {task}")
    images = row.get("images") or []
    if len(images) != 1:
        raise ValueError(f"{row.get('id')}: expected exactly one image")
    image_path = images[0]
    out = {
        "id": new_id,
        "images": [image_path],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image_path},
                    {"type": "text", "text": build_prompt(task)},
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": build_answer(row)}],
            },
        ],
        "meta": meta,
    }
    out["meta"]["prompt_version"] = PROMPT_VERSION
    out["meta"]["prompt_scope"] = TASK_CONFIG[task]["scope"]
    out["meta"]["prompt_checklist"] = TASK_CONFIG[task]["checklist"]
    out["meta"]["prompt_original_id"] = row.get("id")
    return out


def ensure_outputs(args: argparse.Namespace) -> dict[str, Path]:
    outputs = {
        "all": args.output_dir / args.all_name,
        "train": args.output_dir / args.train_name,
        "val": args.output_dir / args.val_name,
        "summary": args.output_dir / args.summary_name,
        "design": args.output_dir / args.design_name,
    }
    if args.dry_run:
        return outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing = [path for path in outputs.values() if path.exists()]
    if existing and not args.overwrite:
        joined = "\n".join(f"- {path}" for path in existing)
        raise FileExistsError(f"Output files already exist. Use --overwrite to replace:\n{joined}")
    return outputs


def prompt_counter(rows: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        meta = row.get("meta") or {}
        counter[meta.get("task") or "unknown"] += 1
    return counter


def verdict_counter(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counters: dict[str, Counter[str]] = {}
    for row in rows:
        meta = row.get("meta") or {}
        task = meta.get("task") or "unknown"
        counters.setdefault(task, Counter())[meta.get("verdict") or "unknown"] += 1
    return {task: dict(counter) for task, counter in sorted(counters.items())}


def build_summary(
    args: argparse.Namespace,
    all_rows: list[dict[str, Any]],
    train_rows: list[dict[str, Any]],
    val_rows: list[dict[str, Any]],
    outputs: dict[str, Path],
) -> dict[str, Any]:
    train_hashes = {row["meta"]["image_sha1"] for row in train_rows}
    val_hashes = {row["meta"]["image_sha1"] for row in val_rows}
    prompts = set()
    answers = set()
    for row in all_rows:
        user_text = row["messages"][0]["content"][1]["text"]
        answer = row["messages"][1]["content"][0]["text"]
        prompts.add(user_text)
        answers.add(answer)
    return {
        "input_dir": str(args.input_dir.resolve()),
        "output_dir": str(args.output_dir.resolve()),
        "files": {name: str(path) for name, path in outputs.items()},
        "prompt_version": PROMPT_VERSION,
        "rows": len(all_rows),
        "train_rows": len(train_rows),
        "val_rows": len(val_rows),
        "rows_by_task": dict(prompt_counter(all_rows)),
        "train_rows_by_task": dict(prompt_counter(train_rows)),
        "val_rows_by_task": dict(prompt_counter(val_rows)),
        "verdict_by_task": verdict_counter(all_rows),
        "unique_prompts": len(prompts),
        "unique_answers": len(answers),
        "train_val_hash_overlap": len(train_hashes & val_hashes),
        "notes": [
            "Prompt v2 keeps a single-turn image-to-structured-answer format.",
            "Long chain-of-thought is not generated; the assistant target keeps only concise visible evidence.",
            "Multi-turn augmentation is intentionally not included in the primary training split.",
        ],
    }


def build_design_doc(summary: dict[str, Any]) -> str:
    internal_prompt = build_prompt("internal_components")
    appearance_prompt = build_prompt("appearance")
    return (
        "# Hydrant SFT Prompt v2\n\n"
        "## 设计取舍\n\n"
        "- 主训练集使用单轮对话：一张图 + 一个明确检查任务 + 一个结构化回答。\n"
        "- 不加入长思维链。当前标注只有标签和框，没有人工逐步观察过程；强行生成长推理会把弱标签包装成伪推理。\n"
        "- 保留短“可见依据”。这能让模型学习把结论绑定到图中可见部件，同时不会训练它输出冗长分析。\n"
        "- 不默认加入多轮对话。巡检推理的线上形态通常是一次拍照一次判定；多轮样本会让模型学到追问式回答，降低主任务输出稳定性。\n\n"
        "## 内部组件 Prompt\n\n"
        "```text\n"
        f"{internal_prompt}"
        "```\n\n"
        "## 外观 Prompt\n\n"
        "```text\n"
        f"{appearance_prompt}"
        "```\n\n"
        "## 输出格式\n\n"
        "```text\n"
        "结论：合规/不合规\n"
        "可见依据：一句话说明直接可见的合规要素或异常。\n"
        "隐患标签：多个隐患用“；”分隔；无隐患写“无”。\n"
        "```\n\n"
        "## 数据统计\n\n"
        f"- 行数：{summary['rows']}\n"
        f"- train / val：{summary['train_rows']} / {summary['val_rows']}\n"
        f"- 任务分布：{json.dumps(summary['rows_by_task'], ensure_ascii=False)}\n"
        f"- 结论分布：{json.dumps(summary['verdict_by_task'], ensure_ascii=False)}\n"
        f"- train/val 图片哈希交叉：{summary['train_val_hash_overlap']}\n"
    )


def main() -> int:
    args = parse_args()
    source_all = read_jsonl(args.input_dir / args.all_name)
    source_train = read_jsonl(args.input_dir / args.train_name)
    source_val = read_jsonl(args.input_dir / args.val_name)

    transformed_by_original_id: dict[str, dict[str, Any]] = {}
    all_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(source_all, start=1):
        new_row = transform_row(row, f"{args.id_prefix}_{idx:06d}")
        all_rows.append(new_row)
        transformed_by_original_id[row["id"]] = new_row

    train_rows = [transformed_by_original_id[row["id"]] for row in source_train]
    val_rows = [transformed_by_original_id[row["id"]] for row in source_val]
    outputs = ensure_outputs(args)
    summary = build_summary(args, all_rows, train_rows, val_rows, outputs)

    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    write_jsonl(outputs["all"], all_rows)
    write_jsonl(outputs["train"], train_rows)
    write_jsonl(outputs["val"], val_rows)
    write_json(outputs["summary"], summary)
    outputs["design"].write_text(build_design_doc(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

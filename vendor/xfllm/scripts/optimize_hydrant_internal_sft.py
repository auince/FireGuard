#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_INPUT_DIR = Path(
    "/opt/datasets/fire-inspection/training_data/202606221711_20260608_indoor_hydrant_internal_components"
)
DEFAULT_OUTPUT_DIR = Path(
    "/opt/datasets/fire-inspection/training_data/202606221711_20260608_indoor_hydrant_internal_components_optimized_reasoned"
)

DEFAULT_PROMPT = (
    "你是消防巡检助手。请根据图片判断“室内消火栓箱体内部组件是否合规”。\n"
    "只依据图片中可见内容，不要推测遮挡或画面外的部件。\n"
    "请按以下格式输出：\n"
    "结论：合规/不合规\n"
    "可见依据：简要说明与结论直接相关的可见部件状态。\n"
    "隐患标签：列出不合规项；如未见异常写“无”。\n"
)


DEFECT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "handwheel_missing",
        "label": "室内消火栓手轮缺失",
        "patterns": ("手轮缺失", "无手轮", "缺少手轮"),
        "evidence": "阀门位置未见应有的手轮，影响手动启闭",
        "visual_anchor": "小目标；通常在阀杆或栓口附近，需要较清晰近景。",
        "difficulty": "中高",
        "priority": "补充手轮存在但角度、遮挡、颜色不同的难负样本。",
    },
    {
        "key": "outlet_direction_wrong",
        "label": "室内消火栓栓口方向错误",
        "patterns": ("栓口方向错误", "栓口朝向错误", "栓口方向不正确", "栓口朝向不正确"),
        "evidence": "栓口朝向异常，与便于连接水带的状态不符",
        "visual_anchor": "需要识别栓口朝向和箱体空间关系。",
        "difficulty": "高",
        "priority": "优先生成正反例成对数据：朝外/朝侧/朝内，避免只学背景。",
    },
    {
        "key": "cabinet_missing",
        "label": "室内消火栓无箱体",
        "patterns": ("无箱体", "箱体缺失", "缺少箱体"),
        "evidence": "未见完整消火栓箱体，内部组件或管路外露",
        "visual_anchor": "大目标；通常容易由整体结构判断。",
        "difficulty": "低",
        "priority": "补充室外裸露管件、破损箱体、门打开但箱体存在的区分样本。",
    },
    {
        "key": "hose_missing",
        "label": "室内消火栓无消防水带",
        "patterns": ("无消防水带", "缺少消防水带", "消防水带缺失"),
        "evidence": "箱内未见盘卷或悬挂的消防水带",
        "visual_anchor": "中大目标；盘卷水带、挂架、空箱之间差异明显。",
        "difficulty": "中",
        "priority": "补充只有水带缺失、水枪仍在位的单缺陷样本。",
    },
    {
        "key": "water_gun_missing",
        "label": "室内消火栓无消防水枪",
        "patterns": ("无消防水枪", "消防水枪缺失", "缺少消防水枪"),
        "evidence": "箱内未见消防水枪",
        "visual_anchor": "小到中目标；容易与接口、管件混淆。",
        "difficulty": "中高",
        "priority": "补充水枪在位、水枪被水带遮挡、水枪形态不同的样本。",
    },
    {
        "key": "fire_interface_missing",
        "label": "室内消火栓消防接口缺失",
        "patterns": ("消防接口缺失", "接口缺失", "无消防接口", "缺少消防接口"),
        "evidence": "接口位置缺少可连接水带的消防接口",
        "visual_anchor": "小目标；常与栓口、闷盖、水带接口混淆。",
        "difficulty": "高",
        "priority": "补充接口存在/接口缺失的近景对照，并单独框出接口位置。",
    },
    {
        "key": "reel_pipe_bent",
        "label": "消防软管卷盘供水管道折弯严重",
        "patterns": ("供水管道折弯严重", "管道折弯严重", "折弯严重"),
        "evidence": "消防软管卷盘供水管道存在明显折弯，可能影响供水",
        "visual_anchor": "线状结构；需要看清管道连续性和弯折角度。",
        "difficulty": "中",
        "priority": "补充正常弯管、轻微弯曲、严重折弯的分级样本。",
    },
    {
        "key": "cabinet_rust",
        "label": "室内消火栓箱锈蚀",
        "patterns": ("箱锈蚀", "锈蚀", "腐蚀"),
        "evidence": "箱体或箱内表面可见锈蚀、腐蚀痕迹",
        "visual_anchor": "纹理/颜色异常；受光照、污渍影响较大。",
        "difficulty": "中",
        "priority": "当前样本极少，需补充不同光照、轻重锈蚀和污渍难负样本。",
    },
    {
        "key": "door_missing",
        "label": "室内消火栓箱门缺失",
        "patterns": ("箱门缺失", "无箱门", "缺少箱门", "门缺失"),
        "evidence": "箱门位置缺失或门板不完整，箱体无法正常关闭防护",
        "visual_anchor": "大目标；需区分箱门打开和箱门缺失。",
        "difficulty": "中",
        "priority": "当前样本极少，需补充箱门打开但未缺失的难负样本。",
    },
)

DEFECT_BY_KEY = {spec["key"]: spec for spec in DEFECT_SPECS}
DEFECT_ORDER = {spec["key"]: i for i, spec in enumerate(DEFECT_SPECS)}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Optimize indoor fire hydrant internal-component SFT JSONL by merging "
            "duplicate images, rebuilding split by image hash, and adding concise "
            "visible-evidence rationales."
        )
    )
    p.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--input-name", default="all.jsonl")
    p.add_argument("--train-name", default="train.jsonl")
    p.add_argument("--val-name", default="val.jsonl")
    p.add_argument("--all-name", default="all.jsonl")
    p.add_argument("--summary-name", default="summary.json")
    p.add_argument("--report-name", default="optimization_report.md")
    p.add_argument("--val-ratio", type=float, default=0.08)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--id-prefix", default="xf_hydrant_internal_opt")
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
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


def assistant_text(row: dict[str, Any]) -> str:
    for msg in row.get("messages") or []:
        if msg.get("role") != "assistant":
            continue
        for item in msg.get("content") or []:
            if item.get("type") == "text":
                return normalize_text(item.get("text"))
    return ""


def collect_source_text(row: dict[str, Any]) -> str:
    meta = row.get("meta") or {}
    values: list[str] = [
        meta.get("category") or "",
        meta.get("category_name") or "",
        assistant_text(row),
    ]
    values.extend(meta.get("labels") or [])
    for box in meta.get("boxes") or []:
        if isinstance(box, dict):
            values.append(box.get("label") or "")
            values.append(box.get("description") or "")
    return "\n".join(normalize_text(v) for v in values if normalize_text(v))


def detect_defects(row: dict[str, Any]) -> list[str]:
    text = collect_source_text(row)
    compact = re.sub(r"\s+", "", text)
    found: set[str] = set()

    if (
        "无消防水枪、消防水带" in compact
        or "无消防水枪和消防水带" in compact
        or "缺少消防水枪、消防水带" in compact
    ):
        found.update({"water_gun_missing", "hose_missing"})

    for spec in DEFECT_SPECS:
        if any(pattern in compact for pattern in spec["patterns"]):
            found.add(spec["key"])

    return sorted(found, key=lambda key: DEFECT_ORDER[key])


def unique_sorted(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        v = normalize_text(value)
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return sorted(out)


def dedupe_boxes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        meta = row.get("meta") or {}
        for box in meta.get("boxes") or []:
            if not isinstance(box, dict):
                continue
            key = json.dumps(
                {
                    "bbox_norm_xyxy": box.get("bbox_norm_xyxy"),
                    "label": normalize_text(box.get("label")),
                    "shape_type": box.get("shape_type") or "",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(box)
    return out


def defect_labels(defect_keys: list[str]) -> list[str]:
    return [DEFECT_BY_KEY[key]["label"] for key in defect_keys]


def build_evidence(defect_keys: list[str]) -> str:
    if not defect_keys:
        return "图中未见影响室内消火栓箱体内部组件合规性的明确异常。"
    return "；".join(DEFECT_BY_KEY[key]["evidence"].rstrip("。；;") for key in defect_keys) + "。"


def build_answer(defect_keys: list[str]) -> str:
    verdict = "不合规" if defect_keys else "合规"
    labels = "；".join(defect_labels(defect_keys)) if defect_keys else "无"
    return f"结论：{verdict}\n可见依据：{build_evidence(defect_keys)}\n隐患标签：{labels}。"


def choose_representative(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def score(row: dict[str, Any]) -> tuple[int, int, str]:
        labels = row.get("meta", {}).get("labels") or []
        boxes = row.get("meta", {}).get("boxes") or []
        return (len(detect_defects(row)), len(labels) + len(boxes), row.get("id") or "")

    return sorted(rows, key=score, reverse=True)[0]


def build_optimized_row(
    *,
    idx: int,
    image_hash: str,
    source_rows: list[dict[str, Any]],
    prompt: str,
    id_prefix: str,
) -> dict[str, Any]:
    representative = choose_representative(source_rows)
    image_path = representative["images"][0]
    metas = [row.get("meta") or {} for row in source_rows]
    defect_keys = sorted(
        {key for row in source_rows for key in detect_defects(row)},
        key=lambda key: DEFECT_ORDER[key],
    )
    categories = unique_sorted([meta.get("category") or "" for meta in metas])
    labels = unique_sorted([label for meta in metas for label in (meta.get("labels") or [])])
    source_jsons = unique_sorted([meta.get("source_json") or "" for meta in metas])
    source_images = unique_sorted([meta.get("source_image") or "" for meta in metas])
    source_ids = unique_sorted([row.get("id") or "" for row in source_rows])

    meta0 = representative.get("meta") or {}
    answer = build_answer(defect_keys)

    return {
        "id": f"{id_prefix}_{idx:06d}",
        "images": [image_path],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image_path},
                    {"type": "text", "text": prompt},
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": answer}],
            },
        ],
        "meta": {
            "source_ids": source_ids,
            "source_jsons": source_jsons,
            "source_images": source_images,
            "image_sha1": image_hash,
            "merged_source_rows": len(source_rows),
            "categories": categories,
            "primary_category": categories[0] if categories else None,
            "original_labels": labels,
            "defect_keys": defect_keys,
            "defect_labels": defect_labels(defect_keys),
            "boxes": dedupe_boxes(source_rows),
            "image_width": meta0.get("image_width"),
            "image_height": meta0.get("image_height"),
            "verdict": "不合规" if defect_keys else "合规",
        },
    }


def stratified_split(
    rows: list[dict[str, Any]], val_ratio: float, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if val_ratio <= 0:
        return sorted(rows, key=lambda row: row["id"]), []
    if val_ratio >= 1:
        raise ValueError("--val-ratio must be < 1")

    rng = random.Random(seed)
    by_primary: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        keys = row["meta"].get("defect_keys") or ["compliant"]
        by_primary[keys[0]].append(row)

    train: list[dict[str, Any]] = []
    val: list[dict[str, Any]] = []
    for key in sorted(by_primary):
        group = sorted(by_primary[key], key=lambda row: row["id"])
        rng.shuffle(group)
        if len(group) <= 1:
            val_n = 0
        else:
            val_n = max(1, round(len(group) * val_ratio))
            val_n = min(val_n, len(group) - 1)
        val.extend(group[:val_n])
        train.extend(group[val_n:])

    return sorted(train, key=lambda row: row["id"]), sorted(val, key=lambda row: row["id"])


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


def defect_counter(rows: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        for key in row["meta"].get("defect_keys") or []:
            counter[DEFECT_BY_KEY[key]["label"]] += 1
    return counter


def primary_counter(rows: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        keys = row["meta"].get("defect_keys") or []
        if keys:
            counter[DEFECT_BY_KEY[keys[0]]["label"]] += 1
        else:
            counter["合规"] += 1
    return counter


def duplicate_stats(source_rows: list[dict[str, Any]], hash_to_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    duplicate_groups = {h: rows for h, rows in hash_to_rows.items() if len(rows) > 1}
    raw_label_inconsistent_groups = 0
    normalized_defect_inconsistent_groups = 0
    split_leak_groups = 0
    for rows in duplicate_groups.values():
        raw_label_sets = {
            tuple(row.get("meta", {}).get("labels") or [assistant_text(row)])
            for row in rows
        }
        if len(raw_label_sets) > 1:
            raw_label_inconsistent_groups += 1
        normalized_defect_sets = {tuple(detect_defects(row)) for row in rows}
        if len(normalized_defect_sets) > 1:
            normalized_defect_inconsistent_groups += 1
        source_splits = {
            row.get("_source_split")
            for row in rows
            if row.get("_source_split") in {"train", "val"}
        }
        if len(source_splits) > 1:
            split_leak_groups += 1

    return {
        "source_rows": len(source_rows),
        "unique_image_hashes": len(hash_to_rows),
        "duplicate_image_groups": len(duplicate_groups),
        "duplicate_source_rows": sum(len(rows) for rows in duplicate_groups.values()),
        "merged_or_removed_duplicate_rows": len(source_rows) - len(hash_to_rows),
        "source_train_val_leak_groups": split_leak_groups,
        "source_raw_label_inconsistent_duplicate_groups": raw_label_inconsistent_groups,
        "source_normalized_defect_inconsistent_duplicate_groups": normalized_defect_inconsistent_groups,
    }


def build_summary(
    *,
    args: argparse.Namespace,
    source_rows: list[dict[str, Any]],
    hash_to_rows: dict[str, list[dict[str, Any]]],
    rows: list[dict[str, Any]],
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    missing_images: list[dict[str, Any]],
    outputs: dict[str, Path],
) -> dict[str, Any]:
    return {
        "input_dir": str(args.input_dir.resolve()),
        "output_dir": str(args.output_dir.resolve()),
        "files": {name: str(path) for name, path in outputs.items()},
        "val_ratio": args.val_ratio,
        "seed": args.seed,
        **duplicate_stats(source_rows, hash_to_rows),
        "optimized_rows": len(rows),
        "train_rows": len(train),
        "val_rows": len(val),
        "missing_image_rows": len(missing_images),
        "verdict_counts": dict(Counter(row["meta"]["verdict"] for row in rows)),
        "by_defect": dict(defect_counter(rows)),
        "train_by_defect": dict(defect_counter(train)),
        "val_by_defect": dict(defect_counter(val)),
        "by_primary_defect": dict(primary_counter(rows)),
        "train_by_primary_defect": dict(primary_counter(train)),
        "val_by_primary_defect": dict(primary_counter(val)),
        "visual_anchors": {
            spec["label"]: {
                "difficulty": spec["difficulty"],
                "visual_anchor": spec["visual_anchor"],
                "data_priority": spec["priority"],
            }
            for spec in DEFECT_SPECS
        },
        "notes": [
            "This dataset uses concise visible evidence, not long hidden chain-of-thought.",
            "Rows are split after image-hash deduplication to prevent train/val leakage.",
            "All source rows are non-compliant; add compliant and hard-negative samples before relying on compliance precision.",
        ],
    }


def render_table(rows: list[list[Any]]) -> str:
    widths = [0] * len(rows[0])
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(str(value)))

    def fmt(row: list[Any]) -> str:
        return "| " + " | ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)) + " |"

    header = fmt(rows[0])
    sep = "| " + " | ".join("-" * widths[i] for i in range(len(widths))) + " |"
    body = [fmt(row) for row in rows[1:]]
    return "\n".join([header, sep, *body])


def build_report(summary: dict[str, Any]) -> str:
    defect_rows = [["异常项", "样本数", "视觉难度", "重点补数据"]]
    by_defect = summary["by_defect"]
    for spec in DEFECT_SPECS:
        label = spec["label"]
        defect_rows.append([label, by_defect.get(label, 0), spec["difficulty"], spec["priority"]])

    lines = [
        "# 室内消火栓内部组件训练数据优化报告",
        "",
        "## 处理结果",
        "",
        f"- 原始样本数：{summary['source_rows']}",
        f"- 唯一图片数：{summary['unique_image_hashes']}",
        f"- 重复图片组：{summary['duplicate_image_groups']}，涉及原始样本 {summary['duplicate_source_rows']} 条",
        f"- 原始 train/val 泄漏图片组：{summary['source_train_val_leak_groups']}",
        f"- 重复图但原始标签文本不一致图片组：{summary['source_raw_label_inconsistent_duplicate_groups']}",
        f"- 重复图但归一化隐患集合不一致图片组：{summary['source_normalized_defect_inconsistent_duplicate_groups']}",
        f"- 优化后样本数：{summary['optimized_rows']}，train={summary['train_rows']}，val={summary['val_rows']}",
        "",
        "## 为什么不生成长思维链",
        "",
        "原始标注里的 description 基本是隐患标签复述，不包含人工观察过程。直接扩成长思维链会把弱标签包装成看似确定的推理，容易训练出幻觉。优化版改为短的“可见依据”：只写与标签直接相关、能从图中检查的部件状态。",
        "",
        "## 模型更可能学到的视觉异常",
        "",
        render_table(defect_rows),
        "",
        "## 后续补数据优先级",
        "",
        "1. 先补合规样本和难负样本。目前原始数据全是不合规，模型会天然偏向输出“不合规”。",
        "2. 栓口方向错误、消防接口缺失、手轮缺失属于小目标或方向判断，应优先补近景、成对正反例和单独框。",
        "3. 锈蚀、箱门缺失、缺少消防水带样本太少，应补到每类至少 80-150 张，再做类别均衡训练。",
        "4. 对同一张图只保留一个合并后的多标签答案，避免 train/val 泄漏和同图标签冲突。",
        "",
    ]
    return "\n".join(lines)


def load_source_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    split_by_id: dict[str, str] = {}
    for split_name in ("train", "val"):
        split_path = args.input_dir / f"{split_name}.jsonl"
        if not split_path.exists():
            continue
        for row in read_jsonl(split_path):
            row_id = row.get("id")
            if isinstance(row_id, str) and row_id:
                split_by_id[row_id] = split_name

    all_path = args.input_dir / args.input_name
    if all_path.exists():
        rows = read_jsonl(all_path)
        for row in rows:
            row["_source_split"] = split_by_id.get(row.get("id"), "all")
        return rows

    rows: list[dict[str, Any]] = []
    for split_name in ("train", "val"):
        path = args.input_dir / f"{split_name}.jsonl"
        for row in read_jsonl(path):
            row["_source_split"] = split_name
            rows.append(row)
    return rows


def main() -> int:
    args = parse_args()
    if not args.input_dir.exists():
        print(f"input dir does not exist: {args.input_dir}", file=sys.stderr)
        return 2

    source_rows = load_source_rows(args)
    hash_to_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missing_images: list[dict[str, Any]] = []
    for row in source_rows:
        images = row.get("images") or []
        if not images:
            missing_images.append({"id": row.get("id"), "reason": "missing_images_field"})
            continue
        path = Path(images[0])
        if not path.exists():
            missing_images.append({"id": row.get("id"), "reason": "missing_image", "image": str(path)})
            continue
        hash_to_rows[image_sha1(path)].append(row)

    optimized_rows = [
        build_optimized_row(
            idx=idx,
            image_hash=image_hash,
            source_rows=hash_to_rows[image_hash],
            prompt=args.prompt,
            id_prefix=args.id_prefix,
        )
        for idx, image_hash in enumerate(sorted(hash_to_rows), start=1)
    ]
    train, val = stratified_split(optimized_rows, args.val_ratio, args.seed)
    outputs = ensure_outputs(args)
    summary = build_summary(
        args=args,
        source_rows=source_rows,
        hash_to_rows=hash_to_rows,
        rows=optimized_rows,
        train=train,
        val=val,
        missing_images=missing_images,
        outputs=outputs,
    )
    report = build_report(summary)

    if not args.dry_run:
        write_jsonl(outputs["all"], optimized_rows)
        write_jsonl(outputs["train"], train)
        write_jsonl(outputs["val"], val)
        write_json(outputs["summary"], summary)
        outputs["report"].write_text(report, encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

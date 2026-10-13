#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_SOURCE_DIR = Path(
    "/opt/datasets/fire-inspection/archive_extracted/202606221711_20260608-室内消火栓内部组件已标注"
)
DEFAULT_OUTPUT_DIR = Path(
    "/opt/datasets/fire-inspection/sft/202606221711_20260608_indoor_hydrant_internal_components"
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

DEFAULT_PROMPT = (
    "你是消防巡检助手。请根据图片判断“室内消火栓箱体内部组件是否合规”。\n"
    "1) 先给出结论：合规/不合规。\n"
    "2) 再用一段简短中文 description 说明你看到的内部组件关键要素与隐患。\n"
)

HAZARD_WORDS = (
    "隐患",
    "缺失",
    "缺少",
    "无",
    "错误",
    "锈蚀",
    "折弯",
    "损坏",
    "破损",
    "模糊",
    "未",
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Convert LabelMe-style indoor fire hydrant internal-component annotations "
            "to Qwen3-VL/TRL SFT JSONL."
        )
    )
    p.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--train-name", default="train.jsonl")
    p.add_argument("--val-name", default="val.jsonl")
    p.add_argument("--all-name", default="all.jsonl")
    p.add_argument("--summary-name", default="summary.json")
    p.add_argument("--skipped-name", default="skipped.jsonl")
    p.add_argument("--val-ratio", type=float, default=0.05)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--id-prefix", default="xf_hydrant_internal")
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--default-verdict", choices=["合规", "不合规"], default="不合规")
    p.add_argument(
        "--include-boxes-in-answer",
        action="store_true",
        help="Append compact bbox information to the assistant answer. By default boxes are stored only in meta.",
    )
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def is_system_file(path: Path) -> bool:
    return "__MACOSX" in path.parts or path.name.startswith("._") or path.name == ".DS_Store"


def iter_json_files(source_dir: Path) -> list[Path]:
    return sorted(
        p for p in source_dir.rglob("*.json") if p.is_file() and not is_system_file(p)
    )


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("root is not a JSON object")
    return data


def find_image_for_json(json_path: Path, data: dict[str, Any]) -> Path | None:
    image_path = data.get("imagePath")
    candidates: list[Path] = []

    if isinstance(image_path, str) and image_path.strip():
        raw = Path(image_path.strip())
        candidates.append(raw if raw.is_absolute() else json_path.parent / raw)

    for ext in sorted(IMAGE_EXTS):
        candidates.append(json_path.with_suffix(ext))
        candidates.append(json_path.with_suffix(ext.upper()))

    for c in candidates:
        if c.exists() and c.is_file() and not is_system_file(c):
            return c.resolve()

    # Last chance: case-insensitive lookup in the same folder.
    target_names = {c.name.lower() for c in candidates if c.name}
    target_stems = {json_path.stem.lower()}
    for child in json_path.parent.iterdir():
        if not child.is_file() or child.suffix.lower() not in IMAGE_EXTS or is_system_file(child):
            continue
        if child.name.lower() in target_names or child.stem.lower() in target_stems:
            return child.resolve()

    return None


def normalize_text(text: Any) -> str:
    if text is None:
        return ""
    s = str(text).replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def unique_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        v = normalize_text(value)
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def split_category(category: str) -> tuple[str | None, str]:
    m = re.match(r"^(\d+)\s*(.+)$", category)
    if not m:
        return None, category
    return m.group(1), m.group(2).strip()


def bbox_from_points(
    points: Any, image_width: int | None, image_height: int | None
) -> tuple[list[float] | None, list[float] | None]:
    if not isinstance(points, list):
        return None, None

    xs: list[float] = []
    ys: list[float] = []
    for pt in points:
        if not isinstance(pt, list) or len(pt) < 2:
            continue
        try:
            xs.append(float(pt[0]))
            ys.append(float(pt[1]))
        except (TypeError, ValueError):
            continue

    if not xs or not ys:
        return None, None

    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    if image_width:
        x1 = max(0.0, min(float(image_width), x1))
        x2 = max(0.0, min(float(image_width), x2))
    if image_height:
        y1 = max(0.0, min(float(image_height), y1))
        y2 = max(0.0, min(float(image_height), y2))

    bbox = [round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3)]
    bbox_norm = None
    if image_width and image_height and image_width > 0 and image_height > 0:
        bbox_norm = [
            round(x1 / image_width, 6),
            round(y1 / image_height, 6),
            round(x2 / image_width, 6),
            round(y2 / image_height, 6),
        ]
    return bbox, bbox_norm


def extract_shapes(data: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    image_width = data.get("imageWidth")
    image_height = data.get("imageHeight")
    width = int(image_width) if isinstance(image_width, int) else None
    height = int(image_height) if isinstance(image_height, int) else None

    labels: list[str] = []
    boxes: list[dict[str, Any]] = []
    shapes = data.get("shapes")
    if not isinstance(shapes, list):
        return [], []

    for idx, shape in enumerate(shapes):
        if not isinstance(shape, dict):
            continue
        label = normalize_text(shape.get("label"))
        desc = normalize_text(shape.get("description"))
        if label:
            labels.append(label)
        bbox, bbox_norm = bbox_from_points(shape.get("points"), width, height)
        boxes.append(
            {
                "index": idx,
                "label": label,
                "description": desc,
                "shape_type": shape.get("shape_type") or "",
                "bbox_xyxy": bbox,
                "bbox_norm_xyxy": bbox_norm,
            }
        )
    return unique_nonempty(labels), boxes


def build_description(data: dict[str, Any], labels: list[str], category_name: str) -> str:
    desc = normalize_text(data.get("description"))
    if desc:
        return desc

    if labels:
        tail = "；".join(x.rstrip("。") for x in labels)
    else:
        tail = category_name.rstrip("。")
    return f"该图片是室内消火栓的箱体内部组件。该室内消火栓箱体内部组件存在以下隐患：{tail}。"


def infer_verdict(description: str, labels: list[str], default: str) -> str:
    text = description + "\n" + "\n".join(labels)
    if "合规" in text and not any(w in text for w in HAZARD_WORDS):
        return "合规"
    if any(w in text for w in HAZARD_WORDS):
        return "不合规"
    return default


def compact_boxes_for_answer(boxes: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for box in boxes:
        label = box.get("label") or f"box_{box.get('index')}"
        bbox = box.get("bbox_xyxy")
        if bbox:
            parts.append(f"{label}: {bbox}")
    if not parts:
        return ""
    return "标注框：" + "；".join(parts)


def build_row(
    *,
    idx: int,
    json_path: Path,
    image_path: Path,
    data: dict[str, Any],
    prompt: str,
    default_verdict: str,
    id_prefix: str,
    include_boxes_in_answer: bool,
) -> dict[str, Any]:
    category = json_path.parent.name
    category_code, category_name = split_category(category)
    labels, boxes = extract_shapes(data)
    description = build_description(data, labels, category_name)
    verdict = infer_verdict(description, labels, default_verdict)
    answer = f"{verdict}\n{description}".strip()
    if include_boxes_in_answer:
        box_text = compact_boxes_for_answer(boxes)
        if box_text:
            answer = f"{answer}\n{box_text}"

    image_s = str(image_path)
    source_json_s = str(json_path.resolve())

    return {
        "id": f"{id_prefix}_{idx:06d}",
        "images": [image_s],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image_s},
                    {"type": "text", "text": prompt},
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": answer}],
            },
        ],
        "meta": {
            "source_json": source_json_s,
            "source_image": image_s,
            "source_imagePath": data.get("imagePath"),
            "category": category,
            "category_code": category_code,
            "category_name": category_name,
            "labels": labels,
            "boxes": boxes,
            "image_width": data.get("imageWidth"),
            "image_height": data.get("imageHeight"),
            "verdict": verdict,
        },
    }


def stratified_split(
    rows: list[dict[str, Any]], val_ratio: float, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if val_ratio <= 0:
        return sorted(rows, key=lambda x: x["id"]), []
    if val_ratio >= 1:
        raise ValueError("--val-ratio must be < 1")

    rng = random.Random(seed)
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_category[row["meta"]["category"]].append(row)

    train: list[dict[str, Any]] = []
    val: list[dict[str, Any]] = []
    for category in sorted(by_category):
        group = sorted(by_category[category], key=lambda x: x["id"])
        rng.shuffle(group)
        if len(group) <= 1:
            val_n = 0
        else:
            val_n = max(1, round(len(group) * val_ratio))
            val_n = min(val_n, len(group) - 1)
        val.extend(group[:val_n])
        train.extend(group[val_n:])

    return sorted(train, key=lambda x: x["id"]), sorted(val, key=lambda x: x["id"])


def ensure_writable_outputs(args: argparse.Namespace) -> dict[str, Path]:
    outputs = {
        "all": args.output_dir / args.all_name,
        "train": args.output_dir / args.train_name,
        "val": args.output_dir / args.val_name,
        "summary": args.output_dir / args.summary_name,
        "skipped": args.output_dir / args.skipped_name,
    }
    if args.dry_run:
        return outputs

    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing = [str(p) for p in outputs.values() if p.exists()]
    if existing and not args.overwrite:
        joined = "\n".join(f"- {p}" for p in existing)
        raise FileExistsError(f"Output files already exist. Use --overwrite to replace:\n{joined}")
    return outputs


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def build_summary(
    *,
    args: argparse.Namespace,
    total_json: int,
    rows: list[dict[str, Any]],
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    outputs: dict[str, Path],
) -> dict[str, Any]:
    by_category = Counter(row["meta"]["category"] for row in rows)
    train_by_category = Counter(row["meta"]["category"] for row in train)
    val_by_category = Counter(row["meta"]["category"] for row in val)
    return {
        "source_dir": str(args.source_dir.resolve()),
        "output_dir": str(args.output_dir.resolve()),
        "files": {k: str(v) for k, v in outputs.items()},
        "total_json": total_json,
        "usable_rows": len(rows),
        "train_rows": len(train),
        "val_rows": len(val),
        "skipped_rows": len(skipped),
        "val_ratio": args.val_ratio,
        "seed": args.seed,
        "by_category": {
            cat: {
                "total": by_category[cat],
                "train": train_by_category[cat],
                "val": val_by_category[cat],
            }
            for cat in sorted(by_category)
        },
        "skipped_reasons": dict(Counter(item["reason"] for item in skipped)),
    }


def main() -> int:
    args = parse_args()
    if not args.source_dir.exists():
        print(f"source dir does not exist: {args.source_dir}", file=sys.stderr)
        return 2

    outputs = ensure_writable_outputs(args)
    json_files = iter_json_files(args.source_dir)

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    next_idx = 1
    for json_path in json_files:
        try:
            data = load_json(json_path)
            image_path = find_image_for_json(json_path, data)
            if image_path is None:
                skipped.append(
                    {
                        "source_json": str(json_path.resolve()),
                        "reason": "missing_image",
                        "imagePath": data.get("imagePath"),
                    }
                )
                continue
            rows.append(
                build_row(
                    idx=next_idx,
                    json_path=json_path,
                    image_path=image_path,
                    data=data,
                    prompt=args.prompt,
                    default_verdict=args.default_verdict,
                    id_prefix=args.id_prefix,
                    include_boxes_in_answer=args.include_boxes_in_answer,
                )
            )
            next_idx += 1
        except Exception as exc:
            skipped.append(
                {
                    "source_json": str(json_path.resolve()),
                    "reason": "error",
                    "error": str(exc),
                }
            )

    train, val = stratified_split(rows, args.val_ratio, args.seed)
    summary = build_summary(
        args=args,
        total_json=len(json_files),
        rows=rows,
        train=train,
        val=val,
        skipped=skipped,
        outputs=outputs,
    )

    if not args.dry_run:
        write_jsonl(outputs["all"], rows)
        write_jsonl(outputs["train"], train)
        write_jsonl(outputs["val"], val)
        write_jsonl(outputs["skipped"], skipped)
        write_json(outputs["summary"], summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

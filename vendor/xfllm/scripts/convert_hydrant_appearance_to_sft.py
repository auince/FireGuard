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


DEFAULT_OUTPUT_DIR = Path(
    "/opt/datasets/fire-inspection/training_data/20260624_indoor_hydrant_appearance_compliance_cleaned"
)

SOURCE_DIRS: dict[str, Path] = {
    "appearance_compliant": Path(
        "/opt/datasets/fire-inspection/archive_extracted/20260430-室内消火栓箱外观合规图片已标注（2026043018）/室内消火栓箱外观合规图片已标注（2026043018）"
    ),
    "operation_instruction_missing": Path(
        "/opt/datasets/fire-inspection/archive_extracted/20260507-室内消火栓箱的明显部位未采用耐久性文字或图形标注其操作说明已经标注/室内消火栓箱的明显部位未采用耐久性文字或图形标注其操作说明已经标注"
    ),
    "door_text_missing": Path(
        "/opt/datasets/fire-inspection/archive_extracted/20260507-室内消火栓箱门上未标注“消火栓”和英文“FIRE HYDRANT”字样照片/室内消火栓箱门上未标注“消火栓”和英文“FIRE HYDRANT”字样照片"
    ),
    "glass_door": Path(
        "/opt/datasets/fire-inspection/archive_extracted/20260516-室内消火栓箱门为玻璃门已标注/室内消火栓箱门为玻璃门已标注"
    ),
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

DEFAULT_PROMPT = (
    "你是消防巡检助手。请根据图片判断“室内消火栓箱体外观是否合规”。\n"
    "只依据图片中可见内容，不要推测遮挡或画面外的部件。\n"
    "请按以下格式输出：\n"
    "结论：合规/不合规\n"
    "可见依据：简要说明与结论直接相关的可见外观、标识或说明状态。\n"
    "隐患标签：列出不合规项；如未见异常写“无”。\n"
)


DEFECT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "door_text_missing",
        "label": "室内消火栓箱门上未标注“消火栓”和英文“FIRE HYDRANT”字样",
        "patterns": (
            r"未标注[“\"']?消火栓",
            r"未标注.*?FIRE\s*HYDRANT",
            r"未.*?FIRE\s*HYDRANT",
        ),
        "evidence": "箱门上未见“消火栓”和英文“FIRE HYDRANT”标识",
        "priority": "补充同角度下文字完整、文字缺失、文字被遮挡的成对样本。",
    },
    {
        "key": "operation_instruction_missing",
        "label": "室内消火栓箱明显部位未采用耐久性文字或图形标注操作说明",
        "patterns": (
            r"未(?:粘贴|采用).*?(?:操作说明|使用说明)",
            r"未.*?(?:操作说明|使用说明)",
        ),
        "evidence": "箱体明显部位未见耐久性文字或图形操作说明",
        "priority": "补充操作说明清晰存在、说明模糊、说明被遮挡的难负样本。",
    },
    {
        "key": "nameplate_missing",
        "label": "室内消火栓箱体无铭牌",
        "patterns": (r"无铭牌", r"未.*铭牌"),
        "evidence": "箱体上未见铭牌",
        "priority": "补充铭牌存在但反光、角度偏斜、字体较小的样本。",
    },
    {
        "key": "nameplate_blurry",
        "label": "室内消火栓箱体铭牌模糊",
        "patterns": (r"铭牌模糊",),
        "evidence": "箱体铭牌内容模糊，难以辨认",
        "priority": "补充清晰铭牌与不同程度模糊铭牌的分级样本。",
    },
    {
        "key": "door_text_blurry",
        "label": "室内消火栓箱门标识模糊",
        "patterns": (r"(?:消火栓|FIRE\s*HYDRANT).*?模糊", r"字样模糊"),
        "evidence": "箱门上的“消火栓”或英文标识模糊",
        "priority": "补充文字清晰、轻微模糊、严重模糊的分级样本。",
    },
    {
        "key": "glass_door",
        "label": "室内消火栓箱门为玻璃门",
        "patterns": (),
        "evidence": "箱门呈玻璃门样式",
        "priority": "该标签来自目录名，需确认业务规则后决定是否作为强不合规项。",
    },
    {
        "key": "obstructed",
        "label": "室内消火栓箱体或箱门被物品遮挡",
        "patterns": (r"遮挡",),
        "evidence": "箱体或箱门被物品遮挡",
        "priority": "补充部分遮挡、完全遮挡和无遮挡对照样本。",
    },
)

DEFECT_BY_KEY = {spec["key"]: spec for spec in DEFECT_SPECS}
DEFECT_ORDER = {spec["key"]: i for i, spec in enumerate(DEFECT_SPECS)}

OUT_OF_SCOPE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("室内消火栓箱内消防水带缺失", r"水带缺失|无消防水带|缺少消防水带"),
    ("室内消火栓箱体内堆放杂物", r"堆放杂物"),
)

HIGH_CONFIDENCE_COMPLIANT_NEEDLES = {
    "body": "消火栓箱体",
    "door": "消火栓箱门",
    "door_text": "FIRE HYDRANT",
    "instruction": "使用说明",
    "nameplate": "铭牌",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Clean indoor fire hydrant appearance compliance annotations into SFT JSONL."
    )
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--train-name", default="train.jsonl")
    p.add_argument("--val-name", default="val.jsonl")
    p.add_argument("--all-name", default="all.jsonl")
    p.add_argument("--summary-name", default="summary.json")
    p.add_argument("--report-name", default="cleaning_report.md")
    p.add_argument("--review-name", default="review.jsonl")
    p.add_argument("--skipped-name", default="skipped.jsonl")
    p.add_argument("--val-ratio", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--id-prefix", default="xf_hydrant_appearance")
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


def is_system_file(path: Path) -> bool:
    return "__MACOSX" in path.parts or path.name.startswith("._") or path.name == ".DS_Store"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("root is not a JSON object")
    return data


def image_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_image_for_json(json_path: Path, data: dict[str, Any]) -> Path | None:
    candidates: list[Path] = []
    image_path = data.get("imagePath")
    if isinstance(image_path, str) and image_path.strip():
        raw = Path(image_path.strip())
        candidates.append(raw if raw.is_absolute() else json_path.parent / raw)

    for ext in sorted(IMAGE_EXTS):
        candidates.append(json_path.with_suffix(ext))
        candidates.append(json_path.with_suffix(ext.upper()))

    for candidate in candidates:
        if candidate.exists() and candidate.is_file() and not is_system_file(candidate):
            return candidate.resolve()

    target_names = {candidate.name.lower() for candidate in candidates if candidate.name}
    for child in json_path.parent.iterdir():
        if not child.is_file() or child.suffix.lower() not in IMAGE_EXTS or is_system_file(child):
            continue
        if child.name.lower() in target_names or child.stem.lower() == json_path.stem.lower():
            return child.resolve()
    return None


def bbox_from_points(
    points: Any, image_width: int | None, image_height: int | None
) -> tuple[list[float] | None, list[float] | None]:
    if not isinstance(points, list):
        return None, None
    xs: list[float] = []
    ys: list[float] = []
    for point in points:
        if not isinstance(point, list) or len(point) < 2:
            continue
        try:
            xs.append(float(point[0]))
            ys.append(float(point[1]))
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


def extract_labels_and_boxes(data: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    width = data.get("imageWidth")
    height = data.get("imageHeight")
    image_width = int(width) if isinstance(width, int) else None
    image_height = int(height) if isinstance(height, int) else None
    shapes = data.get("shapes")
    if not isinstance(shapes, list):
        return [], []

    labels: list[str] = []
    boxes: list[dict[str, Any]] = []
    for idx, shape in enumerate(shapes):
        if not isinstance(shape, dict):
            continue
        label = normalize_text(shape.get("label"))
        desc = normalize_text(shape.get("description"))
        if label:
            labels.append(label)
        bbox, bbox_norm = bbox_from_points(shape.get("points"), image_width, image_height)
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
    return unique_sorted(labels), boxes


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


def detect_defects(source_name: str, labels: list[str]) -> list[str]:
    text = "\n".join(labels)
    compact = re.sub(r"\s+", "", text)
    found: set[str] = set()

    if source_name == "operation_instruction_missing":
        found.add("operation_instruction_missing")
    if source_name == "door_text_missing":
        found.add("door_text_missing")
    if source_name == "glass_door":
        found.add("glass_door")

    for spec in DEFECT_SPECS:
        for pattern in spec["patterns"]:
            if re.search(pattern, compact, flags=re.IGNORECASE):
                found.add(spec["key"])
                break

    return sorted(found, key=lambda key: DEFECT_ORDER[key])


def detect_out_of_scope(labels: list[str]) -> list[str]:
    text = re.sub(r"\s+", "", "\n".join(labels))
    out: list[str] = []
    for label, pattern in OUT_OF_SCOPE_PATTERNS:
        if re.search(pattern, text):
            out.append(label)
    return out


def missing_compliant_needles(labels: list[str]) -> list[str]:
    text = "\n".join(labels)
    return [
        key
        for key, needle in HIGH_CONFIDENCE_COMPLIANT_NEEDLES.items()
        if needle not in text
    ]


def read_sources() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for source_name, source_dir in SOURCE_DIRS.items():
        if not source_dir.exists():
            skipped.append(
                {
                    "source": source_name,
                    "path": str(source_dir),
                    "reason": "source_dir_missing",
                }
            )
            continue
        for json_path in sorted(source_dir.rglob("*.json")):
            if is_system_file(json_path):
                continue
            try:
                data = load_json(json_path)
            except Exception as exc:  # noqa: BLE001
                skipped.append(
                    {
                        "source": source_name,
                        "json": str(json_path),
                        "reason": "invalid_json",
                        "error": str(exc),
                    }
                )
                continue
            image_path = find_image_for_json(json_path, data)
            if image_path is None:
                skipped.append(
                    {
                        "source": source_name,
                        "json": str(json_path),
                        "reason": "missing_image",
                    }
                )
                continue

            labels, boxes = extract_labels_and_boxes(data)
            rows.append(
                {
                    "source": source_name,
                    "json_path": str(json_path.resolve()),
                    "image_path": str(image_path),
                    "image_sha1": image_sha1(image_path),
                    "image_width": data.get("imageWidth"),
                    "image_height": data.get("imageHeight"),
                    "labels": labels,
                    "boxes": boxes,
                    "defect_keys": detect_defects(source_name, labels),
                    "out_of_scope_labels": detect_out_of_scope(labels),
                    "missing_compliant_needles": (
                        missing_compliant_needles(labels)
                        if source_name == "appearance_compliant"
                        else []
                    ),
                }
            )
    return rows, skipped


def dedupe_boxes(source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in source_rows:
        for box in row.get("boxes") or []:
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


def choose_representative(source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    def score(row: dict[str, Any]) -> tuple[int, int, int, str]:
        width = row.get("image_width")
        height = row.get("image_height")
        pixels = width * height if isinstance(width, int) and isinstance(height, int) else 0
        return (
            len(row.get("defect_keys") or []),
            len(row.get("labels") or []),
            pixels,
            row.get("image_path") or "",
        )

    return sorted(source_rows, key=score, reverse=True)[0]


def build_evidence(defect_keys: list[str], compliant_labels: list[str]) -> str:
    if defect_keys:
        return "；".join(DEFECT_BY_KEY[key]["evidence"].rstrip("。；;") for key in defect_keys) + "。"

    visible_parts: list[str] = []
    label_text = "\n".join(compliant_labels)
    if "消火栓箱体" in label_text:
        visible_parts.append("箱体")
    if "消火栓箱门" in label_text:
        visible_parts.append("箱门")
    if "FIRE HYDRANT" in label_text:
        visible_parts.append("箱门上的“消火栓”和英文“FIRE HYDRANT”标识")
    if "使用说明" in label_text or "操作说明" in label_text:
        visible_parts.append("操作说明")
    if "铭牌" in label_text:
        visible_parts.append("铭牌")

    if visible_parts:
        return "可见" + "、".join(visible_parts) + "，未见本任务关注的外观隐患。"
    return "标注来源为外观合规样本，未见本任务关注的外观隐患。"


def build_answer(defect_keys: list[str], compliant_labels: list[str]) -> str:
    verdict = "不合规" if defect_keys else "合规"
    labels = "；".join(DEFECT_BY_KEY[key]["label"] for key in defect_keys) if defect_keys else "无"
    return f"结论：{verdict}\n可见依据：{build_evidence(defect_keys, compliant_labels)}\n隐患标签：{labels}。"


def build_optimized_rows(
    source_rows: list[dict[str, Any]], prompt: str, id_prefix: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        by_hash[row["image_sha1"]].append(row)

    review_rows: list[dict[str, Any]] = []
    optimized: list[dict[str, Any]] = []
    for idx, image_hash in enumerate(sorted(by_hash), start=1):
        group = by_hash[image_hash]
        representative = choose_representative(group)
        sources = unique_sorted([row["source"] for row in group])
        defect_keys = sorted(
            {key for row in group for key in row.get("defect_keys", [])},
            key=lambda key: DEFECT_ORDER[key],
        )
        all_labels = unique_sorted([label for row in group for label in row.get("labels", [])])
        compliant_labels = unique_sorted(
            [
                label
                for row in group
                if row["source"] == "appearance_compliant"
                for label in row.get("labels", [])
            ]
        )
        out_of_scope = unique_sorted(
            [label for row in group for label in row.get("out_of_scope_labels", [])]
        )
        source_conflict = "appearance_compliant" in sources and bool(defect_keys)
        missing_needles = sorted(
            {
                needle
                for row in group
                if row["source"] == "appearance_compliant"
                for needle in row.get("missing_compliant_needles", [])
            }
        )
        review_flags: list[str] = []
        if source_conflict:
            review_flags.append("same_image_in_compliant_and_defect_sources")
        if len(group) > 1:
            review_flags.append("duplicate_image_group")
        if not defect_keys and missing_needles:
            review_flags.append("candidate_compliant_missing_required_annotations")
        if any(not row.get("labels") for row in group):
            review_flags.append("empty_json_shapes")
        if out_of_scope:
            review_flags.append("contains_out_of_scope_internal_labels")

        image_path = representative["image_path"]
        row = {
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
                    "content": [{"type": "text", "text": build_answer(defect_keys, compliant_labels)}],
                },
            ],
            "meta": {
                "image_sha1": image_hash,
                "merged_source_rows": len(group),
                "sources": sources,
                "source_jsons": unique_sorted([row["json_path"] for row in group]),
                "source_images": unique_sorted([row["image_path"] for row in group]),
                "original_labels": all_labels,
                "defect_keys": defect_keys,
                "defect_labels": [DEFECT_BY_KEY[key]["label"] for key in defect_keys],
                "out_of_scope_labels": out_of_scope,
                "boxes": dedupe_boxes(group),
                "image_width": representative.get("image_width"),
                "image_height": representative.get("image_height"),
                "verdict": "不合规" if defect_keys else "合规",
                "source_conflict": source_conflict,
                "review_flags": review_flags,
                "missing_compliant_needles": missing_needles,
            },
        }
        optimized.append(row)
        if review_flags:
            review_rows.append(row)
    return optimized, review_rows


def primary_key(row: dict[str, Any]) -> str:
    keys = row["meta"].get("defect_keys") or []
    if keys:
        return keys[0]
    return "compliant"


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
        by_primary[primary_key(row)].append(row)

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


def counter_by_defect(rows: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        for key in row["meta"].get("defect_keys") or []:
            counter[DEFECT_BY_KEY[key]["label"]] += 1
    return counter


def counter_by_primary(rows: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        key = primary_key(row)
        counter[DEFECT_BY_KEY[key]["label"] if key != "compliant" else "合规"] += 1
    return counter


def build_summary(
    *,
    args: argparse.Namespace,
    source_rows: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    review_rows: list[dict[str, Any]],
    outputs: dict[str, Path],
) -> dict[str, Any]:
    source_counter = Counter(row["source"] for row in source_rows)
    hash_counter = Counter(row["image_sha1"] for row in source_rows)
    duplicate_groups = {h: n for h, n in hash_counter.items() if n > 1}
    cross_source_groups = 0
    for image_hash in duplicate_groups:
        sources = {row["source"] for row in source_rows if row["image_sha1"] == image_hash}
        if len(sources) > 1:
            cross_source_groups += 1

    review_counter: Counter[str] = Counter()
    for row in review_rows:
        review_counter.update(row["meta"].get("review_flags") or [])

    return {
        "output_dir": str(args.output_dir.resolve()),
        "files": {name: str(path) for name, path in outputs.items()},
        "source_dirs": {name: str(path) for name, path in SOURCE_DIRS.items()},
        "val_ratio": args.val_ratio,
        "seed": args.seed,
        "source_rows": len(source_rows),
        "source_rows_by_source": dict(source_counter),
        "skipped_rows": len(skipped),
        "unique_image_hashes": len(hash_counter),
        "duplicate_image_groups": len(duplicate_groups),
        "duplicate_source_rows": sum(duplicate_groups.values()),
        "cross_source_duplicate_groups": cross_source_groups,
        "optimized_rows": len(rows),
        "train_rows": len(train),
        "val_rows": len(val),
        "review_rows": len(review_rows),
        "review_flags": dict(review_counter),
        "verdict_counts": dict(Counter(row["meta"]["verdict"] for row in rows)),
        "by_defect": dict(counter_by_defect(rows)),
        "train_by_defect": dict(counter_by_defect(train)),
        "val_by_defect": dict(counter_by_defect(val)),
        "by_primary_defect": dict(counter_by_primary(rows)),
        "train_by_primary_defect": dict(counter_by_primary(train)),
        "val_by_primary_defect": dict(counter_by_primary(val)),
        "notes": [
            "Appearance data is cleaned as a separate task from internal-component compliance.",
            "Defect labels win when the same image appears in both compliant and defect source folders.",
            "The glass-door label is inferred from its source directory name and should be confirmed as a business rule.",
            "Internal labels such as missing hose are retained in meta.out_of_scope_labels but excluded from the appearance answer.",
        ],
    }


def render_table(rows: list[list[Any]]) -> str:
    widths = [0] * len(rows[0])
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(str(value)))

    def fmt(row: list[Any]) -> str:
        return "| " + " | ".join(str(value).ljust(widths[idx]) for idx, value in enumerate(row)) + " |"

    header = fmt(rows[0])
    sep = "| " + " | ".join("-" * widths[idx] for idx in range(len(widths))) + " |"
    return "\n".join([header, sep, *[fmt(row) for row in rows[1:]]])


def build_report(summary: dict[str, Any]) -> str:
    defect_rows = [["标签", "样本数", "补数据建议"]]
    by_defect = summary["by_defect"]
    for spec in DEFECT_SPECS:
        label = spec["label"]
        defect_rows.append([label, by_defect.get(label, 0), spec["priority"]])

    lines = [
        "# 室内消火栓箱体外观训练数据清洗报告",
        "",
        "## 处理结果",
        "",
        f"- 源标注行数：{summary['source_rows']}",
        f"- 唯一图片数：{summary['unique_image_hashes']}",
        f"- 重复图片组：{summary['duplicate_image_groups']}，涉及源标注 {summary['duplicate_source_rows']} 条",
        f"- 跨来源重复图片组：{summary['cross_source_duplicate_groups']}",
        f"- 清洗后样本数：{summary['optimized_rows']}，train={summary['train_rows']}，val={summary['val_rows']}",
        f"- 需复核样本数：{summary['review_rows']}",
        "",
        "## 结论分布",
        "",
        json.dumps(summary["verdict_counts"], ensure_ascii=False, indent=2),
        "",
        "## 隐患标签分布",
        "",
        render_table(defect_rows),
        "",
        "## 清洗规则",
        "",
        "1. 将外观合规与外观隐患作为独立任务处理，不与内部组件训练集混合。",
        "2. 按图片 SHA1 合并重复图，重新划分 train/val，避免相同图片泄漏。",
        "3. 同一图片同时出现在合规和隐患目录时，隐患标签优先，并写入 review.jsonl 复核。",
        "4. “门上未标注消火栓/FIRE HYDRANT”目录的 JSON 只框了箱体，因此按目录名补充隐患标签。",
        "5. “箱门为玻璃门”按目录名补充为外观标签；是否作为强不合规项需要业务确认。",
        "6. 水带缺失、箱内堆物等内部问题只保留在 meta.out_of_scope_labels，不写入外观任务答案。",
        "",
        "## 后续建议",
        "",
        "1. 人工优先复核 review.jsonl 中的跨来源冲突样本。",
        "2. 对门上文字缺失、操作说明缺失、铭牌缺失补充同角度正负对照。",
        "3. 如果玻璃门不是业务上的不合规项，应从 defect_keys 中移除 glass_door 后重新生成。",
        "4. 合规样本最好补到 200 张以上，并确保门上文字、操作说明、铭牌都清晰可见。",
        "",
    ]
    return "\n".join(lines)


def ensure_outputs(args: argparse.Namespace) -> dict[str, Path]:
    outputs = {
        "all": args.output_dir / args.all_name,
        "train": args.output_dir / args.train_name,
        "val": args.output_dir / args.val_name,
        "summary": args.output_dir / args.summary_name,
        "report": args.output_dir / args.report_name,
        "review": args.output_dir / args.review_name,
        "skipped": args.output_dir / args.skipped_name,
    }
    if args.dry_run:
        return outputs

    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing = [path for path in outputs.values() if path.exists()]
    if existing and not args.overwrite:
        joined = "\n".join(f"- {path}" for path in existing)
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


def main() -> int:
    args = parse_args()
    source_rows, skipped = read_sources()
    optimized_rows, review_rows = build_optimized_rows(
        source_rows, prompt=args.prompt, id_prefix=args.id_prefix
    )
    train, val = stratified_split(optimized_rows, args.val_ratio, args.seed)
    outputs = ensure_outputs(args)
    summary = build_summary(
        args=args,
        source_rows=source_rows,
        skipped=skipped,
        rows=optimized_rows,
        train=train,
        val=val,
        review_rows=review_rows,
        outputs=outputs,
    )

    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    write_jsonl(outputs["all"], optimized_rows)
    write_jsonl(outputs["train"], train)
    write_jsonl(outputs["val"], val)
    write_jsonl(outputs["review"], review_rows)
    write_jsonl(outputs["skipped"], skipped)
    write_json(outputs["summary"], summary)
    outputs["report"].write_text(build_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

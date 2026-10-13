#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
from typing import Any

from PIL import Image


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
TRAINING_ROOT = Path("/opt/datasets/fire-inspection/training_data").resolve()


@dataclass(frozen=True)
class TaskConfig:
    prefix: str
    names: tuple[str, ...]
    names_cn: tuple[str, ...]


TASKS = {
    "outdoor_hydrant": TaskConfig(
        prefix="outdoor_hydrant",
        names=("outdoor_hydrant",),
        names_cn=("\u5ba4\u5916\u6d88\u706b\u6813",),
    ),
    "fire_extinguisher": TaskConfig(
        prefix="fire_extinguisher",
        names=(
            "fire_extinguisher",
            "fire_extinguisher_pressure_indicator",
        ),
        names_cn=(
            "\u706d\u706b\u5668",
            "\u706d\u706b\u5668/\u538b\u529b\u6307\u793a\u5668",
        ),
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert LabelMe datasets into reproducible YOLO detection datasets."
    )
    parser.add_argument("--task", choices=sorted(TASKS), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=20260723)
    parser.add_argument(
        "--materialize",
        choices=("hardlink", "copy"),
        default="hardlink",
        help="Hard links save space while keeping split samples addressable.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def resolve_class_id(task: str, _source_group: str, shape: dict[str, Any]) -> int | None:
    label = str(shape.get("label") or "").strip()
    if task == "outdoor_hydrant":
        if label == "\u5ba4\u5916\u6d88\u706b\u6813":
            return 0
        return None

    if label == "\u706d\u706b\u5668":
        return 0
    if label == "\u706d\u706b\u5668/\u538b\u529b\u6307\u793a\u5668":
        return 1
    return None


def load_record(json_path: Path, task: str) -> dict[str, Any]:
    data = json.loads(json_path.read_text(encoding="utf-8-sig"))
    image_name = str(data.get("imagePath") or "").strip()
    image_path = json_path.parent / image_name
    if not image_path.is_file():
        candidates = [
            path
            for path in json_path.parent.glob(f"{json_path.stem}.*")
            if path.suffix.lower() in IMAGE_SUFFIXES
        ]
        if len(candidates) != 1:
            raise ValueError(f"Cannot resolve image for {json_path}")
        image_path = candidates[0]

    with Image.open(image_path) as image:
        width, height = image.size
        image.verify()

    source_group = json_path.parent.name
    boxes: list[dict[str, Any]] = []
    clipped = 0
    skipped = 0
    for shape in data.get("shapes", []):
        if shape.get("shape_type") != "rectangle":
            skipped += 1
            continue

        class_id = resolve_class_id(task, source_group, shape)
        if class_id is None:
            skipped += 1
            continue

        points = shape.get("points") or []
        if len(points) < 2:
            skipped += 1
            continue

        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        raw = (min(xs), min(ys), max(xs), max(ys))
        bounded = (
            min(max(raw[0], 0.0), float(width)),
            min(max(raw[1], 0.0), float(height)),
            min(max(raw[2], 0.0), float(width)),
            min(max(raw[3], 0.0), float(height)),
        )
        if bounded != raw:
            clipped += 1

        x1, y1, x2, y2 = bounded
        if x2 - x1 < 1.0 or y2 - y1 < 1.0:
            skipped += 1
            continue

        boxes.append(
            {
                "class_id": class_id,
                "source_label": str(shape.get("label") or ""),
                "xyxy": bounded,
            }
        )

    if not boxes:
        raise ValueError(f"No usable boxes in {json_path}")

    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    return {
        "json_path": json_path,
        "image_path": image_path,
        "source_group": source_group,
        "source_description": str(data.get("description") or "").strip(),
        "width": width,
        "height": height,
        "sha256": digest,
        "boxes": boxes,
        "clipped_boxes": clipped,
        "skipped_shapes": skipped,
    }


def deduplicate(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["sha256"]].append(record)

    kept: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for digest, group in sorted(grouped.items()):
        source_groups = {record["source_group"] for record in group}
        if len(source_groups) > 1:
            raise ValueError(
                f"Duplicate image has conflicting source groups: {digest} {sorted(source_groups)}"
            )
        ordered = sorted(
            group,
            key=lambda record: (-len(record["boxes"]), str(record["image_path"])),
        )
        kept.append(ordered[0])
        for duplicate in ordered[1:]:
            duplicates.append(
                {
                    "sha256": digest,
                    "kept": str(ordered[0]["image_path"]),
                    "removed": str(duplicate["image_path"]),
                }
            )

    return sorted(kept, key=lambda record: str(record["image_path"])), duplicates


def build_stratify_key(record: dict[str, Any]) -> str:
    class_ids = sorted({box["class_id"] for box in record["boxes"]})
    return f"{record['source_group']}|{'-'.join(str(class_id) for class_id in class_ids)}"


def split_records(
    records: list[dict[str, Any]], val_ratio: float, seed: int
) -> dict[str, list[dict[str, Any]]]:
    if not 0.0 < val_ratio < 0.5:
        raise ValueError("--val-ratio must be between 0 and 0.5")

    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_group[build_stratify_key(record)].append(record)

    result = {"train": [], "val": []}
    for index, (_group_name, group) in enumerate(sorted(by_group.items())):
        ordered = sorted(group, key=lambda record: record["sha256"])
        random.Random(seed + index).shuffle(ordered)
        val_count = max(1, round(len(ordered) * val_ratio))
        if val_count >= len(ordered):
            val_count = max(1, len(ordered) - 1)
        result["val"].extend(ordered[:val_count])
        result["train"].extend(ordered[val_count:])

    for split in result:
        result[split].sort(key=lambda record: str(record["image_path"]))
    return result


def materialize_file(source: Path, target: Path, mode: str) -> None:
    if mode == "copy":
        shutil.copy2(source, target)
        return
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def write_dataset(
    task: str,
    source: Path,
    output: Path,
    splits: dict[str, list[dict[str, Any]]],
    duplicates: list[dict[str, Any]],
    seed: int,
    val_ratio: float,
    materialize: str,
) -> None:
    config = TASKS[task]
    for split in ("train", "val"):
        (output / "images" / split).mkdir(parents=True, exist_ok=True)
        (output / "labels" / split).mkdir(parents=True, exist_ok=True)
    (output / "metadata").mkdir(parents=True, exist_ok=True)

    manifest_path = output / "metadata" / "source_manifest.jsonl"
    class_counts = Counter()
    split_counts = Counter()
    group_counts = Counter()
    clipped_boxes = 0
    skipped_shapes = 0
    sequence = 0
    with manifest_path.open("w", encoding="utf-8") as manifest:
        for split in ("train", "val"):
            for record in splits[split]:
                sequence += 1
                sample_id = f"{config.prefix}_{sequence:06d}"
                suffix = record["image_path"].suffix.lower()
                image_target = output / "images" / split / f"{sample_id}{suffix}"
                label_target = output / "labels" / split / f"{sample_id}.txt"
                materialize_file(record["image_path"], image_target, materialize)

                label_lines = []
                sample_classes = []
                for box in record["boxes"]:
                    class_id = box["class_id"]
                    x1, y1, x2, y2 = box["xyxy"]
                    width = record["width"]
                    height = record["height"]
                    center_x = ((x1 + x2) / 2.0) / width
                    center_y = ((y1 + y2) / 2.0) / height
                    box_width = (x2 - x1) / width
                    box_height = (y2 - y1) / height
                    values = (center_x, center_y, box_width, box_height)
                    if not all(0.0 <= value <= 1.0 for value in values):
                        raise ValueError(f"Invalid normalized box for {record['json_path']}")
                    label_lines.append(
                        f"{class_id} " + " ".join(f"{value:.6f}" for value in values)
                    )
                    class_counts[config.names[class_id]] += 1
                    sample_classes.append(config.names[class_id])

                label_target.write_text("\n".join(label_lines) + "\n", encoding="utf-8")
                split_counts[split] += 1
                group_counts[f"{split}:{record['source_group']}"] += 1
                clipped_boxes += record["clipped_boxes"]
                skipped_shapes += record["skipped_shapes"]
                manifest.write(
                    json.dumps(
                        {
                            "sample_id": sample_id,
                            "split": split,
                            "source_group": record["source_group"],
                            "source_image": str(record["image_path"]),
                            "source_json": str(record["json_path"]),
                            "sha256": record["sha256"],
                            "width": record["width"],
                            "height": record["height"],
                            "classes": sample_classes,
                            "source_description": record["source_description"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    yaml_lines = [
        f"path: {output}",
        "train: images/train",
        "val: images/val",
        "names:",
    ]
    yaml_lines.extend(f"  {index}: {name}" for index, name in enumerate(config.names))
    (output / "data.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
    (output / "classes.txt").write_text("\n".join(config.names) + "\n", encoding="utf-8")
    (output / "classes_cn.json").write_text(
        json.dumps(
            {
                str(index): {"name": name, "name_cn": config.names_cn[index]}
                for index, name in enumerate(config.names)
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "metadata" / "duplicates_removed.json").write_text(
        json.dumps(duplicates, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "task": task,
        "source": str(source),
        "output": str(output),
        "seed": seed,
        "val_ratio": val_ratio,
        "materialize": materialize,
        "images": dict(sorted(split_counts.items())),
        "source_groups": dict(sorted(group_counts.items())),
        "boxes": dict(sorted(class_counts.items())),
        "duplicates_removed": len(duplicates),
        "clipped_boxes": clipped_boxes,
        "skipped_shapes": skipped_shapes,
    }
    (output / "metadata" / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def prepare_output(output: Path, force: bool) -> None:
    resolved = output.resolve()
    if TRAINING_ROOT not in resolved.parents:
        raise ValueError(f"Output must be below {TRAINING_ROOT}: {resolved}")
    if output.exists():
        if not force:
            raise FileExistsError(f"Output already exists: {output}")
        shutil.rmtree(output)


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_dir():
        raise FileNotFoundError(source)

    prepare_output(output, args.force)
    json_paths = sorted(source.rglob("*.json"))
    if not json_paths:
        raise ValueError(f"No LabelMe JSON files found below {source}")

    records = [load_record(path, args.task) for path in json_paths]
    unique_records, duplicates = deduplicate(records)
    splits = split_records(unique_records, args.val_ratio, args.seed)
    write_dataset(
        task=args.task,
        source=source,
        output=output,
        splits=splits,
        duplicates=duplicates,
        seed=args.seed,
        val_ratio=args.val_ratio,
        materialize=args.materialize,
    )


if __name__ == "__main__":
    main()

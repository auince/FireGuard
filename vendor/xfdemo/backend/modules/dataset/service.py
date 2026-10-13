from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.common.images import send_image
from backend.config.paths import DATASET_FILES, DATASET_ROOT


def as_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _normalize_scope(meta):
    scope = str(meta.get("scope_label_in_answer") or meta.get("task") or "unknown")
    if scope == "internal_components":
        return "内部组件"
    return scope


def _assistant_text(row):
    return _message_text(row, "assistant")


def _message_text(row, role):
    for message in row.get("messages", []):
        if message.get("role") != role:
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("text"):
                    parts.append(item.get("text", ""))
                elif item.get("type") == "image" or item.get("image"):
                    parts.append("[image]")
            return "\n".join(parts)
    return ""


def _display_text(text):
    return str(text or "").replace("\n", "；")


def _source_name(source):
    source = str(source or "unknown")
    if "/training_data/" in source:
        return source.split("/training_data/", 1)[1]
    if "/archive_extracted" in source:
        return "archive_extracted"
    return source


def _clean_label(label, verdict):
    label_text = str(label or "").strip().strip("。.;；,，")
    if label_text in {"合规/无隐患", "无隐患", "无", "", "无隐患标签"}:
        return "合规样本" if verdict == "合规" else "未标注隐患标签"
    return label_text


def _normalize_labels(labels, verdict):
    if isinstance(labels, str):
        labels = [labels]
    normalized = []
    for label in labels or []:
        label_text = _clean_label(label, verdict)
        if label_text not in normalized:
            normalized.append(label_text)
    if normalized:
        return normalized
    return ["合规样本"] if verdict == "合规" else ["未标注隐患标签"]


def _assistant_field(assistant, field_name):
    prefix = f"{field_name}："
    for line in assistant.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            return line.split("：", 1)[1].strip()
    return ""


def _assistant_labels(assistant, verdict):
    label_text = _assistant_field(assistant, "隐患标签")
    if not label_text:
        return _normalize_labels([], verdict)
    parts = [part.strip() for part in re.split("[;；、,，]", label_text) if part.strip()]
    return _normalize_labels(parts, verdict)


def _label_source(meta, verdict):
    if meta.get("original_labels") or meta.get("categories") or meta.get("boxes"):
        return "原始标注字段"
    if verdict == "合规":
        return "合规样本集"
    return "meta.defect_labels"


def _label_status(true_labels, model_labels):
    truth = {label for label in true_labels if label not in {"未标注隐患标签"}}
    model = {label for label in model_labels if label not in {"未标注隐患标签"}}
    return "一致" if truth == model else "需核对"


def _image_size(image_path, meta):
    width = int(meta.get("image_width") or 0)
    height = int(meta.get("image_height") or 0)
    if width > 0 and height > 0:
        return width, height
    try:
        with open(image_path, "rb") as handle:
            header = handle.read(24)
            if header.startswith(b"\x89PNG\r\n\x1a\n"):
                return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
            handle.seek(0)
            if handle.read(2) == b"\xff\xd8":
                while True:
                    marker_start = handle.read(1)
                    if not marker_start:
                        break
                    if marker_start != b"\xff":
                        continue
                    marker = handle.read(1)
                    while marker == b"\xff":
                        marker = handle.read(1)
                    if marker in {b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6", b"\xc7", b"\xc9", b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"}:
                        handle.read(3)
                        h = int.from_bytes(handle.read(2), "big")
                        w = int.from_bytes(handle.read(2), "big")
                        return w, h
                    segment_length = int.from_bytes(handle.read(2), "big")
                    if segment_length < 2:
                        break
                    handle.seek(segment_length - 2, 1)
    except Exception:
        pass
    return width, height


def _annotation_boxes(meta, fallback_labels, image_width=0, image_height=0):
    boxes = []
    image_width = float(image_width or meta.get("image_width") or 0)
    image_height = float(image_height or meta.get("image_height") or 0)
    for index, box in enumerate(meta.get("boxes") or []):
        coords = box.get("bbox_norm_xyxy") or []
        if len(coords) != 4:
            xyxy = box.get("bbox_xyxy") or []
            if len(xyxy) == 4 and image_width > 0 and image_height > 0:
                coords = [xyxy[0] / image_width, xyxy[1] / image_height, xyxy[2] / image_width, xyxy[3] / image_height]
        if len(coords) != 4:
            continue
        x1, y1, x2, y2 = [max(0, min(1, float(value))) for value in coords]
        if x2 <= x1 or y2 <= y1:
            continue
        label = _clean_label(box.get("label") or (fallback_labels[index] if index < len(fallback_labels) else fallback_labels[0] if fallback_labels else ""), "")
        boxes.append({
            "label": label,
            "left": x1 * 100,
            "top": y1 * 100,
            "width": (x2 - x1) * 100,
            "height": (y2 - y1) * 100,
        })
    return boxes


def record_from_row(row, split):
    meta = row.get("meta") or {}
    verdict = str(meta.get("verdict", "unknown"))
    true_labels = _normalize_labels(meta.get("defect_labels") or meta.get("categories") or [], verdict)
    image_path = (row.get("images") or [""])[0]
    image_width, image_height = _image_size(image_path, meta)
    assistant_raw = _assistant_text(row)
    model_verdict = _assistant_field(assistant_raw, "结论") or verdict
    model_scope = _assistant_field(assistant_raw, "检查范围") or _normalize_scope(meta)
    model_labels = _assistant_labels(assistant_raw, model_verdict)
    label_status = _label_status(true_labels, model_labels)
    annotation_boxes = _annotation_boxes(meta, true_labels, image_width, image_height)
    assistant = _display_text(assistant_raw)
    return {
        "id": row.get("id", ""),
        "split": split,
        "imagePath": image_path,
        "imageUrl": f"/api/dataset/image?path={image_path}" if image_path else "",
        "imageWidth": image_width,
        "imageHeight": image_height,
        "annotationBoxes": annotation_boxes,
        "verdict": verdict,
        "scope": _normalize_scope(meta),
        "defectLabels": true_labels,
        "trueLabels": true_labels,
        "trueLabelSource": _label_source(meta, verdict),
        "originalLabels": meta.get("original_labels") or meta.get("categories") or [],
        "modelVerdict": model_verdict,
        "modelScope": model_scope,
        "modelLabels": model_labels,
        "modelSource": "assistant 输出解析",
        "labelStatus": label_status,
        "labelMatched": label_status == "一致",
        "primaryCategory": meta.get("primary_category", ""),
        "sourceDataset": _source_name(meta.get("source_dataset", "")),
        "promptVersion": meta.get("prompt_version", ""),
        "assistantExcerpt": assistant[:900],
        "assistantText": assistant,
    }


def iter_dataset_rows(split):
    dataset_path = DATASET_FILES.get(split, DATASET_FILES["train"])
    if not dataset_path.exists():
        return
    with dataset_path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def list_ultra_strict_samples(split, page, page_size, verdict_filter="", scope_filter="", defect_filter="", query=""):
    records = []
    total = 0
    start = (page - 1) * page_size
    end = start + page_size
    query = query.strip().lower()
    for row in iter_dataset_rows(split):
        record = record_from_row(row, split)
        if verdict_filter and record["verdict"] != verdict_filter:
            continue
        if scope_filter and record["scope"] != scope_filter:
            continue
        if defect_filter and defect_filter not in record["defectLabels"]:
            continue
        if query:
            haystack = " ".join(
                [
                    record["id"],
                    record["imagePath"],
                    record["verdict"],
                    record["scope"],
                    record["modelVerdict"],
                    record["modelScope"],
                    record["labelStatus"],
                    record["primaryCategory"],
                    record["sourceDataset"],
                    record["assistantExcerpt"],
                    " ".join(record["trueLabels"]),
                    " ".join(record["modelLabels"]),
                ]
            ).lower()
            if query not in haystack:
                continue
        if start <= total < end:
            records.append(record)
        total += 1
    return {
        "records": records,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


def send_dataset_image(raw_path):
    image_path = Path(raw_path).expanduser().resolve()
    image_path.relative_to(DATASET_ROOT)
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(raw_path)
    return send_image(image_path)

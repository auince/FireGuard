from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover
    Image = None
    ImageDraw = None
    PIL_IMPORT_ERROR = exc
else:
    PIL_IMPORT_ERROR = None

from backend.common.images import decode_data_url, image_extension, send_image, versioned_image_url
from backend.config.paths import INSPECTION_HISTORY_DIR, INSPECTION_HISTORY_FILE, INSPECTION_HISTORY_IMAGE_DIR
from backend.modules.history.report_document import VERDICT_LABELS, parse_report_document
from backend.modules.history.report_revision import (
    clear_report_revisions,
    delete_report_revisions_for_record,
    report_revisions_by_record,
    report_revision_state,
)


logger = logging.getLogger(__name__)


def now_text():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def history_image_path(filename):
    if not filename:
        return None
    path = (INSPECTION_HISTORY_IMAGE_DIR / filename).resolve()
    path.relative_to(INSPECTION_HISTORY_IMAGE_DIR.resolve())
    return path


def store_history_image(image):
    if not image:
        return {"imageUrl": "", "imageName": "", "imageBytes": 0, "imagePath": None}
    if isinstance(image, str) and not image.startswith("data:"):
        filename = image.rsplit("/", 1)[-1]
        return {"imageUrl": image, "imageName": filename, "imageBytes": 0, "imagePath": history_image_path(filename)}
    content, mime = decode_data_url(image)
    if not content:
        return {"imageUrl": "", "imageName": "", "imageBytes": 0, "imagePath": None}
    INSPECTION_HISTORY_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(content).hexdigest()[:16]
    filename = f"{datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d_%H%M%S')}_{digest}{image_extension(mime)}"
    path = INSPECTION_HISTORY_IMAGE_DIR / filename
    if not path.exists():
        path.write_bytes(content)
    return {
        "imageUrl": versioned_image_url("/api/history/image/", path),
        "imageName": filename,
        "imageBytes": len(content),
        "imagePath": path,
    }


def render_yolo_history_image(image_path, yolo):
    if Image is None or ImageDraw is None:
        logger.warning("YOLO history visualization unavailable: Pillow import failed: %s", PIL_IMPORT_ERROR)
        return {"yoloImageUrl": "", "yoloImageName": ""}
    if not image_path or not Path(image_path).exists():
        logger.warning("YOLO history visualization skipped: source image is missing: %s", image_path)
        return {"yoloImageUrl": "", "yoloImageName": ""}
    detections = (yolo or {}).get("detections") or []
    if not detections:
        return {"yoloImageUrl": "", "yoloImageName": ""}
    try:
        image = Image.open(image_path).convert("RGB")
    except Exception as exc:
        logger.warning("YOLO history visualization could not open %s: %s", image_path, exc)
        return {"yoloImageUrl": "", "yoloImageName": ""}
    draw = ImageDraw.Draw(image)
    width, height = image.size
    stroke = max(3, int(min(width, height) * 0.004))
    badge_size = max(22, int(min(width, height) * 0.032))
    for index, item in enumerate(detections, 1):
        bbox = item.get("bbox") or []
        if len(bbox) != 4:
            bbox_norm = item.get("bboxNorm") or []
            if len(bbox_norm) == 4:
                bbox = [bbox_norm[0] * width, bbox_norm[1] * height, bbox_norm[2] * width, bbox_norm[3] * height]
        if len(bbox) != 4:
            continue
        x1, y1, x2, y2 = [float(v) for v in bbox]
        x1 = max(0, min(width - 1, x1))
        y1 = max(0, min(height - 1, y1))
        x2 = max(x1 + 1, min(width, x2))
        y2 = max(y1 + 1, min(height, y2))
        draw.rectangle([x1, y1, x2, y2], outline=(220, 38, 38), width=stroke)
        bx = max(2, min(width - badge_size - 2, x1 + 4))
        by = max(2, min(height - badge_size - 2, y1 + 4))
        draw.rounded_rectangle([bx, by, bx + badge_size, by + badge_size], radius=badge_size // 2, fill=(220, 38, 38), outline=(255, 255, 255), width=max(1, stroke // 2))
        number = str(index)
        try:
            tb = draw.textbbox((0, 0), number)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        except Exception:
            tw, th = len(number) * 6, 10
        draw.text((bx + (badge_size - tw) / 2, by + (badge_size - th) / 2 - 1), number, fill=(255, 255, 255))
    output_name = f"{Path(image_path).stem}_yolo{Path(image_path).suffix or '.jpg'}"
    output_path = INSPECTION_HISTORY_IMAGE_DIR / output_name
    try:
        image.save(output_path)
    except Exception as exc:
        logger.warning("YOLO history visualization could not save %s: %s", output_path, exc)
        return {"yoloImageUrl": "", "yoloImageName": ""}
    return {
        "yoloImageUrl": versioned_image_url("/api/history/image/", output_path),
        "yoloImageName": output_name,
    }


def parse_report_fields(report):
    report = str(report or "")
    cn_colon = chr(0xFF1A)
    cn_period = chr(0x3002)
    cn_semicolon = chr(0xFF1B)
    cn_dot = chr(0x3001)
    cn_comma = chr(0xFF0C)

    def pick(name, stop_at_semicolon=True):
        separators = ":" + cn_colon
        stops = "\n" + (";" + cn_semicolon if stop_at_semicolon else "")
        pattern = re.escape(name) + r"\s*[" + re.escape(separators) + r"]\s*([^" + re.escape(stops) + r"]+)"
        match = re.search(pattern, report)
        return match.group(1).strip().strip(cn_period + cn_semicolon + ";") if match else ""

    labels_text = pick("隐患标签", stop_at_semicolon=False)
    suggestions_text = pick("建议项", stop_at_semicolon=False)
    split_chars = cn_semicolon + ";" + cn_dot + "," + cn_comma
    labels = [part.strip().strip(cn_period) for part in re.split("[" + re.escape(split_chars) + "]", labels_text) if part.strip()]
    if labels == ["无"]:
        labels = []
    suggestions = [part.strip().strip(cn_period) for part in re.split("[" + re.escape(split_chars) + "]", suggestions_text) if part.strip()]
    if suggestions == ["无"]:
        suggestions = []
    return {
        "scope": pick("检查范围"),
        "verdict": pick("结论"),
        "labels": labels,
        "suggestions": suggestions,
    }


def append_history(data, response, usage=None, finish_reason="", task="", yolo=None, trace=None):
    INSPECTION_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    image_info = store_history_image((data or {}).get("image"))
    yolo_image_info = render_yolo_history_image(image_info.get("imagePath"), yolo)
    parsed = parse_report_fields(response)
    trace_final = ((trace or {}).get("summary") or {}).get("final") or {}
    if not parsed.get("scope") and trace_final.get("scope"):
        parsed["scope"] = trace_final.get("scope")
    if not parsed.get("verdict") and trace_final.get("verdict"):
        parsed["verdict"] = trace_final.get("verdict")
    if not parsed.get("labels") and trace_final.get("labels"):
        parsed["labels"] = trace_final.get("labels")
    record = {
        "id": uuid.uuid4().hex[:12],
        "createdAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "createdText": now_text(),
        "query": (data or {}).get("query", ""),
        "imageUrl": image_info["imageUrl"],
        "imageName": image_info["imageName"],
        "imageBytes": image_info["imageBytes"],
        "yoloImageUrl": yolo_image_info.get("yoloImageUrl", ""),
        "yoloImageName": yolo_image_info.get("yoloImageName", ""),
        "response": response or "",
        "responseExcerpt": (response or "")[:500],
        "modelReportDocument": parse_report_document(response or ""),
        "usage": usage or {},
        "finishReason": finish_reason,
        "task": task,
        "yolo": yolo or {},
        "trace": trace or {},
        **parsed,
    }
    with INSPECTION_HISTORY_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {**record, **report_revision_state(record)}


def read_history_records(reverse=True):
    if not INSPECTION_HISTORY_FILE.exists():
        return []
    records = []
    with INSPECTION_HISTORY_FILE.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if reverse:
        records.reverse()
    return records


def get_history_record(record_id):
    for record in read_history_records(reverse=False):
        if record.get("id") == record_id:
            return record
    raise KeyError(record_id)


def write_history_records(records):
    INSPECTION_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = INSPECTION_HISTORY_FILE.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    temp_file.replace(INSPECTION_HISTORY_FILE)


def delete_history_images(record):
    for field in ("imageName", "yoloImageName"):
        image_name = record.get(field) or ""
        if not image_name:
            continue
        try:
            image_path = history_image_path(image_name)
        except Exception:
            continue
        try:
            image_path.unlink(missing_ok=True)
        except TypeError:
            if image_path.exists():
                image_path.unlink()


def trace_summary(record):
    trace = record.get("trace") or {}
    return trace.get("summary") or {}


def trace_issues(record):
    return trace_summary(record).get("issues") or []


def trace_has_issue(record, issue_type):
    return any(issue.get("type") == issue_type for issue in trace_issues(record))


def list_history(page, page_size, verdict_filter="", query=""):
    records = []
    grouped_reviews = reviews_by_record()
    grouped_revisions = report_revisions_by_record()
    for original_record in read_history_records():
        record = dict(original_record)
        revision_state = report_revision_state(
            record,
            grouped_revisions.get(str(record.get("id") or ""), []),
        )
        record.update(revision_state)
        effective_document = revision_state["effectiveReportDocument"]
        record["modelVerdict"] = record.get("verdict") or ""
        record["verdict"] = VERDICT_LABELS[effective_document["verdict"]]
        record["responseExcerpt"] = revision_state["effectiveResponse"][:500]
        if revision_state["reportRevisionSummary"]["hasCorrection"]:
            record["labels"] = []
        image_name = record.get("imageName") or ""
        if image_name:
            record["imageUrl"] = versioned_image_url("/api/history/image/", INSPECTION_HISTORY_IMAGE_DIR / image_name)
        yolo_image_name = record.get("yoloImageName") or ""
        if yolo_image_name:
            record["yoloImageUrl"] = versioned_image_url("/api/history/image/", INSPECTION_HISTORY_IMAGE_DIR / yolo_image_name)
        if verdict_filter and record.get("verdict") != verdict_filter:
            continue
        if query:
            haystack = " ".join(
                [
                    record.get("id", ""),
                    record.get("createdText", ""),
                    record.get("query", ""),
                    record.get("imageName", ""),
                    record.get("verdict", ""),
                    record.get("scope", ""),
                    " ".join(record.get("labels") or []),
                    record.get("responseExcerpt", ""),
                ]
            ).lower()
            if query.lower() not in haystack:
                continue
        record_reviews = grouped_reviews.get(record.get("id") or "", [])
        record["reviews"] = record_reviews
        record["reviewSummary"] = summarize_reviews(record_reviews)
        if not record.get("reviewNote") and record_reviews:
            record["reviewNote"] = str(record_reviews[0].get("comment") or "")
        records.append(record)
    total = len(records)
    start = (page - 1) * page_size
    return {"records": records[start:start + page_size], "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size}


def clear_history():
    records = read_history_records(reverse=False)
    for record in records:
        delete_history_images(record)
    if INSPECTION_HISTORY_FILE.exists():
        INSPECTION_HISTORY_FILE.unlink()
    clear_reviews()
    clear_report_revisions()
    return {"deleted": True, "count": len(records)}


def delete_history_record(record_id):
    records = read_history_records(reverse=False)
    kept = []
    deleted = None
    for record in records:
        if record.get("id") == record_id:
            deleted = record
            continue
        kept.append(record)
    if deleted is None:
        raise KeyError(record_id)
    write_history_records(kept)
    delete_history_images(deleted)
    delete_reviews_for_record(record_id)
    delete_report_revisions_for_record(record_id)
    return {"deleted": True, "id": record_id}


def send_history_image(filename):
    image_path = (INSPECTION_HISTORY_IMAGE_DIR / filename).resolve()
    image_path.relative_to(INSPECTION_HISTORY_IMAGE_DIR.resolve())
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(filename)
    return send_image(image_path)




INSPECTION_REVIEW_FILE = INSPECTION_HISTORY_DIR / "reviews.jsonl"


def _compact_text(value, limit=2000):
    text = str(value or "").strip()
    return text[:limit]


def read_review_records(reverse=True):
    if not INSPECTION_REVIEW_FILE.exists():
        return []
    reviews = []
    with INSPECTION_REVIEW_FILE.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                reviews.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if reverse:
        reviews.reverse()
    return reviews


def write_review_records(reviews):
    INSPECTION_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = INSPECTION_REVIEW_FILE.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as handle:
        for review in reviews:
            handle.write(json.dumps(review, ensure_ascii=False) + "\n")
    temp_file.replace(INSPECTION_REVIEW_FILE)


def reviews_by_record():
    grouped = {}
    for review in read_review_records():
        grouped.setdefault(review.get("recordId") or "", []).append(review)
    return grouped


def list_reviews(record_id=""):
    reviews = read_review_records()
    if record_id:
        reviews = [review for review in reviews if review.get("recordId") == record_id]
    return {"records": reviews, "total": len(reviews)}


def summarize_reviews(reviews):
    if not reviews:
        return {"count": 0, "latest": None, "hasCorrection": False}
    latest = reviews[0]
    return {
        "count": len(reviews),
        "latest": latest,
        "hasCorrection": bool(latest.get("correctedVerdict") or latest.get("correctedLabels")),
    }


def create_review(data):
    payload = data or {}
    record_id = _compact_text(payload.get("recordId"), 80)
    if not record_id:
        raise ValueError("record_id required")
    if not any(record.get("id") == record_id for record in read_history_records(reverse=False)):
        raise KeyError(record_id)
    corrected_labels = payload.get("correctedLabels") or []
    if isinstance(corrected_labels, str):
        corrected_labels = [part.strip() for part in re.split("[\n;\uFF1B,\uFF0C]", corrected_labels) if part.strip()]
    review = {
        "id": uuid.uuid4().hex[:12],
        "recordId": record_id,
        "createdAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "createdText": now_text(),
        "reviewer": _compact_text(payload.get("reviewer") or "\u4eba\u5de5\u590d\u6838", 80),
        "acceptModelResult": payload.get("acceptModelResult") if isinstance(payload.get("acceptModelResult"), bool) else None,
        "correctedVerdict": _compact_text(payload.get("correctedVerdict"), 40),
        "correctedLabels": [_compact_text(item, 120) for item in corrected_labels if _compact_text(item, 120)][:20],
        "errorSource": _compact_text(payload.get("errorSource"), 40),
        "comment": _compact_text(payload.get("comment"), 2000),
        "useForTraining": bool(payload.get("useForTraining")),
    }
    INSPECTION_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with INSPECTION_REVIEW_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(review, ensure_ascii=False) + "\n")
    return review


def delete_review(review_id):
    reviews = read_review_records(reverse=False)
    kept = []
    deleted = None
    for review in reviews:
        if review.get("id") == review_id:
            deleted = review
            continue
        kept.append(review)
    if deleted is None:
        raise KeyError(review_id)
    write_review_records(kept)
    return {"deleted": True, "id": review_id}


def delete_reviews_for_record(record_id):
    reviews = read_review_records(reverse=False)
    kept = [review for review in reviews if review.get("recordId") != record_id]
    if len(kept) != len(reviews):
        write_review_records(kept)


def clear_reviews():
    count = len(read_review_records(reverse=False))
    if INSPECTION_REVIEW_FILE.exists():
        INSPECTION_REVIEW_FILE.unlink()
    return count


def inspection_monitor_stats(limit):
    records = read_history_records()[:limit]
    traced = [record for record in records if record.get("trace")]
    total_input_tokens = 0
    total_output_tokens = 0
    total_duration_ms = 0
    for record in records:
        usage = record.get("usage") or {}
        total_input_tokens += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        total_output_tokens += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_duration_ms += int(((record.get("trace") or {}).get("summary") or {}).get("totalDurationMs") or 0)
    stage_totals = {}
    for record in traced:
        for stage in (record.get("trace") or {}).get("stages") or []:
            name = stage.get("name") or "unknown"
            bucket = stage_totals.setdefault(name, {"name": name, "title": stage.get("title") or name, "count": 0, "warn": 0, "error": 0, "skipped": 0, "totalDurationMs": 0})
            bucket["count"] += 1
            bucket["totalDurationMs"] += int(stage.get("durationMs") or 0)
            if stage.get("status") == "warn":
                bucket["warn"] += 1
            if stage.get("status") == "error":
                bucket["error"] += 1
            if stage.get("status") == "skipped":
                bucket["skipped"] += 1
    stages = []
    for bucket in stage_totals.values():
        count = bucket["count"] or 1
        stages.append({**bucket, "avgDurationMs": round(bucket["totalDurationMs"] / count)})
    stages.sort(key=lambda item: item["name"])
    recent = []
    for record in records[:30]:
        item = dict(record)
        image_name = item.get("imageName") or ""
        if image_name:
            item["imageUrl"] = versioned_image_url("/api/history/image/", INSPECTION_HISTORY_IMAGE_DIR / image_name)
        yolo_image_name = item.get("yoloImageName") or ""
        if yolo_image_name:
            item["yoloImageUrl"] = versioned_image_url("/api/history/image/", INSPECTION_HISTORY_IMAGE_DIR / yolo_image_name)
        recent.append(item)
    return {
        "total": len(records),
        "withTrace": len(traced),
        "usage": {
            "inputTokens": total_input_tokens,
            "outputTokens": total_output_tokens,
            "totalTokens": total_input_tokens + total_output_tokens,
            "inputTokensPerSecond": round(total_input_tokens / max(total_duration_ms / 1000, 0.001), 2),
            "outputTokensPerSecond": round(total_output_tokens / max(total_duration_ms / 1000, 0.001), 2),
            "avgDurationMs": round(total_duration_ms / max(len(traced), 1)),
        },
        "qwenCorrected": sum(1 for record in traced if trace_has_issue(record, "qwen_corrected")),
        "yoloPossibleMiss": sum(1 for record in traced if trace_has_issue(record, "yolo_possible_miss")),
        "yoloPossibleFalsePositive": sum(1 for record in traced if trace_has_issue(record, "yolo_possible_false_positive")),
        "vlmFallbackUsed": sum(1 for record in traced if trace_has_issue(record, "vlm_fallback_used")),
        "judgeNeedsManualReview": sum(1 for record in traced if trace_has_issue(record, "judge_needs_manual_review")),
        "yoloUnavailable": sum(1 for record in traced if trace_has_issue(record, "yolo_unavailable")),
        "stages": stages,
        "recent": recent,
    }

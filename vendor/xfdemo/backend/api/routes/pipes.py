from __future__ import annotations

import base64
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request, send_file

from backend.infrastructure.pipes.client import PipeCountingError, get_pipe_counting_client


from backend.config.paths import PIPE_HISTORY_DIR as HISTORY_ROOT, PIPE_HISTORY_IMAGE_DIR as HISTORY_IMAGES, PIPE_HISTORY_FILE as HISTORY_FILE
MAX_IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_history_lock = threading.Lock()

pipes_bp = Blueprint("pipes", __name__)


def _now_text() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def _decode_image(value: Any) -> tuple[bytes, str]:
    if not isinstance(value, str) or not value.startswith("data:image/"):
        raise ValueError("请上传有效图片")
    header, separator, payload = value.partition(",")
    if not separator or not payload:
        raise ValueError("图片数据不完整")
    mime = header[5:].split(";", 1)[0].lower()
    if mime not in {"image/jpeg", "image/jpg", "image/png", "image/webp"}:
        raise ValueError("仅支持 JPG、PNG、WEBP 图片")
    try:
        content = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError("图片数据无法解析") from exc
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("图片为空或超过 20MB")
    return content, mime


def _image_suffix(mime: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(mime, ".jpg")


def _store_image(content: bytes, mime: str) -> tuple[str, str]:
    HISTORY_IMAGES.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{_image_suffix(mime)}"
    (HISTORY_IMAGES / filename).write_bytes(content)
    return filename, f"/api/pipes/history/image/{quote(filename)}"


def _read_records() -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    records = []
    for line in HISTORY_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _write_records(records: list[dict[str, Any]]) -> None:
    HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(item, ensure_ascii=False) for item in records)
    HISTORY_FILE.write_text(text + ("\n" if text else ""), encoding="utf-8")


def _append_record(result: dict[str, Any], image_name: str, image_url: str) -> dict[str, Any]:
    record = {
        "id": uuid.uuid4().hex,
        "createdAt": _now_text(),
        "imageName": image_name,
        "imageUrl": image_url,
        "total": int(result.get("total") or 0),
        "counts": result.get("counts") or {},
        "detections": result.get("detections") or [],
        "classes": result.get("classes") or [],
        "imageWidth": int(result.get("imageWidth") or 0),
        "imageHeight": int(result.get("imageHeight") or 0),
        "confidence": result.get("confidence"),
        "iou": result.get("iou"),
        "elapsedMs": int(result.get("elapsedMs") or 0),
        "inferenceMs": int(result.get("inferenceMs") or 0),
        "modelVersion": result.get("modelVersion") or "",
    }
    with _history_lock:
        records = _read_records()
        records.append(record)
        _write_records(records[-500:])
    return record


def _safe_history_image(filename: str) -> Path | None:
    path = (HISTORY_IMAGES / filename).resolve()
    try:
        path.relative_to(HISTORY_IMAGES.resolve())
    except ValueError:
        return None
    return path


@pipes_bp.get("/pipes/health")
def pipes_health():
    try:
        result = get_pipe_counting_client().health()
        return jsonify(result)
    except PipeCountingError as exc:
        return jsonify({"status": "unavailable", "error": str(exc)}), 503


@pipes_bp.post("/pipes/count")
def count_pipes():
    payload = request.get_json(silent=True) or {}
    try:
        content, mime = _decode_image(payload.get("image"))
        service_payload = {
            "image": payload.get("image"),
            "confidence": payload.get("confidence", 0.25),
            "iou": payload.get("iou", 0.45),
            "classes": payload.get("classes", [0, 1, 2, 3]),
            "imageSize": payload.get("imageSize", 640),
            "maxDetections": payload.get("maxDetections", 2000),
        }
        result = get_pipe_counting_client().count(service_payload)
        image_name, image_url = _store_image(content, mime)
        record = _append_record(result, image_name, image_url)
        return jsonify({**result, "history": record})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except PipeCountingError as exc:
        return jsonify({"error": str(exc)}), 502


@pipes_bp.get("/pipes/history")
def pipe_history():
    try:
        limit = max(1, min(100, int(request.args.get("limit", "20"))))
    except ValueError:
        limit = 20
    with _history_lock:
        records = list(reversed(_read_records()))[:limit]
    return jsonify({"records": records, "total": len(records)})


@pipes_bp.delete("/pipes/history")
def clear_pipe_history():
    with _history_lock:
        records = _read_records()
        for record in records:
            path = _safe_history_image(str(record.get("imageName") or ""))
            if path and path.exists():
                path.unlink()
        _write_records([])
    return jsonify({"deleted": len(records)})


@pipes_bp.delete("/pipes/history/<record_id>")
def delete_pipe_history(record_id: str):
    with _history_lock:
        records = _read_records()
        deleted = next((item for item in records if item.get("id") == record_id), None)
        if not deleted:
            return jsonify({"error": "计数记录不存在"}), 404
        kept = [item for item in records if item.get("id") != record_id]
        _write_records(kept)
        path = _safe_history_image(str(deleted.get("imageName") or ""))
        if path and path.exists():
            path.unlink()
    return jsonify({"deleted": 1})


@pipes_bp.get("/pipes/history/image/<path:filename>")
def pipe_history_image(filename: str):
    path = _safe_history_image(filename)
    if not path or not path.exists() or not path.is_file():
        return jsonify({"error": "图片不存在"}), 404
    return send_file(
        path,
        mimetype=IMAGE_MIME_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        conditional=True,
        max_age=0,
    )

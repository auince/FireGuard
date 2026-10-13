from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import quote

from flask import send_file

IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def decode_data_url(image: str | None):
    if not isinstance(image, str) or not image.startswith("data:"):
        return None, None
    header, _, payload = image.partition(",")
    if not payload:
        return None, None
    mime = header[5:].split(";", 1)[0] or "image/jpeg"
    try:
        return base64.b64decode(payload), mime
    except Exception:
        return None, None


def image_extension(mime: str | None) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    return mapping.get(str(mime or "").lower(), ".jpg")


def versioned_image_url(prefix: str, image_path: Path) -> str:
    version = ""
    try:
        stat = image_path.stat()
        version = f"?v={stat.st_mtime_ns:x}-{stat.st_size:x}"
    except OSError:
        pass
    return f"{prefix}{quote(image_path.name)}{version}"


def send_image(image_path: Path):
    mimetype = IMAGE_MIME_TYPES.get(image_path.suffix.lower(), "application/octet-stream")
    response = send_file(image_path, mimetype=mimetype, conditional=True, max_age=0)
    response.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

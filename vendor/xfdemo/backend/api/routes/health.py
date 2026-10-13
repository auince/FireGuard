from flask import Blueprint, jsonify

from backend.config.settings import get_settings
from backend.infrastructure.database.postgres import database_is_ready

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health():
    settings = get_settings()
    missing = []
    if not settings.api_key:
        missing.append("DASHSCOPE_API_KEY")
    return jsonify(
        {
            "status": "running",
            "provider": "aliyun-compatible-openai",
            "configured": not missing,
            "missing": missing,
            "base_url": settings.base_url,
            "model": settings.model,
            "enable_thinking": settings.enable_thinking,
            "database": "ready" if database_is_ready() else "unavailable",
        }
    )

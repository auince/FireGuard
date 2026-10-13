from __future__ import annotations

from flask import Flask, g, jsonify, request

from backend.config.auth import get_auth_settings
from backend.modules.auth.service import user_from_session


PUBLIC_ENDPOINTS = {
    "health.health",
    "auth.login",
    "auth.register",
}


def register_auth_guard(app: Flask) -> None:
    @app.before_request
    def require_authenticated_user():
        if request.method == "OPTIONS" or request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if request.endpoint is None:
            return None
        settings = get_auth_settings()
        user = user_from_session(request.cookies.get(settings.cookie_name))
        if not user:
            return jsonify({"error": "登录状态已失效，请重新登录"}), 401
        g.current_user = user
        return None

from __future__ import annotations

from flask import Blueprint, g, jsonify, make_response, request

from backend.config.auth import get_auth_settings
from backend.modules.auth.service import (
    AuthError,
    authenticate_user,
    create_session,
    public_user,
    register_user,
    revoke_session,
)


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _set_session_cookie(response, token: str) -> None:
    settings = get_auth_settings()
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.session_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="Lax",
        path="/",
    )


def _clear_session_cookie(response) -> None:
    settings = get_auth_settings()
    response.delete_cookie(
        settings.cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="Lax",
        path="/",
    )


@auth_bp.post("/register")
def register():
    try:
        user = register_user(request.get_json(silent=True) or {})
        token = create_session(user["id"])
        response = make_response(jsonify({"user": user}), 201)
        _set_session_cookie(response, token)
        return response
    except AuthError as exc:
        return jsonify({"error": str(exc)}), exc.status_code


@auth_bp.post("/login")
def login():
    try:
        data = request.get_json(silent=True) or {}
        user_row = authenticate_user(
            str(data.get("identifier") or ""),
            str(data.get("password") or ""),
        )
        token = create_session(str(user_row["id"]))
        response = make_response(jsonify({"user": public_user(user_row)}))
        _set_session_cookie(response, token)
        return response
    except AuthError as exc:
        return jsonify({"error": str(exc)}), exc.status_code


@auth_bp.post("/logout")
def logout():
    settings = get_auth_settings()
    revoke_session(request.cookies.get(settings.cookie_name))
    response = make_response(jsonify({"ok": True}))
    _clear_session_cookie(response)
    return response


@auth_bp.get("/me")
def me():
    return jsonify({"user": g.current_user})

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg2 import errors
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash

from backend.config.auth import get_auth_settings
from backend.infrastructure.database.postgres import database_connection


USERNAME_PATTERN = re.compile(r"^[\w\u4e00-\u9fff-]{3,24}$", re.UNICODE)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AuthError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    created_at = row.get("created_at")
    return {
        "id": str(row["id"]),
        "username": row["username"],
        "email": row["email"],
        "displayName": row["display_name"],
        "role": row.get("role") or "user",
        "createdAt": created_at.isoformat() if created_at else None,
    }


def _validate_registration(username: str, email: str, password: str, display_name: str) -> None:
    if not USERNAME_PATTERN.fullmatch(username):
        raise AuthError("用户名需为 3-24 位中文、字母、数字、下划线或连字符")
    if not EMAIL_PATTERN.fullmatch(email) or len(email) > 254:
        raise AuthError("请输入有效的邮箱地址")
    if len(password) < 8 or len(password) > 128:
        raise AuthError("密码长度需为 8-128 位")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise AuthError("密码需同时包含字母和数字")
    if not 1 <= len(display_name) <= 48:
        raise AuthError("显示名称长度需为 1-48 位")


def register_user(payload: dict[str, Any]) -> dict[str, Any]:
    username = str(payload.get("username") or "").strip()
    email = str(payload.get("email") or "").strip()
    password = str(payload.get("password") or "")
    display_name = str(payload.get("displayName") or username).strip()
    _validate_registration(username, email, password, display_name)

    user_id = uuid.uuid4()
    try:
        with database_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        id, username, username_normalized, email, email_normalized,
                        display_name, password_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, username, email, display_name, role, created_at
                    """,
                    (
                        str(user_id), username, username.casefold(), email,
                        email.casefold(), display_name,
                        generate_password_hash(password, method="scrypt"),
                    ),
                )
                row = cursor.fetchone()
    except errors.UniqueViolation as exc:
        constraint = exc.diag.constraint_name or ""
        field = "邮箱" if "email" in constraint else "用户名"
        raise AuthError(f"该{field}已被注册", 409) from exc
    return public_user(dict(row))


def authenticate_user(identifier: str, password: str) -> dict[str, Any]:
    normalized = identifier.strip().casefold()
    if not normalized or not password:
        raise AuthError("请输入用户名/邮箱和密码")
    with database_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, username, email, display_name, password_hash, role, created_at
                FROM users
                WHERE is_active = TRUE
                  AND (username_normalized = %s OR email_normalized = %s)
                LIMIT 1
                """,
                (normalized, normalized),
            )
            row = cursor.fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        raise AuthError("用户名、邮箱或密码错误", 401)
    return dict(row)


def create_session(user_id: str) -> str:
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=get_auth_settings().session_days)
    with database_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM auth_sessions WHERE expires_at <= NOW()")
            cursor.execute(
                """
                INSERT INTO auth_sessions (id, user_id, token_hash, expires_at)
                VALUES (%s, %s, %s, %s)
                """,
                (str(uuid.uuid4()), user_id, token_hash, expires_at),
            )
    return raw_token


def user_from_session(raw_token: str | None) -> dict[str, Any] | None:
    if not raw_token:
        return None
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with database_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE auth_sessions AS sessions
                SET last_seen_at = NOW()
                FROM users
                WHERE sessions.user_id = users.id
                  AND sessions.token_hash = %s
                  AND sessions.expires_at > NOW()
                  AND users.is_active = TRUE
                RETURNING users.id, users.username, users.email,
                          users.display_name, users.role, users.created_at
                """,
                (token_hash,),
            )
            row = cursor.fetchone()
    return public_user(dict(row)) if row else None


def revoke_session(raw_token: str | None) -> None:
    if not raw_token:
        return
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with database_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM auth_sessions WHERE token_hash = %s", (token_hash,))

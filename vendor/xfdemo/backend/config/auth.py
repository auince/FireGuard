from __future__ import annotations

import os
from dataclasses import dataclass

from backend.config.settings import env_bool, env_int, first_env, load_env


@dataclass(frozen=True)
class AuthSettings:
    database_url: str
    cookie_name: str
    cookie_secure: bool
    session_days: int


def get_auth_settings() -> AuthSettings:
    load_env()
    return AuthSettings(
        database_url=first_env("AUTH_DATABASE_URL", "DATABASE_URL") or "",
        cookie_name=os.getenv("AUTH_COOKIE_NAME", "xf_session").strip() or "xf_session",
        cookie_secure=env_bool("AUTH_COOKIE_SECURE", "false"),
        session_days=max(1, env_int("AUTH_SESSION_DAYS", "7")),
    )

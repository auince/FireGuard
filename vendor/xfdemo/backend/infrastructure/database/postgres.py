from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator

from psycopg2 import pool
from psycopg2.extensions import connection

from backend.config.auth import get_auth_settings


_pool: pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username VARCHAR(32) NOT NULL,
    username_normalized VARCHAR(32) NOT NULL UNIQUE,
    email VARCHAR(254) NOT NULL,
    email_normalized VARCHAR(254) NOT NULL UNIQUE,
    display_name VARCHAR(48) NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(16) NOT NULL DEFAULT 'user',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS role VARCHAR(16) NOT NULL DEFAULT 'user';

CREATE TABLE IF NOT EXISTS auth_sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at);
"""


def get_pool() -> pool.ThreadedConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            database_url = get_auth_settings().database_url
            if not database_url:
                raise RuntimeError("AUTH_DATABASE_URL is not configured")
            _pool = pool.ThreadedConnectionPool(1, 10, database_url, connect_timeout=5)
    return _pool


@contextmanager
def database_connection() -> Iterator[connection]:
    database_pool = get_pool()
    conn = database_pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        database_pool.putconn(conn)


def init_database(attempts: int = 12, delay_seconds: float = 1.5) -> None:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with database_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(SCHEMA_SQL)
            return
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(delay_seconds)
    raise RuntimeError("PostgreSQL initialization failed") from last_error


def database_is_ready() -> bool:
    try:
        with database_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
    except Exception:
        return False

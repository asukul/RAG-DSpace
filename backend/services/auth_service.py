"""
Authentication service.

- Verifies Google ID tokens (issued by Google Identity Services on the frontend).
- Issues backend session JWTs signed with `JWT_SECRET`.
- Persists users + search activity in a small SQLite database.
- Bootstraps the first admin (adisak.sukul@gmail.com) on initialization.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "USERS_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "users.db"),
)
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me-please-32chars-min")
JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = int(os.environ.get("JWT_TTL_HOURS", "24"))

GOOGLE_OAUTH_CLIENT_ID = os.environ.get(
    "GOOGLE_OAUTH_CLIENT_ID",
    "",  # Set per environment; verification will fail loudly if missing.
)

DEFAULT_ADMIN_EMAIL = os.environ.get(
    "DEFAULT_ADMIN_EMAIL", "adisak.sukul@gmail.com"
).lower()


class AuthService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._google_request = google_requests.Request()
        self._init_db()
        self._bootstrap_admin()

    # ------------------------------------------------------------------
    # SQLite
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    email        TEXT UNIQUE NOT NULL,
                    google_sub   TEXT UNIQUE,
                    name         TEXT,
                    picture      TEXT,
                    role         TEXT NOT NULL DEFAULT 'user',
                    created_at   TEXT NOT NULL,
                    last_login   TEXT
                );

                CREATE TABLE IF NOT EXISTS search_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      INTEGER,
                    query        TEXT NOT NULL,
                    mode         TEXT,
                    duration_ms  INTEGER,
                    result_count INTEGER,
                    timestamp    TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_search_log_user
                    ON search_log(user_id);
                CREATE INDEX IF NOT EXISTS idx_search_log_ts
                    ON search_log(timestamp);
                """
            )
        logger.info(f"AuthService: SQLite ready at {DB_PATH}")

    def _bootstrap_admin(self) -> None:
        """Ensure the default admin row exists with role='admin'."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, role FROM users WHERE email = ?",
                (DEFAULT_ADMIN_EMAIL,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO users (email, name, role, created_at)
                    VALUES (?, ?, 'admin', ?)
                    """,
                    (DEFAULT_ADMIN_EMAIL, "Adisak Sukul", now),
                )
                logger.info(
                    f"AuthService: bootstrapped admin user {DEFAULT_ADMIN_EMAIL}"
                )
            elif row["role"] != "admin":
                conn.execute(
                    "UPDATE users SET role = 'admin' WHERE id = ?",
                    (row["id"],),
                )
                logger.info(
                    f"AuthService: promoted {DEFAULT_ADMIN_EMAIL} to admin"
                )

    # ------------------------------------------------------------------
    # Google ID-token verification
    # ------------------------------------------------------------------

    def verify_google_id_token(self, token: str) -> Dict[str, Any]:
        """
        Verify a Google ID token and return the decoded payload.
        Raises ValueError on any failure.
        """
        if not GOOGLE_OAUTH_CLIENT_ID:
            raise ValueError(
                "GOOGLE_OAUTH_CLIENT_ID is not configured on the backend."
            )
        try:
            payload = google_id_token.verify_oauth2_token(
                token,
                self._google_request,
                GOOGLE_OAUTH_CLIENT_ID,
                clock_skew_in_seconds=10,
            )
        except Exception as e:
            raise ValueError(f"Invalid Google ID token: {e}") from e

        # Sanity checks
        if payload.get("iss") not in (
            "accounts.google.com",
            "https://accounts.google.com",
        ):
            raise ValueError("Wrong issuer for Google ID token")
        if not payload.get("email_verified"):
            raise ValueError("Google account email is not verified")
        return payload

    # ------------------------------------------------------------------
    # Login flow
    # ------------------------------------------------------------------

    def login_with_google(self, id_token_jwt: str) -> Dict[str, Any]:
        """
        Verify a Google ID token, upsert the user, and return a session JWT
        plus the user record. Caller (route handler) wraps any errors as 401.
        """
        payload = self.verify_google_id_token(id_token_jwt)
        email = (payload.get("email") or "").lower()
        google_sub = payload.get("sub")
        name = payload.get("name")
        picture = payload.get("picture")
        if not email or not google_sub:
            raise ValueError("Token missing email/sub claim")

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO users
                        (email, google_sub, name, picture, role, created_at, last_login)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (email, google_sub, name, picture, "user", now, now),
                )
            else:
                conn.execute(
                    """
                    UPDATE users
                       SET google_sub = COALESCE(?, google_sub),
                           name       = COALESCE(?, name),
                           picture    = COALESCE(?, picture),
                           last_login = ?
                     WHERE id = ?
                    """,
                    (google_sub, name, picture, now, row["id"]),
                )

            user = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()

        user_dict = dict(user)
        token = self._issue_session_jwt(user_dict)
        return {"token": token, "user": _public_user(user_dict)}

    # ------------------------------------------------------------------
    # Session JWT
    # ------------------------------------------------------------------

    def _issue_session_jwt(self, user: Dict[str, Any]) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user["id"]),
            "email": user["email"],
            "role": user["role"],
            "name": user.get("name"),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=JWT_TTL_HOURS)).timestamp()),
        }
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    def decode_session_jwt(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    def get_user_from_token(self, token: str) -> Optional[Dict[str, Any]]:
        claims = self.decode_session_jwt(token)
        if not claims:
            return None
        try:
            user_id = int(claims.get("sub", ""))
        except ValueError:
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Search activity
    # ------------------------------------------------------------------

    def log_search(
        self,
        user_id: Optional[int],
        query: str,
        mode: Optional[str],
        duration_ms: int,
        result_count: int,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO search_log
                        (user_id, query, mode, duration_ms, result_count, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, query, mode, duration_ms, result_count, ts),
                )
        except Exception as e:
            logger.error(f"AuthService.log_search failed: {e}")

    # ------------------------------------------------------------------
    # Admin reads
    # ------------------------------------------------------------------

    def list_users(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT u.id, u.email, u.name, u.picture, u.role,
                       u.created_at, u.last_login,
                       (SELECT COUNT(*) FROM search_log s WHERE s.user_id = u.id) AS search_count
                FROM users u
                ORDER BY COALESCE(u.last_login, u.created_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_recent_searches(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.id, s.query, s.mode, s.duration_ms, s.result_count, s.timestamp,
                       u.email AS user_email, u.name AS user_name, u.role AS user_role
                FROM search_log s
                LEFT JOIN users u ON u.id = s.user_id
                ORDER BY s.timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_user_searches(self, user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, query, mode, duration_ms, result_count, timestamp
                FROM search_log
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        with self._lock, self._connect() as conn:
            user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            admin_count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin'"
            ).fetchone()[0]
            search_count = conn.execute(
                "SELECT COUNT(*) FROM search_log"
            ).fetchone()[0]
            recent_24h = conn.execute(
                """
                SELECT COUNT(*) FROM search_log
                WHERE datetime(timestamp) >= datetime('now', '-1 day')
                """
            ).fetchone()[0]
        return {
            "user_count": user_count,
            "admin_count": admin_count,
            "search_count": search_count,
            "searches_last_24h": recent_24h,
        }

    def set_role(self, email: str, role: str) -> bool:
        if role not in ("user", "admin"):
            return False
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE users SET role = ? WHERE email = ?",
                (role, email.lower()),
            )
            return cur.rowcount > 0


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name"),
        "picture": user.get("picture"),
        "role": user.get("role", "user"),
    }


# Singleton — instantiated lazily so the import is cheap.
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service

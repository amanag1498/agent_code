"""Portable username/password login module.

This module is intentionally self-contained so it can be copied into another
project or device with minimal changes. It supports both SQLite-backed and
JSON-backed storage using only the Python standard library.
"""

from __future__ import annotations

from base64 import b64decode, b64encode
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import hmac
import json
import secrets
from pathlib import Path
import sqlite3


PBKDF2_ITERATIONS = 120_000


@dataclass(slots=True)
class UserAccount:
    """Stored login account."""

    username: str
    password_hash: str
    salt: str
    created_at: str
    active: bool = True


@dataclass(slots=True)
class AuthResult:
    """Authentication response payload."""

    success: bool
    username: str | None
    message: str
    authenticated_at: str | None = None


class JsonFileUserStore:
    """Simple JSON-backed user store for portable deployments."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_users(self) -> list[UserAccount]:
        payload = self._read_payload()
        return [UserAccount(**item) for item in payload.get("users", [])]

    def has_users(self) -> bool:
        return bool(self.list_users())

    def get_user(self, username: str) -> UserAccount | None:
        normalized = username.strip().lower()
        for account in self.list_users():
            if account.username.lower() == normalized:
                return account
        return None

    def save_user(self, account: UserAccount) -> UserAccount:
        payload = self._read_payload()
        users = [UserAccount(**item) for item in payload.get("users", [])]
        replaced = False
        normalized = account.username.lower()
        for index, current in enumerate(users):
            if current.username.lower() == normalized:
                users[index] = account
                replaced = True
                break
        if not replaced:
            users.append(account)
        payload["users"] = [asdict(item) for item in sorted(users, key=lambda item: item.username.lower())]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return account

    def _read_payload(self) -> dict:
        if not self.path.exists():
            return {"users": []}


class SQLiteUserStore:
    """SQLite-backed user store for app-integrated authentication."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self._ensure_schema()

    def list_users(self) -> list[UserAccount]:
        rows = self.connection.execute(
            """
            SELECT username, password_hash, salt, created_at, active
            FROM auth_users
            ORDER BY username
            """
        ).fetchall()
        return [
            UserAccount(
                username=row["username"],
                password_hash=row["password_hash"],
                salt=row["salt"],
                created_at=row["created_at"],
                active=bool(row["active"]),
            )
            for row in rows
        ]

    def has_users(self) -> bool:
        row = self.connection.execute("SELECT COUNT(*) AS count FROM auth_users").fetchone()
        return bool(row and int(row["count"]) > 0)

    def get_user(self, username: str) -> UserAccount | None:
        row = self.connection.execute(
            """
            SELECT username, password_hash, salt, created_at, active
            FROM auth_users
            WHERE lower(username) = lower(?)
            """,
            (username.strip(),),
        ).fetchone()
        if row is None:
            return None
        return UserAccount(
            username=row["username"],
            password_hash=row["password_hash"],
            salt=row["salt"],
            created_at=row["created_at"],
            active=bool(row["active"]),
        )

    def save_user(self, account: UserAccount) -> UserAccount:
        self.connection.execute(
            """
            INSERT INTO auth_users(username, password_hash, salt, created_at, active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash=excluded.password_hash,
                salt=excluded.salt,
                active=excluded.active
            """,
            (
                account.username,
                account.password_hash,
                account.salt,
                account.created_at,
                int(account.active),
            ),
        )
        self.connection.commit()
        return account

    def _ensure_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        self.connection.commit()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"users": []}


class LoginService:
    """Create users and authenticate username/password logins."""

    def __init__(self, user_store: JsonFileUserStore) -> None:
        self.user_store = user_store

    def register_user(self, username: str, password: str, overwrite: bool = False) -> UserAccount:
        normalized = self._normalize_username(username)
        self._validate_password(password)
        existing = self.user_store.get_user(normalized)
        if existing and not overwrite:
            raise ValueError(f"User '{normalized}' already exists.")
        salt = secrets.token_bytes(16)
        account = UserAccount(
            username=normalized,
            password_hash=self._hash_password(password, salt),
            salt=b64encode(salt).decode("ascii"),
            created_at=datetime.utcnow().isoformat(timespec="seconds"),
            active=True,
        )
        return self.user_store.save_user(account)

    def authenticate(self, username: str, password: str) -> AuthResult:
        normalized = self._normalize_username(username)
        account = self.user_store.get_user(normalized)
        if account is None:
            return AuthResult(success=False, username=None, message="Unknown username.")
        if not account.active:
            return AuthResult(success=False, username=account.username, message="User account is disabled.")
        salt = b64decode(account.salt.encode("ascii"))
        expected = self._hash_password(password, salt)
        if not hmac.compare_digest(expected, account.password_hash):
            return AuthResult(success=False, username=account.username, message="Invalid password.")
        return AuthResult(
            success=True,
            username=account.username,
            message="Authentication successful.",
            authenticated_at=datetime.utcnow().isoformat(timespec="seconds"),
        )

    def disable_user(self, username: str) -> UserAccount:
        account = self._require_user(username)
        updated = UserAccount(
            username=account.username,
            password_hash=account.password_hash,
            salt=account.salt,
            created_at=account.created_at,
            active=False,
        )
        return self.user_store.save_user(updated)

    def enable_user(self, username: str) -> UserAccount:
        account = self._require_user(username)
        updated = UserAccount(
            username=account.username,
            password_hash=account.password_hash,
            salt=account.salt,
            created_at=account.created_at,
            active=True,
        )
        return self.user_store.save_user(updated)

    def change_password(self, username: str, new_password: str) -> UserAccount:
        account = self._require_user(username)
        self._validate_password(new_password)
        salt = secrets.token_bytes(16)
        updated = UserAccount(
            username=account.username,
            password_hash=self._hash_password(new_password, salt),
            salt=b64encode(salt).decode("ascii"),
            created_at=account.created_at,
            active=account.active,
        )
        return self.user_store.save_user(updated)

    def _require_user(self, username: str) -> UserAccount:
        normalized = self._normalize_username(username)
        account = self.user_store.get_user(normalized)
        if account is None:
            raise ValueError(f"User '{normalized}' does not exist.")
        return account

    @staticmethod
    def _normalize_username(username: str) -> str:
        cleaned = username.strip()
        if len(cleaned) < 3:
            raise ValueError("Username must contain at least 3 characters.")
        return cleaned

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 8:
            raise ValueError("Password must contain at least 8 characters.")

    @staticmethod
    def _hash_password(password: str, salt: bytes) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PBKDF2_ITERATIONS,
        )
        return b64encode(digest).decode("ascii")

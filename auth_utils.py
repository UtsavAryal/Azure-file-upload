from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
from pathlib import Path
from typing import Optional

PASSWORD_HASH_ITERATIONS = 260_000


def get_user_db_path() -> Path:
    return Path(os.getenv("APP_USER_DB", "users.db"))


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(get_user_db_path())
    connection.row_factory = sqlite3.Row
    return connection


def init_user_store() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_gmail_address(email: str) -> bool:
    local_part, separator, domain = normalize_email(email).partition("@")
    return bool(local_part and separator and domain == "gmail.com")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    encoded_salt = base64.b64encode(salt).decode("ascii")
    encoded_digest = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${encoded_salt}${encoded_digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, encoded_salt, encoded_digest = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False

        salt = base64.b64decode(encoded_salt.encode("ascii"))
        expected_digest = base64.b64decode(encoded_digest.encode("ascii"))
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
    except (ValueError, TypeError):
        return False

    return hmac.compare_digest(actual_digest, expected_digest)


def get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            "SELECT id, email, password_hash, created_at FROM users WHERE email = ?",
            (normalize_email(email),),
        ).fetchone()


def get_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            "SELECT id, email, password_hash, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()


def create_user(email: str, password: str) -> tuple[bool, str, Optional[sqlite3.Row]]:
    normalized_email = normalize_email(email)
    if not is_gmail_address(normalized_email):
        return False, "Please use a Gmail address ending in @gmail.com.", None

    if len(password) < 8:
        return False, "Password must be at least 8 characters.", None

    try:
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (normalized_email, hash_password(password)),
            )
            connection.commit()
    except sqlite3.IntegrityError:
        return False, "An account already exists for this Gmail address.", None

    return True, "Account created.", get_user_by_email(normalized_email)


def authenticate_user(email: str, password: str) -> Optional[sqlite3.Row]:
    user = get_user_by_email(email)
    if user and verify_password(password, user["password_hash"]):
        return user
    return None

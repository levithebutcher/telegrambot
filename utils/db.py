"""
Database helper using SQLite for tracking users, downloads count, and bot settings.
"""

import sqlite3
import os
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize database tables."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                downloads_count INTEGER DEFAULT 0
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.commit()


def add_or_update_user(user_id: int, username: Optional[str], first_name: Optional[str]) -> None:
    """Register user if not exists, or update username/first_name."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO users (user_id, username, first_name)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name
                """,
                (user_id, username, first_name),
            )
            conn.commit()
    except Exception as e:
        logger.error("Failed to add/update user %s: %s", user_id, e)


def increment_download_count(user_id: int) -> None:
    """Increment the download count for a given user."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET downloads_count = downloads_count + 1 WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()
    except Exception as e:
        logger.error("Failed to increment download count for user %s: %s", user_id, e)


def get_user_count() -> int:
    """Return total number of registered users."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            return cursor.fetchone()[0]
    except Exception:
        return 0


def get_total_downloads() -> int:
    """Return total downloads processed across all users."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(downloads_count) FROM users")
            row = cursor.fetchone()
            return row[0] if row and row[0] else 0
    except Exception:
        return 0


def get_all_user_ids() -> List[int]:
    """Return list of all registered user IDs."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            return [row["user_id"] for row in cursor.fetchall()]
    except Exception:
        return []


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get a persistent setting."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default
    except Exception:
        return default


def set_setting(key: str, value: str) -> None:
    """Set a persistent setting."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()
    except Exception as e:
        logger.error("Failed to set setting %s: %s", key, e)

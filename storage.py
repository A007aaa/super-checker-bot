"""
Storage helper for alerts/seen/processed using SQLite (PoC).
- Uses STORAGE_DB env var or ./alerts.db
- Stores only value_hash for new entries (sha256) but preserves legacy `value` column for compatibility.
- Provides: init_db, is_alerted, mark_alerted, is_seen, mark_seen, is_processed, mark_processed

Important: This module does not delete or rewrite existing rows. To migrate legacy plaintext values to hashed values, use the provided `migrate_plaintext_to_hash()` helper manually.
"""
import os
import sqlite3
import threading
import hashlib
import time
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("STORAGE_DB", "./alerts.db")
_sql_lock = threading.Lock()


def _get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize DB schema if missing."""
    with _sql_lock:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT NOT NULL,
            value TEXT,
            value_hash TEXT UNIQUE,
            first_seen INTEGER NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            value_hash TEXT UNIQUE,
            first_seen INTEGER NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS processed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            value_hash TEXT UNIQUE,
            first_seen INTEGER NOT NULL
        )
        """)
        conn.commit()
        conn.close()
        logger.info(f"Storage initialized at {DB_PATH}")


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def is_alerted(item_type: str, value: str) -> bool:
    """Return True if this item has already been alerted.
    Checks both legacy plaintext `value` and `value_hash` to remain compatible.
    """
    h = _hash_value(value)
    with _sql_lock:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM alerts WHERE value_hash = ? LIMIT 1", (h,))
        if cur.fetchone():
            conn.close()
            return True
        cur.execute("SELECT 1 FROM alerts WHERE item_type = ? AND value = ? LIMIT 1", (item_type, value))
        found = cur.fetchone() is not None
        conn.close()
        return found


def mark_alerted(item_type: str, value: str) -> None:
    """Mark an alert; store value_hash and keep plaintext in `value` only if DB is empty (compatibility).
    By default we store the hash; if the DB currently has zero rows, we will optionally store the plaintext as well
    to preserve earlier behaviour (this is conservative)."""
    h = _hash_value(value)
    ts = int(time.time())
    with _sql_lock:
        conn = _get_conn()
        cur = conn.cursor()
        try:
            cur.execute("INSERT OR IGNORE INTO alerts (item_type, value_hash, first_seen) VALUES (?, ?, ?)",
                        (item_type, h, ts))
            cur.execute("SELECT COUNT(*) as c FROM alerts")
            count = cur.fetchone()[0]
            if count == 1:
                cur.execute("UPDATE alerts SET value = ? WHERE value_hash = ?", (value, h))
            conn.commit()
        finally:
            conn.close()


def is_seen(value: str) -> bool:
    h = _hash_value(value)
    with _sql_lock:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM seen WHERE value_hash = ? LIMIT 1", (h,))
        found = cur.fetchone() is not None
        conn.close()
        return found


def mark_seen(value: str) -> None:
    h = _hash_value(value)
    ts = int(time.time())
    with _sql_lock:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO seen (value_hash, first_seen) VALUES (?, ?)", (h, ts))
        conn.commit()
        conn.close()


def is_processed(value: str) -> bool:
    h = _hash_value(value)
    with _sql_lock:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM processed WHERE value_hash = ? LIMIT 1", (h,))
        found = cur.fetchone() is not None
        conn.close()
        return found


def mark_processed(value: str) -> None:
    h = _hash_value(value)
    ts = int(time.time())
    with _sql_lock:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO processed (value_hash, first_seen) VALUES (?, ?)", (h, ts))
        conn.commit()
        conn.close()


def migrate_plaintext_to_hash(dry_run: bool = True) -> int:
    """Migrate existing alerts.value plaintext into value_hash for records missing it.
    If dry_run True, returns number of rows that would be migrated without changing the DB.
    If dry_run False, performs the migration in-place.
    """
    with _sql_lock:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, value FROM alerts WHERE value IS NOT NULL AND (value_hash IS NULL OR value_hash = '')")
        rows = cur.fetchall()
        if dry_run:
            conn.close()
            return len(rows)
        for r in rows:
            vid = r[0]
            val = r[1]
            h = _hash_value(val)
            cur.execute("UPDATE alerts SET value_hash = ? WHERE id = ?", (h, vid))
        conn.commit()
        conn.close()
        return len(rows)

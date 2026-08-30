import sqlite3
import threading
import os
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.getenv('STORAGE_DB', 'alerts.db')

_sql_lock = threading.Lock()

def _get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn

def init_db():
    with _sql_lock:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT NOT NULL,
            value TEXT NOT NULL,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(item_type, value)
        )
        ''')
        conn.commit()
        conn.close()
        logger.info(f"Storage initialized at {DB_PATH}")


def mark_alerted(item_type, value):
    with _sql_lock:
        conn = _get_conn()
        cur = conn.cursor()
        try:
            cur.execute('INSERT OR IGNORE INTO alerts (item_type, value) VALUES (?, ?)', (item_type, value))
            conn.commit()
            inserted = cur.rowcount
        except Exception as e:
            logger.error(f"Storage insert error: {e}")
            inserted = 0
        finally:
            conn.close()
        return inserted > 0


def is_alerted(item_type, value):
    with _sql_lock:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute('SELECT 1 FROM alerts WHERE item_type = ? AND value = ? LIMIT 1', (item_type, value))
        row = cur.fetchone()
        conn.close()
        return bool(row)

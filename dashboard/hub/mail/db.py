"""Data layer for data/mail.db (gitignored, a local Gmail mirror written by mail sync).

Schema comes from db/migrations/mail/; connect() self-heals a missing database
the same way automations/db.py does.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from news.db import _ensure_schema
from sqlite_helpers import apply_pragmas


def default_path() -> Path:
    from vault_path import vault_root

    return vault_root() / "data" / "mail.db"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open mail.db (default: VAULT/data/mail.db), creating the schema if
    absent. Caller closes. Tests pass a tmp path."""
    path = Path(path) if path else default_path()
    _ensure_schema(path, "mail")
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    apply_pragmas(conn)  # warehouse PRAGMA baseline (WAL, synchronous, busy_timeout, foreign_keys, temp_store)
    return conn


_readers: dict[str, sqlite3.Connection] = {}
_reader_lock = threading.Lock()


@contextmanager
def reader():
    """One long-lived read connection per database path with a 64 MB page cache, one caller at a time.

    A fresh connection starts with SQLite's 2 MB cache and re-reads the header index over /mnt/c on
    every list request (~0.6 s for 7.9k messages); this one stays warm and re-reads only the pages
    another connection changed (~20 ms measured right after a write). Reads only: writes use connect().
    ponytail: one global lock, so parallel list requests queue (~20 ms each); a pool if that shows up.
    """
    key = str(default_path())
    with _reader_lock:
        conn = _readers.get(key)
        if conn is None:
            _ensure_schema(Path(key), "mail")
            conn = sqlite3.connect(key, timeout=10, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            apply_pragmas(conn)
            conn.execute("PRAGMA cache_size = -65536")
            _readers[key] = conn
        yield conn

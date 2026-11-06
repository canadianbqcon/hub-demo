"""Data layer for data/automations.db (gitignored, written by the gmail-lane job).

Schema comes from db/migrations/automations/; connect() self-heals a missing
database the same way news/db.py does, so the lane and the dashboard never
error on "no such table" after a fresh checkout or a deleted file.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from news.db import _ensure_schema
from sqlite_helpers import apply_pragmas


def default_path() -> Path:
    from vault_path import vault_root

    return vault_root() / "data" / "automations.db"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open automations.db (default: VAULT/data/automations.db), creating the
    schema if absent. Caller closes. Tests pass a tmp path."""
    path = Path(path) if path else default_path()
    _ensure_schema(path, "automations")
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    apply_pragmas(conn)  # warehouse PRAGMA baseline (WAL, synchronous, busy_timeout, foreign_keys, temp_store)
    return conn

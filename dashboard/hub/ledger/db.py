"""Connection layer for data/cs2.db.

Read-only from the Hub's side. The schema is frozen by the migration
(schema_migrations version 1) and the only writer is collect.py, so init()
does NOT create tables — it just points _conn() at the file, mirroring
stocks/db.py.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlite_helpers import connect

_db_path: Path | None = None


def init(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def _conn():
    with connect(_db_path, "ledger.db") as conn:
        yield conn

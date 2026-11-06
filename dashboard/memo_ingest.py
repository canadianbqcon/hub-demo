from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

from sqlite_helpers import apply_pragmas
from vault_path import icloud_root, vault_root

logger = logging.getLogger(__name__)

VAULT_ROOT = vault_root()
DROP_FOLDER = Path(
    os.environ.get("VAULT_MEMOS_DROP_FOLDER")
    or icloud_root() / "Drop" / "VaultMemos"
)
DB_PATH = VAULT_ROOT / "data" / "purchases.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    apply_pragmas(conn)
    return conn


def read_pending_memos() -> list[dict]:
    """Return unprocessed memo dicts from the drop folder (not in done/)."""
    memos = []
    for path in sorted(DROP_FOLDER.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not data.get("processed", False):
                data["_path"] = str(path)
                memos.append(data)
        except Exception:
            logger.exception("skipping malformed memo %s", path.name)
    return memos


def write_transaction_memo(
    transcript: str,
    recorded_at: str,
    lat: float | None,
    lon: float | None,
    location_label: str,
    vendor_guess: str,
    amount_guess: float | None,
    category_guess: str,
    payment_method_guess: str,
) -> int:
    """Insert a pending transaction memo row. Returns the new row id."""
    conn = _conn()
    cur = conn.execute(
        """
        INSERT INTO transaction_memos
            (transcript, recorded_at, lat, lon, location_label, vendor_guess,
             amount_guess, category_guess, payment_method_guess, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            transcript,
            recorded_at,
            lat,
            lon,
            location_label,
            vendor_guess,
            amount_guess,
            category_guess,
            payment_method_guess,
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    assert row_id is not None  # row just inserted above
    return row_id


def fetch_pending_memos() -> list[dict]:
    """Return all transaction_memos rows with status='pending', oldest first."""
    conn = _conn()
    rows = conn.execute(
        """
        SELECT id, transcript, recorded_at, location_label, vendor_guess,
               amount_guess, category_guess, payment_method_guess, status
        FROM transaction_memos
        WHERE status = 'pending'
        ORDER BY recorded_at
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def link_memo_to_ynab(memo_id: int, transaction_uid: str, memo_text: str) -> None:
    """Flip memo row to linked and store the book txn uid."""
    conn = _conn()
    conn.execute(
        """
        UPDATE transaction_memos
        SET status = 'linked',
            transaction_uid = ?,
            updated = datetime('now')
        WHERE id = ?
        """,
        (transaction_uid, memo_id),
    )
    conn.commit()
    conn.close()


def archive_memo_file(filepath: str) -> None:
    """Move a processed JSON (and its .m4a if present) to done/."""
    path = Path(filepath)
    done_dir = path.parent / "done"
    done_dir.mkdir(exist_ok=True)
    path.rename(done_dir / path.name)
    audio = path.with_suffix(".m4a")
    if audio.exists():
        audio.rename(done_dir / audio.name)


def format_memo_text(row: dict) -> str:
    """Format a transaction_memos row into a YNAB memo string."""
    parts: list[str] = []
    if row.get("vendor_guess"):
        parts.append(row["vendor_guess"])
    if row.get("location_label"):
        parts.append(row["location_label"])
    if row.get("amount_guess") is not None:
        parts.append(f"${row['amount_guess']:.2f}")
    if row.get("payment_method_guess"):
        parts.append(row["payment_method_guess"])
    if row.get("transcript"):
        parts.append(f'"{row["transcript"]}"')
    return " · ".join(parts)

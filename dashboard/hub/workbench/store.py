"""Workbench decisions store: the append-only sign-off ledger for /build
creation mode.

No global connection state: every function takes an optional `db` path so
tests can point at a scratch database (the CLI and API layer use the real
one, `db_path()`, by default). The store never creates the database file:
sqlite3.connect() would silently create an empty one, which is wrong for a
CLI that must exit 3 when the DB is missing: so every connect checks the
file exists first. Schema and migration: db/migrations/workbench/001_init.sql.
Design: docs/archive/specs/2026-09-24-build-creation-mode-design.md §3.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

# dashboard/ on sys.path → vault_path (the Hub already inserts it, but make
# this module importable standalone too: mirrors purchases/api.py).
if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

KINDS = ("spec", "design", "plan", "mark")
VERDICTS = ("approved", "sent_back", "not_applicable", "abandoned")
# not_applicable/abandoned rows may have no doc to hash (§3): a non-screen
# build's design sign-off, or a build abandoned before a doc existed.
NO_DOC_VERDICTS = ("not_applicable", "abandoned")

BUSY_TIMEOUT_MS = 2000


class StaleDocument(Exception):
    """record() was given expected_sha256 and the file's real hash differs:
    the doc changed between when the caller rendered it and this call."""


class AlreadyDecided(StaleDocument):
    """An approval of a doc whose newest row is already that same approval
    (same hash, same pick): the caller is a stale page, so recording it would
    only add a misleading row."""


def db_path() -> Path:
    return vault_root() / "data" / "workbench.db"


def _roots() -> dict[str, Path]:
    root = vault_root()
    return {
        "spec": root / "docs" / "specs",
        "plan": root / "docs" / "plans",
        "design": root / "data" / "workbench" / "options",
    }


def _validate_doc_path(kind: str, doc_path) -> Path:
    """doc_path must resolve under this kind's root (specs/plans/options)."""
    resolved = Path(doc_path).resolve()
    root = _roots()[kind].resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"doc_path {resolved} is outside the {kind} root ({root})")
    return resolved


@contextmanager
def _conn(db: "Path | str | None" = None):
    path = Path(db) if db else db_path()
    if not path.exists():
        raise FileNotFoundError(f"workbench db not found: {path}")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    # Own busy_timeout, deliberately shorter than the dashboard's shared 5000ms
    # default (sqlite_helpers.py): a click that can't get the lock in 2s should
    # fail fast with a retry message, not make the browser hang (see spec §6).
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(folder: Path) -> dict[str, str]:
    """relative path -> sha256, for every file in the folder. Changes if any
    file's content changes, or a file is added or removed. The top-level
    build.txt (the set's build tag) is metadata and is skipped."""
    return {
        f.relative_to(folder).as_posix(): _file_hash(f)
        for f in sorted(folder.rglob("*"))
        if f.is_file() and not (f.name == "build.txt" and f.parent == folder)
    }


def doc_hash(path) -> str:
    """sha256 of a file, or the manifest hash of every file in a directory
    (an option folder): either way, any change to the doc changes the hash."""
    path = Path(path)
    if path.is_dir():
        blob = json.dumps(_manifest(path), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()
    return _file_hash(path)


def _snapshot(kind: str, path: Path) -> str:
    if kind == "design":
        return json.dumps(_manifest(path), sort_keys=True, indent=2)
    return path.read_text()


def record(
    slug: str,
    kind: str,
    doc_path,
    verdict: str,
    choice: "str | None" = None,
    comment: "str | None" = None,
    expected_sha256: "str | None" = None,
    db: "Path | str | None" = None,
) -> dict:
    """Append one decision row. Never updates or deletes a prior row.

    doc_path is None only for not_applicable/abandoned (nothing to hash).
    expected_sha256, when given, must match the doc's real hash right now:
    the API layer passes the hash it rendered, so a doc edited after render
    but before the click raises StaleDocument instead of recording a stale
    approval.
    """
    if kind == "mark":
        raise ValueError("mark rows are written by record_mark(), not record()")
    if kind not in KINDS:
        raise ValueError(f"bad kind: {kind!r}, expected one of {KINDS}")
    if verdict not in VERDICTS:
        raise ValueError(f"bad verdict: {verdict!r}, expected one of {VERDICTS}")

    sha256 = None
    snapshot = None
    resolved_path = None
    if doc_path is not None:
        resolved_path = _validate_doc_path(kind, doc_path)
        sha256 = doc_hash(resolved_path)
        if expected_sha256 is not None and expected_sha256 != sha256:
            raise StaleDocument(f"{resolved_path} changed since it was rendered")
        snapshot = _snapshot(kind, resolved_path)
    elif verdict not in NO_DOC_VERDICTS:
        raise ValueError(f"doc_path is required for verdict {verdict!r}")

    row_id = str(uuid.uuid4())
    with _conn(db) as conn:
        if verdict == "approved":
            last = conn.execute(
                "SELECT verdict, doc_sha256, choice FROM decisions "
                "WHERE build_slug = ? AND kind = ? AND doc_path = ? ORDER BY seq DESC LIMIT 1",
                (slug, kind, str(resolved_path)),
            ).fetchone()
            if last and tuple(last) == ("approved", sha256, choice):
                raise AlreadyDecided(f"{resolved_path.name} is already approved at this version; reload the page")  # pyright: ignore[reportOptionalMemberAccess]  resolved_path is a Path here
        seq = (
            conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM decisions WHERE build_slug = ?",
                (slug,),
            ).fetchone()[0]
            + 1
        )
        conn.execute(
            "INSERT INTO decisions "
            "(id, seq, build_slug, kind, doc_path, doc_sha256, verdict, "
            " choice, comment, snapshot, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (
                row_id,
                seq,
                slug,
                kind,
                str(resolved_path) if resolved_path else None,
                sha256,
                verdict,
                choice,
                comment,
                snapshot,
            ),
        )
        row = conn.execute(
            "SELECT * FROM decisions WHERE id = ?", (row_id,)
        ).fetchone()
    return dict(row)


def record_mark(
    session: str,
    n: int,
    verdict: str,
    words: "str | None",
    snapshot: dict,
    db: "Path | str | None" = None,
) -> dict:
    """Append one mark verdict row: Close = approved, Send back = sent_back.

    A mark has no doc, so doc_path and doc_sha256 stay NULL; choice holds the
    mark number, comment his words, snapshot the mark entry before the change.
    A session holds several marks, so current() does not serve this kind.
    """
    if verdict not in ("approved", "sent_back"):
        raise ValueError(f"bad mark verdict: {verdict!r}, expected approved or sent_back")
    row_id = str(uuid.uuid4())
    with _conn(db) as conn:
        seq = (
            conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM decisions WHERE build_slug = ?",
                (session,),
            ).fetchone()[0]
            + 1
        )
        conn.execute(
            "INSERT INTO decisions "
            "(id, seq, build_slug, kind, doc_path, doc_sha256, verdict, "
            " choice, comment, snapshot, decided_at) "
            "VALUES (?, ?, ?, 'mark', NULL, NULL, ?, ?, ?, ?, datetime('now'))",
            (row_id, seq, session, verdict, str(n), words, json.dumps(snapshot)),
        )
        row = conn.execute(
            "SELECT * FROM decisions WHERE id = ?", (row_id,)
        ).fetchone()
    return dict(row)


def current(slug: str, kind: str, db: "Path | str | None" = None) -> "dict | None":
    """The current verdict row for this build/kind: the highest seq. An
    approval is final: edits after it are his own, made in session, so they
    never void it; new work on the item is a new set or build. The hash still
    guards the click itself (record()'s expected_sha256).
    Marks are never current: a session holds several, see record_mark().
    """
    if kind == "mark":
        return None
    with _conn(db) as conn:
        row = conn.execute(
            "SELECT * FROM decisions WHERE build_slug = ? AND kind = ? "
            "ORDER BY seq DESC, decided_at DESC LIMIT 1",  # seq ties after a two-machine merge
            (slug, kind),
        ).fetchone()
    return dict(row) if row else None

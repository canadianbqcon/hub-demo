"""Shared SQLite connection helpers for the dashboard.

The canonical PRAGMA block lives here as a single source of truth.
See data/CLAUDE.md → SQLite operational discipline.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


# One idle connection per database, held for the life of the process.
#
# Not a pool, never queried: its whole job is to stop the file from going fully
# closed. On /mnt/c (WSL -> the Windows drive over 9p) the last connection
# closing releases the file handle and the WAL index, so the NEXT open re-pays
# all of it. Measured against data/trips.db, opening + 4 pragmas + one SELECT:
#
#     nothing pinned   21.3 ms per open
#     pinned            6.1 ms per open
#     pin closed again 22.4 ms per open
#
# Hub opens a connection per db call and a dozen or more per request, so this
# was the largest single component of page latency — the trips guest-codes
# endpoint spent 315 ms of its 312 ms wall clock inside connection setup.
#
# The pin also owns the one-time `PRAGMA journal_mode = WAL`. That is a
# file-level setting which persists across connections once written, and it is
# by far the most expensive statement in the contract block (~13 ms, since it
# takes an exclusive lock and touches the -wal file), so every later connection
# to the same database skips it. Reading the mode instead of setting it saves
# nothing: whichever statement runs first on a cold connection pays the file
# open, so the check costs the same as the write.
#
# ponytail: one idle handle per path, no pooling and no locking, because it is
# never executed against after _pin() returns — an autocommit connection with no
# statement in flight holds no lock and blocks no WAL checkpoint. Give it a
# query to run and it needs a lock first.
_pinned: dict[str, sqlite3.Connection] = {}


def _pin(db_key: str) -> None:
    """Open this database's keep-alive connection, once per process."""
    if db_key in _pinned:
        return
    conn = sqlite3.connect(db_key, check_same_thread=False)
    try:
        apply_pragmas(conn)          # includes the one journal_mode = WAL write
    except Exception:
        conn.close()                 # a pin that failed to configure is not a pin
        raise
    _pinned[db_key] = conn


def apply_pragmas(conn: sqlite3.Connection, db_key: str | None = None) -> None:
    """Apply the warehouse contract's mandatory PRAGMA block to a connection.

    Call this on every new connection opened against any dashboard SQLite
    database, before any query. Per-connection settings (synchronous,
    busy_timeout, foreign_keys, temp_store) take effect immediately and must be
    re-applied on every connect; journal_mode is file-level and persists, so
    passing `db_key` (the database path) skips it once that database has a pin
    holding it — see `_pinned` above. Omit `db_key` and it is applied in full,
    which is right for a caller opening its own long-lived connection.
    """
    if db_key is None or db_key not in _pinned:
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA temp_store = MEMORY")


# One live connection per database PER THREAD, reused for as long as that thread
# runs. The pin above stopped the file handle from going cold between opens; this
# stops the opens themselves.
#
# Every Hub module calls connect() once per db function, so a single request opens
# a dozen or more — trips' crew tab (/api/trips/<id>/preferences) opened 14, six of
# them card_look() and seven prefs_for_refs(), once per crew member. Even pinned,
# an open on /mnt/c costs ~2.5 ms plus ~3.2 ms for the four contract PRAGMAs, so
# that endpoint spent ~93 ms of its 103 ms wall clock opening and configuring
# connections it already had. Sharing one collapses that to a single open.
#
# Werkzeug's threaded=True gives each request its own thread, so thread-local IS
# request-local here: the sharing lasts exactly one request and cannot leak state
# between two of them. close_scoped() is the explicit release, wired to Flask's
# teardown_request; a caller that never calls it (a CLI script, a test, the skill
# scheduler thread) just keeps one handle per database for its own lifetime, which
# is what the pin was already doing.
#
# Freshness is unaffected. Python's sqlite3 opens an implicit transaction only
# before DML, so a connection that has just committed sits in autocommit and every
# SELECT re-reads the latest WAL snapshot rather than an old one.
#
# ponytail: depth counter, not a nesting ban. No `with connect()` nests on the same
# database today, but a helper called inside one could start doing so at any time,
# and only the outermost exit committing is the difference between that being fine
# and it silently committing half a write.
_scoped = threading.local()


class _Scoped(sqlite3.Connection):
    """A scoped connection, whose close() is a no-op.

    The connection outlives every individual `with connect()` block, so a caller
    that closes it by hand would pull it out from under the rest of the request.
    tasks.py is the live example: it hands out a raw connection and its ten call
    sites each close it, which is correct for a connection they own and wrong for
    a shared one. Swallowing close() lets that stay written the way it is.

    close_scoped() is the real release and calls _release() instead.
    """

    def close(self) -> None:
        pass

    def _release(self) -> None:
        super().close()


def _scoped_conns() -> dict:
    conns = getattr(_scoped, "conns", None)
    if conns is None:
        conns = _scoped.conns = {}
    return conns


def close_scoped() -> None:
    """Release this thread's connections. Wired to Flask's teardown_request.

    Never raises: it runs in teardown, where an exception would mask whatever the
    request was already failing on. A connection still inside a `with connect()`
    block is left alone — closing it under a live caller is the one way this could
    turn a slow request into a broken one.
    """
    conns = getattr(_scoped, "conns", None)
    if not conns:
        return
    for key, entry in list(conns.items()):
        if entry["depth"]:
            continue
        try:
            entry["conn"]._release()
        except Exception:
            logger.exception("scoped connection for %s failed to close", key)
        conns.pop(key, None)


def _unpin(db_key: str) -> None:
    """Drop this database's keep-alive connection so the next open starts clean."""
    conn = _pinned.pop(db_key, None)
    if conn is None:
        return
    try:
        conn.close()
    except Exception:                        # noqa: BLE001
        logger.exception("pinned connection for %s failed to close", db_key)


def _open(db_key: str, pin: bool = True) -> dict:
    """One fresh scoped connection, pragmas applied.

    `pin=False` is the recovery path: the pin is the thing being blamed, so it is
    not re-taken until the real connection has proved the file opens again.
    """
    if pin:
        _pin(db_key)   # keeps the file open between connections — see _pinned above
    fresh = sqlite3.connect(db_key, factory=_Scoped)
    # apply_pragmas() can raise (a WAL file the filesystem refuses to create,
    # say), and a leaked fd there is what turns one bad open into a permanently
    # unopenable database. No closing() — this connection outlives the caller.
    try:
        fresh.row_factory = sqlite3.Row
        apply_pragmas(fresh, db_key)
    except Exception:
        fresh._release()
        raise
    return {"conn": fresh, "depth": 0}


def _entry(db_path: Path | str | None, module: str) -> dict:
    """This thread's cache entry for one database, opening it on first use."""
    if db_path is None:
        raise RuntimeError(f"{module}.init() must be called before any query")
    key = str(db_path)
    conns = _scoped_conns()
    entry = conns.get(key)
    if entry is None:
        try:
            entry = conns[key] = _open(key)
        except sqlite3.OperationalError as exc:
            # On 2026-08-26 every Hub module 500'd because the -wal and -shm
            # sidecars were unlinked on the Windows side while both services held
            # the file open. Over 9p the name cannot then be recreated, so every
            # new connection fails — and the pin, which exists to hold the file
            # open for the life of the process, is what keeps it hostage. Recovery
            # was stopping both services by hand. Dropping the pin and opening
            # again is the same recovery, done once, in process.
            if "unable to open database file" not in str(exc):
                raise
            logger.warning("%s could not be opened (%s) — dropping the pinned "
                           "handle and retrying once", key, exc)
            _unpin(key)
            entry = conns[key] = _open(key, pin=False)
            try:                    # only now that the file provably opens again
                _pin(key)
            except sqlite3.OperationalError:
                # No pin means slower opens, not a broken database. The next call
                # tries again; failing the request here would undo the recovery.
                logger.warning("%s reopened but could not be re-pinned", key)
    return entry


def scoped(db_path: Path | str | None, module: str = "this module"):
    """This thread's connection, handed over raw — no commit, no close.

    For a caller that owns its own transaction boundaries and cannot be a `with`
    block: tasks.py hands one connection to ten functions that each commit for
    themselves. Prefer connect() everywhere else, which commits for you.
    """
    return _entry(db_path, module)["conn"]


@contextmanager
def connect(db_path: Path | str | None, module: str = "this module"):
    """The dashboard's one SQLite connection context manager.

    Yields a Row-factory connection with the contract PRAGMAs applied, and commits
    on a clean exit / rolls back and re-raises on an exception. The connection is
    this thread's, reused across every call until close_scoped() releases it —
    see `_scoped` above. Every Hub module's `_conn()` is a two-line wrapper around
    this that supplies its own module-global path — see data/CLAUDE.md → SQLite
    operational discipline.

    `db_path` of None means `init()` was never called; connecting anyway would
    create a database file literally named "None", so it raises instead. `module`
    only names the offender in that message.
    """
    entry = _entry(db_path, module)
    conn = entry["conn"]
    entry["depth"] += 1
    try:
        yield conn
        if entry["depth"] == 1:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        entry["depth"] -= 1


def row(r: sqlite3.Row | None) -> dict | None:
    """One Row as a plain dict; None passes through so a missed lookup stays None."""
    return dict(r) if r else None


def row_strict(r: sqlite3.Row | None) -> dict:
    """One Row as a dict, for lookups that cannot miss (SELECT on our own lastrowid).

    `row()` returns None on a miss, which is right for real lookups but makes an
    insert-then-read function's `-> dict` signature a lie. This is the narrowing
    version: a None here means the row we just wrote vanished, which is a bug, not
    an empty result.
    """
    if r is None:
        raise RuntimeError("expected a row that was just written, got none")
    return dict(r)


def rows(rs) -> list[dict]:
    return [dict(r) for r in rs]

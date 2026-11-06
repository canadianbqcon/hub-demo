from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlite_helpers import connect as sqlite_connect, row as _row, row_strict as _row_strict, rows as _rows

_db_path: Path | None = None


def init(db_path: Path) -> None:
    """Build the schema for a fresh database.

    This block and every file in db/migrations/checklists/ must describe the SAME schema. Nothing runs migrations at boot (app.py calls init() directly), so a fresh
    machine gets its schema only from here — an init() that lags the migrations means
    ensure_grocery_list() crashes on `no such column: protected` and the Hub will not start.
    tests/test_checklists_bootstrap.py asserts the two agree; keep them in step.
    """
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript("""
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS checklists (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                category    TEXT DEFAULT '',
                description TEXT DEFAULT '',
                protected   INTEGER NOT NULL DEFAULT 0,
                source      TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS checklist_items (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                checklist_id INTEGER NOT NULL REFERENCES checklists(id) ON DELETE CASCADE,
                text         TEXT NOT NULL,
                section      TEXT DEFAULT '',
                checked      INTEGER DEFAULT 0,
                sort_order   INTEGER DEFAULT 0,
                qty          TEXT DEFAULT '',
                note         TEXT DEFAULT ''
            );

            CREATE TRIGGER IF NOT EXISTS checklists_protect_delete
            BEFORE DELETE ON checklists
            FOR EACH ROW WHEN OLD.protected = 1
            BEGIN
                SELECT RAISE(ABORT, 'checklist is protected and cannot be deleted');
            END;

            CREATE TRIGGER IF NOT EXISTS checklists_protect_identity
            BEFORE UPDATE ON checklists
            FOR EACH ROW
            WHEN OLD.protected = 1 AND (NEW.protected <> 1 OR NEW.category <> OLD.category)
            BEGIN
                SELECT RAISE(ABORT, 'protected checklist identity is immutable');
            END;

            CREATE UNIQUE INDEX IF NOT EXISTS checklists_one_protected_per_category
            ON checklists(category) WHERE protected = 1;

            CREATE UNIQUE INDEX IF NOT EXISTS checklists_one_per_source
            ON checklists(source) WHERE source <> '';
        """)


def _conn():
    return sqlite_connect(_db_path, "checklists.db")




class ProtectedChecklist(Exception):
    """Raised when a write would delete or re-identify a protected checklist."""


# ── Checklists ────────────────────────────────────────────────────────────────


def list_checklists() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM checklists ORDER BY category, name"
        ).fetchall()
        result = []
        for r in rows:
            cl = dict(r)
            total = conn.execute(
                "SELECT COUNT(*) FROM checklist_items WHERE checklist_id=?", (cl["id"],)
            ).fetchone()[0]
            checked = conn.execute(
                "SELECT COUNT(*) FROM checklist_items WHERE checklist_id=? AND checked=1",
                (cl["id"],),
            ).fetchone()[0]
            cl["total"] = total
            cl["checked"] = checked
            result.append(cl)
    return result


def get_checklist(cid: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM checklists WHERE id=?", (cid,)).fetchone()
        if not row:
            return None
        cl = dict(row)
        cl["items"] = _rows(
            conn.execute(
                "SELECT * FROM checklist_items WHERE checklist_id=? ORDER BY sort_order, id",
                (cid,),
            ).fetchall()
        )
    return cl


def create_checklist(data: dict) -> dict:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO checklists (name, category, description) VALUES (?,?,?)",
            (
                data.get("name", ""),
                data.get("category", ""),
                data.get("description", ""),
            ),
        )
        row = conn.execute(
            "SELECT * FROM checklists WHERE id=?", (cur.lastrowid,)
        ).fetchone()
    cl = dict(row)
    cl["items"] = []
    cl["total"] = 0
    cl["checked"] = 0
    return cl


def update_checklist(cid: int, data: dict) -> dict | None:
    allowed = {"name", "category", "description"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if updates:
        sets = ", ".join(f"{k}=?" for k in updates)
        try:
            with _conn() as conn:
                conn.execute(
                    f"UPDATE checklists SET {sets} WHERE id=?", (*updates.values(), cid)
                )
        except sqlite3.IntegrityError as e:
            # A protected row's category is immutable — changing it would orphan the
            # canonical-list lookup and silently spawn a second grocery list.
            raise ProtectedChecklist(str(e)) from e
    return get_checklist(cid)


def delete_checklist(cid: int) -> bool:
    """Delete a checklist. Raises ProtectedChecklist if the row is protected.

    The guard itself lives in a database trigger, not here — a trigger holds for every
    writer, including scripts and future modules that never call this function. This only
    translates the trigger's abort into something the API layer can turn into a 409.

    A trigger RAISE(ABORT) surfaces as sqlite3.IntegrityError, verified on
    Python 3.14.4 / SQLite 3.46.1 (it is NOT OperationalError).
    """
    try:
        with _conn() as conn:
            cur = conn.execute("DELETE FROM checklists WHERE id=?", (cid,))
    except sqlite3.IntegrityError as e:
        raise ProtectedChecklist(str(e)) from e
    return cur.rowcount > 0


# ── The canonical grocery list ────────────────────────────────────────────────
#
# One protected row, shared by /checklists and /recipes. /recipes does not keep its own
# copy of the list; it reads and writes these same rows, so an edit on either surface is
# the same edit. The protection is what keeps that link unbreakable.

GROCERY_CATEGORY = "grocery"
GROCERY_NAME = "Grocery"


def ensure_grocery_list() -> dict:
    """Return the canonical grocery checklist, creating it if it does not exist.

    Idempotent and safe to call on every read. Keyed on (category, protected) rather than
    name, because both of those are immutable for a protected row while the name is not —
    so Sam can rename the list without orphaning it.

    Select-then-insert is not atomic across two concurrent requests, so the partial unique
    index on (category) WHERE protected=1 is the real guarantee: the loser of a race gets an
    IntegrityError and re-selects rather than creating a second canonical list.
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM checklists WHERE category=? AND protected=1",
            (GROCERY_CATEGORY,),
        ).fetchone()
        if row is None:
            try:
                conn.execute(
                    "INSERT INTO checklists (name, category, description, protected)"
                    " VALUES (?,?,?,1)",
                    (GROCERY_NAME, GROCERY_CATEGORY,
                     "Shared with /recipes. Cannot be deleted."),
                )
            except sqlite3.IntegrityError:
                pass  # lost the race; the winner's row is there now
            row = conn.execute(
                "SELECT * FROM checklists WHERE category=? AND protected=1",
                (GROCERY_CATEGORY,),
            ).fetchone()
    assert row is not None, "select-then-insert-or-race guarantees a row here"
    checklist = get_checklist(row["id"])
    assert checklist is not None, f"checklist {row['id']} vanished between insert and read"
    return checklist


# ── Lists another module owns ─────────────────────────────────────────────────
#
# Same arrangement the grocery list has with /recipes, generalised: a module that
# shows a checklist does not keep one. It asks for its list by `source` and gets the
# rows that live here, so /checklists is the one place every list on the Hub can be
# read and edited, and the module is a second door onto the same rows.


def ensure_source_list(source: str, name: str, category: str = "",
                       description: str = "") -> dict:
    """Return the checklist belonging to `source`, creating it if it does not exist.

    `source` is "<module>:<record id>:<what>" — "trips:59:grocery". Idempotent and safe
    on every read, the same way ensure_grocery_list() is, and guarded by the same kind of
    partial unique index: select-then-insert is not atomic across two requests, so the
    loser of a race re-selects rather than creating a second list for the one trip.

    `name` is only used on creation. Renaming the list on /checklists is allowed and
    must survive, so nothing here writes over an existing row's name.
    """
    if not source:
        raise ValueError("a source list needs a source")
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM checklists WHERE source=?", (source,)).fetchone()
        if row is None:
            try:
                conn.execute(
                    "INSERT INTO checklists (name, category, description, source)"
                    " VALUES (?,?,?,?)", (name, category, description, source))
            except sqlite3.IntegrityError:
                pass  # lost the race; the winner's row is there now
            row = conn.execute(
                "SELECT * FROM checklists WHERE source=?", (source,)).fetchone()
    assert row is not None, "select-then-insert-or-race guarantees a row here"
    checklist = get_checklist(row["id"])
    assert checklist is not None, f"checklist {row['id']} vanished between insert and read"
    return checklist


def find_source_list(source: str) -> dict | None:
    """The list for `source`, or None. The read that must NOT create one.

    Deleting a trip has to be able to take its list with it, and a delete that ends by
    asking ensure_source_list() for the row would put it straight back.
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT id FROM checklists WHERE source=?", (source,)).fetchone()
    return get_checklist(row["id"]) if row else None


def delete_source_list(source: str) -> bool:
    """Drop the list a module record owned. Called when that record is deleted."""
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM checklists WHERE source=? AND protected=0", (source,))
    return cur.rowcount > 0


def add_items_bulk(cid: int, items: list[dict]) -> int:
    """Append many items in ONE transaction. Returns how many landed.

    add_item() opens its own connection per call and computes MAX(sort_order) separately
    each time, so sending a multi-recipe grocery batch through it is dozens of independent
    transactions that can interleave sort orders and can fail halfway, leaving a partial
    batch on the list. This is all-or-nothing.
    """
    if not items:
        return 0
    with _conn() as conn:
        base = {}
        for it in items:
            section = it.get("section", "")
            if section not in base:
                base[section] = conn.execute(
                    "SELECT COALESCE(MAX(sort_order),0) FROM checklist_items"
                    " WHERE checklist_id=? AND section=?",
                    (cid, section),
                ).fetchone()[0]
            base[section] += 1
            conn.execute(
                "INSERT INTO checklist_items"
                " (checklist_id, text, section, checked, sort_order, qty, note)"
                " VALUES (?,?,?,0,?,?,?)",
                (cid, it.get("text", ""), section, base[section],
                 it.get("qty", ""), it.get("note", "")),
            )
    return len(items)


def clear_checked(cid: int) -> int:
    """Remove the ticked items from a list. The way a standing grocery list gets reused."""
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM checklist_items WHERE checklist_id=? AND checked=1", (cid,)
        )
    return cur.rowcount


def reset_checklist(cid: int) -> dict | None:
    with _conn() as conn:
        conn.execute(
            "UPDATE checklist_items SET checked=0 WHERE checklist_id=?", (cid,)
        )
    return get_checklist(cid)


def checklist_count() -> int:
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM checklists").fetchone()[0]


# ── Items ─────────────────────────────────────────────────────────────────────


def add_item(cid: int, data: dict) -> dict:
    with _conn() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order),0) FROM checklist_items WHERE checklist_id=? AND section=?",
            (cid, data.get("section", "")),
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO checklist_items"
            " (checklist_id, text, section, checked, sort_order, qty, note)"
            " VALUES (?,?,?,?,?,?,?)",
            (cid, data.get("text", ""), data.get("section", ""), 0, max_order + 1,
             data.get("qty", ""), data.get("note", "")),
        )
        row = conn.execute(
            "SELECT * FROM checklist_items WHERE id=?", (cur.lastrowid,)
        ).fetchone()
    return _row_strict(row)


def update_item(cid: int, item_id: int, data: dict) -> dict | None:
    allowed = {"text", "section", "checked", "sort_order", "qty", "note"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        with _conn() as conn:
            row = conn.execute(
                "SELECT * FROM checklist_items WHERE id=? AND checklist_id=?",
                (item_id, cid),
            ).fetchone()
        return _row(row) if row else None
    sets = ", ".join(f"{k}=?" for k in updates)
    with _conn() as conn:
        conn.execute(
            f"UPDATE checklist_items SET {sets} WHERE id=? AND checklist_id=?",
            (*updates.values(), item_id, cid),
        )
        row = conn.execute(
            "SELECT * FROM checklist_items WHERE id=? AND checklist_id=?",
            (item_id, cid),
        ).fetchone()
    return _row(row) if row else None


def delete_item(cid: int, item_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM checklist_items WHERE id=? AND checklist_id=?", (item_id, cid)
        )
    return cur.rowcount > 0


def rename_section(cid: int, from_name: str, to_name: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE checklist_items SET section=? WHERE checklist_id=? AND section=?",
            (to_name, cid, from_name),
        )


def delete_section(cid: int, name: str, keep_items: bool = True) -> None:
    with _conn() as conn:
        if keep_items:
            conn.execute(
                "UPDATE checklist_items SET section='' WHERE checklist_id=? AND section=?",
                (cid, name),
            )
        else:
            conn.execute(
                "DELETE FROM checklist_items WHERE checklist_id=? AND section=?",
                (cid, name),
            )


def reorder_items(cid: int, ids: list[int]) -> None:
    with _conn() as conn:
        for order, item_id in enumerate(ids):
            conn.execute(
                "UPDATE checklist_items SET sort_order=? WHERE id=? AND checklist_id=?",
                (order, item_id, cid),
            )

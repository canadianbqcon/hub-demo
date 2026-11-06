"""Per-application written material: resume notes, cover letter, company research."""
from __future__ import annotations

from .db_core import _conn, _touch_app


# ── Resume notes ──────────────────────────────────────────────────────────────


def list_resume_notes(app_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM resume_notes WHERE application_id = ? ORDER BY id",
            (app_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_resume_note(app_id: int, data: dict) -> dict:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO resume_notes (application_id, section, note, char_limit) VALUES (?, ?, ?, ?)",
            (
                app_id,
                data.get("section", "general"),
                data.get("note", ""),
                data.get("char_limit"),
            ),
        )
        row = conn.execute(
            "SELECT * FROM resume_notes WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        _touch_app(conn, app_id)
    return dict(row)


def update_resume_note(note_id: int, data: dict) -> dict | None:
    fields = {k: v for k, v in data.items() if k in {"section", "note", "char_limit"}}
    with _conn() as conn:
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE resume_notes SET {sets} WHERE id = ?",
                (*fields.values(), note_id),
            )
        row = conn.execute(
            "SELECT * FROM resume_notes WHERE id = ?", (note_id,)
        ).fetchone()
    return dict(row) if row else None


def delete_resume_note(note_id: int) -> None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT application_id FROM resume_notes WHERE id = ?", (note_id,)
        ).fetchone()
        conn.execute("DELETE FROM resume_notes WHERE id = ?", (note_id,))
        if row:
            _touch_app(conn, row["application_id"])


# ── Cover letter ──────────────────────────────────────────────────────────────


def get_cover_letter(app_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM cover_letters WHERE application_id = ?", (app_id,)
        ).fetchone()
    return dict(row) if row else None


def upsert_cover_letter(app_id: int, data: dict) -> dict:
    with _conn() as conn:
        existing = conn.execute(
            "SELECT id FROM cover_letters WHERE application_id = ?", (app_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE cover_letters SET tone = ?, angle = ?, draft = ?, updated = date('now', 'localtime')
                   WHERE application_id = ?""",
                (
                    data.get("tone", ""),
                    data.get("angle", ""),
                    data.get("draft", ""),
                    app_id,
                ),
            )
        else:
            conn.execute(
                "INSERT INTO cover_letters (application_id, tone, angle, draft) VALUES (?, ?, ?, ?)",
                (
                    app_id,
                    data.get("tone", ""),
                    data.get("angle", ""),
                    data.get("draft", ""),
                ),
            )
        row = conn.execute(
            "SELECT * FROM cover_letters WHERE application_id = ?", (app_id,)
        ).fetchone()
        _touch_app(conn, app_id)
    return dict(row)


# ── Company research ──────────────────────────────────────────────────────────


def list_research(app_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM company_research WHERE application_id = ? ORDER BY category, id",
            (app_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_research(app_id: int, data: dict) -> dict:
    """Write one research row, keyed on (application_id, category, subcategory).

    Upsert, not insert: a re-run of Stage 2 (or a second session researching the
    same application) overwrites its own subcategory instead of stacking a
    duplicate row beside it. Migration 006 owns the unique index this relies on.
    """
    category = data.get("category", "general")
    subcategory = data.get("subcategory", "") or ""
    with _conn() as conn:
        conn.execute(
            """INSERT INTO company_research (application_id, category, subcategory, content)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (application_id, category, subcategory)
               DO UPDATE SET content = excluded.content""",
            (app_id, category, subcategory, data.get("content", "")),
        )
        row = conn.execute(
            """SELECT * FROM company_research
               WHERE application_id = ? AND category = ? AND subcategory = ?""",
            (app_id, category, subcategory),
        ).fetchone()
        _touch_app(conn, app_id)
    return dict(row)


def update_research(item_id: int, data: dict) -> dict | None:
    fields = {
        k: v for k, v in data.items() if k in {"category", "subcategory", "content"}
    }
    if not fields:
        return None
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _conn() as conn:
        conn.execute(
            f"UPDATE company_research SET {sets} WHERE id = ?",
            (*fields.values(), item_id),
        )
        row = conn.execute(
            "SELECT * FROM company_research WHERE id = ?", (item_id,)
        ).fetchone()
        if row:
            _touch_app(conn, row["application_id"])
    return dict(row) if row else None


def delete_research(item_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM company_research WHERE id = ?", (item_id,))

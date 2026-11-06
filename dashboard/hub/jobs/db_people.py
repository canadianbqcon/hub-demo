"""Interviewers, the skills library and its gaps, and the STAR story bank."""
from __future__ import annotations

import json

from .db_core import _conn, _row, _touch_app


# ── Interviewers ──────────────────────────────────────────────────────────────


def list_interviewers(app_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM interviewers WHERE application_id = ? ORDER BY id",
            (app_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_interviewer(app_id: int, data: dict) -> dict:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO interviewers (application_id, name, role, linkedin_url, background, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                app_id,
                data.get("name", ""),
                data.get("role", ""),
                data.get("linkedin_url", ""),
                data.get("background", ""),
                data.get("notes", ""),
            ),
        )
        row = conn.execute(
            "SELECT * FROM interviewers WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        _touch_app(conn, app_id)
    return dict(row)


def update_interviewer(iid: int, data: dict) -> dict | None:
    fields = {
        k: v
        for k, v in data.items()
        if k in {"name", "role", "linkedin_url", "background", "notes"}
    }
    with _conn() as conn:
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE interviewers SET {sets} WHERE id = ?",
                (*fields.values(), iid),
            )
        row = conn.execute("SELECT * FROM interviewers WHERE id = ?", (iid,)).fetchone()
    return dict(row) if row else None


def delete_interviewer(iid: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM interviewers WHERE id = ?", (iid,))


# ── Skills ────────────────────────────────────────────────────────────────────


def list_skills() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM skills ORDER BY category, name").fetchall()
    return [dict(r) for r in rows]


def create_skill(data: dict) -> dict:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO skills (name, category, level, notes) VALUES (?, ?, ?, ?)",
            (
                data.get("name", ""),
                data.get("category", "general"),
                data.get("level", "learning"),
                data.get("notes", ""),
            ),
        )
        row = conn.execute(
            "SELECT * FROM skills WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return dict(row)


def update_skill(skill_id: int, data: dict) -> dict | None:
    fields = {
        k: v for k, v in data.items() if k in {"name", "category", "level", "notes"}
    }
    with _conn() as conn:
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE skills SET {sets}, updated = date('now', 'localtime') WHERE id = ?",
                (*fields.values(), skill_id),
            )
        row = conn.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
    return dict(row) if row else None


def delete_skill(skill_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM skills WHERE id = ?", (skill_id,))


def list_app_skills(app_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT s.*, aps.gap, aps.notes as gap_notes
               FROM skills s JOIN application_skills aps ON s.id = aps.skill_id
               WHERE aps.application_id = ? ORDER BY s.category, s.name""",
            (app_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def link_skill(app_id: int, skill_id: int, data: dict) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO application_skills (application_id, skill_id, gap, notes)
               VALUES (?, ?, ?, ?)""",
            (app_id, skill_id, data.get("gap", "medium"), data.get("notes", "")),
        )


def unlink_skill(app_id: int, skill_id: int) -> None:
    with _conn() as conn:
        conn.execute(
            "DELETE FROM application_skills WHERE application_id = ? AND skill_id = ?",
            (app_id, skill_id),
        )


# ── Stories ───────────────────────────────────────────────────────────────────


def list_stories() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM stories ORDER BY updated DESC").fetchall()
    return [_row(r) for r in rows]


def create_story(data: dict) -> dict:
    with _conn() as conn:
        tags = json.dumps(data.get("tags", []))
        cur = conn.execute(
            """INSERT INTO stories (title, situation, task, action, result, tags)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                data.get("title", ""),
                data.get("situation", ""),
                data.get("task", ""),
                data.get("action", ""),
                data.get("result", ""),
                tags,
            ),
        )
        row = conn.execute(
            "SELECT * FROM stories WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return _row(row)


def update_story(story_id: int, data: dict) -> dict | None:
    allowed = {"title", "situation", "task", "action", "result", "tags"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    with _conn() as conn:
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE stories SET {sets}, updated = date('now', 'localtime') WHERE id = ?",
                (*fields.values(), story_id),
            )
        row = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
    return _row(row) if row else None


def delete_story(story_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM stories WHERE id = ?", (story_id,))


def list_app_stories(app_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT s.*, aps.notes as link_notes
               FROM stories s JOIN application_stories aps ON s.id = aps.story_id
               WHERE aps.application_id = ? ORDER BY s.updated DESC""",
            (app_id,),
        ).fetchall()
    return [_row(r) for r in rows]


def link_story(app_id: int, story_id: int, notes: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO application_stories (application_id, story_id, notes) VALUES (?, ?, ?)",
            (app_id, story_id, notes),
        )


def unlink_story(app_id: int, story_id: int) -> None:
    with _conn() as conn:
        conn.execute(
            "DELETE FROM application_stories WHERE application_id = ? AND story_id = ?",
            (app_id, story_id),
        )

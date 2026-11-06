"""Application process steps, resume files, and the interview Q&A bank."""
from __future__ import annotations

from .db_core import _conn, _today, _touch_app


# ── Application process steps ─────────────────────────────────────────────────


def list_process_steps(app_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM application_process_steps WHERE application_id = ? ORDER BY step_order, id",
            (app_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_process_step(app_id: int, data: dict) -> dict:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO application_process_steps
               (application_id, step_order, label, step_type, status, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                app_id,
                data.get("step_order", 0),
                data.get("label", ""),
                data.get("step_type", "interview"),
                data.get("status", "pending"),
                data.get("notes", ""),
            ),
        )
        row = conn.execute(
            "SELECT * FROM application_process_steps WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        _touch_app(conn, app_id)
    return dict(row)


def update_process_step(step_id: int, data: dict) -> dict | None:
    fields = {
        k: v
        for k, v in data.items()
        if k in {"label", "step_type", "status", "notes", "step_order"}
    }
    if not fields:
        with _conn() as conn:
            row = conn.execute(
                "SELECT * FROM application_process_steps WHERE id = ?", (step_id,)
            ).fetchone()
        return dict(row) if row else None
    fields["updated"] = _today()
    fields["step_id"] = step_id
    set_clause = ", ".join(f"{k} = :{k}" for k in fields if k not in ("step_id",))
    with _conn() as conn:
        conn.execute(
            f"UPDATE application_process_steps SET {set_clause}, updated = :updated WHERE id = :step_id",
            fields,
        )
        row = conn.execute(
            "SELECT * FROM application_process_steps WHERE id = ?", (step_id,)
        ).fetchone()
        if row:
            _touch_app(conn, row["application_id"])
    return dict(row) if row else None


def delete_process_step(step_id: int) -> None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT application_id FROM application_process_steps WHERE id = ?",
            (step_id,),
        ).fetchone()
        conn.execute("DELETE FROM application_process_steps WHERE id = ?", (step_id,))
        if row:
            _touch_app(conn, row["application_id"])


def bulk_set_process_steps(
    app_id: int, steps: list[dict], replace: bool = False
) -> list[dict] | None:
    """Seed the process steps for an application. Returns None if it would clobber.

    This is a full replace, and it is the only write path that deletes steps the
    user may have since edited by hand -- the UI never calls it, only Stage 2
    seeding does. So a second Stage 2 run on an application that already has
    steps destroys the first run's work silently (app #113, 2026-07-15).
    Seeding therefore refuses when steps already exist; `replace=True` is the
    explicit opt-in for a deliberate re-seed.
    """
    with _conn() as conn:
        if not replace:
            existing = conn.execute(
                "SELECT COUNT(*) FROM application_process_steps WHERE application_id = ?",
                (app_id,),
            ).fetchone()[0]
            if existing:
                return None
        conn.execute(
            "DELETE FROM application_process_steps WHERE application_id = ?", (app_id,)
        )
        for i, s in enumerate(steps):
            conn.execute(
                """INSERT INTO application_process_steps
                   (application_id, step_order, label, step_type, status, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    app_id,
                    s.get("step_order", i),
                    s.get("label", ""),
                    s.get("step_type", "interview"),
                    s.get("status", "pending"),
                    s.get("notes", ""),
                ),
            )
        rows = conn.execute(
            "SELECT * FROM application_process_steps WHERE application_id = ? ORDER BY step_order, id",
            (app_id,),
        ).fetchall()
        _touch_app(conn, app_id)
    return [dict(r) for r in rows]


# ── Resumes ───────────────────────────────────────────────────────────────────


def list_resumes_base() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM resumes WHERE application_id IS NULL ORDER BY variant, label"
        ).fetchall()
    return [dict(r) for r in rows]


COVER_VARIANT = "cover-letter"


def list_app_resumes(app_id: int) -> list[dict]:
    # Cover letter PDFs share the resumes table (variant 'cover-letter') but are
    # kept out of here, so the submitter never uploads one as the resume.
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM resumes WHERE application_id = ? AND COALESCE(variant, '') != ? "
            "ORDER BY created DESC, id DESC",
            (app_id, COVER_VARIANT),
        ).fetchall()
    return [dict(r) for r in rows]


def get_cover_pdf(app_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM resumes WHERE application_id = ? AND variant = ? "
            "ORDER BY created DESC, id DESC LIMIT 1",
            (app_id, COVER_VARIANT),
        ).fetchone()
    return dict(row) if row else None


def create_resume(app_id: int | None, data: dict) -> dict:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO resumes (application_id, file_path, variant, label, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                app_id,
                data.get("file_path", ""),
                data.get("variant", ""),
                data.get("label", ""),
                data.get("notes", ""),
            ),
        )
        row = conn.execute(
            "SELECT * FROM resumes WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        if app_id:
            _touch_app(conn, app_id)
    return dict(row)


def update_resume(resume_id: int, data: dict) -> dict | None:
    fields = {
        k: v for k, v in data.items() if k in {"file_path", "variant", "label", "notes"}
    }
    with _conn() as conn:
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE resumes SET {sets}, updated = date('now', 'localtime') WHERE id = ?",
                (*fields.values(), resume_id),
            )
        row = conn.execute(
            "SELECT * FROM resumes WHERE id = ?", (resume_id,)
        ).fetchone()
    return dict(row) if row else None


def delete_resume(resume_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))


def get_resume(resume_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM resumes WHERE id = ?", (resume_id,)
        ).fetchone()
    return dict(row) if row else None


# ── Interview Q&A ─────────────────────────────────────────────────────────────

_QA_TEMPLATE_SEED = [
    # Intro (100–199)
    ("intro", "Walk me through your background and how you got here.", 100),
    ("intro", "What are you looking for in your next role?", 110),
    ("intro", "Why are you leaving your current position?", 120),
    # Motivation (200–299)
    ("motivation", "Why do you want this role specifically?", 200),
    ("motivation", "Why this company?", 210),
    ("motivation", "What excites you most about this opportunity?", 220),
    # Behavioral (300–399)
    (
        "behavioral",
        "Tell me about a time you managed a difficult or ambiguous situation.",
        300,
    ),
    (
        "behavioral",
        "Tell me about a time you worked cross-functionally with multiple teams.",
        310,
    ),
    (
        "behavioral",
        "Tell me about a time you identified and fixed a broken process.",
        320,
    ),
    (
        "behavioral",
        "Tell me about a time you had to prioritize competing demands under pressure.",
        330,
    ),
    (
        "behavioral",
        "Tell me about a time you dealt with a difficult stakeholder or colleague.",
        340,
    ),
    ("behavioral", "Tell me about a time you had to learn something new quickly.", 350),
    (
        "behavioral",
        "Tell me about a time you made a mistake and how you handled it.",
        360,
    ),
    # Situational (400–499)
    (
        "situational",
        "If you had to take on this role's core responsibility on day 1, how would you approach it?",
        400,
    ),
    (
        "situational",
        "How do you handle a situation where you disagree with your manager's decision?",
        410,
    ),
    # Culture (500–599)
    ("culture", "What kind of work environment do you do your best work in?", 500),
    ("culture", "How do you handle feedback, including critical feedback?", 510),
    ("culture", "How would your previous colleagues describe your working style?", 520),
    # Ask them (600–699)
    ("ask_them", "What does success look like in the first 30, 60, and 90 days?", 600),
    ("ask_them", "What are the biggest challenges the team is facing right now?", 610),
]


def _seed_qa_template(conn) -> None:
    existing = conn.execute(
        "SELECT COUNT(*) FROM interview_qa WHERE is_template = 1"
    ).fetchone()[0]
    if existing > 0:
        return
    conn.executemany(
        """INSERT INTO interview_qa (question_type, question, sort_order, is_template)
           VALUES (?, ?, ?, 1)""",
        _QA_TEMPLATE_SEED,
    )


def list_qa_template() -> list[dict]:
    with _conn() as conn:
        _seed_qa_template(conn)
        rows = conn.execute(
            "SELECT * FROM interview_qa WHERE is_template = 1 ORDER BY sort_order, id"
        ).fetchall()
    return [dict(r) for r in rows]


def list_app_qa(app_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM interview_qa
               WHERE application_id = ?
               ORDER BY sort_order, id""",
            (app_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_qa(app_id: int | None, data: dict) -> dict:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO interview_qa
               (application_id, source_template_id, question_type, question, answer, notes, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                app_id,
                data.get("source_template_id"),
                data.get("question_type", "behavioral"),
                data.get("question", ""),
                data.get("answer", ""),
                data.get("notes", ""),
                data.get("sort_order", 0),
            ),
        )
        row = conn.execute(
            "SELECT * FROM interview_qa WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        if app_id:
            _touch_app(conn, app_id)
    return dict(row)


def update_qa(qa_id: int, data: dict) -> dict | None:
    fields = {
        k: v
        for k, v in data.items()
        if k in {"question_type", "question", "answer", "notes", "sort_order"}
    }
    with _conn() as conn:
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE interview_qa SET {sets}, updated = date('now', 'localtime') WHERE id = ?",
                (*fields.values(), qa_id),
            )
        row = conn.execute(
            "SELECT * FROM interview_qa WHERE id = ?", (qa_id,)
        ).fetchone()
    return dict(row) if row else None


def delete_qa(qa_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM interview_qa WHERE id = ?", (qa_id,))


def clone_template_to_app(app_id: int) -> list[dict]:
    """Clone all template questions into an application. Skips already-cloned questions."""
    with _conn() as conn:
        _seed_qa_template(conn)
        templates = conn.execute(
            "SELECT * FROM interview_qa WHERE is_template = 1 ORDER BY sort_order, id"
        ).fetchall()
        already_cloned = {
            row["source_template_id"]
            for row in conn.execute(
                "SELECT source_template_id FROM interview_qa WHERE application_id = ? AND source_template_id IS NOT NULL",
                (app_id,),
            ).fetchall()
        }
        new_rows = []
        for t in templates:
            if t["id"] in already_cloned:
                continue
            cur = conn.execute(
                """INSERT INTO interview_qa
                   (application_id, source_template_id, question_type, question, sort_order)
                   VALUES (?, ?, ?, ?, ?)""",
                (app_id, t["id"], t["question_type"], t["question"], t["sort_order"]),
            )
            new_rows.append(cur.lastrowid)
        _touch_app(conn, app_id)
        rows = conn.execute(
            "SELECT * FROM interview_qa WHERE application_id = ? ORDER BY sort_order, id",
            (app_id,),
        ).fetchall()
    return [dict(r) for r in rows]

"""Connection, schema bootstrap, and the helpers every jobs.db section uses."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sqlite_helpers import connect as sqlite_connect

_db_path: Path | None = None


def init(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        # Schema management has moved to data/migrations/jobs/ (see data/warehouse-contract.md).
        # CREATE TABLE IF NOT EXISTS below is a fresh-DB bootstrap only; on any existing
        # vault the canonical schema comes from `python data/migrate.py up jobs`.
        conn.executescript("""
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS glossary (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                term       TEXT NOT NULL,
                definition TEXT DEFAULT '',
                category   TEXT DEFAULT 'general',
                known      INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS applications (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                company     TEXT NOT NULL,
                role        TEXT NOT NULL,
                status      TEXT DEFAULT 'researching',
                priority    TEXT DEFAULT 'medium',
                source      TEXT DEFAULT '',
                job_url     TEXT DEFAULT '',
                salary_min  REAL,
                salary_max  REAL,
                date_applied TEXT DEFAULT '',
                location    TEXT DEFAULT '',
                notes       TEXT DEFAULT '',
                created     TEXT DEFAULT (date('now', 'localtime')),
                updated     TEXT DEFAULT (date('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS resume_notes (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                section        TEXT DEFAULT 'general',
                note           TEXT DEFAULT '',
                created        TEXT DEFAULT (date('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS cover_letters (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                tone           TEXT DEFAULT '',
                angle          TEXT DEFAULT '',
                draft          TEXT DEFAULT '',
                created        TEXT DEFAULT (date('now', 'localtime')),
                updated        TEXT DEFAULT (date('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS company_research (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                category       TEXT DEFAULT 'general',
                subcategory    TEXT DEFAULT '',
                content        TEXT DEFAULT '',
                created        TEXT DEFAULT (date('now', 'localtime'))
            );

            -- Natural key create_research() upserts against (migration 006).
            CREATE UNIQUE INDEX IF NOT EXISTS idx_company_research_natural_key
                ON company_research (application_id, category, subcategory);

            CREATE TABLE IF NOT EXISTS interviewers (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                name           TEXT NOT NULL,
                role           TEXT DEFAULT '',
                linkedin_url   TEXT DEFAULT '',
                background     TEXT DEFAULT '',
                notes          TEXT DEFAULT '',
                created        TEXT DEFAULT (date('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS skills (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                level    TEXT DEFAULT 'learning',
                notes    TEXT DEFAULT '',
                created  TEXT DEFAULT (date('now', 'localtime')),
                updated  TEXT DEFAULT (date('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS application_skills (
                application_id INTEGER REFERENCES applications(id) ON DELETE CASCADE,
                skill_id       INTEGER REFERENCES skills(id) ON DELETE CASCADE,
                gap            TEXT DEFAULT 'medium',
                notes          TEXT DEFAULT '',
                PRIMARY KEY (application_id, skill_id)
            );

            CREATE TABLE IF NOT EXISTS stories (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT NOT NULL,
                situation  TEXT DEFAULT '',
                task       TEXT DEFAULT '',
                action     TEXT DEFAULT '',
                result     TEXT DEFAULT '',
                tags       TEXT DEFAULT '[]',
                created    TEXT DEFAULT (date('now', 'localtime')),
                updated    TEXT DEFAULT (date('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS application_stories (
                application_id INTEGER REFERENCES applications(id) ON DELETE CASCADE,
                story_id       INTEGER REFERENCES stories(id) ON DELETE CASCADE,
                notes          TEXT DEFAULT '',
                PRIMARY KEY (application_id, story_id)
            );

            CREATE TABLE IF NOT EXISTS application_process_steps (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                step_order     INTEGER NOT NULL DEFAULT 0,
                label          TEXT NOT NULL,
                step_type      TEXT DEFAULT 'interview',
                status         TEXT DEFAULT 'pending',
                notes          TEXT DEFAULT '',
                created        TEXT DEFAULT (date('now', 'localtime')),
                updated        TEXT DEFAULT (date('now', 'localtime'))
            );
        """)


def _conn():
    return sqlite_connect(_db_path, "jobs.db")


def _row(r) -> dict:
    d = dict(r)
    for k in ("tags",):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                d[k] = []
    return d


# ── Helpers ───────────────────────────────────────────────────────────────────


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def _touch_app(conn: sqlite3.Connection, app_id: int) -> None:
    conn.execute(
        "UPDATE applications SET updated = date('now', 'localtime') WHERE id = ?", (app_id,)
    )


def application_count() -> int:
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]

"""Purchase-research data layer for the Hub module.

Ported verbatim from the legacy 5001 ``dashboard/purchases/db.py``. Reads/writes
the shared ``data/purchases.db`` — the same file the 5001 app used and already
fully migrated (schema_migrations at version 3 via ``db/migrate.py``). The
``init()`` CREATE-IF-NOT-EXISTS bootstrap is therefore a no-op on the populated
vault DB; it only matters on a fresh machine where the Hub is first to touch it.
"""

from __future__ import annotations

import sys
import json
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import overload

from sqlite_helpers import connect as sqlite_connect, row as _row, rows as _rows

_db_path: Path | None = None


def init(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript("""
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS projects (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL,
                status   TEXT DEFAULT 'active',
                category TEXT DEFAULT '',
                notes    TEXT DEFAULT '',
                created  TEXT DEFAULT (date('now')),
                updated  TEXT DEFAULT (date('now'))
            );

            CREATE TABLE IF NOT EXISTS decisions (
                project_id       INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT NOT NULL,
                category         TEXT DEFAULT '',
                use_case         TEXT DEFAULT '',
                use_context      TEXT DEFAULT '',
                pain_point       TEXT DEFAULT '',
                value_prop       TEXT DEFAULT '',
                purchase_type    TEXT DEFAULT 'one-time-product',
                stage            TEXT DEFAULT 'need',
                time_horizon     TEXT DEFAULT '',
                depth            TEXT DEFAULT 'standard',
                budget_max       REAL,
                currency         TEXT DEFAULT 'USD',
                hard_constraints TEXT DEFAULT '',
                soft_preferences TEXT DEFAULT '',
                verdict_candidate_id INTEGER,
                verdict_reason   TEXT DEFAULT '',
                notes            TEXT DEFAULT '',
                created          TEXT DEFAULT (date('now')),
                updated          TEXT DEFAULT (date('now'))
            );

            CREATE TABLE IF NOT EXISTS candidates (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id     INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                name            TEXT NOT NULL,
                vendor          TEXT DEFAULT '',
                base_price      REAL,
                currency        TEXT DEFAULT 'USD',
                url             TEXT DEFAULT '',
                image_url       TEXT DEFAULT '',
                status          TEXT DEFAULT 'considering',
                rank            INTEGER,
                ecosystem_notes TEXT DEFAULT '',
                return_policy   TEXT DEFAULT '',
                warranty        TEXT DEFAULT '',
                notes           TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS criteria (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                name        TEXT NOT NULL,
                priority    TEXT DEFAULT 'nice-to-have',
                weight      INTEGER DEFAULT 3,
                notes       TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS specs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                criterion_id INTEGER REFERENCES criteria(id) ON DELETE SET NULL,
                key          TEXT NOT NULL,
                value        TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS reviews (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id       INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                candidate_id      INTEGER REFERENCES candidates(id) ON DELETE CASCADE,
                source_type       TEXT DEFAULT 'article',
                url               TEXT DEFAULT '',
                title             TEXT DEFAULT '',
                author            TEXT DEFAULT '',
                takeaway          TEXT DEFAULT '',
                sentiment         TEXT DEFAULT 'mixed',
                is_current_version INTEGER DEFAULT 1,
                notes             TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS pros_cons (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                kind         TEXT DEFAULT 'pro',
                text         TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS price_points (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id  INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                vendor        TEXT DEFAULT '',
                price         REAL NOT NULL,
                currency      TEXT DEFAULT 'USD',
                url           TEXT DEFAULT '',
                observed_on   TEXT DEFAULT (date('now')),
                in_stock      INTEGER DEFAULT 1,
                channel_notes TEXT DEFAULT '',
                notes         TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS budget_entries (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id     INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                label           TEXT DEFAULT '',
                planned_amount  REAL DEFAULT 0,
                actual_amount   REAL,
                currency        TEXT DEFAULT 'USD',
                paid_on         TEXT DEFAULT '',
                payment_method  TEXT DEFAULT '',
                status          TEXT DEFAULT 'planned'
            );

            CREATE TABLE IF NOT EXISTS candidate_scores (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                criterion_id INTEGER NOT NULL REFERENCES criteria(id) ON DELETE CASCADE,
                score        REAL NOT NULL,
                notes        TEXT NOT NULL DEFAULT '',
                UNIQUE (candidate_id, criterion_id)
            ) STRICT;

            CREATE TABLE IF NOT EXISTS dimensions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id   INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                name          TEXT NOT NULL,
                explainer     TEXT NOT NULL DEFAULT '',
                range_text    TEXT NOT NULL DEFAULT '',
                tier_low      TEXT NOT NULL DEFAULT '',
                tier_typical  TEXT NOT NULL DEFAULT '',
                tier_high     TEXT NOT NULL DEFAULT '',
                fit_zone      TEXT NOT NULL DEFAULT '',
                fit_reasoning TEXT NOT NULL DEFAULT '',
                sort          INTEGER NOT NULL DEFAULT 0
            ) STRICT;

            CREATE TABLE IF NOT EXISTS brands (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                name        TEXT NOT NULL,
                summary     TEXT NOT NULL DEFAULT '',
                sort        INTEGER NOT NULL DEFAULT 0
            ) STRICT;

            CREATE TABLE IF NOT EXISTS evidence (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id  INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                subject_type TEXT NOT NULL DEFAULT 'brand',
                subject      TEXT NOT NULL DEFAULT '',
                candidate_id INTEGER REFERENCES candidates(id) ON DELETE CASCADE,
                claim        TEXT NOT NULL,
                source_type  TEXT NOT NULL DEFAULT '',
                source_url   TEXT NOT NULL DEFAULT '',
                longevity    TEXT NOT NULL DEFAULT '',
                grade        TEXT NOT NULL DEFAULT '',
                grade_reason TEXT NOT NULL DEFAULT ''
            ) STRICT;

            CREATE TABLE IF NOT EXISTS price_steps (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id   INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                dimension_id  INTEGER REFERENCES dimensions(id) ON DELETE SET NULL,
                label         TEXT NOT NULL,
                spec_value    TEXT NOT NULL DEFAULT '',
                price         REAL NOT NULL,
                per_unit_note TEXT NOT NULL DEFAULT '',
                knee          INTEGER NOT NULL DEFAULT 0,
                note          TEXT NOT NULL DEFAULT ''
            ) STRICT;

            CREATE TABLE IF NOT EXISTS constraints (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                name        TEXT NOT NULL,
                requirement TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'proposed',
                origin      TEXT NOT NULL DEFAULT '',
                note        TEXT NOT NULL DEFAULT ''
            ) STRICT;

            CREATE TABLE IF NOT EXISTS candidate_constraints (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id  INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                constraint_id INTEGER NOT NULL REFERENCES constraints(id) ON DELETE CASCADE,
                status        TEXT NOT NULL DEFAULT 'unknown',
                note          TEXT NOT NULL DEFAULT '',
                UNIQUE (candidate_id, constraint_id)
            ) STRICT;

            CREATE TABLE IF NOT EXISTS orders (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id     INTEGER REFERENCES decisions(id) ON DELETE SET NULL,
                item            TEXT NOT NULL,
                vendor          TEXT NOT NULL DEFAULT '',
                url             TEXT NOT NULL DEFAULT '',
                image_url       TEXT NOT NULL DEFAULT '',
                order_number    TEXT NOT NULL DEFAULT '',
                ordered_on      TEXT NOT NULL DEFAULT '',
                total           REAL,
                currency        TEXT NOT NULL DEFAULT 'USD',
                carrier         TEXT NOT NULL DEFAULT '',
                tracking_number TEXT NOT NULL DEFAULT '',
                ship_status     TEXT NOT NULL DEFAULT 'ordered',
                eta             TEXT NOT NULL DEFAULT '',
                delivered_on    TEXT NOT NULL DEFAULT '',
                return_days     INTEGER,
                return_by       TEXT NOT NULL DEFAULT '',
                return_policy   TEXT NOT NULL DEFAULT '',
                returned_on     TEXT NOT NULL DEFAULT '',
                delivery_address TEXT NOT NULL DEFAULT '',
                delivery_lat    REAL,
                delivery_lng    REAL,
                source          TEXT NOT NULL DEFAULT 'manual',
                notes           TEXT NOT NULL DEFAULT '',
                created         TEXT NOT NULL DEFAULT (date('now')),
                updated         TEXT NOT NULL DEFAULT (date('now'))
            ) STRICT;

            CREATE TABLE IF NOT EXISTS order_emails (
                message_id TEXT PRIMARY KEY,
                order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                kind       TEXT NOT NULL DEFAULT '',
                sender     TEXT NOT NULL DEFAULT '',
                subject    TEXT NOT NULL DEFAULT '',
                received   TEXT NOT NULL DEFAULT ''
            ) STRICT;
        """)
        for col, defn in [
            ("use_context", "TEXT DEFAULT ''"),
            ("pain_point", "TEXT DEFAULT ''"),
            ("outcome_rating", "INTEGER"),
            ("outcome_well", "TEXT NOT NULL DEFAULT ''"),
            ("outcome_regret", "TEXT NOT NULL DEFAULT ''"),
            ("would_repurchase", "TEXT NOT NULL DEFAULT ''"),
            ("decided_date", "TEXT NOT NULL DEFAULT ''"),
            ("section_state", "TEXT NOT NULL DEFAULT '{}'"),
            # What you actually bought, once the verdict is a real order. One
            # decision buys one thing, so these ride the decision rather than a
            # table of their own.
            ("order_vendor", "TEXT NOT NULL DEFAULT ''"),
            ("order_number", "TEXT NOT NULL DEFAULT ''"),
            ("order_placed", "TEXT NOT NULL DEFAULT ''"),
            ("order_total", "REAL"),
            ("ship_status", "TEXT NOT NULL DEFAULT ''"),
            ("carrier", "TEXT NOT NULL DEFAULT ''"),
            ("tracking_number", "TEXT NOT NULL DEFAULT ''"),
            ("eta", "TEXT NOT NULL DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE decisions ADD COLUMN {col} {defn}")
            except sqlite3.OperationalError:
                pass
        for table, col, defn in [
            ("candidates", "assessment", "TEXT NOT NULL DEFAULT ''"),
            ("criteria", "dimension_id", "INTEGER REFERENCES dimensions(id)"),
            ("dimensions", "options", "TEXT NOT NULL DEFAULT '[]'"),
            ("dimensions", "deciding", "TEXT NOT NULL DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
            except sqlite3.OperationalError:
                pass


def _conn():
    return sqlite_connect(_db_path, "purchases.db")




# ── Projects ──────────────────────────────────────────────────────────────────

_PROJECT_FIELDS = {"name", "status", "category", "notes"}


def list_projects() -> list[dict]:
    # `stage` carries the primary (most recently updated) decision's stage so the
    # rail can show a stage pip per row and roll a live/closed totals strip like
    # the jobs funnel. Most projects hold exactly one decision.
    with _conn() as conn:
        rows = conn.execute(
            "SELECT p.*, COUNT(d.id) AS decision_count, "
            " (SELECT stage FROM decisions WHERE project_id = p.id "
            "  ORDER BY updated DESC LIMIT 1) AS stage, "
            " (SELECT budget_max FROM decisions WHERE project_id = p.id "
            "  ORDER BY updated DESC LIMIT 1) AS budget_max "
            "FROM projects p "
            "LEFT JOIN decisions d ON d.project_id = p.id "
            "GROUP BY p.id ORDER BY p.updated DESC"
        ).fetchall()
    return _rows(rows)


def get_project(project_id: int) -> dict | None:
    with _conn() as conn:
        return _row(
            conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        )


def create_project(data: dict) -> dict:
    fields = {k: data[k] for k in _PROJECT_FIELDS if k in data}
    fields.setdefault("name", "Untitled project")
    cols = ", ".join(fields)
    ph = ", ".join(f":{k}" for k in fields)
    with _conn() as conn:
        cur = conn.execute(f"INSERT INTO projects ({cols}) VALUES ({ph})", fields)
        new = _row(
            conn.execute(
                "SELECT * FROM projects WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        )
        assert new is not None  # row just inserted above
        return new


def update_project(project_id: int, data: dict) -> dict | None:
    updates = {k: v for k, v in data.items() if k in _PROJECT_FIELDS}
    if updates:
        updates["updated"] = _today()
        sets = ", ".join(f"{k}=?" for k in updates)
        with _conn() as conn:
            conn.execute(
                f"UPDATE projects SET {sets} WHERE id=?",
                (*updates.values(), project_id),
            )
    return get_project(project_id)


def delete_project(project_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    return cur.rowcount > 0


def get_full_project(project_id: int) -> dict | None:
    p = get_project(project_id)
    if not p:
        return None
    with _conn() as conn:
        p["decisions"] = _rows(
            conn.execute(
                "SELECT * FROM decisions WHERE project_id=? ORDER BY updated DESC",
                (project_id,),
            ).fetchall()
        )
    return p


# ── Decisions ─────────────────────────────────────────────────────────────────

_DECISION_FIELDS = {
    "project_id",
    "name",
    "category",
    "use_case",
    "use_context",
    "pain_point",
    "purchase_type",
    "stage",
    "time_horizon",
    "depth",
    "budget_max",
    "currency",
    "hard_constraints",
    "soft_preferences",
    "verdict_candidate_id",
    "verdict_reason",
    "notes",
    "outcome_rating",
    "outcome_well",
    "outcome_regret",
    "would_repurchase",
    "decided_date",
    "order_vendor",
    "order_number",
    "order_placed",
    "order_total",
    "ship_status",
    "carrier",
    "tracking_number",
    "eta",
}


def list_decisions() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY "
            " CASE stage "
            "  WHEN 'priorities' THEN 0 "   # awaiting-you most often lives here
            "  WHEN 'need' THEN 1 WHEN 'landscape' THEN 1 WHEN 'market' THEN 1 "
            "  WHEN 'candidates' THEN 1 WHEN 'compare' THEN 1 "
            "  WHEN 'decided' THEN 2 WHEN 'cancelled' THEN 3 ELSE 4 END, "
            " updated DESC"
        ).fetchall()
    return _rows(rows)


def get_decision(decision_id: int) -> dict | None:
    with _conn() as conn:
        return _row(
            conn.execute(
                "SELECT * FROM decisions WHERE id=?", (decision_id,)
            ).fetchone()
        )


# decisions.stage values; the Hub's stage dropdown has exactly these. "verdict"
# is a section name, not a stage: a decision waiting on his pick stays "compare".
STAGES = ("need", "landscape", "priorities", "market", "candidates", "compare",
          "decided", "cancelled")


def _check_stage(data: dict) -> None:
    if "stage" in data and data["stage"] not in STAGES:
        raise ValueError(f"unknown stage {data['stage']!r}, expected one of {STAGES}")


def create_decision(data: dict) -> dict:
    _check_stage(data)
    fields = {k: data.get(k) for k in _DECISION_FIELDS if k in data}
    fields.setdefault("name", "Untitled decision")
    cols = ", ".join(fields)
    placeholders = ", ".join(f":{k}" for k in fields)
    with _conn() as conn:
        cur = conn.execute(
            f"INSERT INTO decisions ({cols}) VALUES ({placeholders})", fields
        )
        new = _row(
            conn.execute(
                "SELECT * FROM decisions WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        )
        assert new is not None  # row just inserted above
        return new


def update_decision(decision_id: int, data: dict) -> dict | None:
    _check_stage(data)
    updates = {k: v for k, v in data.items() if k in _DECISION_FIELDS}
    if updates:
        updates["updated"] = _today()
        sets = ", ".join(f"{k}=?" for k in updates)
        with _conn() as conn:
            conn.execute(
                f"UPDATE decisions SET {sets} WHERE id=?",
                (*updates.values(), decision_id),
            )
        if updates and _NEED_FIELDS & set(updates):
            _mark_downstream_stale(decision_id, "need")
    return get_decision(decision_id)


def delete_decision(decision_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM decisions WHERE id=?", (decision_id,))
    return cur.rowcount > 0


def get_full_decision(decision_id: int) -> dict | None:
    d = get_decision(decision_id)
    if not d:
        return None
    with _conn() as conn:
        d["candidates"] = _rows(
            conn.execute(
                "SELECT * FROM candidates WHERE decision_id=? ORDER BY COALESCE(rank, 999), id",
                (decision_id,),
            ).fetchall()
        )
        d["criteria"] = _rows(
            conn.execute(
                "SELECT * FROM criteria WHERE decision_id=? ORDER BY CASE priority WHEN 'dealbreaker' THEN 0 WHEN 'must-have' THEN 1 ELSE 2 END, weight DESC, id",
                (decision_id,),
            ).fetchall()
        )
        d["reviews"] = _rows(
            conn.execute(
                "SELECT * FROM reviews WHERE decision_id=? ORDER BY id DESC",
                (decision_id,),
            ).fetchall()
        )
        d["budget_entries"] = _rows(
            conn.execute(
                "SELECT * FROM budget_entries WHERE decision_id=? ORDER BY id",
                (decision_id,),
            ).fetchall()
        )
        d["dimensions"] = _rows(conn.execute(
            "SELECT * FROM dimensions WHERE decision_id=? ORDER BY sort, id", (decision_id,)).fetchall())
        d["brands"] = _rows(conn.execute(
            "SELECT * FROM brands WHERE decision_id=? ORDER BY sort, id", (decision_id,)).fetchall())
        d["evidence"] = _rows(conn.execute(
            "SELECT * FROM evidence WHERE decision_id=? ORDER BY id", (decision_id,)).fetchall())
        d["price_steps"] = _rows(conn.execute(
            "SELECT * FROM price_steps WHERE decision_id=? ORDER BY dimension_id, price, id",
            (decision_id,)).fetchall())
        d["constraints"] = _rows(conn.execute(
            "SELECT * FROM constraints WHERE decision_id=? "
            "ORDER BY CASE status WHEN 'locked' THEN 0 ELSE 1 END, id", (decision_id,)).fetchall())
        candidate_ids = [c["id"] for c in d["candidates"]]
        if candidate_ids:
            placeholders = ",".join("?" * len(candidate_ids))
            d["specs"] = _rows(
                conn.execute(
                    f"SELECT * FROM specs WHERE candidate_id IN ({placeholders})",
                    candidate_ids,
                ).fetchall()
            )
            d["pros_cons"] = _rows(
                conn.execute(
                    f"SELECT * FROM pros_cons WHERE candidate_id IN ({placeholders}) ORDER BY kind, id",
                    candidate_ids,
                ).fetchall()
            )
            d["price_points"] = _rows(
                conn.execute(
                    f"SELECT * FROM price_points WHERE candidate_id IN ({placeholders}) ORDER BY observed_on DESC, id DESC",
                    candidate_ids,
                ).fetchall()
            )
            d["candidate_scores"] = _rows(
                conn.execute(
                    f"SELECT * FROM candidate_scores WHERE candidate_id IN ({placeholders})",
                    candidate_ids,
                ).fetchall()
            )
            d["candidate_constraints"] = _rows(conn.execute(
                f"SELECT * FROM candidate_constraints WHERE candidate_id IN ({placeholders})",
                candidate_ids).fetchall())
        else:
            d["specs"] = []
            d["pros_cons"] = []
            d["price_points"] = []
            d["candidate_scores"] = []
            d["candidate_constraints"] = []
    d["order"] = order_for_decision(decision_id)
    _attach_scores(d)
    try:
        d["section_state"] = json.loads(d.get("section_state") or "{}")
    except (TypeError, ValueError):
        d["section_state"] = {}
    return d


# Price is judged by the step-up ladder, never as a criterion: a capped 1-10
# price score at weight 3 of 40 let a near-tie at 55% more money look close to
# the top. Older decisions still carry a price-shaped criterion; it is left out
# of the match score by name.
_PRICE_CRITERION = re.compile(r"\b(price|cost|value)\b", re.IGNORECASE)

# ponytail: one flat NYC rate (8.875%); a per-decision rate when he buys from
# another state. Shipping is assumed folded into base_price by /purchase.
SALES_TAX = 0.08875

# Dollars per match point a step up may cost and still earn its price.
# ponytail: a default, to be calibrated from his picks (decision 21's steps ran
# $3.50-$7.00 a point against $40.00 and $150.00, so any cutoff in 10-40 agrees).
STEP_CUTOFF = 20.0


def _attach_scores(d: dict) -> None:
    """Compute each candidate's match score and the decision's step-up ladder.

    match_score is 0-100: sum(score · weight) over the non-price criteria,
    divided by 10 · sum(weight) of all of them, so an unscored criterion counts
    as zero instead of flattering a half-scored candidate. score_coverage
    ("3/5") still says how complete it is. candidates_ranked lists ids by
    match_score desc, scored ahead of unscored.

    all_in_price is base_price (the one listing the candidate is scored on)
    plus sales tax. d["ladder"] walks the scored, priced, non-rejected
    candidates cheapest first; each step is compared against the current base
    and accepted when it gains match points at no more than STEP_CUTOFF dollars
    a point, which makes it the new base. d["ladder_pick"] is the last base.
    """
    for c in d.get("criteria", []):
        c["in_match"] = not _PRICE_CRITERION.search(c.get("name") or "")
    crits = [c for c in d.get("criteria", []) if c["in_match"]]
    weight_by_crit = {c["id"]: float(c.get("weight") or 0) for c in crits}
    max_points = 10 * sum(weight_by_crit.values())
    scores_by_cand: dict[int, list[tuple[float, float]]] = {}
    for s in d.get("candidate_scores", []):
        w = weight_by_crit.get(s["criterion_id"])
        if w is None:
            continue  # price criterion, or one no longer on this decision
        scores_by_cand.setdefault(s["candidate_id"], []).append((s["score"], w))

    for c in d.get("candidates", []):
        pairs = scores_by_cand.get(c["id"], [])
        c["scored_count"] = len(pairs)
        c["score_coverage"] = f"{len(pairs)}/{len(crits)}" if crits else "0/0"
        c["match_score"] = (
            round(100 * sum(sc * w for sc, w in pairs) / max_points, 1)
            if pairs and max_points else None
        )
        c["all_in_price"] = (
            round(c["base_price"] * (1 + SALES_TAX), 2) if c.get("base_price") is not None else None
        )

    d["candidates_ranked"] = [
        c["id"]
        for c in sorted(
            d.get("candidates", []),
            key=lambda c: (
                c.get("match_score") is not None,
                c.get("match_score") or 0,
                c.get("scored_count") or 0,
            ),
            reverse=True,
        )
    ]

    rungs = sorted(
        (c for c in d.get("candidates", [])
         if c["match_score"] is not None and c["all_in_price"] is not None
         and c.get("status") != "rejected"),
        key=lambda c: (c["all_in_price"], -c["match_score"]),
    )
    ladder: list[dict] = []
    base = None
    for c in rungs:
        step = {"candidate_id": c["id"], "all_in_price": c["all_in_price"],
                "match_score": c["match_score"], "vs_id": None, "gain": None,
                "extra": None, "per_point": None, "accepted": True}
        if base is not None:
            gain = round(c["match_score"] - base["match_score"], 1)
            extra = round(c["all_in_price"] - base["all_in_price"], 2)
            per_point = round(extra / gain, 2) if gain > 0 else None
            step.update(vs_id=base["id"], gain=gain, extra=extra, per_point=per_point,
                        accepted=per_point is not None and per_point <= STEP_CUTOFF)
        if step["accepted"]:
            base = c
        ladder.append(step)
    d["ladder"] = ladder
    d["ladder_pick"] = base["id"] if base else None
    d["step_cutoff"] = STEP_CUTOFF


def decision_count() -> int:
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]


# ── Generic sub-resource helpers ──────────────────────────────────────────────


def _today() -> str:
    with _conn() as conn:
        return conn.execute("SELECT date('now')").fetchone()[0]


def _add(table: str, parent_col: str, parent_id: int, data: dict, allowed: set) -> dict:
    fields = {k: v for k, v in data.items() if k in allowed}
    fields[parent_col] = parent_id
    cols = ", ".join(fields)
    placeholders = ", ".join(f":{k}" for k in fields)
    with _conn() as conn:
        cur = conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", fields
        )
        new = _row(
            conn.execute(
                f"SELECT * FROM {table} WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        )
        assert new is not None  # row just inserted above
        return new


def _update(
    table: str, row_id: int, parent_col: str, parent_id: int, data: dict, allowed: set
) -> dict | None:
    updates = {k: v for k, v in data.items() if k in allowed}
    if updates:
        sets = ", ".join(f"{k}=?" for k in updates)
        with _conn() as conn:
            conn.execute(
                f"UPDATE {table} SET {sets} WHERE id=? AND {parent_col}=?",
                (*updates.values(), row_id, parent_id),
            )
    with _conn() as conn:
        return _row(
            conn.execute(
                f"SELECT * FROM {table} WHERE id=? AND {parent_col}=?",
                (row_id, parent_id),
            ).fetchone()
        )


def _delete(table: str, row_id: int, parent_col: str, parent_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            f"DELETE FROM {table} WHERE id=? AND {parent_col}=?", (row_id, parent_id)
        )
    return cur.rowcount > 0


# ── Candidates (parent: decisions) ────────────────────────────────────────────

_CANDIDATE_FIELDS = {
    "name",
    "vendor",
    "base_price",
    "currency",
    "url",
    "image_url",
    "status",
    "rank",
    "ecosystem_notes",
    "return_policy",
    "warranty",
    "notes",
    "assessment",
}


def add_candidate(did, data):
    return _add("candidates", "decision_id", did, data, _CANDIDATE_FIELDS)


def update_candidate(did, cid, data):
    return _update("candidates", cid, "decision_id", did, data, _CANDIDATE_FIELDS)


def delete_candidate(did, cid):
    return _delete("candidates", cid, "decision_id", did)


# ── Criteria (parent: decisions) ──────────────────────────────────────────────

_CRITERION_FIELDS = {"name", "priority", "weight", "notes", "dimension_id"}


def add_criterion(did, data):
    return _add("criteria", "decision_id", did, data, _CRITERION_FIELDS)


def update_criterion(did, crid, data):
    row = _update("criteria", crid, "decision_id", did, data, _CRITERION_FIELDS)
    if row and ("weight" in data or "priority" in data):
        _mark_downstream_stale(did, "priorities")
    return row


def delete_criterion(did, crid):
    return _delete("criteria", crid, "decision_id", did)


# ── Reviews (parent: decisions) ───────────────────────────────────────────────

_REVIEW_FIELDS = {
    "candidate_id",
    "source_type",
    "url",
    "title",
    "author",
    "takeaway",
    "sentiment",
    "is_current_version",
    "notes",
}


def add_review(did, data):
    return _add("reviews", "decision_id", did, data, _REVIEW_FIELDS)


def update_review(did, rid, data):
    return _update("reviews", rid, "decision_id", did, data, _REVIEW_FIELDS)


def delete_review(did, rid):
    return _delete("reviews", rid, "decision_id", did)


# ── Budget entries (parent: decisions) ────────────────────────────────────────

_BUDGET_FIELDS = {
    "label",
    "planned_amount",
    "actual_amount",
    "currency",
    "paid_on",
    "payment_method",
    "status",
}


def add_budget(did, data):
    return _add("budget_entries", "decision_id", did, data, _BUDGET_FIELDS)


def update_budget(did, bid, data):
    return _update("budget_entries", bid, "decision_id", did, data, _BUDGET_FIELDS)


def delete_budget(did, bid):
    return _delete("budget_entries", bid, "decision_id", did)


# ── Specs (parent: candidates) ────────────────────────────────────────────────

_SPEC_FIELDS = {"criterion_id", "key", "value"}


def add_spec(cid, data):
    return _add("specs", "candidate_id", cid, data, _SPEC_FIELDS)


def update_spec(cid, sid, data):
    return _update("specs", sid, "candidate_id", cid, data, _SPEC_FIELDS)


def delete_spec(cid, sid):
    return _delete("specs", sid, "candidate_id", cid)


# ── Pros/cons (parent: candidates) ────────────────────────────────────────────

_PROCON_FIELDS = {"kind", "text"}


def add_proscon(cid, data):
    return _add("pros_cons", "candidate_id", cid, data, _PROCON_FIELDS)


def update_proscon(cid, pcid, data):
    return _update("pros_cons", pcid, "candidate_id", cid, data, _PROCON_FIELDS)


def delete_proscon(cid, pcid):
    return _delete("pros_cons", pcid, "candidate_id", cid)


# ── Price points (parent: candidates) ─────────────────────────────────────────

_PRICE_FIELDS = {
    "vendor",
    "price",
    "currency",
    "url",
    "observed_on",
    "in_stock",
    "channel_notes",
    "notes",
}


def add_price(cid, data):
    return _add("price_points", "candidate_id", cid, data, _PRICE_FIELDS)


def update_price(cid, pid, data):
    return _update("price_points", pid, "candidate_id", cid, data, _PRICE_FIELDS)


def delete_price(cid, pid):
    return _delete("price_points", pid, "candidate_id", cid)


# ── Pipeline research tables (parent: decisions) ──────────────────────────────

_DIMENSION_FIELDS = {"name", "explainer", "range_text", "tier_low", "tier_typical",
                     "tier_high", "fit_zone", "fit_reasoning", "sort",
                     "options", "deciding"}
_BRAND_FIELDS = {"name", "summary", "sort"}
_EVIDENCE_FIELDS = {"subject_type", "subject", "candidate_id", "claim", "source_type",
                    "source_url", "longevity", "grade", "grade_reason"}
_PRICE_STEP_FIELDS = {"dimension_id", "label", "spec_value", "price", "per_unit_note",
                      "knee", "note"}
_CONSTRAINT_FIELDS = {"name", "requirement", "status", "origin", "note"}


def add_dimension(did, data):
    return _add("dimensions", "decision_id", did, data, _DIMENSION_FIELDS)

def update_dimension(did, rid, data):
    row = _update("dimensions", rid, "decision_id", did, data, _DIMENSION_FIELDS)
    if row:
        _mark_downstream_stale(did, "landscape")
    return row

def delete_dimension(did, rid):
    return _delete("dimensions", rid, "decision_id", did)


def add_brand(did, data):
    return _add("brands", "decision_id", did, data, _BRAND_FIELDS)

def update_brand(did, rid, data):
    return _update("brands", rid, "decision_id", did, data, _BRAND_FIELDS)

def delete_brand(did, rid):
    return _delete("brands", rid, "decision_id", did)


def add_evidence(did, data):
    return _add("evidence", "decision_id", did, data, _EVIDENCE_FIELDS)

def update_evidence(did, rid, data):
    return _update("evidence", rid, "decision_id", did, data, _EVIDENCE_FIELDS)

def delete_evidence(did, rid):
    return _delete("evidence", rid, "decision_id", did)


def add_price_step(did, data):
    return _add("price_steps", "decision_id", did, data, _PRICE_STEP_FIELDS)

def update_price_step(did, rid, data):
    return _update("price_steps", rid, "decision_id", did, data, _PRICE_STEP_FIELDS)

def delete_price_step(did, rid):
    return _delete("price_steps", rid, "decision_id", did)


def add_constraint(did, data):
    return _add("constraints", "decision_id", did, data, _CONSTRAINT_FIELDS)

def update_constraint(did, rid, data):
    return _update("constraints", rid, "decision_id", did, data, _CONSTRAINT_FIELDS)

def delete_constraint(did, rid):
    return _delete("constraints", rid, "decision_id", did)


def set_constraint_check(cid: int, constraint_id: int, status: str, note: str = "") -> dict:
    """Upsert a candidate's pass/fail/unknown check on one constraint."""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO candidate_constraints (candidate_id, constraint_id, status, note) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(candidate_id, constraint_id) DO UPDATE SET "
            "status=excluded.status, note=excluded.note",
            (cid, constraint_id, status, note),
        )
        row = _row(conn.execute(
            "SELECT * FROM candidate_constraints WHERE candidate_id=? AND constraint_id=?",
            (cid, constraint_id)).fetchone())
        assert row is not None
        return row


# ── Section state, checkpoint, staleness ──────────────────────────────────────

PIPELINE_SECTIONS = ["need", "landscape", "priorities", "market",
                     "candidates", "compare", "verdict"]
# sections downstream of each section, for stale-marking on late upstream edits
_DOWNSTREAM = {s: PIPELINE_SECTIONS[i + 1:] for i, s in enumerate(PIPELINE_SECTIONS)}
_NEED_FIELDS = {"use_case", "use_context", "pain_point", "value_prop",
                "budget_max", "hard_constraints", "soft_preferences"}


def get_section_state(did) -> dict:
    d = get_decision(did)
    if not d:
        return {}
    try:
        return json.loads(d.get("section_state") or "{}")
    except (TypeError, ValueError):
        return {}


def set_section_status(did, section: str, status: str) -> dict:
    st = get_section_state(did)
    st[section] = status
    with _conn() as conn:
        conn.execute("UPDATE decisions SET section_state=?, updated=date('now') WHERE id=?",
                     (json.dumps(st), did))
    return st


def _mark_downstream_stale(did, from_section: str) -> None:
    """Flip done downstream sections to stale after a late upstream edit."""
    st = get_section_state(did)
    changed = False
    for s in _DOWNSTREAM.get(from_section, []):
        if st.get(s) == "done":
            st[s] = "stale"
            changed = True
    if changed:
        with _conn() as conn:
            conn.execute("UPDATE decisions SET section_state=? WHERE id=?",
                         (json.dumps(st), did))


def confirm_priorities(did) -> dict | None:
    """The one mid-pipeline checkpoint. Guard: priorities must be awaiting-you."""
    if get_section_state(did).get("priorities") != "awaiting-you":
        raise ValueError("priorities not awaiting-you")
    set_section_status(did, "priorities", "done")
    return update_decision(did, {"stage": "market"})


# ── Candidate scores (parent: candidates; one per criterion) ──────────────────


def set_score(cid: int, criterion_id: int, score: float, notes: str = "") -> dict:
    """Upsert a candidate's score on one criterion (UNIQUE(candidate, criterion))."""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO candidate_scores (candidate_id, criterion_id, score, notes) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(candidate_id, criterion_id) DO UPDATE SET "
            "score=excluded.score, notes=excluded.notes",
            (cid, criterion_id, score, notes),
        )
        row = _row(
            conn.execute(
                "SELECT * FROM candidate_scores WHERE candidate_id=? AND criterion_id=?",
                (cid, criterion_id),
            ).fetchone()
        )
        assert row is not None  # just upserted above
        return row


def delete_score(cid: int, criterion_id: int) -> bool:
    """Clear a candidate's score on one criterion (= mark that cell unscored)."""
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM candidate_scores WHERE candidate_id=? AND criterion_id=?",
            (cid, criterion_id),
        )
    return cur.rowcount > 0


# ── Cross-table helpers ───────────────────────────────────────────────────────


def get_candidate(did: int, cid: int) -> dict | None:
    with _conn() as conn:
        return _row(
            conn.execute(
                "SELECT * FROM candidates WHERE id=? AND decision_id=?", (cid, did)
            ).fetchone()
        )


# ── Orders — the things actually bought ───────────────────────────────────────
#
# One row per parcel, not per decision: a purchase can exist with no research
# behind it (bought on the spot, or lifted out of a confirmation email), and a
# decision that ended in a purchase owns exactly one. Migration 007 moved the
# eight order_* columns off `decisions` into here; those columns still exist but
# nothing reads them.

_ORDER_FIELDS = {
    "decision_id", "item", "vendor", "url", "image_url", "order_number",
    "ordered_on", "total", "currency", "carrier", "tracking_number",
    "ship_status", "eta", "delivered_on", "return_days", "return_by",
    "return_policy", "returned_on", "delivery_address", "source", "notes",
}

SHIP_STATUSES = ["ordered", "shipped", "out for delivery", "delivered", "returned", "cancelled"]
_CLOSED_STATUSES = ("delivered", "returned", "cancelled")


@overload
def _decorate_order(o: dict) -> dict: ...
@overload
def _decorate_order(o: None) -> None: ...
def _decorate_order(o: dict | None) -> dict | None:
    """Add the derived return-window fields. Stored return_by wins over a
    computed one, so a vendor's own stated date is never overwritten by an
    arithmetic guess; otherwise a delivered order with a return window resolves
    to delivered_on + return_days. days_left is negative once the window shuts,
    which is what lets the UI say "closed 3 days ago" rather than going blank."""
    if o is None:
        return None
    by = (o.get("return_by") or "").strip()
    delivered = (o.get("delivered_on") or "").strip()
    days = o.get("return_days")
    if not by and delivered and days:
        try:
            by = (date.fromisoformat(delivered) + timedelta(days=int(days))).isoformat()
        except ValueError:
            by = ""
    o["return_by_effective"] = by
    o["return_days_left"] = None
    if by:
        try:
            o["return_days_left"] = (date.fromisoformat(by) - date.today()).days
        except ValueError:
            pass
    return o


def list_orders() -> list[dict]:
    """In-flight parcels first (an order you are waiting on is the reason to
    open this tab), then everything settled, newest delivery first."""
    with _conn() as conn:
        rows = _rows(conn.execute(
            "SELECT o.*, d.name AS decision_name FROM orders o "
            "LEFT JOIN decisions d ON d.id = o.decision_id "
            "ORDER BY CASE WHEN o.ship_status IN ('delivered','returned','cancelled') "
            "         THEN 1 ELSE 0 END, "
            "         COALESCE(NULLIF(o.delivered_on,''), NULLIF(o.eta,''), "
            "                  NULLIF(o.ordered_on,''), o.created) DESC, o.id DESC"
        ).fetchall())
    return [_decorate_order(r) for r in rows]


def get_order(order_id: int) -> dict | None:
    with _conn() as conn:
        return _decorate_order(_row(
            conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()))


def order_for_decision(decision_id: int) -> dict | None:
    with _conn() as conn:
        return _decorate_order(_row(conn.execute(
            "SELECT * FROM orders WHERE decision_id=? ORDER BY id LIMIT 1",
            (decision_id,)).fetchone()))


def create_order(data: dict) -> dict:
    fields = {k: data[k] for k in _ORDER_FIELDS if k in data}
    fields.setdefault("item", "Untitled item")
    fields.setdefault("ship_status", "ordered")
    _stamp_delivery(fields, fields.get("ship_status"))
    _geocode_delivery(fields)
    cols = ", ".join(fields)
    ph = ", ".join(f":{k}" for k in fields)
    with _conn() as conn:
        cur = conn.execute(f"INSERT INTO orders ({cols}) VALUES ({ph})", fields)
        new = _row(conn.execute("SELECT * FROM orders WHERE id=?", (cur.lastrowid,)).fetchone())
    assert new is not None
    return _decorate_order(new)


def update_order(order_id: int, data: dict) -> dict | None:
    fields = {k: data[k] for k in _ORDER_FIELDS if k in data}
    if not fields:
        return get_order(order_id)
    _stamp_delivery(fields, fields.get("ship_status"))
    if "delivery_address" in fields:
        with _conn() as conn:
            was = conn.execute(
                "SELECT delivery_address FROM orders WHERE id=?", (order_id,)).fetchone()
        _geocode_delivery(fields, was["delivery_address"] if was else "")
    sets = ", ".join(f"{k}=:{k}" for k in fields)
    fields["id"] = order_id
    with _conn() as conn:
        conn.execute(f"UPDATE orders SET {sets}, updated=date('now') WHERE id=:id", fields)
        return _decorate_order(_row(
            conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()))


def _geocode_delivery(fields: dict, previous: str | None = None) -> None:
    """Attach a point to a delivery address the moment it is written.

    Same bargain trips makes for a guest's home: an address that Nominatim
    cannot place keeps its text and loses only its pin, and a CHANGED address
    always drops the old coordinates rather than leaving a pin on the door of
    the place it used to go. Never raises — a map is not worth a failed save."""
    if "delivery_address" not in fields:
        return
    addr = str(fields["delivery_address"] or "").strip()
    fields["delivery_address"] = addr
    if previous is not None and addr == str(previous or "").strip():
        return
    fields["delivery_lat"] = fields["delivery_lng"] = None
    if not addr:
        return
    try:
        import geocode  # local: dashboard/ is on the path in the Hub

        hit = geocode.geocode(addr)
        if hit:
            fields["delivery_lat"], fields["delivery_lng"] = hit
    except Exception as e:  # an unplaceable address is not a failed save
        print(f"geocode failed for {addr!r}: {e}", file=sys.stderr)


def _stamp_delivery(fields: dict, status: str | None) -> None:
    """Marking an order delivered dates it today unless a date came with it —
    the whole point of the status flip is "it arrived", and typing the date a
    second time is the step that gets skipped, which is what leaves a return
    window uncomputable. Same for a return."""
    if status == "delivered" and not (fields.get("delivered_on") or "").strip():
        fields["delivered_on"] = date.today().isoformat()
    if status == "returned" and not (fields.get("returned_on") or "").strip():
        fields["returned_on"] = date.today().isoformat()


def delete_order(order_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM orders WHERE id=?", (order_id,))
    return cur.rowcount > 0


# ── Email ledger (the Gmail scan's dedupe + attach surface) ───────────────────


def seen_email_ids() -> set[str]:
    with _conn() as conn:
        return {r[0] for r in conn.execute("SELECT message_id FROM order_emails")}


def link_email(message_id: str, order_id: int, kind: str, sender: str,
               subject: str, received: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO order_emails "
            "(message_id, order_id, kind, sender, subject, received) VALUES (?,?,?,?,?,?)",
            (message_id, order_id, kind, sender, subject, received))


def emails_for_order(order_id: int) -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute(
            "SELECT * FROM order_emails WHERE order_id=? ORDER BY received DESC",
            (order_id,)).fetchall())


def _vendor_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def match_order(vendor: str, order_number: str, tracking: str = "") -> dict | None:
    """Find the order a shipping email belongs to. A tracking number or order
    number is an exact key and is tried first; failing that, the most recent
    undelivered order from the same vendor ("Ski Barn" also matches "SKI BARN
    INC") that has no other parcel's tracking on it. A shipping notice with none
    of these is left to the caller to open as a new order rather than guessed
    onto someone else's parcel."""
    tracking = tracking.strip()
    with _conn() as conn:
        for col, key in (("tracking_number", tracking), ("order_number", order_number.strip())):
            if key:
                hit = _row(conn.execute(
                    f"SELECT * FROM orders WHERE {col}=? ORDER BY id DESC LIMIT 1",
                    (key,)).fetchone())
                if hit:
                    return _decorate_order(hit)
        want = _vendor_key(vendor)
        if not want:
            return None
        for r in conn.execute(
                "SELECT * FROM orders WHERE ship_status NOT IN ('delivered','returned','cancelled') "
                "ORDER BY id DESC").fetchall():
            if tracking and (r["tracking_number"] or "").strip():
                continue  # already carries a different parcel
            have = _vendor_key(r["vendor"])
            if have and (have == want or (min(len(have), len(want)) >= 4
                                          and (have in want or want in have))):
                return _decorate_order(_row(r))
    return None

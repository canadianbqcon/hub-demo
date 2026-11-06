"""One-shot: lift score data out of `tags` (X.X/10) and `notes` (P=… C=… prefix)
into dedicated `score`, `score_p`, `score_c` columns on `activities`.

Idempotent — rows already migrated (no score-shaped tag, no P=/C= prefix in notes)
are left untouched. Safe to re-run.

Final score formula: score = GROUP_WEIGHT * score_p + COMMUNITY_WEIGHT * score_c.
Run rescore() after changing weights to recompute all rows that have both sub-scores.
"""

from __future__ import annotations

import json
import re
import sqlite3

from vault_path import vault_root

DB_PATH = vault_root() / "data" / "trips.db"

# Blend weights for the final composite score.
GROUP_WEIGHT = 0.40
COMMUNITY_WEIGHT = 0.60

SCORE_TAG_RE = re.compile(r"^(\d+(?:\.\d+)?)/10$")
PC_PREFIX_RE = re.compile(
    r"^\s*P\s*=\s*(\d+(?:\.\d+)?)\s+C\s*=\s*(\d+(?:\.\d+)?)\s*\.\s*",
    re.IGNORECASE,
)


def _ensure_score_columns(cur: sqlite3.Cursor) -> None:
    existing_cols = {
        r[1] for r in cur.execute("PRAGMA table_info(activities)").fetchall()
    }
    for col in ("score", "score_p", "score_c"):
        if col not in existing_cols:
            cur.execute(f"ALTER TABLE activities ADD COLUMN {col} REAL")


def _extract_score_tag(tags: list) -> tuple[list, float | None]:
    """Pop the first X.X/10-shaped tag, if any. Returns (remaining tags, score)."""
    new_tags = list(tags)
    idx = next(
        (i for i, t in enumerate(new_tags) if isinstance(t, str) and SCORE_TAG_RE.match(t)),
        None,
    )
    if idx is None:
        return new_tags, None
    m = SCORE_TAG_RE.match(new_tags[idx])
    assert m
    new_tags.pop(idx)
    return new_tags, float(m.group(1))


def _extract_pc_prefix(notes: str) -> tuple[str, float | None, float | None]:
    """Strip a leading "P=x C=y." prefix, if any. Returns (remaining notes, p, c)."""
    pc = PC_PREFIX_RE.match(notes)
    if not pc:
        return notes, None, None
    return notes[pc.end():], float(pc.group(1)), float(pc.group(2))


def _migrated_row(r: sqlite3.Row) -> dict | None:
    """The new tags/notes/score/score_p/score_c for one row, or None if the row
    is already clean (nothing left to migrate)."""
    try:
        tags = json.loads(r["tags"] or "[]")
    except json.JSONDecodeError:
        tags = []
    notes = r["notes"] or ""

    new_tags, tag_score = _extract_score_tag(tags)
    new_score = r["score"] if r["score"] is not None else tag_score

    new_notes, pc_p, pc_c = _extract_pc_prefix(notes)
    new_p = r["score_p"] if r["score_p"] is not None else pc_p
    new_c = r["score_c"] if r["score_c"] is not None else pc_c

    changed = (
        new_score != r["score"]
        or new_p != r["score_p"]
        or new_c != r["score_c"]
        or new_tags != tags
        or new_notes != notes
    )
    if not changed:
        return None
    return {"tags": new_tags, "notes": new_notes, "score": new_score,
            "score_p": new_p, "score_c": new_c}


def migrate() -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    _ensure_score_columns(cur)

    rows = cur.execute(
        "SELECT id, tags, notes, score, score_p, score_c FROM activities"
    ).fetchall()

    stats = {"scanned": 0, "updated": 0, "skipped_clean": 0}

    for r in rows:
        stats["scanned"] += 1
        changed = _migrated_row(r)
        if changed is None:
            stats["skipped_clean"] += 1
            continue
        cur.execute(
            "UPDATE activities SET tags=?, notes=?, score=?, score_p=?, score_c=? WHERE id=?",
            (
                json.dumps(changed["tags"], ensure_ascii=False),
                changed["notes"],
                changed["score"],
                changed["score_p"],
                changed["score_c"],
                r["id"],
            ),
        )
        stats["updated"] += 1

    conn.commit()
    conn.close()
    return stats


def rescore() -> dict:
    """Recompute `score` for every row that has both score_p and score_c.

    Safe to re-run — rows missing either sub-score are skipped.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(
        "SELECT id, score_p, score_c FROM activities WHERE score_p IS NOT NULL AND score_c IS NOT NULL"
    ).fetchall()

    stats = {"scanned": len(rows), "updated": 0}
    for r in rows:
        new_score = round(
            GROUP_WEIGHT * r["score_p"] + COMMUNITY_WEIGHT * r["score_c"], 1
        )
        cur.execute("UPDATE activities SET score=? WHERE id=?", (new_score, r["id"]))
        stats["updated"] += 1

    conn.commit()
    conn.close()
    return stats


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "rescore":
        print(rescore())
    else:
        print(migrate())

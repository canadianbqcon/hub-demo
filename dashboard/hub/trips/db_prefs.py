"""Crew form preferences: parsed Google Form responses, the live per-member
answer, and the unmatched-submission queue.

Split out of trips/db.py (Task 2).
"""

from __future__ import annotations

from . import db


def save_form_responses(kind: str, responses: list[dict]) -> dict:
    """Upsert parsed Google Form responses. Returns counts, including unmatched.

    `ref` is the SIGNED member key that forms_intake.parse_response has already
    verified, so an empty one means nobody is provably behind this submission.
    It stays unmatched, and Sam attaches it himself (claim_response).

    There is deliberately no fallback to the typed name. The Name field is a
    free-text box on a public form, so matching on it is the same forgery the
    signature exists to stop, just through a different question: type "Priya
    Shah" and the response becomes Megan's. Attaching one person's allergies to
    another is not a mistake anyone catches by reading the board.
    """
    if not responses:
        return {"saved": 0, "unmatched": 0, "unmatched_names": []}
    with db._conn() as conn:
        saved, unmatched = 0, []
        for resp in responses:
            ref = (resp.get("ref") or "").strip()
            name = (resp.get("name") or "").strip()
            if not ref:
                unmatched.append(name)
            conn.execute(
                """INSERT INTO member_prefs
                       (kind, response_id, ref, name, submitted_at, payload, synced_at)
                   VALUES (?,?,?,?,?,?, datetime('now'))
                   ON CONFLICT(kind, response_id) DO UPDATE SET
                       /* A claim sticks. The eleven responses that predate the ref
                          question carry no ref in Google and never will, so a plain
                          ref=excluded.ref un-attributed every one of them on the
                          next sync — silently, because the row is still there and
                          only its owner is gone. Only a response that actually
                          carries a ref may move one. */
                       ref=CASE WHEN excluded.ref != '' THEN excluded.ref
                                ELSE member_prefs.ref END,
                       name=excluded.name,
                       submitted_at=excluded.submitted_at,
                       payload=excluded.payload, synced_at=excluded.synced_at""",
                (kind, resp.get("response_id", ""), ref, name,
                 resp.get("submitted_at", ""), db._json.dumps(resp.get("prefs") or {})),
            )
            saved += 1
    return {"saved": saved, "unmatched": len(unmatched), "unmatched_names": unmatched}


def prefs_for_refs(refs: list[str]) -> dict[str, dict]:
    """The live answer per member: newest submission per (ref, kind).

    Shaped {ref: {"travel": {...}, "food": {...}}}, with a kind absent when that
    form has never been submitted — which is exactly the completion test the gate
    runs, so there is no second query for it.
    """
    refs = [r for r in refs if r]
    if not refs:
        return {}
    marks = ",".join("?" * len(refs))
    with db._conn() as conn:
        rows = conn.execute(
            f"""SELECT kind, ref, name, submitted_at, response_id, payload
                FROM member_prefs
                WHERE ref IN ({marks}) AND ref != ''
                ORDER BY submitted_at ASC""",
            refs,
        ).fetchall()
    out: dict[str, dict] = {}
    # Ascending, so the last write per (ref, kind) is the newest — the same
    # latest-wins rule that makes resubmitting the form the way to change an
    # answer.
    for r in rows:
        try:
            payload = db._json.loads(r["payload"] or "{}")
        except ValueError:
            db.logger.warning("member_prefs: unreadable payload for %s/%s", r["ref"], r["kind"])
            continue
        out.setdefault(r["ref"], {})[r["kind"]] = {
            # response_id rides along because WHICH form this came from decides
            # whether a blank answer is a clear — see api._live_prefs.
            "submitted_at": r["submitted_at"], "name": r["name"],
            "response_id": r["response_id"], "prefs": payload,
        }
    return out


def unmatched_responses() -> list[dict]:
    """Submissions nobody could be identified from — Sam's to resolve."""
    with db._conn() as conn:
        rows = conn.execute(
            """SELECT kind, response_id, name, submitted_at FROM member_prefs
               WHERE ref = '' ORDER BY submitted_at DESC"""
        ).fetchall()
    return db._rows(rows)


def claim_response(kind: str, response_id: str, ref: str) -> bool:
    """Attach an unmatched submission to a member key."""
    with db._conn() as conn:
        cur = conn.execute(
            "UPDATE member_prefs SET ref=? WHERE kind=? AND response_id=?",
            (ref, kind, response_id),
        )
    return cur.rowcount > 0

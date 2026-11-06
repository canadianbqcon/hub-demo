"""Decision log core shared by the Gmail and finance lanes.

Write order for every effect: begin() inserts a `pending` row and commits, the lane
performs the effect, finish() marks it applied or failed. All Gmail writers hold
locked() around claim + effect + log (never across a model call) and take items with
claim(), a conditional UPDATE that returns False when someone else got there first.
undo() and fix() reverse an applied decision; undoing an automatic call blocks its rule
until three fresh human answers agree.
"""

import fcntl
import json
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOCK_PATH = Path(tempfile.gettempdir()) / "hub-automations.lock"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_held = threading.local()


@contextmanager
def locked():
    """Blocking exclusive lock shared by every Gmail writer (lane, page, re-judge) and every rule
    write. Re-entrant per thread: undo holds it and then turns a rule off, which takes it again."""
    if getattr(_held, "depth", 0):
        _held.depth += 1
        try:
            yield
        finally:
            _held.depth -= 1
        return
    with open(LOCK_PATH, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        _held.depth = 1
        try:
            yield
        finally:
            _held.depth = 0
            fcntl.flock(f, fcntl.LOCK_UN)


def begin(conn, lane, ref, action, changed: dict, *, made_by, undo,
          rule_key=None, item_id=None, reason="", rule_id=None, rule_rev=None) -> int:
    """rule_id/rule_rev name the confirmed rule that made an auto effect; NULL is the model's own call."""
    cur = conn.execute(
        "INSERT INTO decision (lane, ref, item_id, rule_key, made_at, made_by, action,"
        " changed_json, state, undo, reason, rule_id, rule_rev) VALUES (?,?,?,?,?,?,?,?,'pending',?,?,?,?)",
        (lane, ref, item_id, rule_key, _now(), made_by, action, json.dumps(changed), undo, reason,
         rule_id, rule_rev))
    conn.commit()
    return cur.lastrowid


def finish(conn, did, state, reason=None):
    conn.execute("UPDATE decision SET state=?, reason=COALESCE(?, reason) WHERE id=?",
                 (state, reason, did))
    conn.commit()


def claim(conn, item_id, from_state, to_state) -> bool:
    cur = conn.execute("UPDATE gmail_item SET state=? WHERE id=? AND state=?",
                       (to_state, item_id, from_state))
    conn.commit()
    return cur.rowcount == 1


def block(conn, lane, rule_key):
    conn.execute("INSERT OR REPLACE INTO rule_block (lane, rule_key, blocked_since) VALUES (?,?,?)",
                 (lane, rule_key, _now()))
    conn.commit()


def blocked(conn, lane, rule_key, human_answers: list[str]) -> bool:
    """Blocked once block() ran, until the last three human answers (the caller passes
    those dated after blocked_since, oldest first) all agree."""
    if not conn.execute("SELECT 1 FROM rule_block WHERE lane=? AND rule_key=?",
                        (lane, rule_key)).fetchone():
        return False
    last = human_answers[-3:]
    return not (len(last) == 3 and len(set(last)) == 1)


TRASH_DAYS = 30


def _undo_gmail(conn, d, gmail) -> dict:
    """Reverse one applied Gmail decision from its recorded label delta. Refuses, with no Gmail
    write, when the live labels no longer show that delta (he changed the message by hand)."""
    before, after = (set(x) for x in json.loads(d["changed_json"])["labels"])
    added, removed = after - before, before - after
    item = conn.execute("SELECT * FROM gmail_item WHERE id=?", (d["item_id"],)).fetchone() if d["item_id"] else None
    if added or removed:
        if gmail is None:
            from automations.gmail_actions import _live_gmail
            gmail = _live_gmail()
        msgs = gmail.users().messages()
        try:
            live = set(msgs.get(userId="me", id=d["ref"], format="minimal").execute().get("labelIds", []))
        except Exception as e:
            if getattr(getattr(e, "resp", None), "status", None) == 404:
                return {"conflict": "the message no longer exists"}
            raise
        if not added <= live or live & removed:
            return {"conflict": "the message's labels changed since this decision"}
        if "TRASH" in added:
            msgs.untrash(userId="me", id=d["ref"]).execute()
            live = set(msgs.get(userId="me", id=d["ref"], format="minimal").execute().get("labelIds", []))
        add, rm = sorted(before - live), sorted(live - before)
        if add or rm:
            msgs.modify(userId="me", id=d["ref"], body={"addLabelIds": add, "removeLabelIds": rm}).execute()
    finish(conn, d["id"], "undone")
    if item is not None:
        st = "proposed" if not (added or removed) else "undone"
        conn.execute("UPDATE gmail_item SET state=?, updated_at=? WHERE id=?", (st, _now(), item["id"]))
        conn.commit()
    # ponytail: only the lane's own calls block their rule; undoing his click is not a correction
    if d["made_by"] == "auto":
        rule_off_or_block(conn, d, "gmail")
    return {"ok": True}


def rule_off_or_block(conn, d, lane):
    """Undo of an auto decision: a confirmed rule that made it is turned off (shown on the rules
    tab with why); a model-only call blocks its key as before."""
    rid = d["rule_id"]
    if rid is not None:
        from automations import rules
        r = rules.get(conn, rid)
        if r is not None and r["state"] == "confirmed":
            rules.set_off(conn, rid, r["rev"], reason=f"undone: decision {d['id']}")
        return
    if d["rule_key"]:
        block(conn, lane, d["rule_key"])


def undo(conn, did, *, gmail=None) -> dict:
    d = conn.execute("SELECT * FROM decision WHERE id=?", (did,)).fetchone()
    if d is None:
        raise LookupError(f"no decision {did}")
    if d["state"] != "applied":
        return {"error": f"nothing to undo: decision is {d['state']}"}
    if d["undo"] == "none":
        return {"error": f"cannot undo: {d['action'].lower()} cannot be reversed"}
    if d["undo"] == "expires" and datetime.fromisoformat(d["made_at"]) < (
            datetime.now(timezone.utc) - timedelta(days=TRASH_DAYS)):
        return {"error": "cannot undo: Gmail has emptied it from the trash"}
    if d["lane"] == "gmail":
        with locked():
            return _undo_gmail(conn, d, gmail)
    if d["lane"] == "voice-memo":
        from automations import voice_memo_lane
        return voice_memo_lane.undo(conn, d)
    from finances import autocat, memo_lane  # each undo(conn, decision_row) -> {"ok"} | {"conflict"}
    fn = {"finance-category": autocat.undo_category, "finance-memo": memo_lane.undo_memo}.get(d["lane"])
    return fn(conn, d) if fn else {"error": f"no undo for {d['lane']}"}


def _fix_result(d) -> dict:
    if d["state"] == "fixed":
        return {"ok": True, "fixed_by": d["fixed_by"]}
    return {"error": d["reason"] or f"decision is {d['state']}"}


def fix(conn, did, answer: dict, fix_key: str, *, gmail=None, apply=None) -> dict:
    """Undo, then apply his answer through the lane's normal human path, so only his answer
    reaches training. A repeated fix_key returns the first call's outcome and changes nothing.
    `apply(answer, decision_row)` overrides the human path (tests)."""
    seen = conn.execute("SELECT * FROM decision WHERE fix_key=?", (fix_key,)).fetchone()
    if seen is not None:
        return _fix_result(seen)
    d = conn.execute("SELECT * FROM decision WHERE id=?", (did,)).fetchone()
    if d is None:
        raise LookupError(f"no decision {did}")
    if d["lane"] == "voice-memo":  # no human path to apply an answer through: undo, then /recap
        return {"error": "voice-memo decisions have no fix: undo it and answer in /recap"}
    if d["fix_key"] is not None:  # an earlier fix with another key owns this decision
        return _fix_result(d)
    conn.execute("UPDATE decision SET fix_key=? WHERE id=?", (fix_key, did))
    conn.commit()
    res: dict = {}
    try:
        res = undo(conn, did, gmail=gmail)
    finally:  # an undo that raised (Gmail 5xx) changed nothing too
        if not (res or {}).get("ok"):  # nothing changed: free the key so a retry gets a real answer
            conn.execute("UPDATE decision SET fix_key=NULL WHERE id=?", (did,))
            conn.commit()
    if not res.get("ok"):
        return res
    try:
        (apply or _apply_human)(conn, d, answer, gmail)
    except Exception as e:
        err = f"fix failed: {e}"[:200]
        finish(conn, did, "undone", err)
        if d["lane"] == "gmail" and d["item_id"]:
            conn.execute("UPDATE gmail_item SET state='proposed', reason=?, updated_at=? WHERE id=?",
                         (err, _now(), d["item_id"]))
            conn.commit()
        return {"error": err}
    new = conn.execute("SELECT id FROM decision WHERE ref=? AND made_by='sam' AND id>? ORDER BY id DESC",
                       (d["ref"], did)).fetchone()
    conn.execute("UPDATE decision SET state='fixed', fixed_by=? WHERE id=?", (new and new[0], did))
    conn.commit()
    return {"ok": True, "fixed_by": new and new[0]}


def _apply_human(conn, d, answer, gmail):
    if d["lane"] == "gmail":
        from automations import gmail_actions
        conn.execute("UPDATE gmail_item SET state='proposed' WHERE id=?", (d["item_id"],))
        conn.commit()
        res = gmail_actions.act(d["item_id"], str(answer.get("action", "")), answer.get("label"),
                                gmail=gmail, conn=conn, note=answer.get("note"))
        if res["state"] not in ("done", "moved", "undone"):
            raise RuntimeError(res.get("detail") or res["state"])
        return
    from automations.api import finance_apply
    body, code = finance_apply({**answer, "uid": d["ref"]})
    if code != 200:
        raise RuntimeError(body.get("error", f"HTTP {code}"))


def list_decisions(conn, lane=None, days=7) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    sql, args = "SELECT * FROM decision WHERE made_at >= ?", [since]
    if lane:
        sql, args = sql + " AND lane = ?", args + [lane]
    return [dict(r) for r in conn.execute(sql + " ORDER BY made_at DESC, id DESC", args)]

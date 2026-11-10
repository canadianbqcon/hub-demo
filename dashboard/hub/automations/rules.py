"""automations/rules.py: the rule store. Every rule write goes through here, under the shared
lock and a rev check; lanes read only confirmed rows. Reads never take the lock."""

from __future__ import annotations

import contextlib
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_HUB = Path(__file__).resolve().parents[1]
if str(_HUB.parent) not in sys.path:  # run as a CLI: dashboard/ holds sqlite_helpers + vault_path
    sys.path[:0] = [str(_HUB), str(_HUB.parent)]

from . import decisions  # noqa: E402

EDITABLE = ("action", "target", "note", "op")
_KIND_RANK = "CASE WHEN kind_of_rule='instruction' AND op IS NOT NULL THEN 0 " \
             "WHEN kind_of_rule='fixed_action' THEN 1 " \
             "WHEN kind_of_rule='files_without_asking' THEN 2 ELSE 3 END"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(conn, rid):
    return conn.execute("SELECT * FROM rule WHERE id=?", (rid,)).fetchone()


def propose(conn, *, lane, rule_key, kind_of_rule, source, source_ref, action=None, target=None,
            note=None, op=None, evidence=None, replaces=None):
    """Insert a proposed rule; None when that source_ref already exists in any state."""
    if conn.execute("SELECT 1 FROM rule WHERE lane=? AND source=? AND source_ref=?",
                    (lane, source, source_ref)).fetchone():
        return None
    now = _now()
    with decisions.locked():
        try:
            cur = conn.execute(
                "INSERT INTO rule (lane, rule_key, state, kind_of_rule, action, target, note, op,"
                " source, source_ref, evidence_json, replaces, created_at, updated_at)"
                " VALUES (?,?,'proposed',?,?,?,?,?,?,?,?,?,?,?)",
                (lane, rule_key, kind_of_rule, action, target, note, op, source, source_ref,
                 json.dumps(evidence) if evidence is not None else None, replaces, now, now))
            conn.commit()
        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e):
                return None
            raise
    return cur.lastrowid


def _move(conn, rid, rev, allowed, state=None, fields=None, old_rev=None):
    """Rev-checked update inside the lock; state=None keeps the state (edit). old_rev, when
    given, is the replaced rule's rev as the tab loaded it."""
    with decisions.locked():
        row = get(conn, rid)
        if row is None:
            return {"conflict": "rule gone"}
        if row["rev"] != rev:
            return {"conflict": "rule changed"}
        if row["state"] not in allowed:
            return {"conflict": f"rule is {row['state']}"}
        now = _now()
        sets = dict(fields or {})
        sets["updated_at"] = now
        sets["rev"] = row["rev"] + 1
        if state:
            sets["state"] = state
            sets["decided_at"] = now
        try:
            if state == "confirmed" and row["replaces"]:
                old = get(conn, row["replaces"])
                if old is None or old["state"] != "confirmed" or old_rev not in (None, old["rev"]):
                    return {"conflict": "replaced rule changed"}
                conn.execute("UPDATE rule SET state='off', rev=rev+1, decided_at=?, updated_at=?"
                             " WHERE id=?", (now, now, old["id"]))
            conn.execute(f"UPDATE rule SET {', '.join(k + '=?' for k in sets)} WHERE id=?",
                         (*sets.values(), rid))
            conn.commit()
        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e):  # another confirmed rule already covers this sender or payee
                return {"conflict": "a confirmed rule already covers this; turn that one off first"}
            raise
        return {"ok": True, "rev": sets["rev"]}


def confirm(conn, rid, rev, old_rev=None):
    return _move(conn, rid, rev, ("proposed",), "confirmed", old_rev=old_rev)


def reject(conn, rid, rev):
    return _move(conn, rid, rev, ("proposed",), "rejected")


def set_off(conn, rid, rev, reason=None):
    return _move(conn, rid, rev, ("confirmed",), "off", {"reason": reason})


def edit(conn, rid, rev, **fields):
    bad = set(fields) - set(EDITABLE)
    if bad:
        raise ValueError(f"not editable: {sorted(bad)}")
    return _move(conn, rid, rev, ("proposed", "confirmed", "off"), None, fields)


def send_back(conn, rid, rev, note):
    """His note on a proposed rule. It stays proposed; reason holds the note as JSON
    ({note, at, status}) until the revise thread rewrites the rule. reason is free on a proposed
    row (only turning off writes it), so no migration."""
    return _move(conn, rid, rev, ("proposed",), None,
                 {"reason": json.dumps({"note": note, "at": _now(), "status": "revising"})})


def revise(conn, rid, rev, sent, **fields):
    """The revise thread's write: the rewritten fields plus the send-back record, still proposed.
    kind_of_rule and rule_key may change too: a sent-back file-without-asking rule becomes a fixed
    rule for every kind of that sender's mail."""
    bad = set(fields) - {*EDITABLE, "kind_of_rule", "rule_key"}
    if bad:
        raise ValueError(f"not editable: {sorted(bad)}")
    return _move(conn, rid, rev, ("proposed",), None, {**fields, "reason": json.dumps(sent)})


def sent_back(r):
    """The send-back record on a proposed rule, or None."""
    if r["state"] != "proposed" or not (r["reason"] or "").startswith("{"):
        return None
    try:
        return json.loads(r["reason"])
    except ValueError:
        return None


def still_confirmed(conn, refs):
    """True when every (rule_id, rev) pair is still confirmed at that rev."""
    return all(
        (r := get(conn, rid)) is not None and r["state"] == "confirmed" and r["rev"] == rev
        for rid, rev in refs)


def confirmed(conn, lane, key):
    """Confirmed rows for a key, precedence-ordered. Gmail key is (domain, kind): domain|kind
    rows first, then domain|*, then *|kind (that kind from any sender), then files_without_asking
    rows keyed by the bare domain; within a group by kind_of_rule. Finance key is the payee id."""
    if lane != "gmail":
        return conn.execute(f"SELECT * FROM rule WHERE lane=? AND state='confirmed' AND rule_key=?"
                            f" ORDER BY {_KIND_RANK}, id", (lane, str(key))).fetchall()
    domain, kind = key
    keys = (f"{domain}|{kind}", f"{domain}|*", f"*|{kind}", domain)
    return conn.execute(
        f"SELECT * FROM rule WHERE lane='gmail' AND state='confirmed' AND rule_key IN (?,?,?,?)"
        f" ORDER BY CASE rule_key WHEN ? THEN 0 WHEN ? THEN 1 WHEN ? THEN 2 ELSE 3 END, {_KIND_RANK}, id",
        (*keys, *keys[:3])).fetchall()


def confirmed_notes(conn, domain, kind):
    """Confirmed note rules for a sender; kind=None (new mail, kind unknown) takes every kind."""
    if kind is None:
        return conn.execute("SELECT * FROM rule WHERE lane='gmail' AND state='confirmed'"
                            " AND kind_of_rule='instruction' AND (rule_key LIKE ? OR rule_key LIKE '*|%')"
                            " ORDER BY id", (f"{domain}|%",)).fetchall()
    return conn.execute(
        "SELECT * FROM rule WHERE lane='gmail' AND state='confirmed' AND kind_of_rule='instruction'"
        " AND rule_key IN (?,?,?) ORDER BY CASE rule_key WHEN ? THEN 0 WHEN ? THEN 1 ELSE 2 END, id",
        (f"{domain}|{kind}", f"{domain}|*", f"*|{kind}", f"{domain}|{kind}", f"{domain}|*")).fetchall()


def list_rules(conn):
    out = []
    for r in conn.execute("SELECT * FROM rule ORDER BY id"):
        d = dict(r)
        d["evidence"] = json.loads(d.pop("evidence_json") or "null")
        out.append(d)
    return out


# ---- discovery: the only proposer ----

FIN = "finance-category"
ACTIVE_DAYS = 90


def _ts(v):
    """Aware datetime from an ISO string; naive values are local time (book.db). None if unparsable."""
    try:
        d = datetime.fromisoformat((v or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.astimezone()


def _gate(conn, lane, source, key):
    """(skip, since, suffix) for a key: skip when a proposed or confirmed rule exists; after a
    rejected or off newest rule, only answers after its decided_at count and the new row's
    source_ref carries @decided_at so it is a fresh identity."""
    rows = conn.execute("SELECT state, decided_at FROM rule WHERE lane=? AND source=? AND rule_key=?"
                        " ORDER BY id DESC", (lane, source, key)).fetchall()
    if any(r["state"] in ("proposed", "confirmed") for r in rows):
        return True, None, ""
    if rows and rows[0]["decided_at"]:
        return False, _ts(rows[0]["decided_at"]), "@" + rows[0]["decided_at"]
    return False, None, ""


def _exists(conn, lane, source, ref):
    return conn.execute("SELECT 1 FROM rule WHERE lane=? AND source=? AND source_ref=?",
                        (lane, source, ref)).fetchone() is not None


def sender_answers(conn, domain, rows):
    """(rows, source_ref) the /gmail KEEP promotion may count for a domain, or (None, None) while a
    proposed or confirmed sender rule exists. After an off or rejected one, only answers after its
    decided_at count, under a fresh @decided_at ref, so the rule can come back."""
    skip, since, suffix = _gate(conn, "gmail", "approved_sender", domain)
    if skip:
        return None, None
    if since:
        rows = [r for r in rows if r.get("ts") and (_ts(r["ts"]) or since) > since]
    return rows, domain + suffix


def _streak_proposal(conn, mod, key, rows, min_senders=1):
    """A fixed_action proposal when the newest STREAK_N answers in rows agree (across at least
    min_senders domains), else None."""
    from . import gmail_lane
    skip, since, suffix = _gate(conn, "gmail", "streak", key)
    if skip:
        return None
    if since:
        rows = [r for r in rows if r.get("ts") and (_ts(r["ts"]) or since) > since]
    answer, label, streak = mod.learned_state(rows)
    if streak < gmail_lane.STREAK_N:
        return None
    agree = sorted(rows, key=lambda r: r["date"])[-streak:]
    if len({mod.norm_domain(r["sender_domain"]) for r in agree}) < min_senders:
        return None
    action = answer.upper().replace(" ", "_")
    action = {"UNSUB": "UNSUBSCRIBE"}.get(action, action)
    return dict(lane="gmail", rule_key=key, kind_of_rule="fixed_action", source="streak",
                source_ref=key + suffix, action=action, target=label if action == "MOVE" else None,
                evidence=[{"date": r["date"], "ts": r.get("ts"), "confirmed": r["confirmed"],
                           "sender": mod.norm_domain(r["sender_domain"])} for r in agree])


SENDER_SCOPED = ("security notice",)  # archetypes whose rules stay per sender


def _streak_candidates(conn):
    """Archetype proposals (*|kind: the newest 3 answers for that archetype agree, any senders).
    Only security mail is still learned per sender: one bank's alerts say nothing about another's."""
    from . import gmail_lane
    path = gmail_lane._decisions_path()
    if not path.exists():
        return []
    mod = gmail_lane._streak_mod()
    allrows = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    for r in allrows:  # old answers carry free-text kinds; read them as their archetype
        r["kind"] = gmail_lane.archetype(r.get("kind"))
    out = []
    for kind in sorted({r["kind"] for r in allrows if r["kind"] and r["kind"] != "other"}):
        if kind in SENDER_SCOPED or gmail_lane.security_like(kind):
            continue
        c = _streak_proposal(conn, mod, f"*|{kind}", [r for r in allrows if r["kind"] == kind])
        if c:
            out.append(c)
    for domain, kind in sorted({(mod.norm_domain(r["sender_domain"]), r["kind"]) for r in allrows
                                if r["kind"] in SENDER_SCOPED}):
        c = _streak_proposal(conn, mod, f"{domain}|{kind}", mod.rows_for(allrows, domain, kind))
        if c:
            out.append(c)
    return out


def archetype_cutover(conn, *, apply=False) -> dict:
    """One-time move from per-sender rules to archetype rules. Remaps stored kinds (inbox rows,
    notes, rule blocks, rule keys) to archetypes; drops never-decided streak proposals so
    discover() re-files them per archetype; widens confirmed notes without a typed op to every
    sender; keeps confirmed per-sender actions working until the archetype rule that replaces
    them is confirmed. Security mail stays per sender. The answer log is left as written."""
    from . import gmail_lane
    arch = gmail_lane.archetype
    plan = []

    def newkey(r):
        dom, _, kind = r["rule_key"].partition("|")
        k = kind if kind in ("", "*") else arch(kind)
        if (r["kind_of_rule"] == "instruction" and not r["op"] and dom != "*" and k not in ("", "*")
                and k not in SENDER_SCOPED):
            dom = "*"
        return f"{dom}|{k}" if _ else dom

    with decisions.locked():
        used = {r[0] for r in conn.execute("SELECT DISTINCT rule_id FROM decision WHERE rule_id IS NOT NULL")}
        for r in conn.execute("SELECT * FROM rule WHERE lane='gmail' ORDER BY id").fetchall():
            nk = newkey(r)
            if (r["state"] == "proposed" and r["source"] == "streak" and r["id"] not in used
                    and nk.split("|")[-1] not in SENDER_SCOPED):
                plan.append(("drop", r["id"], r["rule_key"], None))
            elif nk != r["rule_key"]:
                plan.append(("rekey", r["id"], r["rule_key"], nk))
        if apply:
            for op, rid, _, nk in plan:
                if op == "drop":
                    conn.execute("DELETE FROM rule WHERE id=?", (rid,))
                else:
                    conn.execute("UPDATE rule SET rule_key=?, rev=rev+1, updated_at=? WHERE id=?", (nk, _now(), rid))
            for table in ("gmail_item", "gmail_note"):
                for (k,) in conn.execute(f"SELECT DISTINCT kind FROM {table} WHERE kind IS NOT NULL").fetchall():  # noqa: S608 - fixed names
                    if arch(k) != k:
                        conn.execute(f"UPDATE {table} SET kind=? WHERE kind=?", (arch(k), k))  # noqa: S608
            for rk, since in conn.execute("SELECT rule_key, blocked_since FROM rule_block WHERE lane='gmail'").fetchall():
                dom, bar, kind = rk.partition("|")
                nk = f"{dom}|{arch(kind)}" if bar and kind != "*" else rk
                if nk != rk:
                    conn.execute("DELETE FROM rule_block WHERE lane='gmail' AND rule_key=?", (rk,))
                    conn.execute("INSERT INTO rule_block (lane, rule_key, blocked_since) VALUES ('gmail',?,?)"
                                 " ON CONFLICT DO UPDATE SET blocked_since=min(blocked_since, excluded.blocked_since)",
                                 (nk, since))
            conn.execute("UPDATE gmail_item SET judged_at=NULL WHERE state='proposed'")
            conn.commit()
    filed = discover(conn, dry=not apply)["proposals"] if apply else []
    if apply:  # a confirmed per-sender action the archetype rule agrees with is replaced on its confirm
        for c in filed:
            if not c["rule_key"].startswith("*|"):
                continue
            kind = c["rule_key"][2:]
            old = conn.execute("SELECT id FROM rule WHERE lane='gmail' AND state='confirmed' AND kind_of_rule='fixed_action'"
                               " AND rule_key LIKE ? AND action IS ? AND target IS ? ORDER BY id LIMIT 1",
                               (f"%|{kind}", c["action"], c["target"])).fetchone()
            if old:
                conn.execute("UPDATE rule SET replaces=? WHERE lane='gmail' AND state='proposed' AND rule_key=?",
                             (old[0], c["rule_key"]))
        conn.commit()
    return {"plan": plan, "filed": filed, "applied": apply}


_ANSWERS_SQL = """
SELECT t.payee_id, t.uid, t.date, t.id, t.category_id
FROM txn t LEFT JOIN payee p ON p.id = t.payee_id
WHERE t.approved = 1 AND t.deleted = 0 AND t.transfer_account_id IS NULL AND t.payee_id IS NOT NULL
  AND t.category_id IS NOT NULL AND p.transfer_account_id IS NULL
  AND NOT (t.suggested_confidence IS 'high' AND t.category_id IS t.suggested_category_id)
  AND NOT EXISTS (SELECT 1 FROM split s WHERE s.txn_id = t.id)
ORDER BY t.date, t.id
"""
_RECENT_SQL = "SELECT DISTINCT payee_id FROM txn WHERE deleted = 0 AND payee_id IS NOT NULL AND date >= ?"


def _payee_candidates(conn, bc):
    since90 = (date.today() - timedelta(days=ACTIVE_DAYS)).isoformat()
    active = {r[0] for r in bc.execute(_RECENT_SQL, (since90,))}
    auto = {r[0] for r in conn.execute("SELECT ref FROM decision WHERE lane=? AND made_by='auto'", (FIN,))}
    by = defaultdict(list)
    for r in bc.execute(_ANSWERS_SQL):
        if r[1] not in auto:
            by[r[0]].append(r)
    out = []
    for pid, rows in sorted(by.items()):
        if pid not in active:
            continue
        skip, since, suffix = _gate(conn, FIN, "payee_history", str(pid))
        if skip:
            continue
        if since:  # the txn's own date: a sync re-touches updated_at on old rows
            rows = [r for r in rows if (_ts(r[2]) or since) > since]
        last = rows[-3:]
        if len(last) < 3 or len({r[4] for r in last}) != 1:
            continue
        out.append(dict(lane=FIN, rule_key=str(pid), kind_of_rule="fixed_action",
                        source="payee_history", source_ref=str(pid) + suffix,
                        action=str(last[-1][4]),
                        evidence=[{"uid": r[1], "date": r[2], "category_id": r[4]} for r in last]))
    return out


@contextlib.contextmanager
def _book(book_conn):
    if book_conn is not None:
        yield book_conn
        return
    from finances import book
    with book._conn() as c:  # a context manager yielding the connection
        yield c


def discover(conn, *, book_conn=None, dry=False) -> dict:
    """File streak and payee proposals. dry=True returns the same dict and writes nothing."""
    with _book(book_conn) as bc:
        cands = _streak_candidates(conn) + _payee_candidates(conn, bc)
    n = {"streak": 0, "payee": 0}
    done = []
    for c in cands:
        if dry or propose(conn, **c):
            n["streak" if c["source"] == "streak" else "payee"] += 1
            done.append(c)
    return {**n, "proposals": done}


_OLD_BAR_SQL = """
SELECT t.payee_id, t.category_id, count(*) FROM txn t LEFT JOIN payee p ON p.id = t.payee_id
WHERE t.approved = 1 AND t.deleted = 0 AND t.transfer_account_id IS NULL AND t.payee_id IS NOT NULL
  AND t.category_id IS NOT NULL AND p.transfer_account_id IS NULL AND t.date >= ?
GROUP BY t.payee_id, t.category_id
"""


def _payee_old_bar(conn, bc):
    """/finance's old bar: dominant category count >= 2 and ratio >= 0.6 over 365 days, active 90d."""
    tally = defaultdict(dict)
    for pid, cid, n in bc.execute(_OLD_BAR_SQL, ((date.today() - timedelta(days=365)).isoformat(),)):
        tally[pid][cid] = n
    active = {r[0] for r in bc.execute(
        _RECENT_SQL, ((date.today() - timedelta(days=ACTIVE_DAYS)).isoformat(),))}
    out = []
    for pid, cats in sorted(tally.items()):
        cid, n = max(cats.items(), key=lambda kv: kv[1])
        total = sum(cats.values())
        if pid in active and n >= 2 and n / total >= 0.6:
            out.append(dict(lane=FIN, rule_key=str(pid), kind_of_rule="fixed_action",
                            source="payee_history", source_ref=str(pid), action=str(cid),
                            evidence={"count": n, "total": total, "ratio": round(n / total, 2)}))
    return out


def _sender_candidates():
    """approved-senders.txt domains without an `unsubscribed` mark. Parsed here, not through
    gmail_lane.approved_domains(), which reads confirmed rules once the lane is cut over."""
    from . import gmail_lane
    p = gmail_lane._approved_path()
    lines = p.read_text().splitlines() if p.exists() else []
    doms = {ln.split("#")[0].strip().lower() for ln in lines
            if ln.split("#")[0].strip() and "unsubscribed" not in ln.lower()}
    return [dict(lane="gmail", rule_key=d, kind_of_rule="files_without_asking",
                 source="approved_sender", source_ref=d) for d in sorted(doms)]


def _note_candidates(conn):
    return [dict(lane="gmail", rule_key=f"{r['domain'] or '*'}|{r['kind'] or '*'}",
                 kind_of_rule="instruction", source="note", source_ref=f"note:{r['id']}",
                 note=r["text"], op=r["op"])
            for r in conn.execute("SELECT * FROM gmail_note WHERE active=1 ORDER BY id")]


_COUNT_KEY = {"note": "note", "streak": "streak", "approved_sender": "sender", "payee_history": "payee"}


def cutover(conn, *, book_conn=None, apply=False) -> dict:
    """List (and with apply, file) every learned rule as a proposal under the old bars. Rows
    whose source_ref already exists are skipped, so a second apply writes nothing."""
    with _book(book_conn) as bc:
        cands = (_note_candidates(conn) + _streak_candidates(conn) + _sender_candidates()
                 + _payee_old_bar(conn, bc))
    n = {"note": 0, "streak": 0, "sender": 0, "payee": 0}
    todo = []
    for c in cands:
        if _exists(conn, c["lane"], c["source"], c["source_ref"]):
            continue
        n[_COUNT_KEY[c["source"]]] += 1
        todo.append(c)
    if apply:
        for c in todo:
            rid = propose(conn, **c)
            if rid and c["source"] == "note":
                conn.execute("UPDATE gmail_note SET rule_id=? WHERE id=?",
                             (rid, int(c["source_ref"].split(":")[1])))
        if todo:
            conn.execute("UPDATE gmail_item SET judged_at=NULL WHERE state='proposed'")
        conn.commit()
    return {**n, "proposals": todo, "applied": apply}


def _main(argv):
    if not argv or argv[0] not in ("cutover", "archetypes") or set(argv[1:]) - {"--apply"}:
        print("usage: python3 -m automations.rules cutover|archetypes [--apply]")
        return 2
    from . import db
    apply = "--apply" in argv
    if argv[0] == "archetypes":
        r = archetype_cutover(db.connect(), apply=apply)
        print("APPLIED" if apply else "DRY RUN (nothing written)")
        for op, rid, old, new in r["plan"]:
            print(f"  {op} #{rid} {old}" + (f" -> {new}" if new else ""))
        for c in r["filed"]:
            print(f"  filed {c['rule_key']} -> {c['action']} {c['target'] or ''}")
        return 0
    r = cutover(db.connect(), apply=apply)
    print(f"{'APPLIED' if apply else 'DRY RUN (nothing written)'}")
    print(f"note {r['note']}, streak {r['streak']}, sender {r['sender']}, payee {r['payee']}")
    for c in r["proposals"]:
        what = c.get("action") or c.get("note") or "files without asking"
        print(f"  {c['lane']} {c['source']} {c['rule_key']} [{c['source_ref']}] -> {what}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))

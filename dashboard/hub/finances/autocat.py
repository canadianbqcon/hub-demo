"""Haiku first-pass categorization of new bank rows in data/book.db.

Picks uncategorized, never-suggested rows, asks Haiku for a category from 8
worker threads (results only, no DB writes there), then writes on the calling
thread with a conditional UPDATE so a category set meanwhile always wins.
High-confidence guesses are categorized and approved unless the row is a P2P
outflow or a rideshare (the finance skill always asks about those). Pending
holds are skipped until they post. Everything else keeps the guess in
suggested_*. The prompt pieces are shared with tools/finance-categorize-eval.py.

  cd dashboard/hub && python3 -m finances.autocat [--dry-run] [--limit N]
"""
import collections
import fcntl
import json
import os
import re
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

_HUB = Path(__file__).resolve().parents[1]
if str(_HUB.parent) not in sys.path:  # run as a CLI: dashboard/ holds sqlite_helpers + vault_path
    sys.path[:0] = [str(_HUB), str(_HUB.parent)]

from automations import db as adb  # noqa: E402
from automations import decisions, rules  # noqa: E402

MODEL = "claude-haiku-5-5"
# $/MTok: input, output, cache read, cache write (5m = 1.25x input)
PRICES = {"claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
          "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50)}
P2P = re.compile(r"venmo|zelle|cash ?app", re.I)
# Uber Eats and Uber One are not rides, so they may be auto-approved.
RIDESHARE = re.compile(r"\blyft\b|\buber\b(?![\s*]*(eats|one))|\bempower\s*\*", re.I)  # bank forms: "UBER   *EATS", "EMPOWER* <driver>"

PICK_SQL = """
SELECT t.id, t.uid, t.payee_id, t.date, t.amount_cents AS cents, t.raw_description AS raw,
       p.name AS payee, a.name AS account
FROM txn t
JOIN account a ON a.id = t.account_id
LEFT JOIN payee p ON p.id = t.payee_id
WHERE t.deleted = 0 AND t.pending = 0 AND t.approved = 0 AND t.category_id IS NULL AND t.transfer_account_id IS NULL
  AND t.suggested_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM split s WHERE s.txn_id = t.id)
ORDER BY t.date, t.id LIMIT ?
"""
HIST_SQL = """
SELECT p.name AS payee, t.raw_description AS raw, g.name || ' / ' || k.name AS truth
FROM txn t
JOIN category k ON k.id = t.category_id JOIN category_group g ON g.id = k.group_id
LEFT JOIN payee p ON p.id = t.payee_id
WHERE t.approved = 1 AND t.deleted = 0 AND t.transfer_account_id IS NULL AND t.date >= ?
  AND k.hidden = 0 AND (p.id IS NULL OR p.transfer_account_id IS NULL)
  AND NOT (t.suggested_confidence IS 'high' AND t.category_id IS t.suggested_category_id)
  AND NOT EXISTS (SELECT 1 FROM split s WHERE s.txn_id = t.id)
"""
WRITE_SQL = """
UPDATE txn SET suggested_category_id=?, suggested_confidence=?, suggested_at=?,
       category_id=COALESCE(?, category_id), approved=MAX(approved, ?), updated_at=?
WHERE uid=? AND deleted=0 AND pending=0 AND approved=0 AND category_id IS NULL AND suggested_at IS NULL
  AND transfer_account_id IS NULL AND NOT EXISTS (SELECT 1 FROM split s WHERE s.txn_id = txn.id)
"""
MARK_SQL = "UPDATE txn SET suggested_at=?, updated_at=? " + WRITE_SQL[WRITE_SQL.index("WHERE"):]  # noqa: S608 - both parts are module constants
# waiting rows for the rule pass: PICK_SQL without the never-suggested test, payee known
RULE_PICK_SQL = (PICK_SQL.replace("  AND t.suggested_at IS NULL\n", "  AND t.payee_id IS NOT NULL\n")
                 .replace("ORDER BY t.date, t.id LIMIT ?", "ORDER BY t.date, t.id"))
RULE_WRITE_SQL = ("UPDATE txn SET category_id=?, approved=1, updated_at=? "
                  + WRITE_SQL[WRITE_SQL.index("WHERE"):].replace(" AND suggested_at IS NULL", ""))  # noqa: S608
# real categories only: no card-payment group, no Uncategorized placeholder; income keeps Ready to Assign
CAT_SQL = """
SELECT k.id, g.name || ' / ' || k.name AS full FROM category k JOIN category_group g ON g.id = k.group_id
WHERE k.hidden = 0 AND g.hidden = 0
  AND (g.name NOT IN ('Internal Master Category', 'Credit Card Payments') OR k.name = 'Inflow: Ready to Assign')
"""
LOCK = Path(tempfile.gettempdir()) / "hub-autocat.lock"
AUTOMATIONS_DB = None  # None = the live data/automations.db; tests point it at a tmp path
LANE = "finance-category"


def _payee_blocked(aconn, payee_id) -> bool:
    """True after an undo blocked this payee, until his last three answers since agree."""
    if payee_id is None:
        return False
    key = str(payee_id)
    since = aconn.execute("SELECT blocked_since FROM rule_block WHERE lane=? AND rule_key=?",
                          (LANE, key)).fetchone()
    answers = [] if not since else [
        json.loads(r["changed_json"])["category_id"][1] for r in aconn.execute(
            "SELECT changed_json FROM decision WHERE lane=? AND rule_key=? AND made_by='sam'"
            " AND made_at > ? ORDER BY made_at, id", (LANE, key, since["blocked_since"]))]
    return decisions.blocked(aconn, LANE, key, [str(a) for a in answers])


def undo_category(conn, decision) -> dict:
    """Put one category decision's before values back (conn = automations db). Keeps suggested_*;
    a row changed by hand since is left alone and reported as a conflict. Undoing an automatic
    approval also blocks the payee until three of his answers agree."""
    ch = json.loads(decision["changed_json"])
    (c0, c1), (a0, a1) = ch["category_id"], ch.get("approved", [None, None])
    now = datetime.now().isoformat(timespec="seconds")
    from finances import book
    with book._conn() as c:
        n = c.execute("UPDATE txn SET category_id=?, approved=COALESCE(?, approved), updated_at=?"
                      " WHERE uid=? AND category_id IS ? AND (? IS NULL OR approved=?)",
                      (c0, a0, now, decision["ref"], c1, a1, a1)).rowcount
    if n == 0:
        return {"conflict": "the transaction's category or approval changed since this decision"}
    if decision["made_by"] == "auto":
        decisions.rule_off_or_block(conn, decision, LANE)
    decisions.finish(conn, decision["id"], "undone")
    return {"ok": True}



def system_prompt(cats, by_payee):
    lines = [f"- {p}: " + ", ".join(f"{k} ({n})" for k, n in h.most_common(3))
             for p, h in sorted(by_payee.items())]
    return (
        "You categorize bank transactions for one person's personal budget (NYC, works shifts at "
        "the restaurant Juniper & Co). Pick exactly one category from the list.\n\n"
        "Rules:\n"
        "- Amounts are negative for money out, positive for money in.\n"
        "- A Venmo/Zelle/Cash App INFLOW from a person is someone paying him back: Reimbursements / Payback.\n"
        "- A check deposit is his Juniper & Co paycheck.\n"
        "- Uber and other rides are personal, not work expenses.\n"
        "- Payee history below is strong evidence but not absolute; the same payee can vary.\n"
        "- Set confidence to low when the payee is new or its history is split.\n\n"
        "Categories:\n" + "\n".join(f"- {c}" for c in cats) +
        "\n\nPayee history (payee: category (count)):\n" + "\n".join(lines))


def user_prompt(r):
    return (f"Date: {r['date']}\nAmount: {r['cents'] / 100:+.2f} USD\nAccount: {r['account']}\n"
            f"Payee: {r['payee'] or '(none)'}\nBank description: {r['raw']}")


def schema(cats):
    return {"type": "json_schema", "schema": {
        "type": "object",
        "properties": {"category": {"type": "string", "enum": cats},
                       "confidence": {"type": "string", "enum": ["high", "low"]}},
        "required": ["category", "confidence"], "additionalProperties": False}}


def cost(model, u):
    pi, po, pcr, pcw = PRICES[model]
    return (u.input_tokens * pi + u.output_tokens * po
            + (u.cache_read_input_tokens or 0) * pcr
            + (u.cache_creation_input_tokens or 0) * pcw) / 1e6


def _api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    env = Path(os.environ.get("VAULT_API_CONFIG") or Path.home() / ".config" / "vault-api") / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _allowed(r, conf):
    text = f"{r['payee'] or ''} {r['raw']}"
    return (conf == "high" and not (r["cents"] < 0 and P2P.search(text))
            and not RIDESHARE.search(text))


def predict(client, r, sys_text, cats, model=MODEL, effort="medium"):
    """(category or None, confidence, cost), or None when the call itself failed.

    A refusal, a cut-off or an unparseable answer comes back with category None:
    retrying would only repeat it, so the caller marks the row as tried. An API
    error returns None (the SDK already retries 429/5xx); the error's HTTP status
    is left on the row as `error_status`, and the caller retries it next run
    unless it is a 400 (that row's request is bad, see _row_fault).
    Pure: no DB access, safe in a worker thread.
    """
    try:
        resp = client.messages.create(
            model=model, max_tokens=2048,
            system=[{"type": "text", "text": sys_text, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_prompt(r)}],
            output_config={"effort": effort, "format": schema(cats)})
    except Exception as e:
        print(f"  autocat failed txn {r['id']}: {e}", file=sys.stderr)
        r["error_status"] = getattr(e, "status_code", None)
        return None
    spent = cost(model, resp.usage)
    if resp.stop_reason in ("refusal", "max_tokens"):  # a cut-off repeats on retry
        return None, "low", spent
    try:
        d = json.loads(next(b.text for b in resp.content if b.type == "text"))
        return d["category"], d["confidence"], spent
    except (StopIteration, ValueError, KeyError, TypeError):
        return None, "low", spent


def _row_fault(r) -> bool:
    """Did this row's call fail with a 400 (a request only this row makes bad)?"""
    return r.get("error_status") == 400


def run(client=None, limit=200, dry_run=False):
    """Categorize up to `limit` new posted rows (pending holds wait until they post).
    One writing run at a time across processes (scheduler and the Sync button),
    so a row is never paid for twice; a dry run writes nothing and takes no lock."""
    if dry_run:
        return _run(client, limit, dry_run)
    with open(LOCK, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped", "reason": "another autocat run is in progress"}
        return _run(client, limit, dry_run)


def rule_pass(aconn, book_conn=None, dry_run=False) -> dict:
    """Apply confirmed payee rules to waiting rows (suggested or not). Never raises: a rule table
    that cannot be read means nothing is applied."""
    from finances import book
    try:
        if book_conn is not None:
            return _rule_pass(aconn, book_conn, dry_run)
        with book._conn() as c:
            return _rule_pass(aconn, c, dry_run)
    except Exception as e:  # fail closed: no rule, no write
        print(f"  autocat rule pass failed: {e}", file=sys.stderr)
        return {"ruled": 0, "error": str(e)}


def _rule_pass(aconn, c, dry_run) -> dict:
    ruled, found = 0, {}
    c.row_factory = c.row_factory or sqlite3.Row
    now = datetime.now().isoformat(timespec="seconds")
    for r in [dict(x) for x in c.execute(RULE_PICK_SQL)]:
        if r["payee_id"] not in found:
            found[r["payee_id"]] = rules.confirmed(aconn, LANE, str(r["payee_id"]))
        rs = [x for x in found[r["payee_id"]] if x["kind_of_rule"] == "fixed_action" and x["action"]]
        if not rs or not _allowed(r, "high"):
            continue
        rule, cid = rs[0], int(rs[0]["action"])
        if dry_run:
            print(f"{r['date']} {r['cents'] / 100:+9.2f} {(r['payee'] or r['raw'])[:32]:32} -> rule {rule['id']} [auto]")
            continue
        did = decisions.begin(
            aconn, LANE, r["uid"], "categorize", {"category_id": [None, cid], "approved": [0, 1]},
            made_by="auto", undo="reversible", rule_key=str(r["payee_id"]),
            rule_id=rule["id"], rule_rev=rule["rev"])
        with decisions.locked():  # rule changes take this lock, so an off between check and write cannot slip in
            if not rules.still_confirmed(aconn, [(rule["id"], rule["rev"])]):
                n = 0
            else:
                try:
                    n = c.execute(RULE_WRITE_SQL, (cid, now, r["uid"])).rowcount
                    c.commit()
                except sqlite3.Error as e:
                    decisions.finish(aconn, did, "failed", str(e)[:200])
                    return {"ruled": ruled, "error": f"book write failed: {e}"}
        if n:
            decisions.finish(aconn, did, "applied")
            ruled += 1
        else:
            aconn.execute("DELETE FROM decision WHERE id=?", (did,))
            aconn.commit()
    return {"ruled": ruled}


def _run(client, limit, dry_run):
    aconn = adb.connect(AUTOMATIONS_DB)
    try:
        ruled = rule_pass(aconn, dry_run=dry_run)
        if not dry_run:
            try:
                rules.discover(aconn)
            except Exception as e:  # missing or failing discovery never breaks autocat
                print(f"  rules.discover failed: {e}", file=sys.stderr)
        out = _model_pass(client, limit, dry_run, aconn)
        out["ruled"] = ruled["ruled"]
        return out
    finally:
        aconn.close()


def _model_pass(client, limit, dry_run, aconn):  # noqa: C901 - the run's phases in order; splitting would only thread shared state
    from finances import book
    if client is None:
        key = _api_key()
        if not key:
            return {"status": "skipped", "reason": "no ANTHROPIC_API_KEY"}
        import anthropic
        client = anthropic.Anthropic(api_key=key)
    since = (date.today() - timedelta(days=365)).isoformat()
    out = {"status": "ok", "considered": 0, "approved": 0, "suggested_only": 0, "failed": 0, "cost_usd": 0.0}
    with book._conn() as c:
        rows = [dict(r) for r in c.execute(PICK_SQL, (limit,))]
        if not rows:
            return out
        hist = c.execute(HIST_SQL, (since,)).fetchall()
        cat_ids = {r["full"]: r["id"] for r in c.execute(CAT_SQL)}
    out["considered"] = len(rows)
    now = datetime.now().isoformat(timespec="seconds")
    cats = sorted(cat_ids)
    by_payee = collections.defaultdict(collections.Counter)
    for h in hist:
        by_payee[h["payee"] or h["raw"]][h["truth"]] += 1
    sys_text = system_prompt(cats, by_payee)

    one = lambda r: predict(client, r, sys_text, cats)  # noqa: E731
    preds = [one(rows[0])]  # warms the prompt cache so parallel calls read it
    if _row_fault(rows[0]) and len(rows) > 1:
        preds.append(one(rows[1]))  # one bad row, or a bad request every row would hit?
    if preds[-1] is None and not (len(rows) == 1 and _row_fault(rows[0])):
        # bad key, outage, or the same 400 twice: stop before 200 more failing calls
        return {**out, "status": "error", "reason": "first API call failed", "failed": len(rows)}
    with ThreadPoolExecutor(8) as ex:
        preds += list(ex.map(one, rows[len(preds):]))

    with book._conn() as c:
        for r, p in zip(rows, preds, strict=False):
            if p is None:  # call failed: retried next run, unless the row itself is the problem
                out["failed"] += 1
                if _row_fault(r) and not dry_run:
                    c.execute(MARK_SQL, (now, now, r["uid"]))
                continue
            cat, conf, spent = p
            out["cost_usd"] += spent
            if cat not in cat_ids:  # refused or unparseable: mark tried so it is not re-sent forever
                out["failed"] += 1
                if not dry_run:
                    c.execute(MARK_SQL, (now, now, r["uid"]))
                continue
            allow = _allowed(r, conf) and not _payee_blocked(aconn, r["payee_id"])
            if dry_run:
                print(f"{r['date']} {r['cents'] / 100:+9.2f} {(r['payee'] or r['raw'])[:32]:32} "
                      f"-> {cat} ({conf}){' [auto]' if allow else ''}")
                continue
            cid = cat_ids[cat]
            did = decisions.begin(
                aconn, LANE, r["uid"], "categorize",
                {"category_id": [None, cid], "approved": [0, 1]}, made_by="auto", undo="reversible",
                rule_key=None if r["payee_id"] is None else str(r["payee_id"])) if allow else None
            try:
                n = c.execute(WRITE_SQL, (cid, conf, now, cid if allow else None, int(allow), now,
                                          r["uid"])).rowcount
                if n and allow:
                    c.commit()
            except sqlite3.Error as e:  # e.g. book.db locked by the Sync button: stop, keep earlier rows
                if did:
                    decisions.finish(aconn, did, "failed", str(e)[:200])
                out.update(failed=out["failed"] + 1, reason=f"book write failed: {e}")
                break
            if did and not n:  # the row changed meanwhile: nothing happened
                aconn.execute("DELETE FROM decision WHERE id=?", (did,))
                aconn.commit()
            if n and allow:
                decisions.finish(aconn, did, "applied")
                out["approved"] += 1
            elif n:
                out["suggested_only"] += 1
    out["cost_usd"] = round(out["cost_usd"], 4)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=200)
    a = ap.parse_args()
    print(json.dumps(run(limit=a.limit, dry_run=a.dry_run), indent=2))

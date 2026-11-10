"""Automations Hub blueprint: the Activity feed page, its data, and the page actions.

The feed joins four sources in Python: data/automations.db (Gmail lane items),
book.db (finance rows Haiku categorized and approved, category unchanged),
news.db digests, and log/scheduler-runs.jsonl. Every time is shown as local.
Actions name a gmail_item id, never a raw Gmail id, so the page can only act on
mail the lane saw.
"""

from __future__ import annotations

import functools
import json
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from . import db, decisions, followups, gmail_actions, rules

bp = Blueprint("automations", __name__, template_folder="frontend",
               static_folder="frontend/static", url_prefix="/automations")

UPDATER_LOG = Path("/mnt/c/ProgramData/CraftUpdater/update.log")  # PC only; missing on the Mac
WAITING = ("proposed", "unconfirmed")
GMAIL_LINK = "https://mail.google.com/mail/u/0/#all/"
FINANCE_SQL = """
SELECT t.id, t.date, t.amount_cents, t.raw_description, p.name AS payee, t.suggested_at,
       g.name || ' / ' || k.name AS category
FROM txn t
JOIN category k ON k.id = t.category_id JOIN category_group g ON g.id = k.group_id
LEFT JOIN payee p ON p.id = t.payee_id
WHERE t.suggested_confidence = 'high' AND t.approved = 1 AND t.deleted = 0
  AND t.category_id = t.suggested_category_id AND t.suggested_at >= ?
"""


def _local(ts) -> str:
    """Any stored timestamp as local naive ISO; a naive one without 'T' (SQLite datetime('now')) is UTC."""
    s = str(ts or "")
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return ""  # unreadable: sorts last and falls outside every window
    if d.tzinfo is None and " " in s:
        d = d.replace(tzinfo=timezone.utc)
    return (d.astimezone() if d.tzinfo else d).replace(tzinfo=None).isoformat(timespec="seconds")


def _event(t, kind, bad=False, **rest) -> dict:
    t = _local(t)
    return {"t": t, "day": t[:10], "kind": kind, "bad": bad, **rest}


def _item(r) -> dict:
    d = dict(r)
    d["received_at"] = _local(d["received_at"])
    d["gmail_link"] = GMAIL_LINK + d["msg_id"]
    d["unsub_safe"] = bool(d["unsub_url"]) and gmail_actions.unsub_safe(d["unsub_url"], d["domain"])
    return d


def _finance(since: str) -> list[dict]:
    from finances import book
    with book._conn() as c:
        return [dict(r) for r in c.execute(FINANCE_SQL, (since,))]


def _finance_waiting(since: str) -> list[dict]:
    """Unreviewed book rows minus pending holds, each with its stored memo draft (if any)."""
    from finances import book
    rows = [r for r in book.fetch_unreviewed(since_date=since) if not r["pending"]]
    conn = db.connect()
    try:
        drafts = dict(conn.execute("SELECT txn_uid, memo FROM memo_draft"))
        skipped = {r[0] for r in conn.execute("SELECT txn_uid FROM memo_skip")}
    finally:
        conn.close()
    keep = ("date", "payee", "amount_str", "direction", "needs", "category_name",
            "suggested_category_name", "memo")
    out = []
    for r in rows:
        needs = [n for n in r["needs"] if not (n == "memo" and r["id"] in skipped)]
        if needs:  # a row whose only need was the memo he waived is done
            out.append({"lane": "finance", "uid": r["id"], **{k: r[k] for k in keep}, "needs": needs,
                        "memo_draft": drafts.get(r["id"])})
    return out


def _inflow_category() -> list[dict]:
    """Income's category sits in the hidden Internal group, so the shared category list leaves it out."""
    from finances import book
    try:
        with book._conn() as c:
            r = c.execute("SELECT id FROM category WHERE name = ?", (book.READY_TO_ASSIGN,)).fetchone()
    except Exception:
        return []
    return [{"id": str(r["id"]), "name": book.READY_TO_ASSIGN, "full_name": book.READY_TO_ASSIGN}] if r else []


def _digests(days: list[str]) -> list[dict]:
    from news import db as news_db
    return [d for d in (news_db.get_digest(day) for day in days) if d]


def _runs(since: str) -> list[dict]:
    import scheduler
    return [r for r in scheduler.recent_runs(5000) if _local(r.get("date")) >= since]


@functools.lru_cache(maxsize=1)
def _labels_live() -> tuple:
    # ponytail: cached for the Hub's lifetime; a label added in Gmail shows after a restart
    import os
    import sys
    sys.path.insert(0, os.path.expanduser("~/.config/vault-api"))
    import services
    got = services.gmail_readonly().users().labels().list(userId="me").execute().get("labels", [])
    return tuple(sorted(lb["name"] for lb in got if lb.get("type") == "user"))


def _labels() -> tuple:
    try:
        return _labels_live()
    except Exception:  # not cached, so the next page load tries again
        return ()


def feed(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    week = (now - timedelta(days=7)).isoformat(timespec="seconds")
    conn = db.connect()
    try:
        items = [_item(r) for r in conn.execute("SELECT * FROM gmail_item ORDER BY received_at")]
        for i in items:  # the page shows a Read button where his note said "trash once read"
            i["wants_read"] = i["state"] == "proposed" and (followups.op_for(conn, i["domain"], i["kind"]) or ("",))[0] == "ack_then_trash"
        # a note leaves waiting only once judged to act on this email; standing-only or unjudged notes stay
        notes = conn.execute("SELECT item_id, scope FROM gmail_note WHERE item_id IS NOT NULL").fetchall()
    finally:
        conn.close()
    linked = {r[0] for r in notes}
    handed = {r[0] for r in notes if r[1] in ("once", "both")}
    for i in items:
        i["lane"] = "gmail"
        if i.get("note") and i["id"] not in linked:  # a note from before notes carried their email: handed, as it was then
            handed.add(i["id"])
    waiting = [i for i in items if i["state"] in WAITING and i["id"] not in handed]
    noted = [i for i in items if i["state"] in WAITING and i["id"] in handed]
    # stale = he settled it in Mail or Gmail before answering the lane: not a failure
    events = [_event(i["updated_at"], "sorted", i["state"] == "failed", item=i)
              for i in items if i["state"] not in WAITING and _local(i["updated_at"]) >= week]
    events += [_event(f["suggested_at"], "finance", txn=f) for f in _finance(week)]
    days = [(now - timedelta(days=n)).date().isoformat() for n in range(8)]
    events += [_event(d["created_at"], "digest", date=d["date"],
                      bullets=sum(line.startswith("- ") for line in d["markdown"].splitlines()))
               for d in _digests(days)]
    events += [_event(r["date"], "run", r.get("status") != "ok", run=r)
               for r in _runs((now - timedelta(hours=48)).isoformat(timespec="seconds"))]
    events.sort(key=lambda e: e["t"], reverse=True)
    today = now.date().isoformat()
    return {
        "waiting": waiting, "noted": noted,
        "finance_waiting": _finance_waiting((now - timedelta(days=45)).date().isoformat()), "events": events, "labels": list(_labels()), "inflow": _inflow_category(),
        "digest_today": next((e for e in events if e["kind"] == "digest" and e["date"] == today), None),
        "counts": {"waiting": len(waiting), "noted": len(noted), "sorted": sum(e["kind"] == "sorted" for e in events),
                   "runs": sum(e["kind"] == "run" for e in events),
                   "failed": sum(e["bad"] for e in events)},
    }


# ---- rules tab ----

SOURCE_VIEW = {"approved_sender": "sender", "payee_history": "payee"}


def _split_key(r):
    """(domain, kind) of a gmail rule; kind None means every kind of the sender."""
    dom, _, kind = r["rule_key"].partition("|")
    return dom, (None if kind in ("", "*") else kind)


def rule_text(r, payee=None, category=None) -> str:
    """What a rule does, in one line: the row title on the tab and a decision card's rule line."""
    if r["lane"] != "gmail":
        return f"categorize {payee or 'payee ' + r['rule_key']} as {category or 'category ' + str(r['action'])}"
    dom, kind = _split_key(r)
    what = f"{kind} mail from {'any sender' if dom == '*' else dom}" if kind else f"all mail from {dom}"
    if r["kind_of_rule"] == "files_without_asking":
        return f"file {dom} mail without asking"
    if r["kind_of_rule"] == "instruction":
        return r["note"] or f"follow your note on {what}"
    act = (r["action"] or "").upper()
    return {"DELETE": f"delete {what}", "KEEP": f"keep {what}",
            "MOVE": f"move {what} to {r['target']}"}.get(act, f"{act.lower()} {what}")


def _sender_comments() -> dict:
    from . import gmail_lane
    try:
        lines = gmail_lane._approved_path().read_text().splitlines()
    except OSError:
        return {}
    out = {}
    for ln in lines:
        dom, _, comment = ln.partition("#")
        if dom.strip():
            out[dom.strip().lower()] = comment.strip()
    return out


def _book_names(payee_ids, uids):
    """payee id -> name, category id -> 'Group / Name', uid -> amount_cents, payee id -> waiting count,
    payee id -> its last 3 approved rows; empty when book.db is unreadable."""
    from finances import book
    try:
        with book._conn() as c:
            payees = {str(r[0]): r[1] for r in c.execute("SELECT id, name FROM payee")} if payee_ids else {}
            cats = {str(r[0]): f"{r[1]} / {r[2]}" for r in c.execute(
                "SELECT k.id, g.name, k.name FROM category k JOIN category_group g ON g.id = k.group_id")}
            amts = {r[0]: r[1] for r in c.execute(
                f"SELECT uid, amount_cents FROM txn WHERE uid IN ({','.join('?' * len(uids))})", list(uids))} if uids else {}  # noqa: S608 - placeholders only
            waiting = {str(r[0]): r[1] for r in c.execute(
                "SELECT payee_id, count(*) FROM txn WHERE approved = 0 AND category_id IS NULL AND deleted = 0"
                " AND payee_id IS NOT NULL GROUP BY payee_id")}
            last = {}
            for pid in payee_ids:
                last[str(pid)] = [{"date": r[0], "amount": r[1], "category_id": r[2]} for r in c.execute(
                    "SELECT date, amount_cents, category_id FROM txn WHERE payee_id=? AND approved=1 AND deleted=0"
                    " AND category_id IS NOT NULL ORDER BY date DESC, id DESC LIMIT 3", (pid,))][::-1]
    except Exception as e:
        print(f"rules tab: book.db unreadable: {e}", file=sys.stderr)
        return {}, {}, {}, {}, {}
    return payees, cats, amts, waiting, last


def rules_view(conn) -> list[dict]:
    """Every rule in the shape the rules tab renders (design A, data.js). waiting is read from the
    stored rows only: no model call and no write."""
    rows = rules.list_rules(conn)
    fin = [r for r in rows if r["lane"] != "gmail"]
    uids = {e["uid"] for r in fin if isinstance(r["evidence"], list) for e in r["evidence"] if e.get("uid")}
    payees, cats, amts, fin_wait, last = _book_names({r["rule_key"] for r in fin}, uids) if fin else ({}, {}, {}, {}, {})
    comments = _sender_comments() if any(r["source"] == "approved_sender" for r in rows) else {}
    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    out = []
    for r in rows:
        v = {k: r[k] for k in ("id", "lane", "state", "rev", "kind_of_rule", "target", "note")}
        v["source"] = SOURCE_VIEW.get(r["source"], r["source"])
        v["sent_back"] = rules.sent_back(r)
        v["action"] = (r["action"] or "").lower() or None if r["lane"] == "gmail" else r["action"]
        v["recent"] = [{"made_at": d["made_at"], "action": (d["action"] or "").lower(), "id": d["id"],
                        "title": _decision_title(conn, d)}
                       for d in conn.execute("SELECT * FROM decision WHERE rule_id=? AND made_at >= ?"
                                             " ORDER BY made_at DESC", (r["id"], week))]
        if r["lane"] != "gmail":
            cat = cats.get(str(r["action"]))
            ev = r["evidence"]
            if isinstance(ev, dict):  # cutover files the old bar's tally; show his last 3 answers from the book
                count, total, ev = ev.get("count"), ev.get("total"), last.get(r["rule_key"], [])
            else:
                ev = ev or []
                count, total = sum(str(e.get("category_id")) == str(r["action"]) for e in ev), len(ev)
            v.update(who=payees.get(r["rule_key"], f"payee {r['rule_key']}"), kind=None, category=cat,
                     does=rule_text(r, payees.get(r["rule_key"]), cat),
                     answers=[{"at": e.get("date"), "amount": e.get("amount", amts.get(e.get("uid"))),
                               "category": cats.get(str(e.get("category_id")))} for e in ev],
                     count=count, total=total,
                     waiting_n=fin_wait.get(r["rule_key"], 0))
            out.append(v)
            continue
        dom, kind = _split_key(r)
        v.update(who="any sender" if dom == "*" else dom, kind=kind, does=rule_text(r))
        q, args = "SELECT subject, received_at FROM gmail_item WHERE state IN ('proposed', 'unconfirmed') AND (domain=? OR ?='*')", [dom, dom]
        if kind:
            q, args = q + " AND kind=?", args + [kind]
        if r["kind_of_rule"] == "files_without_asking":
            q += " AND action='MOVE'"  # ponytail: the stored verdict stands in for a fresh one; the lane re-judges on confirm
        v["waiting"] = [{"subject": w[0], "at": w[1]} for w in conn.execute(q + " ORDER BY received_at", args)]
        if r["source"] == "note":
            n = conn.execute("SELECT * FROM gmail_note WHERE id=?", (int(r["source_ref"].split(":")[1].split("@")[0]),)).fetchone()
            it = conn.execute("SELECT subject, received_at FROM gmail_item WHERE id=?", (n["item_id"],)).fetchone() if n and n["item_id"] else None
            v.update(quote=n["text"] if n else r["note"], scope=n["scope"] if n else None, at=n["created_at"] if n else r["created_at"],
                     from_mail={"subject": it[0], "at": it[1]} if it else None)
        elif r["source"] == "streak":
            # ponytail: the decision log keeps no subjects, so the sender names the row
            v["answers"] = [{"at": e.get("ts") or e.get("date"), "action": str(e.get("confirmed") or "").lower(),
                             "subject": e.get("sender") or (None if dom == "*" else dom)}
                            for e in (r["evidence"] or [])]
        else:
            v["comment"] = comments.get(dom, "")
        out.append(v)
    return out


def _after_rule_change(r, note=None, sort=True) -> None:
    """Background, after a confirm or edit: re-type an edited note's op from its new text, then
    sort what is waiting under the rule at once."""
    conn = db.connect()
    try:
        if r["lane"] == "gmail":
            import anthropic
            from . import followups, gmail_lane
            client = anthropic.Anthropic(api_key=gmail_lane._api_key())
            dom, kind = _split_key(r)
            if note is not None:
                got = followups.judge_note(client, note, {"domain": dom, "kind": kind}, None)
                cur = rules.get(conn, r["id"])
                if got and got["op"] and cur is not None:
                    rules.edit(conn, r["id"], cur["rev"], op=got["op"])
            if sort:
                gmail_lane.rejudge(conn, gmail_actions._live_gmail(), client, dom, kind or "*")
        elif sort:
            from finances import autocat
            autocat.rule_pass(conn)
    except Exception as e:  # a daemon thread: never let it die loudly into the page
        print(f"rules after-change failed: {e}", file=sys.stderr)
    finally:
        conn.close()


def _after_send_back(r, note) -> None:
    """Background, after a send-back: Claude rewrites the rule from his note and it stays
    proposed for him to confirm. The send-back record ends revised or failed."""
    conn = db.connect()
    sent = {"note": note, "at": rules._now(), "status": "failed"}
    fields = None
    try:
        import anthropic
        from . import followups, gmail_lane
        client = anthropic.Anthropic(api_key=gmail_lane._api_key())
        if r["lane"] == "gmail":
            line, choices = rule_text(r), list(_labels())
        else:
            from finances import book
            payees, cats = _book_names({r["rule_key"]}, set())[:2]
            line = rule_text(r, payees.get(r["rule_key"]), cats.get(str(r["action"])))
            choices = {str(c["id"]): c["full_name"] for c in book.fetch_categories()}
        fields = followups.revise_rule(client, line, note, r["lane"], r["kind_of_rule"], choices)
        if fields and r["kind_of_rule"] == "files_without_asking":
            fields.update(kind_of_rule="fixed_action", rule_key=f"{r['rule_key']}|*")
    except Exception as e:  # a daemon thread: never let it die loudly into the page
        print(f"rule send-back revise failed: {e}", file=sys.stderr)
    try:
        cur = rules.get(conn, r["id"])
        if cur is not None:
            sent["status"] = "revised" if fields else "failed"
            rules.revise(conn, r["id"], cur["rev"], sent, **(fields or {}))
    finally:
        conn.close()
    if fields and fields.get("note"):
        _after_rule_change(r, note=fields["note"], sort=False)  # re-type the op from the new text


RULE_VERBS = ("confirm", "reject", "off", "edit", "sendback")


@bp.get("/api/rules")
def api_rules():
    conn = db.connect()
    try:
        return jsonify({"rules": rules_view(conn)})
    finally:
        conn.close()


@bp.post("/api/rules/<int:rid>/<verb>")
def api_rule_act(rid, verb):
    if bad := _cross_site():
        return bad
    data = request.get_json(silent=True)
    if verb not in RULE_VERBS:
        return jsonify({"error": f"unknown action {verb}"}), 404
    if not isinstance(data, dict) or not isinstance(data.get("rev"), int) or isinstance(data.get("rev"), bool):
        return jsonify({"error": "rev must be the rule's revision"}), 400
    conn = db.connect()
    try:
        r = rules.get(conn, rid)
        if r is None:
            return jsonify({"error": "no such rule"}), 404
        if verb == "edit":
            fields = {k: data[k] for k in rules.EDITABLE if isinstance(data.get(k), str) and data[k].strip()}
            if not fields:
                return jsonify({"error": "nothing to change"}), 400
            if r["lane"] != "gmail":
                if set(fields) != {"action"} or not fields["action"].isdigit():
                    return jsonify({"error": "a category rule changes only its category id"}), 400
                from finances import book
                with book._conn() as bc:
                    book._check_category(bc, fields["action"])
            if "note" in fields and "op" not in fields:
                fields["op"] = None  # re-typed from the new text in the background
            if r["lane"] == "gmail" and "action" in fields:
                fields["action"] = fields["action"].upper()
                if fields["action"] not in ("MOVE", "DELETE", "KEEP"):
                    return jsonify({"error": "action must be move, delete or keep"}), 400
                if fields["action"] != "MOVE":
                    fields["target"] = None
            res = rules.edit(conn, rid, data["rev"], **fields)
        elif verb == "sendback":
            note = data.get("note").strip() if isinstance(data.get("note"), str) else ""
            if not note:
                return jsonify({"error": "say what is wrong with the rule"}), 400
            res = rules.send_back(conn, rid, data["rev"], note[:500])
            if "conflict" not in res:
                threading.Thread(target=_after_send_back, args=(dict(r), note[:500]), daemon=True).start()
            return (jsonify(res), 409) if "conflict" in res else jsonify(res)
        else:
            res = {"confirm": rules.confirm, "reject": rules.reject, "off": rules.set_off}[verb](conn, rid, data["rev"])
        if "conflict" in res:
            return jsonify(res), 409
        retype = verb == "edit" and "note" in fields and "op" not in data
        sort = verb == "confirm" or (verb == "edit" and r["state"] == "confirmed")
        if retype or sort:
            threading.Thread(target=_after_rule_change, args=(dict(r),),
                             kwargs={"note": fields["note"] if retype else None, "sort": sort}, daemon=True).start()
        return jsonify(res)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@bp.post("/api/note/<int:nid>/scope")
def api_note_scope(nid):
    if bad := _cross_site():
        return bad
    data = request.get_json(silent=True)
    conn = db.connect()
    try:
        return jsonify(gmail_actions.set_scope(conn, nid, (data or {}).get("scope") if isinstance(data, dict) else None))
    except LookupError:
        return jsonify({"error": "no such note"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@bp.get("/")
def index():
    return render_template("automations.html")


@bp.get("/api/feed")
def api_feed():
    return jsonify(feed())


@bp.get("/api/burns")
def api_burns():
    """Every recorded /burn run, newest first, report_json parsed."""
    conn = db.connect()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM burn_run ORDER BY started_at DESC")]
    finally:
        conn.close()
    for r in rows:
        try:
            r["report"] = json.loads(r.pop("report_json"))
        except ValueError:
            r["report"] = {"jobs": []}
    return jsonify(rows)


@bp.get("/api/updates")
def api_updates():
    """Last 64 KB of the Craft updater log, newest first, at most 200 lines. Always HTTP 200."""
    try:
        with open(UPDATER_LOG, "rb") as f:
            size = f.seek(0, 2)
            start = max(0, size - 65536)
            f.seek(start)
            raw = f.read()
    except FileNotFoundError:
        return jsonify({"state": "missing", "lines": []})
    except OSError:
        return jsonify({"state": "error", "lines": []})
    rows = raw.decode("utf-8", errors="replace").split("\n")
    if start:
        rows = rows[1:]  # first line is cut mid-way
    texts = [x.strip() for x in rows if x.strip()][::-1][:200]
    lines = []
    for n, text in enumerate(texts, 1):
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d)", text)
        lines.append({"n": n, "t": m.group(1) if m else None, "text": text,
                      "bad": bool(re.search(r"error|fail|mismatch|missing|exit -?[1-9]", text, re.I))})  # update.ps1 failure wording
    return jsonify({"state": "ok", "lines": lines})


@bp.post("/api/act")
def api_act():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("id"), int) or isinstance(data.get("id"), bool):
        return jsonify({"error": "id must be a gmail_item id"}), 404
    try:
        res = gmail_actions.act(data["id"], str(data.get("action", "")), data.get("label"), note=data.get("note"))
    except LookupError:
        return jsonify({"error": "no such item"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # Gmail or network trouble: JSON, so the page can say what failed
        return jsonify({"error": f"Gmail call failed: {e}"}), 502
    return jsonify(res)


@bp.post("/api/finance/act")
def api_finance_act():
    body, code = finance_apply(request.get_json(silent=True))
    return jsonify(body), code


def finance_apply(data, *, made_by="sam", reason="") -> tuple[dict, int]:
    """A finance write plus one decision per changed field. Shared by the page, decisions.fix()
    and the /finance skill, which passes made_by='auto' for its own confident calls so rule
    discovery does not count them as his answers and the decisions tab can undo them.
    made_by is a Python argument only, never read from the request body."""
    if made_by not in ("sam", "auto"):
        raise ValueError(f"made_by must be sam or auto, not {made_by!r}")
    from finances import book
    if not isinstance(data, dict) or not isinstance(data.get("uid"), str):
        return {"error": "uid must be a transaction uid"}, 404
    with book._conn() as c:
        before = c.execute("SELECT payee_id, category_id, memo, approved FROM txn WHERE uid = ? AND deleted = 0",
                           (data["uid"],)).fetchone()
        if not before:
            return {"error": "no such transaction"}, 404
        cat = data.get("category_id")
        if cat is not None:
            try:
                book._check_category(c, cat)
            except (ValueError, TypeError) as e:
                return {"error": str(e)}, 400
    memo = data.get("memo")
    if memo is not None and not isinstance(memo, str):
        return {"error": "memo must be text"}, 400
    if data.get("no_memo"):  # he chose no memo for this row: stop asking, and the memo lane leaves it
        c = db.connect()
        try:
            c.execute("INSERT OR IGNORE INTO memo_skip (txn_uid, created_at) VALUES (?, ?)", (data["uid"], decisions._now()))
            c.commit()
        finally:
            c.close()
        memo = None
    uid, key = data["uid"], None if before["payee_id"] is None else str(before["payee_id"])
    approve = bool(data.get("approve")) and not before["approved"]
    new_cat = int(cat) if cat is not None and int(cat) != before["category_id"] else None
    new_memo = memo if memo is not None and memo != (before["memo"] or "") else None
    conn = db.connect()
    try:
        steps = []  # (lane, action, changed, write)
        if new_cat is not None:
            ch = {"category_id": [before["category_id"], new_cat]}
            if approve:
                ch["approved"] = [0, 1]
            steps.append(("finance-category", "categorize", ch,
                          lambda: book.update_transaction(uid, category_id=str(new_cat), approved=True if approve else None)))
        elif approve:  # approving the current category is his answer too; the payee gate counts it
            steps.append(("finance-category", "categorize",
                          {"category_id": [before["category_id"]] * 2, "approved": [0, 1]},
                          lambda: book.update_transaction(uid, approved=True)))
        if new_memo is not None:
            steps.append(("finance-memo", "memo", {"memo": [before["memo"] or "", new_memo]},
                          lambda: book.update_transaction_memo(uid, new_memo)))
        failed = False
        for lane, action, changed, write in steps:
            did = decisions.begin(conn, lane, uid, action, changed, made_by=made_by, undo="reversible",
                                   rule_key=key, reason=reason)
            try:
                ok = write()
            except Exception:
                ok = False
            decisions.finish(conn, did, "applied" if ok else "failed")
            failed = failed or not ok
    finally:
        conn.close()
    return ({"error": "write failed"}, 500) if failed else ({"ok": True}, 200)


@bp.get("/api/decisions")
def api_decisions():
    days = request.args.get("days", 7, type=int)
    conn = db.connect()
    try:
        rows = decisions.list_decisions(conn, lane=request.args.get("lane") or None, days=days)
        texts, names = {}, None
        for r in rows:  # a readable name for each ref; blank when the row is gone
            r["title"] = _decision_title(conn, r)
            if r.get("rule_id") and r["rule_id"] not in texts:
                rr = rules.get(conn, r["rule_id"])
                if rr and rr["lane"] != "gmail":
                    if names is None:
                        names = _book_names({rr["rule_key"]}, set())
                    texts[r["rule_id"]] = rule_text(rr, names[0].get(rr["rule_key"]), names[1].get(str(rr["action"])))
                else:
                    texts[r["rule_id"]] = rule_text(rr) if rr else None
            r["rule"] = {"id": r["rule_id"], "text": texts[r["rule_id"]]} if r.get("rule_id") and texts[r["rule_id"]] else None
        return jsonify(rows)
    finally:
        conn.close()


def _decision_title(conn, r) -> str:
    if r["lane"] == "gmail":
        g = conn.execute("SELECT sender, subject FROM gmail_item WHERE id=?", (r["item_id"],)).fetchone()
        return f"{g['sender']}: {g['subject']}" if g else ""
    if r["lane"] == "voice-memo":
        try:
            return str(json.loads(r["changed_json"]).get("transcript") or "")[:60]
        except (TypeError, ValueError, AttributeError):
            return ""
    from finances import book
    try:
        with book._conn() as c:
            t = c.execute("SELECT t.amount_cents, COALESCE(p.name, t.raw_description) AS who FROM txn t"
                          " LEFT JOIN payee p ON p.id = t.payee_id WHERE t.uid = ?", (r["ref"],)).fetchone()
    except Exception:
        return ""
    return f"{t['who']} {t['amount_cents'] / 100:.2f}" if t else ""


def _cross_site():
    """trips/api_intake.py's guard (importing it here is circular): a cross-site form cannot send JSON,
    and a cross-site fetch that does is preflighted and refused, so JSON plus Sec-Fetch-Site covers both."""
    if not request.is_json or request.headers.get("Sec-Fetch-Site", "none") not in ("same-origin", "none"):
        return jsonify({"error": "send this from the Hub page"}), 403
    return None


@bp.post("/api/decisions/<int:did>/undo")
def api_decision_undo(did):
    if bad := _cross_site():
        return bad
    conn = db.connect()
    try:
        res = decisions.undo(conn, did)
    except LookupError:
        return jsonify({"error": "no such decision"}), 404
    except Exception as e:  # Gmail or network trouble
        return jsonify({"error": f"undo failed: {e}"}), 502
    finally:
        conn.close()
    return jsonify(res), 409 if "conflict" in res else 400 if "error" in res else 200


@bp.post("/api/decisions/<int:did>/fix")
def api_decision_fix(did):
    if bad := _cross_site():
        return bad
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("fix_key"), str) or not data["fix_key"]:
        return jsonify({"error": "fix_key is required"}), 400
    if not isinstance(data.get("answer"), dict):
        return jsonify({"error": "answer must be an object"}), 400
    conn = db.connect()
    try:
        res = decisions.fix(conn, did, data["answer"], data["fix_key"])
    except LookupError:
        return jsonify({"error": "no such decision"}), 404
    except Exception as e:
        return jsonify({"error": f"fix failed: {e}"}), 502
    finally:
        conn.close()
    return jsonify(res), 409 if "conflict" in res else 400 if "error" in res else 200

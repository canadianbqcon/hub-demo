"""Mail hub blueprint: reads the data/mail.db mirror, writes labels to Gmail under decisions.locked().

No send path anywhere: the only compose-side calls are drafts.create / drafts.update (claude_actions).
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import sqlite3
import sys
import threading
from collections import Counter
from contextlib import contextmanager

from flask import Blueprint, Response, jsonify, render_template, request

from automations import db as auto_db
from automations import brief, decisions, gmail_actions
from automations.api import _cross_site
from mail import claude_actions
from mail import db as mail_db
from mail import gmail_sync

bp = Blueprint("mail", __name__, template_folder="frontend",
               static_folder="frontend/static", url_prefix="/mail")

PAGE = 50
ACTIONS = {"archive": ([], ["INBOX"]), "read": ([], ["UNREAD"]), "unread": (["UNREAD"], []),
           "move": (None, ["INBOX"]), "trash": (["TRASH"], ["INBOX"])}
MAX_IDS = 500
WAITING = ("proposed", "unconfirmed")
SYSTEM_ALIASES = {"INBOX", "UNREAD", "SENT", "DRAFT", "SPAM", "TRASH"}
claude_client = None  # tests inject a stub; None builds the real Anthropic client
_inflight: set[str] = set()  # thread ids with a summary running
_inflight_lock = threading.Lock()


def gmail_factory():
    """Modify-scope Gmail service for page writes (tests replace this)."""
    sys.path.insert(0, os.path.expanduser("~/.config/vault-api"))
    import services
    return services.gmail()


@bp.before_request
def _guard():
    if request.method == "POST":
        return _cross_site()


@bp.after_request
def _no_store(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


@contextmanager
def _db():
    conn = mail_db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _err(msg, code):
    return jsonify({"error": msg}), code


def _own(conn):
    row = conn.execute("SELECT address FROM account WHERE id = 1").fetchone()
    return (row["address"] if row else "").lower()


def _waiting_items():
    """gmail_item rows the lane is still waiting on; an unreadable automations db means none."""
    try:
        c = auto_db.connect()
    except Exception:
        return []
    try:
        # the newest note typed on the row, with how its reach was judged (gmail_note.scope)
        return [dict(r) for r in c.execute(
            "SELECT i.*, n.id AS note_id, n.scope AS note_scope, n.tries AS note_tries FROM gmail_item i"
            " LEFT JOIN gmail_note n ON n.id = (SELECT max(id) FROM gmail_note WHERE item_id = i.id)"
            " WHERE i.state IN (?, ?) ORDER BY i.id", WAITING)]
    finally:
        c.close()


def _fts_query(q):
    """Each token quoted, so FTS syntax in the text cannot error."""
    return " ".join('"' + t.replace('"', '""') + '"' for t in q.split())


_scan_cache = None  # (connection, data_version, threads)
_INTERNAL = ("labels", "unread_labels")


def _scan(conn):
    """Every thread grouped off the header index, newest first, with the sender rule applied, as
    {"main": [...], "bin": [...]}: spam and trashed messages group apart, so they show only on the
    Spam and Trash tabs and a thread's live messages never carry its binned ones.
    Memoized until another connection commits (PRAGMA data_version moves): the grouping is
    ~80 ms of Python and the mirror changes only on a sync or a label action. Callers hold
    mail_db.reader()'s lock, whose connection never writes, so the version always moves.
    ponytail: loads every header row and groups in Python; fine at ~10k messages, move to SQL
    if the mirror grows an order of magnitude."""
    global _scan_cache
    ver = conn.execute("PRAGMA data_version").fetchone()[0]
    if _scan_cache and _scan_cache[0] is conn and _scan_cache[1] == ver:
        return _scan_cache[2]
    own = _own(conn)
    out, out_bin = {}, {}
    for r in conn.execute(
            "SELECT id, thread_id, internal_date, from_addr, from_name, subject, snippet, label_ids "
            "FROM message WHERE account_id = 1 ORDER BY internal_date, id"):
        labs = json.loads(r["label_ids"] or "[]")
        t = (out_bin if gmail_sync.BIN_LABELS & set(labs) else out).setdefault(r["thread_id"], {"thread_id": r["thread_id"], "message_ids": [], "unread": False,
                                            "sender_addr": "", "sender_name": "",
                                            "labels": set(), "unread_labels": set()})
        t["message_ids"].append(r["id"])
        t["labels"].update(labs)
        if "UNREAD" in labs:
            t["unread"] = True
            t["unread_labels"].update(labs)
        t["newest_date"], t["subject"], t["newest_id"] = r["internal_date"], r["subject"] or "", r["id"]
        t["snippet"] = html.unescape(r["snippet"] or "")  # Gmail sends snippets HTML-escaped ("&#39;", "&amp;")
        if (r["from_addr"] or "").lower() != own or not t["sender_addr"]:  # newest message not from him
            t["sender_addr"], t["sender_name"] = (r["from_addr"] or "").lower(), r["from_name"] or ""
    try:
        titles = dict(conn.execute("SELECT subject, title FROM short_title").fetchall())
    except sqlite3.OperationalError:  # a mail.db not yet at migration 004 (the other machine): full subjects
        titles = {}
    try:
        previews = dict(conn.execute("SELECT msg_id, text FROM list_preview").fetchall())
    except sqlite3.OperationalError:  # a mail.db not yet at migration 005: Gmail's snippets
        previews = {}
    for t in (*out.values(), *out_bin.values()):
        t["title"] = titles.get(t["subject"], t["subject"])  # Haiku list title; the full subject stays in "subject"
        t["preview"] = previews.get(t.pop("newest_id"), t["snippet"])  # Haiku one-liner, snippet until it exists
        t["count"] = len(t["message_ids"])
    order = lambda d: sorted(d.values(), key=lambda t: (t["newest_date"], t["thread_id"]), reverse=True)  # noqa: E731
    threads = {"main": order(out), "bin": order(out_bin)}
    _scan_cache = (conn, ver, threads)
    return threads


def warm():
    """Fill the reader's page cache and the thread scan in the background at Hub start, so the
    first mail visit after a restart is not the ~1.2 s cold one. Called from app.py's serving block only."""
    def run():
        try:
            with mail_db.reader() as conn:
                _scan(conn)
        except Exception:  # a missing or busy mirror only means a cold first visit
            pass
    threading.Thread(target=run, daemon=True).start()


def _threads(conn, label="", q="", frm=None):
    """All matching threads, newest first, as fresh dicts (the cached scan is never handed out)."""
    sets = []
    waiting = _waiting_items()
    wait_msgs = {w["msg_id"] for w in waiting}
    wait_threads = {w["thread_id"] for w in waiting if w["thread_id"]}
    wait_threads |= {r[0] for r in conn.execute("SELECT thread_id FROM message WHERE account_id = 1 AND id IN (%s)"
                                                % ",".join("?" * len(wait_msgs)), list(wait_msgs))} if wait_msgs else set()
    if label.upper() == "ALL":  # All mail: everything but Spam and Trash, as in Gmail
        label = ""
    if label == "waiting":
        sets.append(wait_threads)
    elif label:  # matched against the scan's label sets: a label query here would read every body
        label = label.upper() if label.upper() in SYSTEM_ALIASES else label
    if q.strip():
        # IN, not a JOIN: the join plan drove the FTS match once per message row (250 ms against 2 ms)
        sets.append({r[0] for r in conn.execute(
            "SELECT DISTINCT thread_id FROM message WHERE account_id = 1 AND rowid IN "
            "(SELECT rowid FROM message_fts WHERE message_fts MATCH ?)", (_fts_query(q),))})
    keep = set.intersection(*sets) if sets else None
    out = []
    for t in _scan(conn)["bin" if label in gmail_sync.BIN_LABELS else "main"]:
        if frm is not None and t["sender_addr"] != frm:
            continue
        if keep is not None and t["thread_id"] not in keep:
            continue
        if label and label != "waiting" and label not in t["labels"]:
            continue
        d = {k: v for k, v in t.items() if k not in _INTERNAL}
        d["waiting"] = t["thread_id"] in wait_threads
        out.append(d)
    return out


@bp.get("/")
def index():
    return render_template("mail.html")


@bp.get("/api/status")
def api_status():
    with mail_db.reader() as conn:
        row = conn.execute("SELECT address, synced_at FROM account WHERE id = 1").fetchone()
    return jsonify({"address": row["address"] if row else "", "synced_at": row["synced_at"] if row else None})


@bp.get("/api/labels")
def api_labels():
    with mail_db.reader() as conn:
        unread = Counter(lab for t in _scan(conn)["main"] for lab in t["unread_labels"])  # threads per label, unread messages only
        labels = [{"id": r["id"], "name": r["name"], "type": r["type"], "unread": unread.get(r["id"], 0)}
                  for r in conn.execute("SELECT * FROM label WHERE account_id = 1 ORDER BY name")]
    labels.append({"id": "waiting", "name": "Waiting", "type": "pseudo", "unread": len(_waiting_items())})
    return jsonify(labels)


def _from_arg():
    """The sender filter; present-but-empty is a real sender key (no parsable From), not "no filter"."""
    frm = request.args.get("from")
    return None if frm is None else frm.strip().lower()


@bp.get("/api/senders")
def api_senders():
    with mail_db.reader() as conn:
        threads = _threads(conn, request.args.get("label", ""), request.args.get("q", ""), _from_arg())
    groups = {}
    for t in threads:  # newest first, so a sender's first thread is its newest
        g = groups.setdefault(t["sender_addr"], {
            "key": t["sender_addr"], "name": t["sender_name"] or t["sender_addr"], "addr": t["sender_addr"],
            "threads": 0, "unread": 0, "waiting": 0,
            "newest_subject": t["subject"], "newest_title": t["title"], "newest_date": t["newest_date"]})
        g["threads"] += 1
        g["unread"] += t["unread"]
        g["waiting"] += t["waiting"]
    return jsonify(sorted(groups.values(), key=lambda g: g["newest_date"], reverse=True))


@bp.get("/api/threads")
def api_threads():
    cursor = request.args.get("cursor", "")
    try:
        after = (int(cursor.split("|", 1)[0]), cursor.split("|", 1)[1]) if cursor else None
    except (ValueError, IndexError):
        return _err("bad cursor", 400)
    with mail_db.reader() as conn:
        threads = _threads(conn, request.args.get("label", ""), request.args.get("q", ""), _from_arg())
    if after:
        threads = [t for t in threads if (t["newest_date"], t["thread_id"]) < after]
    page = threads[:PAGE]
    more = len(threads) > PAGE
    return jsonify({"threads": page, "cursor": f"{page[-1]['newest_date']}|{page[-1]['thread_id']}" if more else None})


@bp.get("/api/thread/<thread_id>")
def api_thread(thread_id):
    with mail_db.reader() as conn:
        rows = conn.execute("SELECT * FROM message WHERE account_id = 1 AND thread_id = ? "
                            "ORDER BY internal_date, id", (thread_id,)).fetchall()
        # opened from Spam or Trash (?bin=1) it shows the binned messages, otherwise the live ones;
        # a thread with none of the asked kind shows everything rather than nothing
        want = request.args.get("bin") == "1"
        rows = [r for r in rows if bool(gmail_sync.BIN_LABELS & set(json.loads(r["label_ids"] or "[]"))) == want] or rows
        if not rows:
            return _err("no such thread", 404)
        msgs = []
        for r in rows:
            d = {k: r[k] for k in ("id", "thread_id", "internal_date", "from_addr", "from_name", "to_addrs",
                                   "cc_addrs", "subject", "snippet", "body_text", "body_html")}
            d["label_ids"] = json.loads(r["label_ids"] or "[]")
            d["attachments"] = json.loads(r["attachments_json"] or "[]")
            msgs.append(d)
        ids = {m["id"] for m in msgs}
        s = conn.execute("SELECT * FROM summary WHERE thread_id = ?", (thread_id,)).fetchone()
        summary = None
        if s and s["source_hash"] == claude_actions.source_hash(conn, thread_id):
            summary = {**json.loads(s["text"]), "cost_usd": s["cost_usd"]}
    decisions_ = [w for w in _waiting_items() if w["msg_id"] in ids]
    return jsonify({"messages": msgs, "decisions": decisions_, "summary": summary})


def _refetch(conn, svc, ids):
    """Make the mirror follow Gmail for these ids. ponytail: a failed refetch is swallowed, the
    5-minute sync heals it."""
    for i in ids:
        try:
            gmail_sync._apply_ids(conn, svc, [i], 0)
            conn.commit()
        except Exception:
            conn.rollback()


def _do_act(conn, data, thread_id=None):
    """Validate and run one label action on the given message ids. Returns (json, status)."""
    if not isinstance(data, dict):
        return _err("send JSON", 400)
    action = data.get("action")
    ids = data.get("message_ids")
    if action not in ACTIONS:
        return _err(f"unknown action {action!r}", 400)
    if (not isinstance(ids, list) or not ids or len(ids) > MAX_IDS
            or not all(isinstance(i, str) and i for i in ids)):
        return _err("message_ids must be a non-empty list of ids", 400)
    ids = list(dict.fromkeys(ids))
    have = {r["id"]: r["thread_id"] for r in conn.execute(
        "SELECT id, thread_id FROM message WHERE account_id = 1 AND id IN (%s)" % ",".join("?" * len(ids)), ids)}
    if len(have) != len(ids) or (thread_id and any(t != thread_id for t in have.values())):
        return _err("unknown message id for this view", 400)
    label = data.get("label")
    if action == "move":
        ok = isinstance(label, str) and conn.execute(
            "SELECT 1 FROM label WHERE account_id = 1 AND id = ? AND type = 'user'", (label,)).fetchone()
        if not ok:
            return _err("unknown label", 400)
    svc = gmail_factory()
    add, rem = ACTIONS[action]
    add = add if add is not None else [label]
    with decisions.locked():
        try:
            # one call for every action, trash included (TRASH is an ordinary label to batchModify)
            svc.users().messages().batchModify(userId="me", body={
                "ids": ids, "addLabelIds": add, "removeLabelIds": rem}).execute()
        except Exception as e:
            failed = e
        else:
            failed = None
    if failed:
        # Gmail state is unknown: the mirror follows Gmail, refetched after the lock so the lane is not held up
        _refetch(conn, svc, ids)
        return _err(f"Gmail call failed: {failed}", 502)
    # a successful batchModify applied exactly this change to every id, so the mirror takes it without
    # a get per id (that refetch was most of the click's wait); the 5-minute sync catches anything else
    for i in ids:
        row = conn.execute("SELECT label_ids FROM message WHERE account_id = 1 AND id = ?", (i,)).fetchone()
        labs = [x for x in json.loads(row["label_ids"] or "[]") if x not in rem]
        labs += [x for x in add if x not in labs]
        conn.execute("UPDATE message SET label_ids = ? WHERE account_id = 1 AND id = ?", (json.dumps(labs), i))
    conn.commit()
    return jsonify({"ok": True, "labels": {r["id"]: json.loads(r["label_ids"] or "[]") for r in conn.execute(
        "SELECT id, label_ids FROM message WHERE account_id = 1 AND id IN (%s)" % ",".join("?" * len(ids)), ids)}}), 200


@bp.post("/api/thread/<thread_id>/act")
def api_thread_act(thread_id):
    with _db() as conn:
        return _do_act(conn, request.get_json(silent=True), thread_id)


@bp.post("/api/act")
def api_act():
    with _db() as conn:
        return _do_act(conn, request.get_json(silent=True))


@bp.post("/api/decision/<int:item_id>")
def api_decision(item_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _err("send JSON", 400)
    ac = auto_db.connect()
    try:
        row = ac.execute("SELECT msg_id FROM gmail_item WHERE id = ?", (item_id,)).fetchone()
    finally:
        ac.close()
    if row is None:
        return _err("no such item", 404)
    svc = gmail_factory()
    try:
        res = gmail_actions.act(item_id, str(data.get("action", "")), data.get("label"),
                                gmail=svc, note=data.get("note"))
    except LookupError:
        return _err("no such item", 404)
    except ValueError as e:
        return _err(str(e), 400)
    except Exception as e:
        return _err(f"Gmail call failed: {e}", 502)
    with _db() as conn:
        _refetch(conn, svc, [row["msg_id"]])
    # a card that moved on since the page loaded is refused; the page reloads the thread
    return jsonify(res), 409 if res.get("detail") == "already handled" else 200


@bp.get("/api/brief")
def api_brief():
    ac = auto_db.connect()
    try:
        entries, count = brief.list_entries(ac, request.args.get("trash") == "1")
    finally:
        ac.close()
    return jsonify({"entries": entries, "count": count})


def _brief_mark(eid, fn):
    ac = auto_db.connect()
    try:
        ok = fn(ac, eid)
    finally:
        ac.close()
    return jsonify({"ok": True}) if ok else _err("no such entry", 404)


@bp.post("/api/brief/<int:eid>/delete")
def api_brief_delete(eid):
    return _brief_mark(eid, brief.delete)


@bp.post("/api/brief/<int:eid>/restore")
def api_brief_restore(eid):
    return _brief_mark(eid, brief.restore)


def _brief_domain(data, ac):
    """The sender domain from the body, or None unless gmail_item has seen it."""
    d = str((data or {}).get("domain") or "").rsplit("@", 1)[-1].strip().lower()
    if d and ac.execute("SELECT 1 FROM gmail_item WHERE domain = ? LIMIT 1", (d,)).fetchone():
        return d
    return None


@bp.post("/api/brief/sender")
def api_brief_sender():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get("choice") not in ("read", "unsub"):
        return _err("send JSON with choice read or unsub", 400)
    ac = auto_db.connect()
    try:
        d = _brief_domain(data, ac)
        if d is None:
            return _err("unknown sender domain", 400)
        if data["choice"] == "read":
            return jsonify(gmail_actions.sender_read(ac, d))
        return jsonify(gmail_actions.unsubscribe_sender(ac, d))
    finally:
        ac.close()


@bp.post("/api/brief/sender/done")
def api_brief_sender_done():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _err("send JSON", 400)
    ac = auto_db.connect()
    try:
        d = _brief_domain(data, ac)
        if d is None:
            return _err("unknown sender domain", 400)
        return jsonify(gmail_actions.sender_done(ac, d))
    finally:
        ac.close()


def _thread_exists(conn, thread_id):
    return conn.execute("SELECT 1 FROM message WHERE account_id = 1 AND thread_id = ?", (thread_id,)).fetchone()


@bp.post("/api/thread/<thread_id>/summary")
def api_summary(thread_id):
    with _inflight_lock:
        if thread_id in _inflight:
            return _err("a summary for this thread is already running", 409)
        _inflight.add(thread_id)
    try:
        with _db() as conn:
            if not _thread_exists(conn, thread_id):
                return _err("no such thread", 404)
            return jsonify(claude_actions.summarize(conn, thread_id, client=claude_client))
    except Exception as e:  # missing key, model or JSON trouble: the card shows it, nothing is written
        return _err(f"summary failed: {e}", 502)
    finally:
        with _inflight_lock:
            _inflight.discard(thread_id)


@bp.post("/api/message/<msg_id>/translate")
def api_translate(msg_id):
    with _db() as conn:
        try:
            return jsonify(claude_actions.translate(conn, msg_id, client=claude_client))
        except LookupError:
            return _err("no such message", 404)
        except Exception as e:
            return _err(f"translate failed: {e}", 502)


@bp.post("/api/thread/<thread_id>/draft")
def api_draft(thread_id):
    """{instruction}, or {auto: true} for the draft written when a thread opens, or
    {instruction, previous} to send a draft back with notes."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _err("send JSON", 400)
    auto = data.get("auto") is True
    instruction, previous = str(data.get("instruction") or ""), data.get("previous")
    if previous is not None and not isinstance(previous, str):
        return _err("bad previous", 400)
    if not auto and not instruction.strip():
        return _err("instruction is required", 400)
    with _db() as conn:
        if not _thread_exists(conn, thread_id):
            return _err("no such thread", 404)
        if auto and not claude_actions.auto_draftable(conn, thread_id):
            return jsonify({"skipped": True})  # a no-reply sender or nobody else in it: no model call
        try:
            return jsonify(claude_actions.draft_reply(conn, thread_id, "" if auto else instruction,
                                                      client=claude_client, previous=None if auto else previous))
        except ValueError as e:
            return _err(str(e), 400)
        except Exception as e:
            return _err(f"draft failed: {e}", 502)


@bp.post("/api/thread/<thread_id>/draft/save")
def api_draft_save(thread_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not all(isinstance(data.get(k), str) for k in ("to", "subject", "body")):
        return _err("to, subject and body are required", 400)
    draft_id = data.get("draft_id")
    if draft_id is not None and not isinstance(draft_id, str):
        return _err("bad draft_id", 400)
    with _db() as conn:
        if not _thread_exists(conn, thread_id):
            return _err("no such thread", 404)
        try:
            did = claude_actions.save_draft(conn, gmail_factory(), thread_id, data["to"], data["subject"],
                                            data["body"], draft_id=draft_id)
        except ValueError as e:
            return _err(str(e), 400)
        except Exception as e:
            return _err(f"Gmail call failed: {e}", 502)
    return jsonify({"draft_id": did})


@bp.get("/api/attachment/<msg>/<att>")
def api_attachment(msg, att):
    with _db() as conn:
        row = conn.execute("SELECT attachments_json FROM message WHERE account_id = 1 AND id = ?", (msg,)).fetchone()
    found = next((a for a in json.loads((row and row["attachments_json"]) or "[]")
                  if a.get("attachmentId") == att), None)
    if not found:
        return _err("no such attachment", 404)
    try:
        data = gmail_factory().users().messages().attachments().get(userId="me", messageId=msg, id=att).execute()["data"]
    except Exception as e:
        return _err(f"Gmail call failed: {e}", 502)
    # ponytail: buffered in memory; Gmail caps attachments at 25 MB
    # ASCII only: the header is latin-1 on the wire, so "請求書.pdf" would 500 the download
    name = re.sub(r"[^\w.\- ]", "_", found.get("filename") or "", flags=re.ASCII).strip(" .") or "attachment"
    return Response(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)),
                    mimetype="application/octet-stream", headers={
                        "Content-Disposition": f'attachment; filename="{name}"',
                        "X-Content-Type-Options": "nosniff"})


@bp.post("/api/sync")
def api_sync():
    try:
        res = gmail_sync.run()
    except Exception as e:
        return _err(f"sync failed: {e}", 502)
    if res.get("skipped") == "locked":
        return _err("a sync is already running", 409)
    return jsonify(res)

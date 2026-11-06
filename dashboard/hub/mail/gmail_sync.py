"""Gmail -> data/mail.db mirror: MIME walk, backfill, incremental, locked run().

Reads only (services.gmail_readonly); nothing here can change mail.
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parseaddr
from html import unescape

from mail import db as mail_db

LOCK_PATH = "/tmp/mail-sync.lock"
BATCH = 50
ACCOUNT_ID = 1
# Spam and Trash are mirrored exactly as Gmail holds them, and Gmail empties both after 30 days,
# so the mirror keeps the past 30 days of each with no clock of its own (Trash and Spam tabs, 2026-10-20)
BIN_LABELS = {"SPAM", "TRASH"}
BIN_QUERY = "in:spam OR in:trash"
HISTORY_TYPES = ["messageAdded", "messageDeleted", "labelAdded", "labelRemoved"]
_last_try = 0.0  # monotonic; throttles retries of a failing scheduled run


def _header(part, name):
    name = name.lower()
    return next((h["value"] for h in part.get("headers", []) if h["name"].lower() == name), "")


def _decode(part, data):
    """base64url, then the part's charset. Gmail has already undone the transfer encoding
    (checked live 2026-10-20), so no quoted-printable pass: a second one turns "width=100" into a 0x10 byte."""
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    charset = "utf-8"
    for seg in _header(part, "content-type").split(";")[1:]:
        k, _, v = seg.strip().partition("=")
        if k.lower() == "charset" and v.strip(" \"'"):
            charset = v.strip(" \"'")
    try:
        return raw.decode(charset, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


def extract_parts(payload) -> dict:
    """Walk the MIME tree: text/plain -> text, text/html -> html (raw),
    a part with a filename or attachmentId -> attachment manifest entry."""
    out = {"text": [], "html": [], "attachments": []}

    def walk(part):
        body = part.get("body", {})
        mime = part.get("mimeType", "")
        if part.get("filename") or body.get("attachmentId"):
            out["attachments"].append({
                "filename": part.get("filename", ""), "mimeType": mime,
                "size": body.get("size", 0), "attachmentId": body.get("attachmentId", ""),
                "partId": part.get("partId", ""),
            })
        elif body.get("data") and mime == "text/plain":
            out["text"].append(_decode(part, body["data"]))
        elif body.get("data") and mime == "text/html":
            out["html"].append(_decode(part, body["data"]))
        for sub in part.get("parts", []):
            walk(sub)

    walk(payload or {})
    return {"text": "\n".join(out["text"]), "html": "\n".join(out["html"]),
            "attachments": out["attachments"]}


def _html_text(html) -> str:
    """Plain text of an HTML body (gmail_lane._clean_body's regexes), so an HTML-only message
    is searchable and Claude reads its body, not just the snippet."""
    html = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<(?:br|p|div|tr|td|th|h[1-6])[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = unescape(re.sub(r"<[^>]+>", "", html))
    return re.sub(r" +", " ", re.sub(r"\s*\n\s*", "\n", html)).strip()


def _row(msg) -> dict:
    p = msg.get("payload", {})
    parts = extract_parts(p)
    parts["text"] = parts["text"] or _html_text(parts["html"])
    name, addr = parseaddr(_header(p, "from"))
    return {
        "id": msg["id"], "thread_id": msg["threadId"],
        "internal_date": int(msg.get("internalDate", 0)),
        "from_addr": addr.lower(), "from_name": name,
        "to_addrs": _header(p, "to"), "cc_addrs": _header(p, "cc"),
        "reply_to": _header(p, "reply-to"), "subject": _header(p, "subject"),
        "snippet": msg.get("snippet", ""), "body_text": parts["text"], "body_html": parts["html"],
        "label_ids": json.dumps(msg.get("labelIds", [])),
        "rfc_message_id": _header(p, "message-id"), "rfc_references": _header(p, "references"),
        "attachments_json": json.dumps(parts["attachments"]),
    }


def _store(conn, msg, gen) -> int:
    """Idempotent upsert by message id. Returns 1 if changed."""
    r = _row(msg)
    cols = list(r)
    conn.execute(
        f"INSERT INTO message (account_id, scan_gen, {', '.join(cols)}) "
        f"VALUES (?, ?, {', '.join('?' * len(cols))}) "
        f"ON CONFLICT(account_id, id) DO UPDATE SET scan_gen = excluded.scan_gen, "
        + ", ".join(f"{c} = excluded.{c}" for c in cols if c != "id"),
        [ACCOUNT_ID, gen, *r.values()],
    )
    return 1


def _delete(conn, mid) -> int:
    return conn.execute("DELETE FROM message WHERE account_id = ? AND id = ?", (ACCOUNT_ID, mid)).rowcount


def _get(svc, mid, fmt="full"):
    """messages.get; None when Gmail says 404 (deleted)."""
    try:
        return svc.users().messages().get(userId="me", id=mid, format=fmt).execute()
    except Exception as e:
        if _is_404(e):
            return None
        raise


def _is_404(e) -> bool:
    return getattr(getattr(e, "resp", None), "status", None) == 404


def _account(conn):
    with conn:  # committed now, so no write transaction stays open across the Gmail calls that follow
        conn.execute("INSERT OR IGNORE INTO account (id, provider, address) VALUES (?, 'gmail', '')", (ACCOUNT_ID,))
    return conn.execute("SELECT * FROM account WHERE id = ?", (ACCOUNT_ID,)).fetchone()


def _apply_ids(conn, svc, ids, gen) -> int:
    """Refetch each id (full if new locally, minimal if known) and store it; 404 = deleted.
    Every Gmail call happens before the first write, so the write lock is never held across HTTP."""
    got = []
    for mid in ids:
        known = conn.execute("SELECT 1 FROM message WHERE account_id = ? AND id = ?", (ACCOUNT_ID, mid)).fetchone()
        got.append((mid, known, _get(svc, mid, "minimal" if known else "full")))
    n = 0
    for mid, known, msg in got:
        if msg is None:
            n += _delete(conn, mid)
        elif known:
            conn.execute("UPDATE message SET label_ids = ? WHERE account_id = ? AND id = ?",
                         (json.dumps(msg.get("labelIds", [])), ACCOUNT_ID, mid))
            n += 1
        else:
            n += _store(conn, msg, gen)
    return n


def backfill(conn, svc) -> int:
    """Full scan. Cursor is read before listing; old rows are swept only after the
    scan completes; then incremental() replays changes made during the scan."""
    acct = _account(conn)
    hid = svc.users().getProfile(userId="me").execute()["historyId"]
    gen = acct["scan_gen"] + 1
    n, token = 0, None
    while True:
        resp = svc.users().messages().list(userId="me", pageToken=token, maxResults=500).execute()
        ids = [m["id"] for m in resp.get("messages", [])]
        for i in range(0, len(ids), BATCH):
            # ponytail: one get per message (~20 min for 8k); new_batch_http_request if backfills recur
            msgs = [m for m in (_get(svc, mid) for mid in ids[i:i + BATCH]) if m is not None]  # 404: deleted since listing
            with conn:  # per-batch transaction, opened only after the batch's gets
                for msg in msgs:
                    n += _store(conn, msg, gen)
        token = resp.get("nextPageToken")
        if not token:
            break
    with conn:
        conn.execute("DELETE FROM message WHERE account_id = ? AND scan_gen < ?", (ACCOUNT_ID, gen))
        conn.execute("UPDATE account SET scan_gen = ?, history_id = ? WHERE id = ?", (gen, hid, ACCOUNT_ID))
    return n + incremental(conn, svc, after_backfill=True)


def incremental(conn, svc, after_backfill=False) -> int:
    acct = _account(conn)
    if not acct["history_id"] and not after_backfill:
        return backfill(conn, svc)
    n, token = 0, None
    while True:
        try:
            resp = svc.users().history().list(
                userId="me", startHistoryId=acct["history_id"], historyTypes=HISTORY_TYPES,
                pageToken=token).execute()
        except Exception as e:
            if _is_404(e) and not after_backfill:  # cursor expired
                return backfill(conn, svc)  # a fresh cursor 404ing again raises, never loops
            raise
        ids = []
        for h in resp.get("history", []):
            for key in ("messagesAdded", "messagesDeleted", "labelsAdded", "labelsRemoved"):
                ids += [x["message"]["id"] for x in h.get(key, [])]
        token = resp.get("nextPageToken")
        with conn:  # page upserts and (on the last page) the cursor commit together
            n += _apply_ids(conn, svc, dict.fromkeys(ids), acct["scan_gen"])
            if not token:
                conn.execute("UPDATE account SET history_id = ? WHERE id = ?",
                             (resp.get("historyId", acct["history_id"]), ACCOUNT_ID))
        if not token:
            return n


def bins(conn, svc) -> int:
    """Make the mirror's Spam and Trash match Gmail's. The backfill lists without them and history
    can miss Gmail's own 30-day purge, so each run lists both (a few hundred ids) and refetches
    only the differences: new arrivals in full, rows that left the bin to update or delete."""
    gen = _account(conn)["scan_gen"]
    ids, token = [], None
    while True:
        resp = svc.users().messages().list(userId="me", q=BIN_QUERY, includeSpamTrash=True,
                                           pageToken=token, maxResults=500).execute()
        ids += [m["id"] for m in resp.get("messages", [])]
        token = resp.get("nextPageToken")
        if not token:
            break
    local = {r["id"]: json.loads(r["label_ids"] or "[]") for r in conn.execute(
        "SELECT id, label_ids FROM message WHERE account_id = ?", (ACCOUNT_ID,))}
    listed = set(ids)
    todo = [i for i in ids if not BIN_LABELS & set(local.get(i, []))]
    todo += [i for i, labs in local.items() if BIN_LABELS & set(labs) and i not in listed]
    n = 0
    for i in range(0, len(todo), BATCH):
        with conn:
            n += _apply_ids(conn, svc, todo[i:i + BATCH], gen)
    return n


def _sync_labels(conn, svc):
    labels = svc.users().labels().list(userId="me").execute().get("labels", [])
    with conn:
        conn.execute("DELETE FROM label WHERE account_id = ?", (ACCOUNT_ID,))
        conn.executemany("INSERT INTO label (account_id, id, name, type) VALUES (?, ?, ?, ?)",
                         [(ACCOUNT_ID, x["id"], x["name"], x.get("type")) for x in labels])


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(conn=None, svc=None, min_age_minutes=0) -> dict:
    """One sync under /tmp/mail-sync.lock (shared by scheduler and page refresh).
    min_age_minutes > 0 (scheduler) skips when the last good sync is newer."""
    global _last_try
    fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"skipped": "locked"}
        own = conn is None
        conn = conn or mail_db.connect()
        try:
            acct = _account(conn)
            if min_age_minutes:
                if acct["synced_at"]:
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(acct["synced_at"])
                    if age.total_seconds() < min_age_minutes * 60:
                        return {"skipped": "fresh"}
                if _last_try and time.monotonic() - _last_try < min_age_minutes * 60:
                    return {"skipped": "throttled"}  # last attempt failed; wait out the interval
            _last_try = time.monotonic()
            if svc is None:
                sys.path.insert(0, os.path.expanduser("~/.config/vault-api"))
                import services
                svc = services.gmail_readonly()
            had_cursor = bool(acct["history_id"])
            if not acct["address"]:
                addr = svc.users().getProfile(userId="me").execute().get("emailAddress", "")
                with conn:
                    conn.execute("UPDATE account SET address = ? WHERE id = ?", (addr, ACCOUNT_ID))
            _sync_labels(conn, svc)
            changed = incremental(conn, svc) if had_cursor else backfill(conn, svc)
            changed += bins(conn, svc)
            with conn:
                conn.execute("UPDATE account SET synced_at = ? WHERE id = ?", (_now(), ACCOUNT_ID))
            return {"mode": "incremental" if had_cursor else "backfill", "changed": changed}
        finally:
            if own:
                conn.close()
    finally:
        os.close(fd)

"""Page actions for gmail_item rows: approve, move, keep, delete, unsubscribe, back, note.

Every action loads the row by id, re-reads the message from Gmail, and writes
nothing if the message has moved on (state 'stale'). Rules: CLAUDE-gmail.md
"Keep tracking" and "Unsubscribe safety check"; one-click per execution.md
Phase 7; only a one-click POST returning exactly 200 counts as unsubscribed.
"""

from __future__ import annotations

import ipaddress
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from . import db, decisions

# ponytail: the rules list no ESPs, so this is a small conservative set of
# unsubscribe-hosting domains; extend it here if a legit sender is refused.
KNOWN_ESPS = frozenset({"list-manage.com", "sendgrid.net", "mandrillapp.com", "mailchimp.com"})
_SLD = {"co", "com", "org", "net", "gov", "edu", "ac"}  # second levels under a 2-letter ccTLD


def _gmail_dir() -> Path:
    from vault_path import vault_root

    return vault_root() / ".claude" / "skills" / "gmail"


def default_paths() -> dict:
    d = _gmail_dir()
    return {n: d / n for n in ("known-inbox.json", "approved-senders.txt", "gmail-decisions.jsonl")}


def registrable(host: str) -> str:
    parts = (host or "").lower().strip(".").split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SLD:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def unsub_safe(url: str, sender_domain: str) -> bool:
    u = urllib.parse.urlparse(url or "")
    if u.scheme != "https" or not u.hostname or "." not in u.hostname:
        return False
    try:
        ipaddress.ip_address(u.hostname)
        return False  # IP literal
    except ValueError:
        pass
    reg = registrable(u.hostname)
    sender = registrable((sender_domain or "").rsplit("@", 1)[-1])
    return bool(sender) and (reg == sender or reg in KNOWN_ESPS)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None  # a 3xx surfaces as HTTPError, never silently re-sent as a GET


def _default_http(method: str, url: str, data: dict | None = None) -> int:
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    try:
        return urllib.request.build_opener(_NoRedirect).open(req, timeout=15).status
    except urllib.error.HTTPError as e:
        return e.code


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _set_state(conn, item_id: int, st: str) -> None:
    conn.execute("UPDATE gmail_item SET state=?, updated_at=? WHERE id=?", (st, _now(), item_id))
    conn.commit()


def _live_gmail():
    sys.path.insert(0, os.path.expanduser("~/.config/vault-api"))
    from services import gmail

    return gmail()


def _labels(gmail) -> list:
    return gmail.users().labels().list(userId="me").execute().get("labels", [])


def _label_id(gmail, name: str | None, *, user_only: bool = True) -> str:
    for lb in _labels(gmail):
        if lb["name"] == name and (lb.get("type") == "user" or not user_only):
            return lb["id"]
    raise ValueError(f"not a live user label: {name!r}")


def _modify(gmail, mid, add, remove) -> None:
    gmail.users().messages().modify(
        userId="me", id=mid, body={"addLabelIds": add, "removeLabelIds": remove}
    ).execute()


def _record_keep(paths, row, reason: str) -> None:
    p = paths["known-inbox.json"]
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    today = date.today().isoformat()
    entry = data.get(row["msg_id"])
    if not isinstance(entry, dict):
        entry = {}
    entry.update(
        status="keep", reason=reason, type=entry.get("type", "other"), processed=today,
        trigger_date=entry.get("trigger_date"), trigger_type=entry.get("trigger_type", "manual"),
        destination=entry.get("destination"), subject=row["subject"], sender=row["domain"],
        last_seen=today,
    )
    data[row["msg_id"]] = entry
    _atomic_write(p, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _mark_unsubscribed(paths, domain: str) -> None:
    p = paths["approved-senders.txt"]
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    new = f"{domain}  # unsubscribed {date.today().isoformat()}"
    out, placed = [], False
    for ln in lines:
        if ln.split("#")[0].strip().lower() == domain:
            if not placed:
                out.append(new)
                placed = True
            continue
        out.append(ln)
    if not placed:
        out.append(new)
    _atomic_write(p, "\n".join(out) + "\n")


# gmail-decisions.jsonl uses the /gmail skill's words, so both writers' streaks add up
FILE_WORD = {"UNSUBSCRIBE": "UNSUB", "SECURITY_ALERT": "SECURITY ALERT", "YOUR_CALL": "YOUR CALL"}


def _log_correction(paths, row, confirmed: str, label: str | None) -> None:
    """Every answer is logged, agreements and your-call answers too: three same answers in a row
    teach the lane that sender (gmail_lane.learned)."""
    proposed = (row["action"] or "").upper().replace(" ", "_") or "YOUR_CALL"
    rec = {
        "sender_domain": (row["domain"] or "").rsplit("@", 1)[-1].lower(),
        "category_hint": (row["subject"] or "")[:80],
        "proposed": FILE_WORD.get(proposed, proposed),
        "confirmed": FILE_WORD.get(confirmed, confirmed),
        "confirmed_label": label if confirmed == "MOVE" else None,
        "date": date.today().isoformat(),
        "kind": row["kind"] if "kind" in row.keys() else None,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(paths["gmail-decisions.jsonl"], "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


NOTE_MAX = 2000


def _append_note(conn, row, text, button=None) -> None:
    """Append a dated line to the item's note and record it with its email and button; its reach
    (scope) is judged later by followups.judge_pending, outside the lock, because that is a model call."""
    stamp = f"[{date.today().isoformat()}] {text}"
    conn.execute("UPDATE gmail_item SET note = COALESCE(note || char(10), '') || ?, updated_at=? WHERE id=?",
                 (stamp, _now(), row["id"]))
    conn.execute("INSERT INTO gmail_note (domain, kind, text, created_at, item_id, button) VALUES (?,?,?,?,?,?)",
                 (row["domain"], row["kind"], text, _now(), row["id"], button))
    conn.commit()


def _note(conn, row, text) -> dict:
    """Store his free-text answer; the row stays proposed and the next /gmail run carries it out."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("note is empty")
    if len(text) > NOTE_MAX:
        raise ValueError(f"note is over {NOTE_MAX} characters")
    if row["state"] not in ("proposed", "unconfirmed"):
        return {"state": row["state"], "detail": "already handled"}
    _append_note(conn, row, text)
    return {"state": row["state"], "detail": "note saved for the next /gmail run"}


def _recheck(domain, kind) -> None:
    """Background: own connection and Gmail service, no lock held. Judges any new note's scope,
    files new proposals, then re-judges that kind's waiting siblings."""
    from automations import gmail_lane
    conn = db.connect()
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=gmail_lane._api_key())
        from automations import followups, rules
        followups.judge_pending(conn, client)
        try:  # a book.db hiccup in discover must not cost the rejudge
            rules.discover(conn)
        except Exception as e:
            print(f"gmail_actions recheck discover failed: {e}", file=sys.stderr)
        # rules are per archetype, so an answer re-sorts that archetype's waiting mail from every sender
        wide = kind and kind not in rules.SENDER_SCOPED
        gmail_lane.rejudge(conn, _live_gmail(), client, "*" if wide else domain, kind)
    except Exception as e:  # a daemon thread: never let it die loudly into the page
        print(f"gmail_actions recheck failed: {e}", file=sys.stderr)
    finally:
        conn.close()


def set_scope(conn, note_id, scope) -> dict:
    """His pick on the /mail note line. standing or both files the proposed rule if none is live;
    once withdraws the rule: rejects a still-proposed one, turns a confirmed one off. A done
    action is never undone here."""
    from automations import followups, rules
    if scope not in followups.SCOPES:
        raise ValueError(f"scope must be one of {followups.SCOPES}")
    with decisions.locked():
        n = conn.execute("SELECT * FROM gmail_note WHERE id=?", (note_id,)).fetchone()
        if n is None:
            raise LookupError(f"no gmail_note {note_id}")
        rule = rules.get(conn, n["rule_id"]) if n["rule_id"] else None
        rid = n["rule_id"]
        if scope == "once":
            if rule and rule["state"] == "proposed":
                rules.reject(conn, rule["id"], rule["rev"])
            elif rule and rule["state"] == "confirmed":
                rules.set_off(conn, rule["id"], rule["rev"], reason="your pick: this email only")
        elif not rule or rule["state"] not in ("proposed", "confirmed"):
            rid = followups.propose_note_rule(conn, n, n["text"], n["op"]) or rid
        conn.execute("UPDATE gmail_note SET scope=?, judged_at=?, rule_id=? WHERE id=?",
                     (scope, _now(), rid, note_id))
        conn.commit()
    return {"scope": scope, "rule_id": rid}


def act(item_id, action, label=None, gmail=None, http=None, conn=None, paths=None, note=None,
        recheck=None) -> dict:
    own = conn is None
    conn = conn or db.connect()
    try:
        with decisions.locked():  # the lane's dispatcher takes the same lock, so one row gets one effect
            row = conn.execute("SELECT * FROM gmail_item WHERE id=?", (item_id,)).fetchone()
            if row is None:
                raise LookupError(f"no gmail_item {item_id}")
            if action == "note":  # no Gmail call: nothing changes in the mailbox yet
                answered = row["state"] in ("proposed", "unconfirmed")  # _note stores it only then
                res = _note(conn, row, note)
            else:
                text = str(note or "").strip()[:NOTE_MAX]
                gmail = gmail or _live_gmail()
                paths = paths or default_paths()
                res = _act(conn, row, action, label, gmail, http or _default_http, paths)
                answered = res["state"] in ("done", "undone", "moved")
                if text and res["state"] == "done":  # a note typed beside a button rides along; /gmail reads it
                    _append_note(conn, row, text, f"{action}:{label}" if label else action)
                    res["detail"] += ", note sent"
        if answered:  # outside the lock: the re-check may call the model; the answer is already committed
            threading.Thread(target=recheck or _recheck, args=(row["domain"], row["kind"]), daemon=True).start()
        return res
    finally:
        if own:
            conn.close()


def _effect(conn, row, to_state, action, changed, call, *, undo="reversible") -> bool:
    """Claim the row, log the intent, make the Gmail call, log the result. False when someone else
    already took the row. A failed call hands the row back and re-raises."""
    iid = row["id"]
    if not decisions.claim(conn, iid, row["state"], to_state):
        return False
    did = decisions.begin(conn, "gmail", row["msg_id"], action, changed, made_by="sam", undo=undo,
                          rule_key=f"{row['domain']}|{row['kind']}", item_id=iid)
    try:
        call()
    except Exception as e:
        decisions.finish(conn, did, "failed" if getattr(getattr(e, "resp", None), "status", None) else "unknown",
                         str(e)[:200])
        decisions.claim(conn, iid, to_state, row["state"])
        raise
    decisions.finish(conn, did, "applied")
    _set_state(conn, iid, to_state)
    return True


def _chg(before, after) -> dict:
    return {"labels": [sorted(before), sorted(after)]}


def _trashed(have) -> set:
    return (set(have) - {"INBOX"}) | {"TRASH"}


def _trash(gmail, mid) -> None:
    gmail.users().messages().trash(userId="me", id=mid).execute()


def _act(conn, row, action, label, gmail, http, paths) -> dict:  # noqa: C901 - one branch per action verb; each is short and independent
    if action == "approve":
        a = (row["action"] or "").upper().replace(" ", "_")
        action = {"MOVE": "move", "DELETE": "delete", "UNSUBSCRIBE": "unsubscribe", "KEEP": "keep",
                  "SECURITY_ALERT": "keep"}.get(a)
        if action is None:
            raise ValueError(f"nothing to approve for {a or 'no proposal'}")
        label = row["label"] if action == "move" else None
    if action not in ("move", "keep", "delete", "unsubscribe", "unsubscribed", "back", "read"):
        raise ValueError(f"unknown action {action!r}")
    allowed = {"back": ("moved",), "unsubscribed": ("unconfirmed",), "read": ("proposed",)}.get(
        action, ("proposed", "unconfirmed"))
    if row["state"] not in allowed:
        return {"state": row["state"], "detail": "already handled"}
    iid, mid = row["id"], row["msg_id"]
    try:
        have = set(
            gmail.users().messages().get(userId="me", id=mid, format="minimal").execute().get("labelIds", [])
        )
    except Exception as e:
        if getattr(getattr(e, "resp", None), "status", None) != 404:
            raise
        if action == "unsubscribed":  # he emptied the trash too; the unsubscribe still counts
            _mark_unsubscribed(paths, (row["domain"] or "").rsplit("@", 1)[-1].lower())
            _set_state(conn, iid, "done")
            return {"state": "done", "detail": "unsubscribed"}
        _set_state(conn, iid, "stale")
        return {"state": "stale", "detail": "message no longer exists"}
    if action == "back":
        try:
            lid = _label_id(gmail, row["label"], user_only=False)
        except ValueError:  # the label was deleted in Gmail
            lid = None
        if lid not in have:
            _set_state(conn, iid, "stale")
            return {"state": "stale", "detail": "message no longer carries its label"}
    elif "INBOX" not in have and action != "unsubscribed":  # he may archive it after unsubscribing
        _set_state(conn, iid, "stale")
        return {"state": "stale", "detail": "message left the inbox"}

    if action == "back":
        if not _effect(conn, row, "undone", "BACK", _chg(have, (have - {lid}) | {"INBOX"}),
                       lambda: _modify(gmail, mid, ["INBOX"], [lid])):
            return {"state": row["state"], "detail": "already handled"}
        _log_correction(paths, row, "KEEP", None)
        return {"state": "undone", "detail": "back in inbox"}

    if action == "move":
        lid = _label_id(gmail, label)
        if not _effect(conn, row, "done", "MOVE", _chg(have, (have - {"INBOX"}) | {lid}),
                       lambda: _modify(gmail, mid, [lid], ["INBOX"])):
            return {"state": row["state"], "detail": "already handled"}
        _log_correction(paths, row, "MOVE", label)
        return {"state": "done", "detail": f"moved to {label}"}

    if action == "keep":
        if not _effect(conn, row, "done", "KEEP", _chg(have, have), lambda: _record_keep(
                paths, row, row["reason"] or "kept from the Automations page")):
            return {"state": row["state"], "detail": "already handled"}
        _log_correction(paths, row, "KEEP", None)
        return {"state": "done", "detail": "kept in inbox"}

    if action in ("delete", "read"):  # read is the ack_then_trash click: same trash, no training row
        if not _effect(conn, row, "done", "DELETE" if action == "delete" else "READ", _chg(have, _trashed(have)),
                       lambda: _trash(gmail, mid), undo="expires"):
            return {"state": row["state"], "detail": "already handled"}
        if action == "delete":
            _log_correction(paths, row, "DELETE", None)
        return {"state": "done", "detail": "trashed" if action == "delete" else "read, trashed"}

    if action == "unsubscribed":  # he finished an unconfirmed unsubscribe in a browser
        if not _effect(conn, row, "done", "UNSUBSCRIBE", _chg(have, _trashed(have)),
                       lambda: "TRASH" in have or _trash(gmail, mid), undo="expires"):
            return {"state": row["state"], "detail": "already handled"}
        _mark_unsubscribed(paths, (row["domain"] or "").rsplit("@", 1)[-1].lower())
        return {"state": "done", "detail": "unsubscribed and trashed"}

    # unsubscribe
    url, domain = row["unsub_url"], (row["domain"] or "").rsplit("@", 1)[-1].lower()
    if not unsub_safe(url, domain):
        return {"state": row["state"], "detail": "unsafe"}
    try:
        if row["unsub_one_click"]:
            ok = http("POST", url, {"List-Unsubscribe": "One-Click"}) == 200
        else:
            http("GET", url)
            ok = False  # a GET is an attempt, never a confirmation
    except Exception:
        ok = False
    if not ok:
        _set_state(conn, iid, "unconfirmed")
        return {"state": "unconfirmed", "detail": f"finish in a browser: {url}"}
    if not _effect(conn, row, "done", "UNSUBSCRIBE", _chg(have, _trashed(have)), lambda: _trash(gmail, mid),
                   undo="expires"):
        return {"state": row["state"], "detail": "already handled"}
    _mark_unsubscribed(paths, domain)
    _log_correction(paths, row, "UNSUBSCRIBE", None)
    return {"state": "done", "detail": "unsubscribed"}


# ---- Brief sender choice (brief_sender); mirrors the per-row unsubscribe above, keyed by domain ----

def _upsert_sender(conn, domain, choice, state) -> None:
    conn.execute(
        "INSERT INTO brief_sender (domain, choice, unsub_state, updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(domain) DO UPDATE SET choice=excluded.choice, unsub_state=excluded.unsub_state, "
        "updated_at=excluded.updated_at", (domain, choice, state, _now()))
    conn.commit()


def _sender_state(conn, domain, detail) -> dict:
    r = conn.execute("SELECT choice, unsub_state FROM brief_sender WHERE domain=?", (domain,)).fetchone()
    return {"choice": r["choice"] if r else "read", "unsub_state": r["unsub_state"] if r else None, "detail": detail}


def unsubscribe_sender(conn, domain, http=None, paths=None) -> dict:
    domain = (domain or "").rsplit("@", 1)[-1].lower()
    http, paths = http or _default_http, paths or default_paths()
    row = conn.execute(
        "SELECT unsub_url, unsub_one_click FROM gmail_item WHERE domain=? AND unsub_url IS NOT NULL "
        "AND unsub_url<>'' ORDER BY received_at DESC, id DESC LIMIT 1", (domain,)).fetchone()
    if row is None:  # still his instruction: stop the entries, nothing to send
        _upsert_sender(conn, domain, "unsub", "unconfirmed")
        return {"choice": "unsub", "unsub_state": "unconfirmed", "detail": "no unsubscribe link"}
    url = row["unsub_url"]
    if not unsub_safe(url, domain):
        return _sender_state(conn, domain, "unsafe")
    ok = False
    if row["unsub_one_click"]:  # POST only; a GET is never sent
        try:
            ok = http("POST", url, {"List-Unsubscribe": "One-Click"}) == 200
        except Exception:
            ok = False
    if ok:
        _upsert_sender(conn, domain, "unsub", "done")
        _mark_unsubscribed(paths, domain)
        return {"choice": "unsub", "unsub_state": "done", "detail": "unsubscribed"}
    _upsert_sender(conn, domain, "unsub", "unconfirmed")
    return {"choice": "unsub", "unsub_state": "unconfirmed", "detail": f"finish in a browser: {url}", "url": url}


def sender_done(conn, domain, paths=None) -> dict:
    domain = (domain or "").rsplit("@", 1)[-1].lower()
    cur = conn.execute("UPDATE brief_sender SET unsub_state='done', updated_at=? WHERE domain=? "
                       "AND choice='unsub' AND unsub_state='unconfirmed'", (_now(), domain))
    conn.commit()
    if cur.rowcount:
        _mark_unsubscribed(paths or default_paths(), domain)
    return _sender_state(conn, domain, "done" if cur.rowcount else "unchanged")


def sender_read(conn, domain) -> dict:
    domain = (domain or "").rsplit("@", 1)[-1].lower()
    _upsert_sender(conn, domain, "read", None)
    return {"choice": "read", "unsub_state": None, "detail": "read"}

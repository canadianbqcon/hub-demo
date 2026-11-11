"""Bell rows for things waiting on him, kept in step with where they live.

Each source returns {key: post() kwargs} for what waits on him right now; reconcile()
hands that to db.sync(), which adds the new ones and removes the ones he has since
dealt with at the root (an email read, a rule confirmed, a mark closed). A source
that fails to read is skipped for that run, never synced as empty, so a locked store
does not wipe its rows. Runs from the notify-push tick, read-only against every store.

The source name is the Hub module whose icon the row shows.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from . import db

log = logging.getLogger(__name__)

MAIL_SINCE = datetime(2026, 11, 11, 2, 30, tzinfo=timezone.utc)  # mail from before the feature never rings
MAIL_DAYS = 3  # an email still unread after this stops ringing
MAIL_SKIP = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "SPAM", "TRASH"}
JOB_FIT = 75  # fit_score is 0-100; the Jobs page shows it as 7.5 out of 10
JOB_DAYS = 30
JOB_DONE = ("applied", "cut", "ignored", "rejected")


def _ro(name: str) -> sqlite3.Connection:
    from vault_path import vault_root

    path = vault_root() / "data" / name
    if not path.exists():
        raise FileNotFoundError(name)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _utc(ts) -> datetime:
    """A store timestamp (ISO, with or without offset, or SQLite's 'YYYY-MM-DD HH:MM:SS' in UTC)."""
    d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _past(d: datetime) -> datetime:
    return min(d, datetime.now(timezone.utc))  # a clock-skewed future time would hide the row


def mail(now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = max(MAIL_SINCE, now - timedelta(days=MAIL_DAYS))
    conn = _ro("mail.db")
    try:
        rows = conn.execute(
            "SELECT id, from_name, from_addr, subject, internal_date, label_ids FROM message "
            "WHERE internal_date >= ? AND label_ids LIKE '%\"INBOX\"%' AND label_ids LIKE '%\"UNREAD\"%'",
            (int(since.timestamp() * 1000),)).fetchall()
    finally:
        conn.close()
    out = {}
    for r in rows:
        if any(f'"{x}"' in r["label_ids"] for x in MAIL_SKIP):
            continue
        out[f"mail:{r['id']}"] = {
            "title": r["from_name"] or r["from_addr"] or "unknown sender",
            "body": r["subject"] or "(no subject)",
            "url": "/mail/?label=INBOX&sender=" + quote(r["from_addr"] or "", safe="@"),
            "due_at": _past(datetime.fromtimestamp(r["internal_date"] / 1000, timezone.utc)),
        }
    return out


def automations() -> dict:
    """One row for every proposed rule: keyed by the newest, so a fresh proposal rings
    again, while confirming or rejecting older ones only updates the count."""
    conn = _ro("automations.db")
    try:
        r = conn.execute("SELECT COUNT(*) n, MAX(id) top, MAX(created_at) at FROM rule WHERE state='proposed'").fetchone()
    finally:
        conn.close()
    if not r["n"]:
        return {}
    n = r["n"]
    return {f"automations:rules:{r['top']}": {
        "title": f"{n} rule{'s' if n != 1 else ''} wait{'' if n != 1 else 's'} for your yes",
        "body": None, "url": "/automations/?tab=rules", "due_at": _past(_utc(r["at"]))}}


def trips() -> dict:
    conn = _ro("trips.db")
    try:
        codes = conn.execute("SELECT id, name, first_name, last_name, created_at FROM guest_codes WHERE status='pending'").fetchall()
        subs = conn.execute(
            "SELECT i.id, i.submitted_at, t.name trip FROM trip_intake i LEFT JOIN trips t ON t.id = i.trip_id "
            "WHERE i.status='pending'").fetchall()
    finally:
        conn.close()
    out = {}
    for r in codes:
        who = " ".join(x for x in (r["first_name"], r["last_name"]) if x) or r["name"] or "someone"
        out[f"trips:code:{r['id']}"] = {"title": f"{who} asked for a trip code", "body": None,
                                        "url": "/trips/crew", "due_at": _past(_utc(r["created_at"]))}
    for r in subs:
        out[f"trips:intake:{r['id']}"] = {"title": "a crew member sent trip changes", "body": r["trip"],
                                          "url": "/trips/crew", "due_at": _past(_utc(r["submitted_at"]))}
    return out


def jobs(now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    conn = _ro("jobs.db")
    try:
        rows = conn.execute(
            "SELECT id, company, role, fit_score, score_role, fit_reason, created FROM applications "
            f"WHERE COALESCE(fit_score, score_role * 10) > ? AND status NOT IN ({','.join('?' * len(JOB_DONE))}) "
            "AND created >= ?",
            (JOB_FIT, *JOB_DONE, (now - timedelta(days=JOB_DAYS)).date().isoformat())).fetchall()
    finally:
        conn.close()
    out = {}
    for r in rows:
        fit = (r["fit_score"] if r["fit_score"] is not None else r["score_role"] * 10) / 10
        out[f"jobs:fit:{r['id']}"] = {
            "title": f"{r['role']} at {r['company']}", "body": f"fit {fit:.1f}" + (f": {_cut(r['fit_reason'])}" if r["fit_reason"] else ""),
            "url": f"/jobs/#app/{r['id']}", "due_at": _past(_utc(r["created"]))}
    return out


def _cut(t: str, n: int = 110) -> str:
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"


_SHORT = re.compile(r"\s*(?:[—–:-]\s*)?(?:design(?: spec)?|spec|implementation plan|plan)$", re.I)


def _short(t: str) -> str:
    return _SHORT.sub("", t or "").strip() or t


def workbench() -> dict:
    """The Workbench inbox (workbench-docs.jsx inboxRows, ported): each build's first
    unapproved step when it waits on him, plus marks sessions with fixes to check."""
    from marks import store as marks_store
    from workbench import names as wb_names
    from workbench import api as wb
    from workbench import store as wb_store

    roots = wb_store._roots()
    docs = {}
    for kind in ("spec", "plan"):
        root = roots[kind].resolve()
        paths = [p for p in root.glob("*.md") if not p.name.endswith("-gates.md")] if root.is_dir() else []
        with ThreadPoolExecutor(max_workers=16) as pool:  # /mnt/c latency, not CPU, as in api_docs
            items = list(pool.map(lambda p, k=kind: wb._doc_summary(k, p), paths))
        items.sort(key=lambda d: (d["date"] or "", d["_mtime"]), reverse=True)
        docs[kind] = items
    oroot = roots["design"]
    wb._load_caches(oroot)
    real = oroot.resolve()
    with ThreadPoolExecutor(max_workers=16) as pool:
        sets = list(pool.map(lambda d: wb._option_item(d, real), [
            d for d in (oroot.iterdir() if oroot.is_dir() else []) if d.is_dir() and not d.name.startswith(".")]))
    sets.sort(key=lambda d: d["mtime"], reverse=True)
    with wb_store._conn() as conn:
        hist = conn.execute("SELECT kind, doc_path, doc_sha256, verdict, seq FROM decisions").fetchall()
    latest = {}
    for r in hist:
        k = (r["kind"], r["doc_path"])
        if k not in latest or (r["seq"] or 0) > (latest[k]["seq"] or 0):
            latest[k] = r

    def verdict(kind, path):
        r = latest.get((kind, path))
        return r["verdict"] if r else None

    def waits(kind, d):
        r = latest.get((kind, d["path"]))
        return r is None or (r["verdict"] == "sent_back" and d.get("sha256") and r["doc_sha256"]
                             and d["sha256"] != r["doc_sha256"])

    builds = {}  # slug -> {"spec", "plan", "sets", "title"}; the last doc per slug wins, as in groupBuilds
    for kind in ("spec", "plan"):
        for d in docs[kind]:
            builds.setdefault(d["slug"], {"sets": []})[kind] = d
    for d in reversed(sets):
        builds.setdefault(d["build"] or d["slug"], {"sets": []})["sets"].append(d)

    def set_no(d):
        m = re.search(r"-(\d+)-", d["slug"])
        return int(m.group(1)) if m else -1

    def first_open(slug):
        b = builds[slug]
        steps = ([("spec", b["spec"])] if "spec" in b else []) + \
            [("design", s) for s in sorted(b["sets"], key=set_no)] + ([("plan", b["plan"])] if "plan" in b else [])
        return next((d["path"] for k, d in steps if verdict(k, d["path"]) != "approved"), None)

    try:
        short = wb_names._load(wb_names._cache_path())  # Haiku's 2-4 word build names, as the Workbench shows
    except Exception:  # noqa: BLE001 - names are cosmetic
        short = {}

    def name(slug):
        b = builds.get(slug, {})
        d = b.get("spec") or b.get("plan") or (b["sets"][0] if b.get("sets") else None)
        return (short.get(d["title"]) or _short(d["title"])) if d else slug

    out = {}
    for kind in ("spec", "plan"):
        for slug, b in builds.items():
            d = b.get(kind)
            if not d or not waits(kind, d) or first_open(slug) not in (None, d["path"]):
                continue
            out[f"workbench:{slug}:{kind}"] = {
                "title": f"Sign off the {name(slug)} {kind}", "body": None,
                "url": f"/workbench/?build={quote(slug)}&step={kind}",
                "due_at": _past(datetime.fromtimestamp(d["_mtime"], timezone.utc))}
    for d in sets:
        slug = d["build"] or d["slug"]
        if d["ready"] is False or not waits("design", d) or first_open(slug) not in (None, d["path"]):
            continue
        out[f"workbench:{slug}:{d['slug']}"] = {
            "title": f"{'Check' if d['cards'] == 1 else 'Pick'} {_short(d['title'])}",
            "body": None if not d["build"] else name(slug),
            "url": f"/workbench/?build={quote(slug)}&step={quote(d['slug'])}",
            "due_at": _past(datetime.fromtimestamp(d["mtime"], timezone.utc))}
    for s in marks_store.list_sessions():
        n = sum(m.get("status") == "fixed" for m in s["marks"])
        if not n:
            continue
        sid = s["session"]
        try:
            at = datetime.strptime(sid[:17], "%Y-%m-%d-%H%M%S").astimezone()  # local time, as the Workbench reads it
        except ValueError:
            at = datetime.now(timezone.utc)
        out[f"workbench:mark:{sid}"] = {
            "title": f"Check {n} fixed mark{'s' if n != 1 else ''}", "body": None,
            "url": f"/workbench/?walk={quote(sid)}", "due_at": _past(at)}
    return out


SOURCES = {"mail": mail, "automations": automations, "trips": trips, "jobs": jobs, "workbench": workbench}


def reconcile(conn, sources=None) -> dict:
    """Sync every source; one that raises is logged and left as it was."""
    counts = {}
    for name, fn in (sources or SOURCES).items():
        t = time.monotonic()
        try:
            counts[name] = db.sync(name, fn(), conn=conn) | {"ms": round((time.monotonic() - t) * 1000)}
        except Exception as e:  # noqa: BLE001 - a broken source (or a locked store) must not stop the others
            log.warning("notify source %s skipped: %s: %s", name, type(e).__name__, e)
    return counts

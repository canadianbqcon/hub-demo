"""Breaking-news push alerts (ntfy.sh), evaluated once per poll.

Two qualifying rules, each cluster alerting at most once (`alerts` table,
`cluster_id` PK dedupes by construction):

  - a reporting cluster reaches >=4 distinct outlets across >=2 of L/C/R
    within 60 minutes of its own first_seen;
  - any item lands from a Fed press / BLS / BEA source, in the poll that's
    running right now (never a backlog item from an earlier poll).

Both rules only qualify against *this poll's* view of the world -- the 60-min
window and the fetched-this-run check both exist so the first poll after
deploy, which sees weeks of backlog at once, doesn't blast every old cluster
that already happens to sit above the threshold.

Qualifying writes a `pending` row immediately. Sending is gated on the clock:
outside 23:00-07:00 America/New_York it goes out right away; anything that
qualified during quiet hours stays `pending` and is swept up, together with
whatever else is still pending, into one combined push by the first evaluate()
that runs at or after 07:00. A day (also NY-local) caps at 6 *pushes* (ntfy
notifications), not 6 stories -- everything currently pending goes out
together as one push, so a morning with 5 backlogged stories still spends
only 1 of the day's 6. A pending alert older than PENDING_EXPIRY is marked
`failed` (there is no 'expired' status in the schema's CHECK) rather than
combined into a push hours after it would have mattered.
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from news import cluster, db

MIN_OUTLETS = 4
MIN_BUCKETS = 2
FIRST_SEEN_WINDOW = timedelta(minutes=60)
FED_SOURCES = {"fed-press", "bea", "bls-empsit", "bls-cpi", "bls-ppi"}
# Only rate decisions, jobs, inflation and GDP push (his call, 2026-11-03). The
# Fed feed is mostly bank approvals and enforcement actions, BEA also carries
# trade. BLS feeds are one release each (jobs, CPI, PPI), so they all pass.
# Personal Income and Outlays stays: it is the PCE inflation print.
ECON_KEEP = {
    "fed-press": re.compile(r"FOMC statement|federal funds rate", re.I),
    "bea": re.compile(r"\bGDP\b|gross domestic product|personal income and outlays", re.I),
}
DEAD_AFTER_FAILURES = 24  # 6 hours of 15-minute polls, every one failed

TZ = ZoneInfo("America/New_York")
QUIET_START = dt_time(23, 0)
QUIET_END = dt_time(7, 0)
DAILY_CAP = 6
PENDING_EXPIRY = timedelta(hours=12)

NTFY_TOPIC_PATH = Path.home() / ".config" / "vault-api" / "ntfy_topic"

# The Hub's tailnet-only HTTPS address (`tailscale serve` on demo-desktop
# proxies it to 127.0.0.1:5002), the link Sam's phone uses.
# ponytail: hardcoded; notify/db.py is the second caller and imports HUB_BASE.
HUB_BASE = "https://demo-desktop.tail0demo0.ts.net"
HUB_NEWS_URL = HUB_BASE + "/news/"


def story_url(cluster_id: int) -> str:
    """The news page opened on one story (news.jsx reads the hash on load). A
    combined push links its first story; the rest are a scroll away."""
    return f"{HUB_NEWS_URL}#cluster-{cluster_id}"


def _ntfy_topic() -> str:
    """Read the ntfy topic, generating and persisting one on first real send.
    Never called from a test that passes its own `send` -- this is the only
    thing in this module that touches disk or network."""
    if not NTFY_TOPIC_PATH.exists():
        NTFY_TOPIC_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Create at 0o600 from the first byte written -- write_text() + a
        # later chmod() leaves the file world-readable for the window between
        # the two calls, and this token IS the whole access control for the
        # push channel.
        fd = os.open(str(NTFY_TOPIC_PATH), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        try:
            os.write(fd, secrets.token_hex(16).encode("utf-8"))
        finally:
            os.close(fd)
    return NTFY_TOPIC_PATH.read_text(encoding="utf-8").strip()


def _post(title: str, body: str, url: str) -> None:
    """POST one push to ntfy.sh. Raises on any HTTP/network error; the caller
    marks the alert(s) `failed` and never retries. Title and click link go in
    the query string, not headers: Python sends headers as latin-1, so a
    headline with a curly quote or emoji would raise."""
    query = urllib.parse.urlencode({"title": title, "click": url})
    req = urllib.request.Request(
        f"https://ntfy.sh/{_ntfy_topic()}?{query}",
        data=body.encode("utf-8"),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def _reporting_cluster_ids_over_threshold(conn: sqlite3.Connection, now: datetime) -> list[int]:
    """Reporting/primary-lane clusters that hit >=4 distinct outlets across
    >=2 of L/C/R, restricted to clusters born in the last hour (the backlog
    guard)."""
    cutoff = (now - FIRST_SEEN_WINDOW).isoformat()
    sources = {s["id"]: s for s in db.list_sources()}
    qualifying = []
    for row in conn.execute("SELECT id FROM clusters WHERE first_seen >= ?", (cutoff,)).fetchall():
        cid = row["id"]
        members = conn.execute("SELECT source_id FROM items WHERE cluster_id = ?", (cid,)).fetchall()
        lanes = {sources.get(m["source_id"], {}).get("lane") for m in members}
        if not lanes <= {"reporting", "primary"}:
            continue
        member_dicts = [
            {
                "source_id": m["source_id"],
                "lean": sources.get(m["source_id"], {}).get("lean"),
                "name": sources.get(m["source_id"], {}).get("name", m["source_id"]),
            }
            for m in members
        ]
        counts, _, _ = cluster.bucket_summary(member_dicts)
        outlets = sum(counts.values())
        buckets_hit = sum(1 for v in counts.values() if v > 0)
        if outlets >= MIN_OUTLETS and buckets_hit >= MIN_BUCKETS:
            qualifying.append(cid)
    return qualifying


def _fed_cluster_ids_this_poll(conn: sqlite3.Connection, now: datetime) -> list[int]:
    """Clusters that just gained an item from a Fed/BLS/BEA source, fetched in
    the poll running right now (fetched_at is stamped identically for every
    item inserted in one poll_once call -- see poll.py's _insert_entries) and
    published within the last hour, so an empty cache does not treat weeks of
    releases as new."""
    placeholders = ", ".join("?" for _ in FED_SOURCES)
    rows = conn.execute(
        "SELECT cluster_id, source_id, title FROM items WHERE fetched_at = ? AND published_at >= ? "  # noqa: S608  identifiers from fixed whitelist/placeholders, values bound
        f"AND source_id IN ({placeholders})",
        (now.isoformat(), (now - FIRST_SEEN_WINDOW).isoformat(), *FED_SOURCES),
    ).fetchall()
    out = []
    for r in rows:
        keep = ECON_KEEP.get(r["source_id"])
        if r["cluster_id"] is not None and r["cluster_id"] not in out \
                and (keep is None or keep.search(r["title"] or "")):
            out.append(r["cluster_id"])
    return out


def _qualify(conn: sqlite3.Connection, now: datetime) -> None:
    now_iso = now.isoformat()
    already = {r["cluster_id"] for r in conn.execute("SELECT cluster_id FROM alerts").fetchall()}
    for cid in _reporting_cluster_ids_over_threshold(conn, now):
        if cid not in already:
            conn.execute(
                "INSERT INTO alerts (cluster_id, status, reason, qualified_at) "
                "VALUES (?, 'pending', 'outlets', ?)",
                (cid, now_iso),
            )
            already.add(cid)
    for cid in _fed_cluster_ids_this_poll(conn, now):
        if cid not in already:
            conn.execute(
                "INSERT INTO alerts (cluster_id, status, reason, qualified_at) "
                "VALUES (?, 'pending', 'fed', ?)",
                (cid, now_iso),
            )
            already.add(cid)


def _in_quiet_hours(local_dt: datetime) -> bool:
    t = local_dt.time()
    return t >= QUIET_START or t < QUIET_END


def _pushes_sent_today(conn: sqlite3.Connection, local_dt: datetime) -> int:
    """Distinct push notifications sent today (NY-local), not distinct
    alerts. Every row `evaluate()` marks `sent` in one call shares the exact
    same `sent_at` (see below), so counting distinct timestamps counts pushes
    -- the daily cap is on notifications landing on his phone, not on how many
    stories got combined into one of them."""
    today = local_dt.date()
    seen = set()
    for row in conn.execute("SELECT sent_at FROM alerts WHERE status = 'sent'").fetchall():
        if row["sent_at"] and datetime.fromisoformat(row["sent_at"]).astimezone(TZ).date() == today:
            seen.add(row["sent_at"])
    return len(seen)


def _expire_stale_pending(conn: sqlite3.Connection, now: datetime) -> None:
    """A pending alert older than PENDING_EXPIRY is marked `failed` (never
    retried, same as a bad send) instead of riding along into a push hours
    after the story stopped being breaking news. 'expired' isn't in the
    schema's status CHECK, so `failed` is the closest already-allowed status
    with the right "never retried" meaning."""
    cutoff = (now - PENDING_EXPIRY).isoformat()
    conn.execute(
        "UPDATE alerts SET status = 'failed' WHERE status = 'pending' AND qualified_at < ?",
        (cutoff,),
    )


def _cluster_title(conn: sqlite3.Connection, cluster_id: int) -> str:
    row = conn.execute("SELECT title FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    return row["title"] if row else f"cluster {cluster_id}"


def evaluate(conn: sqlite3.Connection, now: datetime, send=_post) -> int:
    """Qualify newly-eligible clusters, then send whatever's pending if the
    clock and the daily cap allow it. Returns the number of alerts marked
    `sent` this call (0 during quiet hours, at cap, or with nothing pending)."""
    _qualify(conn, now)
    _expire_stale_pending(conn, now)
    # Commit here so the qualify/expire writes never sit open across the
    # network send below -- `conn` is the caller's whole-poll `with db._cache()`
    # connection (poll.py commits it once at the very end), and _post()'s 10s
    # ntfy timeout held inside an open write transaction was locking out every
    # other Hub write to news-cache.db for up to that long.
    conn.commit()

    local_now = now.astimezone(TZ)
    if _in_quiet_hours(local_now):
        return 0

    pending = conn.execute("SELECT * FROM alerts WHERE status = 'pending' ORDER BY qualified_at").fetchall()
    if not pending:
        return 0

    # `remaining` still bounds how many stories fit in this one push -- that
    # part of the design (don't cram an unbounded list into one notification
    # body) never was the bug. What was wrong is what it's measured against:
    # this used to be DAILY_CAP minus alert ROWS already sent today, so one
    # combined push of 5 stories spent 5 of the day's 6 pushes on a single
    # notification. Measuring against pushes already sent means one combined
    # push -- of any size -- spends exactly 1.
    remaining = DAILY_CAP - _pushes_sent_today(conn, local_now)
    if remaining <= 0:
        return 0

    batch = pending[:remaining]
    titles = [_cluster_title(conn, r["cluster_id"]) for r in batch]
    title = "Breaking news" if len(batch) == 1 else f"{len(batch)} breaking stories"
    body = "\n".join(titles)

    now_iso = now.isoformat()
    try:
        send(title, body, story_url(batch[0]["cluster_id"]))
    except Exception:  # noqa: BLE001 -- one bad send marks its batch failed, never retried
        for r in batch:
            conn.execute("UPDATE alerts SET status = 'failed' WHERE cluster_id = ?", (r["cluster_id"],))
        conn.commit()
        return 0

    for r in batch:
        conn.execute(
            "UPDATE alerts SET status = 'sent', sent_at = ? WHERE cluster_id = ?",
            (now_iso, r["cluster_id"]),
        )
    conn.commit()
    return len(batch)


def check_dead_sources(conn: sqlite3.Connection, now: datetime, sources: list[dict], send=_post) -> int:
    """One push per outage when an enabled feed has failed DEAD_AFTER_FAILURES
    polls in a row (Reuters sat dead for two days with only a stale flag on
    the Sources tab). A `_dead:<id>` poll_state row marks the outage as told;
    it is dropped once the feed fetches again, so the next outage pushes too.
    Held through quiet hours, outside the breaking-news daily cap. Returns
    the number of sources reported."""
    state = {r["source_id"]: r for r in conn.execute("SELECT * FROM poll_state").fetchall()}
    told = {k[len("_dead:"):] for k in state if k.startswith("_dead:")}
    enabled = {s["id"] for s in sources}
    for sid in told:
        row = state.get(sid)
        if sid not in enabled or row is None or not row["consecutive_failures"]:
            conn.execute("DELETE FROM poll_state WHERE source_id = ?", (f"_dead:{sid}",))
    dead = [s for s in sources
            if s["id"] not in told and state.get(s["id"]) is not None
            and (state[s["id"]]["consecutive_failures"] or 0) >= DEAD_AFTER_FAILURES]
    conn.commit()  # same reason as evaluate(): never hold a write open across the send
    if not dead or _in_quiet_hours(now.astimezone(TZ)):
        return 0

    lines = []
    for s in dead:
        row = state[s["id"]]
        last_ok = (row["last_ok_at"] or "never")[:16].replace("T", " ")
        lines.append(f"{s.get('name') or s['id']}: {row['last_error'] or 'failing'} (last worked {last_ok} UTC)")
    title = "News source down" if len(dead) == 1 else f"{len(dead)} news sources down"
    try:
        send(title, "\n".join(lines), HUB_NEWS_URL)
    except Exception:  # noqa: BLE001 -- unmarked, so the next poll tries again
        return 0
    for s in dead:
        conn.execute("INSERT OR REPLACE INTO poll_state (source_id, last_run_at) VALUES (?, ?)",
                     (f"_dead:{s['id']}", now.isoformat()))
    conn.commit()
    return len(dead)


# ── Morning brief and evening wrap (his call, 2026-11-03) ───────────────────
# Each goes out once a day, held to its own window, outside the breaking-news
# cap (two scheduled pushes are not breaking news). A `_brief:<date>` /
# `_wrap:<date>` poll_state row marks the day as told, the way `_dead:` does.
BRIEF_AT, BRIEF_UNTIL = dt_time(7, 0), dt_time(12, 0)   # the digest retries until noon
WRAP_AT = dt_time(20, 0)                                # until quiet hours at 23:00
BRIEF_HEADLINES = WRAP_STORIES = 4
_CITE = re.compile(r"\s*\[#\d+\]")


def _told(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute("SELECT 1 FROM poll_state WHERE source_id = ?", (key,)).fetchone() is not None


def _mark(conn: sqlite3.Connection, key: str, now: datetime) -> None:
    conn.execute("INSERT OR REPLACE INTO poll_state (source_id, last_run_at) VALUES (?, ?)", (key, now.isoformat()))
    conn.commit()


def brief_lines(markdown: str, n: int = BRIEF_HEADLINES) -> list[str]:
    """First sentence of the digest's first n bullets, citations stripped."""
    out = []
    for line in markdown.splitlines():
        line = line.strip()
        if line.startswith(("- ", "* ")):
            text = _CITE.sub("", line[2:]).strip()
            out.append(re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0])
            if len(out) == n:
                break
    return out


def _wrap_cluster_ids(conn: sqlite3.Connection, since: datetime) -> list[int]:
    """Today's most-covered stories: distinct outlets per cluster born since `since`."""
    rows = conn.execute(
        "SELECT c.id, COUNT(DISTINCT i.source_id) AS n FROM clusters c JOIN items i ON i.cluster_id = c.id "
        "WHERE c.first_seen >= ? GROUP BY c.id ORDER BY n DESC, c.id DESC LIMIT ?",
        (since.isoformat(), WRAP_STORIES),
    ).fetchall()
    return [r["id"] for r in rows]


def scheduled_pushes(conn: sqlite3.Connection, now: datetime, send=_post, digest=None) -> list[str]:
    """Send the morning brief and the evening wrap when their window is open.
    `digest(date) -> dict|None` is db.get_digest; injectable for tests. Returns
    which of 'brief'/'wrap' went out this call."""
    local = now.astimezone(TZ)
    day, t, sent = local.date().isoformat(), local.time(), []
    if BRIEF_AT <= t < BRIEF_UNTIL and not _told(conn, f"_brief:{day}"):
        row = (digest or db.get_digest)(day)
        lines = brief_lines(row["markdown"]) if row else []
        if lines:  # no digest yet: the next poll tries again, until noon
            try:
                send("Morning brief", "\n".join(f"• {x}" for x in lines), HUB_NEWS_URL)
                _mark(conn, f"_brief:{day}", now)
                sent.append("brief")
            except Exception:  # noqa: BLE001 -- unmarked, so the next poll tries again
                pass
    if WRAP_AT <= t < QUIET_START and not _told(conn, f"_wrap:{day}"):
        # stored stamps are UTC isoformat, compared as text, so the bound must be UTC too
        start = datetime.combine(local.date(), dt_time(0, 0), TZ).astimezone(now.tzinfo)
        ids = _wrap_cluster_ids(conn, start)
        if ids:
            try:
                send("Evening wrap", "\n".join(f"• {_cluster_title(conn, c)}" for c in ids), story_url(ids[0]))
                _mark(conn, f"_wrap:{day}", now)
                sent.append("wrap")
            except Exception:  # noqa: BLE001
                pass
    return sent

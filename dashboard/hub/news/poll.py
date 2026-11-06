"""Poll every enabled source, parse entries, cluster new items, prune.

Registered as TRIGGER_JOBS["news-poll"] (wired in Task 8, imported lazily
there so a bug here cannot break the scheduler). `run()` is the scheduler
entry point: cadence-gated on poll_state._run, guarded by a non-blocking
module lock. `poll_once()` is the actual work and is also what `cli.py poll`
calls directly for a manual, cadence-free run.

Workers (ThreadPoolExecutor) only fetch bytes over the network; every
database write happens on the poll thread afterwards, committed one source at
a time, so 8 concurrent fetches never contend for a SQLite write lock and no
single poll holds the write lock for the whole run.
"""

from __future__ import annotations

import email.utils
import fcntl
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser

from news import alerts, cluster, db, embed, judge
from vault_path import vault_root

# The "Mozilla/5.0 (compatible; ...)" prefix is what state.gov's edge filter lets through; a bare bot token gets a 403.
USER_AGENT = "Mozilla/5.0 (compatible; vault-hub-news/1.0; +https://github.com/SamRivera/vault-code)"
FETCH_TIMEOUT = 20
FETCH_MAX_BYTES = 10 * 1024 * 1024
FETCH_MAX_REDIRECTS = 5
MAX_WORKERS = 8
_NEW_YORK = ZoneInfo("America/New_York")
_ALLOWED_SCHEMES = {"http", "https"}


class _CappedRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = FETCH_MAX_REDIRECTS


# Replaces only the default HTTPRedirectHandler (build_opener drops the
# built-in one for any handler class passed in); the scheme check in _fetch()
# below is what actually keeps file://, ftp://, data:, etc. out -- a source
# url is config Sam edits (or the PATCH-able API, see db.py's
# _PATCHABLE_SOURCE_FIELDS), so it is trusted-but-verify, not attacker input.
_opener = urllib.request.build_opener(_CappedRedirectHandler)

RUN_INTERVAL_MINUTES = 15
TOPICS_INTERVAL_MINUTES = 60
ITEM_TTL_DAYS = 30
ARTICLE_TTL_DAYS = 7
VECTOR_TTL_DAYS = 3

RUN_LOG = Path(vault_root()) / "log" / "scheduler-runs.jsonl"
# ponytail: one line per poll that saw new items, kept apart from RUN_LOG so the
# status panel stays quiet; it is how the judge's daily cost and failure counts
# are read. Grows ~96 lines a day unrotated; rotate if it ever matters.
GROUPING_LOG = Path(vault_root()) / "log" / "news-grouping.jsonl"

# ponytail: one feed (arXiv cs.AI) needs a per-run item cap per its own seed
# rating_note; a generic `max_items` column would be the upgrade if a second
# feed ever needs the same treatment.
_CAPPED_SOURCES = {"arxiv-cs-ai": 20}

_lock = threading.Lock()


def _poll_lock_path() -> Path:
    cache = db._cache_path
    if cache is None:
        raise RuntimeError("news db not initialised: call db.init() before polling")
    return cache.with_name(cache.stem + ".poll.lock")


@contextmanager
def process_poll_lock():
    """Cross-process poll guard: flock a lock file beside news-cache.db, same
    pattern as scheduler.py's own overlap guard. `_lock` above only keeps two
    polls from overlapping inside one process -- the scheduler and a manual
    `cli.py poll` are separate processes, so without this both could run
    poll_once() at once (duplicate alert INSERTs -> IntegrityError rollback,
    duplicate pushes). Yields False, holding nothing, when another process
    already has it; never blocks."""
    path = _poll_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        yield False
        return
    try:
        yield True
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


_SITEMAP_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}

_TOPIC_URL = {
    "ticker": "https://feeds.finance.yahoo.com/rss/2.0/headline?s={q}&region=US&lang=en-US",
    "repo": "https://github.com/{q}/releases.atom",
    "pypi": "https://pypi.org/rss/project/{q}/releases.xml",
    "subreddit": "https://www.reddit.com/r/{q}/.rss",
}
_TOPIC_LANE_LEAN = {
    "ticker": ("reporting", "center"),
    "repo": ("primary", "primary"),
    "pypi": ("primary", "primary"),
    "subreddit": ("community", "center"),
}


# ── Fetch (worker threads; no DB access) ───────────────────────────────────


def _fetch(source: dict) -> tuple:
    """One conditional GET. Returns (status, body, etag, last_modified).

    status is the HTTP status on a response (200, 304, 403, ...), or None on
    a network-level failure (timeout, DNS, connection refused) with `body`
    carrying the error text instead of feed bytes.
    """
    if urllib.parse.urlparse(source["url"]).scheme not in _ALLOWED_SCHEMES:
        return None, f"unsupported URL scheme: {source['url']!r}", None, None
    headers = {"User-Agent": USER_AGENT}
    if "bls.gov" in source["url"]:  # bls.gov 403s any agent that names no contact (tested 2026-10-15)
        headers["User-Agent"] = "vault-hub-news/1.0 (demo@example.com)"
    if source.get("etag"):
        headers["If-None-Match"] = source["etag"]
    if source.get("last_modified"):
        headers["If-Modified-Since"] = source["last_modified"]
    req = urllib.request.Request(source["url"], headers=headers)
    try:
        with _opener.open(req, timeout=FETCH_TIMEOUT) as resp:
            body = resp.read(FETCH_MAX_BYTES + 1)
            if len(body) > FETCH_MAX_BYTES:
                return None, f"response exceeded the {FETCH_MAX_BYTES}-byte read cap", None, None
            return resp.status, body, resp.headers.get("ETag"), resp.headers.get("Last-Modified")
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, None, exc.headers.get("ETag") or source.get("etag"), \
                exc.headers.get("Last-Modified") or source.get("last_modified")
        return exc.code, None, None, None
    except Exception as exc:  # noqa: BLE001 -- one bad source must never sink the run
        return None, str(exc), None, None


# ── Parsing ─────────────────────────────────────────────────────────────────


def _struct_to_dt(struct) -> datetime | None:
    if not struct:
        return None
    try:
        return datetime(*struct[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


_AMPM_RE = re.compile(r"\b(\d{1,2}):(\d{2})(:\d{2})?\s*([AP])M\b", re.IGNORECASE)


def _ampm_to_dt(raw) -> datetime | None:
    """12-hour feed dates ("Tue, 27 Oct 2026 10:04 PM EDT", NY1 and NBC New
    York), which feedparser reads as 10:04 UTC: it drops both the PM and the
    zone name, filing the item up to 16 hours early. None for anything
    without AM/PM, so every other feed keeps feedparser's parse."""
    raw = str(raw or "")
    m = _AMPM_RE.search(raw)
    if not m:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(4).upper() == "P" else 0)
    fixed = raw[:m.start()] + f"{hour:02d}:{m.group(2)}{m.group(3) or ''}" + raw[m.end():]
    try:
        dt = email.utils.parsedate_to_datetime(fixed)
    except (TypeError, ValueError):
        return None
    # ponytail: a 12-hour date with no zone is taken as New York time (both
    # feeds seen doing this are NYC outlets); a non-NYC one would need a
    # per-source zone.
    return (dt if dt.tzinfo else dt.replace(tzinfo=_NEW_YORK)).astimezone(timezone.utc)


def _iso_to_dt(s: str) -> datetime | None:
    """Parse `s`, normalized to UTC. A non-UTC offset (a sitemap's own
    publication_date, say) converts to +00:00 rather than being kept as-is --
    prune/last_seen/last_item_at cutoffs all compare stored ISO strings
    lexically, which is only correct when every stored string carries the
    same offset."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _parse_feed(body: bytes) -> list[dict]:
    """rss/gnews/atom, via feedparser (handles the 5+ date formats checked in
    feedcheck.txt; stdlib xml.etree rejects malformed XML outright)."""
    parsed = feedparser.parse(body)
    entries = []
    for e in parsed.entries:
        title = str(e.get("title") or "").strip()
        url = e.get("link", "")
        if not title or not url:
            continue
        guid = e.get("id") or e.get("guid") or url
        summary = e.get("summary") or e.get("description") or ""
        published = (_ampm_to_dt(e.get("published") or e.get("updated"))
                     or _struct_to_dt(e.get("published_parsed") or e.get("updated_parsed")))
        src_el = e.get("source")  # Google News names the real outlet here
        src = src_el.get("href", "") if isinstance(src_el, dict) else ""
        entries.append({"guid": guid, "url": url, "title": title, "summary": summary,
                        "published": published, "source_href": src})
    return entries


def _parse_sitemap(body: bytes) -> list[dict]:
    """Reuters' news-sitemap: <url><loc>..</loc><news:news><news:title>..
    <news:publication_date>..</news:publication_date></news:news></url>."""
    entries = []
    try:
        # expat 2.4+ caps entity expansion and ElementTree never fetches external entities
        root = ET.fromstring(body)  # noqa: S314
    except ET.ParseError:
        return entries
    for url_el in root.findall("sm:url", _SITEMAP_NS):
        loc = (url_el.findtext("sm:loc", default="", namespaces=_SITEMAP_NS) or "").strip()
        news_el = url_el.find("news:news", _SITEMAP_NS)
        if news_el is None or not loc:
            continue
        title = (news_el.findtext("news:title", default="", namespaces=_SITEMAP_NS) or "").strip()
        if not title:
            continue
        published = _iso_to_dt(news_el.findtext("news:publication_date", default="", namespaces=_SITEMAP_NS))
        entries.append({"guid": loc, "url": loc, "title": title, "summary": "", "published": published})
    return entries


def _parse_entries(source: dict, body: bytes) -> list[dict]:
    entries = _parse_sitemap(body) if source.get("kind") == "sitemap" else _parse_feed(body)
    cap = _CAPPED_SOURCES.get(source["id"])
    return entries[:cap] if cap else entries


# ── Topic feeds (_topics cadence, 60 min) ──────────────────────────────────


def _domain_whitelist() -> set[str]:
    hosts = set()
    for s in db.list_sources():
        host = urllib.parse.urlparse(s.get("url", "")).netloc.lower()
        if host:
            hosts.add(host)
    return hosts


def _ensure_topic_source_row(source_id: str, name: str, lane: str, lean: str) -> None:
    # ponytail: registers a placeholder `sources` row (empty url, enabled=0)
    # purely so cluster.assign's section/lane lookup works for topic items the
    # same way it does for real outlets. enabled=0 is load-bearing: this row
    # must never be picked up by poll_once's `sources` list, which would fetch
    # '' every run (always failing) and collide with this same id under
    # _topic_sources()'s virtual dict -- whichever fetch result lands last in
    # poll_once's `results` dict would silently overwrite the other (a real
    # topic result was lost to it once).
    with db._news() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sources (id, name, url, kind, section, lane, lean, enabled) "
            "VALUES (?, ?, '', 'rss', 'topics', ?, ?, 0)",
            (source_id, name, lane, lean),
        )


def _topic_sources() -> list[dict]:
    """One virtual "source" dict per enabled topic, so it flows through the
    same fetch/parse/cluster pipeline as a real outlet."""
    virtual = []
    for t in db.list_topics():
        if not t.get("enabled"):
            continue
        kind, query = t["kind"], t["query"]
        if kind == "keyword":
            q = urllib.parse.quote(f"{query} when:1d")
            url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
            fkind, lane, lean = "gnews", "reporting", "center"
        elif kind in _TOPIC_URL:
            # default safe="/" -- "repo" queries are "owner/repo" and the
            # slash must survive unescaped for the GitHub releases URL.
            url = _TOPIC_URL[kind].format(q=urllib.parse.quote(query))
            fkind = "rss"
            lane, lean = _TOPIC_LANE_LEAN[kind]
        else:
            continue
        source_id = f"topic:{kind}:{query}"
        _ensure_topic_source_row(source_id, query, lane, lean)
        virtual.append({"id": source_id, "name": query, "url": url, "kind": fkind,
                         "section": "topics", "lane": lane, "lean": lean})
    return virtual


def _filter_keyword_entries(entries: list[dict], whitelist: set[str]) -> list[dict]:
    """Keyword topics run over Google News search, which has no server-side
    domain filter. Its links all point at news.google.com, so the outlet comes
    from <source url=...> (feedparser: entry.source.href), falling back to the
    link host for any other feed."""
    return [e for e in entries
            if any(_host_matches(e.get("source_href") or e["url"], d) for d in whitelist)]


def _host_matches(url: str, domain: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host == domain or host.endswith("." + domain)


# ── poll_state cadence + fetch-result bookkeeping ──────────────────────────


def _last_run_at(conn, key: str) -> str | None:
    row = conn.execute("SELECT last_run_at FROM poll_state WHERE source_id = ?", (key,)).fetchone()
    return row["last_run_at"] if row else None


def _due(last_run_iso: str | None, interval_minutes: int, now: datetime) -> bool:
    if not last_run_iso:
        return True
    dt = _iso_to_dt(last_run_iso)
    if dt is None:
        return True
    return now - dt >= timedelta(minutes=interval_minutes)


def _touch_last_run(conn, key: str, now_iso: str) -> None:
    conn.execute(
        "INSERT INTO poll_state (source_id, last_run_at) VALUES (?, ?) "
        "ON CONFLICT(source_id) DO UPDATE SET last_run_at = excluded.last_run_at",
        (key, now_iso),
    )


def _touch_ok(conn, source_id: str, etag, last_modified, now_iso: str, last_item_iso: str | None) -> None:
    conn.execute(
        """
        INSERT INTO poll_state (source_id, etag, last_modified, last_ok_at, last_item_at, last_error, consecutive_failures)
        VALUES (?, ?, ?, ?, ?, NULL, 0)
        ON CONFLICT(source_id) DO UPDATE SET
            etag = excluded.etag,
            last_modified = excluded.last_modified,
            last_ok_at = excluded.last_ok_at,
            last_item_at = COALESCE(excluded.last_item_at, poll_state.last_item_at),
            last_error = NULL,
            consecutive_failures = 0
        """,
        (source_id, etag, last_modified, now_iso, last_item_iso),
    )


def _touch_failed(conn, source_id: str, error_text: str) -> None:
    conn.execute(
        """
        INSERT INTO poll_state (source_id, last_error, consecutive_failures)
        VALUES (?, ?, 1)
        ON CONFLICT(source_id) DO UPDATE SET
            last_error = excluded.last_error,
            consecutive_failures = poll_state.consecutive_failures + 1
        """,
        (source_id, str(error_text)[:500]),
    )


def _kept(entries: list[dict], now: datetime):
    """(entry, clamped published) for each entry _insert_entries may insert: none past
    the prune line, then the first per guid. The guid set is load-bearing: without it
    the embed step would take a later copy's title while the insert keeps the first.
    One rule for both steps, so they never pick differently."""
    cutoff, guids = now - timedelta(days=ITEM_TTL_DAYS), set()
    for e in entries:
        clamped = min(e["published"], now) if e["published"] else now
        if clamped < cutoff or e["guid"] in guids:
            continue  # past the prune line (would churn every poll), or a later copy
        guids.add(e["guid"])
        yield e, clamped


def _insert_entries(conn, source: dict, entries: list[dict], now: datetime,
                     sources: dict | None = None, vectors: dict | None = None,
                     close_calls: list | None = None, stats: dict | None = None) -> tuple[int, datetime | None]:
    """INSERT OR IGNORE (dedupe on source_id+guid), cluster each new row.
    published_at = min(parsed, fetched_at) -- a missing or future date can
    never dodge pruning or pin itself to the top.

    `sources` is the id->row map cluster.assign needs; pass it in once per
    poll rather than letting assign() reload news.db's whole sources table on
    every single item (poll_once does exactly that -- see its own docstring).

    `vectors` maps guid -> embedding (None or absent = no vector); each new
    row's vector is stored before assign() so the cosine path can see it.
    `close_calls` collects assign()'s judge candidates; `stats["embedded"]`
    counts vectors actually stored."""
    inserted = 0
    latest = None
    now_iso = now.isoformat()
    vector_from = now - timedelta(days=VECTOR_TTL_DAYS)
    for e, clamped in _kept(entries, now):
        cur = conn.execute(
            "INSERT OR IGNORE INTO items (source_id, guid, url, title, summary, published_at, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source["id"], e["guid"], e["url"], e["title"], e["summary"], clamped.isoformat(), now_iso),
        )
        if cur.rowcount:
            inserted += 1
            vec = (vectors or {}).get(e["guid"])
            if vec is not None and clamped >= vector_from:  # an older one prunes this poll
                embed.store(conn, cur.lastrowid, vec)
                if stats is not None:
                    stats["embedded"] = stats.get("embedded", 0) + 1
            cluster.assign(conn, cur.lastrowid, sources, close_calls)
            if latest is None or clamped > latest:
                latest = clamped
    return inserted, latest


def _prune(conn, now: datetime) -> None:
    item_cutoff = (now - timedelta(days=ITEM_TTL_DAYS)).isoformat()
    article_cutoff = (now - timedelta(days=ARTICLE_TTL_DAYS)).isoformat()
    vector_cutoff = (now - timedelta(days=VECTOR_TTL_DAYS)).isoformat()
    conn.execute("DELETE FROM items WHERE published_at < ?", (item_cutoff,))
    conn.execute("DELETE FROM clusters WHERE last_seen < ?", (item_cutoff,))
    # Vectors only serve the 3-day candidate window; also sweep orphans of deleted items.
    conn.execute("DELETE FROM item_vectors WHERE item_id IN "
                 "(SELECT id FROM items WHERE published_at < ?)", (vector_cutoff,))
    conn.execute("DELETE FROM item_vectors WHERE item_id NOT IN (SELECT id FROM items)")
    conn.execute("DELETE FROM articles WHERE fetched_at < ?", (article_cutoff,))
    # A cluster deleted above (or by cluster.merge -- see its own docstring)
    # can leave behind an alerts row keyed on an id that no longer exists;
    # sweep those here rather than teaching every deleter to remember it.
    conn.execute("DELETE FROM alerts WHERE cluster_id NOT IN (SELECT id FROM clusters)")


# ── The poll itself ─────────────────────────────────────────────────────────


def poll_once(now: datetime | None = None, fetch=_fetch,
              topics_interval_minutes: int = TOPICS_INTERVAL_MINUTES, judge_client=None) -> dict:
    """Fetch every enabled source (+ due topic feeds), parse, cluster, prune.

    Each source's writes (fetch-state touch + any new items) commit as their
    own transaction, one source at a time, rather than the whole poll holding
    one long-lived write lock -- a Hub request writing anywhere else in
    news-cache.db would otherwise queue behind the entire poll. `fetch` only
    runs in worker threads and touches no database. Embedding (Ollama) runs
    between a source's read and its write transaction, never inside one.
    Returns {"ok", "failed", "new_items"} plus the embed and judge counters
    (embedded, embed_failed, close_calls, judged_yes, judged_no,
    judge_rejected, stale, over_cap, judge_cost_usd).
    """
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()

    sources = [s for s in db.list_sources() if s.get("enabled") and s.get("url")]

    with db._cache() as conn:
        topics_due = _due(_last_run_at(conn, "_topics"), topics_interval_minutes, now)
        state_by_id = {r["source_id"]: r for r in conn.execute("SELECT * FROM poll_state").fetchall()}

    topic_sources = _topic_sources() if topics_due else []
    jobs = sources + topic_sources
    for j in jobs:
        st = state_by_id.get(j["id"])
        j["etag"] = st["etag"] if st else None
        j["last_modified"] = st["last_modified"] if st else None

    whitelist = _domain_whitelist() if topic_sources else set()

    # One id->row map for cluster.assign, loaded once (news.db, small) rather
    # than once per inserted item -- loaded here, after _topic_sources() has
    # registered any brand-new topic's placeholder row, so assign sees it too.
    sources_by_id = {s["id"]: s for s in db.list_sources()}

    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch, j): j["id"] for j in jobs}
        for fut in as_completed(futures):
            sid = futures[fut]
            try:
                results[sid] = fut.result()
            except Exception as exc:  # noqa: BLE001 -- belt: fetch() already catches its own errors
                results[sid] = (None, str(exc), None, None)

    ok = failed = new_items = embedded = embed_failed = 0
    close_calls: list[dict] = []
    vector_from = now - timedelta(days=VECTOR_TTL_DAYS)  # older titles are not worth embedding
    embed_down = False  # first all-None reply skips Ollama for the rest of this poll: one timeout, not one per source
    jobs_by_id = {j["id"]: j for j in jobs}
    for sid, (status, body, etag, last_modified) in results.items():
        source = jobs_by_id[sid]
        is_success = status == 304 or (isinstance(status, int) and 200 <= status < 300)

        entries: list[dict] = []
        vectors: dict = {}
        if is_success and status != 304 and body:
            entries = _parse_entries(source, body)
            if source.get("kind") == "gnews" and source.get("section") == "topics":
                entries = _filter_keyword_entries(entries, whitelist)
            if entries:
                with db._cache() as conn:  # short read, closed before Ollama runs
                    seen = {r["guid"] for r in conn.execute(
                        "SELECT guid FROM items WHERE source_id = ?", (sid,))}
                fresh = {e["guid"]: e["title"] for e, clamped in _kept(entries, now)
                         if e["guid"] not in seen and clamped >= vector_from}
                if fresh and not embed_down:
                    got = embed.embed(list(fresh.values()))
                    embed_down = all(v is None for v in got)
                    vectors = dict(zip(fresh, got))

        source_calls: list[dict] = []
        stats = {"embedded": 0}
        with db._cache() as conn:
            if not is_success:
                failed += 1
                error_text = body if isinstance(body, str) else f"HTTP {status}"
                _touch_failed(conn, sid, error_text)
                continue

            ok += 1
            last_item_iso = None
            if entries:
                n, latest = _insert_entries(conn, source, entries, now, sources_by_id,
                                            vectors, source_calls, stats)
                new_items += n
                embedded += stats["embedded"]
                # Choice: any new item left without a vector counts as embed_failed,
                # including NEWS_EMBED_OFF, so the counter reads "grouped by Jaccard only".
                embed_failed += n - stats["embedded"]
                if latest is not None:
                    last_item_iso = latest.isoformat()
            _touch_ok(conn, sid, etag, last_modified, now_iso, last_item_iso)
        close_calls.extend(source_calls)  # only after the source committed

    judged = judge.run(close_calls, sources_by_id, judge_client)  # never raises: a judge bug leaves pairs split

    with db._cache() as conn:
        alerts.evaluate(conn, now)
        alerts.check_dead_sources(conn, now, sources)
        alerts.scheduled_pushes(conn, now)

        _touch_last_run(conn, "_run", now_iso)
        if topics_due:
            _touch_last_run(conn, "_topics", now_iso)

        _prune(conn, now)

    return {"ok": ok, "failed": failed, "new_items": new_items,
            "embedded": embedded, "embed_failed": embed_failed, **judged}


# ── Scheduler entry point ───────────────────────────────────────────────────


def _write_grouping_log(now: datetime, new_items: int, counters: dict) -> None:
    GROUPING_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(GROUPING_LOG, "a") as fh:
        fh.write(json.dumps({"date": now.isoformat(), "new_items": new_items, **counters}) + "\n")


def _write_run_log(outcome: str, now: datetime, extra: dict | None = None) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RUN_LOG, "a") as fh:
        fh.write(json.dumps({
            "job": "news-poll", "scheduled_time": "", "date": now.isoformat(),
            "status": "failed", "outcome": outcome, **(extra or {}),
        }) + "\n")


def run(job: dict) -> None:
    """TRIGGER_JOBS["news-poll"] callable (wired in Task 8): evaluated every
    scheduler tick, decides for itself whether it's due (poll_state._run vs
    job["interval_minutes"]), and never blocks -- a tick that finds the
    module lock held is a no-op, same posture as an overlapping tick.

    Only a failed run (an exception, or over half the sources failing) is
    logged; a routine run's only record is poll_state itself, so 96 runs a
    day never bury the Hub status panel (spec: "Run log").
    """
    if not _lock.acquire(blocking=False):
        return
    try:
        with process_poll_lock() as acquired:
            if not acquired:
                return
            now = datetime.now(timezone.utc)
            with db._cache() as conn:
                last_run = _last_run_at(conn, "_run")
            if not _due(last_run, job.get("interval_minutes", RUN_INTERVAL_MINUTES), now):
                return
            try:
                summary = poll_once(
                    now=now,
                    topics_interval_minutes=job.get("topics_interval_minutes", TOPICS_INTERVAL_MINUTES),
                )
            except Exception as exc:  # noqa: BLE001 -- the lock's `finally` still releases
                _write_run_log(f"{type(exc).__name__}: {exc}", now)
                return
            counters = {k: v for k, v in summary.items() if k not in ("ok", "failed", "new_items")}
            if summary["new_items"]:
                _write_grouping_log(now, summary["new_items"], counters)
            total = summary["ok"] + summary["failed"]
            if total and summary["failed"] > total / 2:
                _write_run_log(f"{summary['failed']}/{total} sources failed", now, counters)
    finally:
        _lock.release()

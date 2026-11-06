"""News Hub blueprint -- routes under /news.

Card/detail building joins news-cache.db's clusters/items with news.db's
sources in Python (no ATTACH -- see cluster.py's module docstring), through
cluster.cluster_members()/cluster_lane() so api.py, cli.py's digest-input and
the home card all read a cluster the same way.
"""

from __future__ import annotations

import sys
import json
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from . import cluster, db, poll, reader

# A write that fails validation (a STRICT type mismatch, a CHECK/UNIQUE
# constraint, a bad column) raises one of these from sqlite3, or TypeError/
# ValueError from the request JSON itself -- all of them are "the caller sent
# something invalid", i.e. a 400, never an unhandled 500.
_BAD_INPUT_ERRORS = (sqlite3.IntegrityError, sqlite3.OperationalError, TypeError, ValueError)


def _json_object() -> dict | None:
    """The request's JSON body if it's an object, else None. `request.get_json`
    happily returns a top-level list/string/number (`[1]`, `"x"`) for any
    caller that sent one -- handed straight to `.get()` below, that raises
    AttributeError -> 500 instead of the 400 a bad request deserves."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    return data if isinstance(data, dict) else None


bp = Blueprint(
    "news",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/news",
)

_HUB_DIR = Path(__file__).resolve().parent.parent
_SCHEDULER_CONFIG = _HUB_DIR / "scheduler-config.json"

_MAIN_SECTIONS = ("economy", "politics", "world", "nyc", "tech")
_ALL_SECTIONS = _MAIN_SECTIONS + ("topics",)
_LANE_TABS = {"opinion", "audience", "community"}
_VALID_TABS = {"today"} | set(_ALL_SECTIONS) | _LANE_TABS

_STALE_HOURS = 3

# The cache keeps 30 days (~60k clusters, 2026-11-03). Every tab once read all
# of it: section tabs shipped up to 15k cards (4 MB) and lane tabs took 7-10s,
# and "today" ranked month-old stories by outlet count. Each tab now reads a
# recent window by last_seen (indexed) and ships at most its newest N.
# ponytail: no pagination; add a "load older" call if a window ever feels short.
_TODAY_HOURS = 24
_TAB_HOURS = 48
_TODAY_LIMIT = 30
_TAB_LIMIT = 150


@bp.route("/")
def index():
    return render_template("news.html")


# ── Shared read helpers ────────────────────────────────────────────────────


def _sources_by_id() -> dict:
    return {s["id"]: s for s in db.list_sources()}


def _all_clusters(conn, sections=None, since: str | None = None) -> list[dict]:
    where, args = [], []
    if sections:
        where.append(f"section IN ({', '.join('?' * len(sections))})")
        args.extend(sections)
    if since:
        where.append("last_seen >= ?")  # isoformat on both sides, so string order is time order
        args.append(since)
    sql = "SELECT * FROM clusters" + (" WHERE " + " AND ".join(where) if where else "")
    return [dict(r) for r in conn.execute(sql, tuple(args)).fetchall()]  # noqa: S608  placeholders only, values bound


def _card(row: dict, members: list[dict]) -> dict:
    buckets, primary, gap = cluster.bucket_summary(members)
    names = sorted({m["name"] for m in members if m.get("lean") != "primary"})
    return {
        "id": row["id"],
        "title": row["title"],
        "section": row["section"],
        "last_seen": row["last_seen"],
        "outlets": buckets["L"] + buckets["C"] + buckets["R"],
        "buckets": buckets,
        "primary": primary,
        "names": names,
        "gap": gap,
    }


_CARDS_MEMO: dict[str, tuple[tuple, list[dict]]] = {}


def _db_stamp() -> tuple:
    """Changes whenever either news database is written (the -wal file takes
    every write before a checkpoint folds it into the main file)."""
    out = []
    for p in (db._cache_path, db._news_path):
        for f in (Path(f"{p}"), Path(f"{p}-wal")):
            try:
                st = f.stat()
                out.append((st.st_mtime_ns, st.st_size))
            except OSError:
                out.append(None)
    return tuple(out)


def _cards_for_tab(tab: str) -> list[dict]:
    # A tab is rebuilt only when a poll or an edit has written since the last
    # build; a moved item writes the db too, so it shows on the next read.
    _start_refresher()
    stamp = _db_stamp()
    hit = _CARDS_MEMO.get(tab)
    if hit and hit[0] == stamp:
        return hit[1]
    cards = _build_cards_for_tab(tab)
    _CARDS_MEMO[tab] = (stamp, cards)
    return cards


def _refresh_all() -> None:
    for tab in ["today"] + sorted(_VALID_TABS - {"today"}):
        try:
            stamp = _db_stamp()  # taken before the build, so a write mid-build reads as stale next pass
            if _CARDS_MEMO.get(tab, (None,))[0] != stamp:
                _CARDS_MEMO[tab] = (stamp, _build_cards_for_tab(tab))
        except Exception as e:  # a locked db mid-poll; the next pass retries
            print(f"news cards refresh failed ({tab}): {e}", file=sys.stderr)


def warm() -> None:
    """Build every tab in the background at Hub start and start the refresher,
    so even the first /news visit after a restart reads built tabs. Called from
    app.py's serving block only."""
    def run():
        _refresh_all()
        _start_refresher()
    threading.Thread(target=run, daemon=True, name="news-cards-warm").start()


_refresher: threading.Thread | None = None


def _start_refresher() -> None:
    """The poll writes every 15 minutes, so without this most opens of /news
    would be the first after a write and pay the full rebuild. Started on the
    first read (or warm()), not at import, so tests and scripts never spawn it.

    Rebuilds every tab, "today" first, so a tab click never pays a cold build
    (lane tabs read ~3.7k clusters' members, ~1s cold on /mnt/c). All eleven
    together are ~3s of work per poll write, checked every 30s.
    """
    global _refresher
    if _refresher is not None:
        return

    def loop():
        while True:
            time.sleep(30)
            _refresh_all()

    _refresher = threading.Thread(target=loop, daemon=True, name="news-cards-refresh")
    _refresher.start()


def _build_cards_for_tab(tab: str) -> list[dict]:
    sources = _sources_by_id()
    hours = _TODAY_HOURS if tab == "today" else _TAB_HOURS
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with db._cache() as conn:
        if tab == "today":
            rows = _all_clusters(conn, _MAIN_SECTIONS, since)
        elif tab in _LANE_TABS:
            rows = _all_clusters(conn, since=since)
        else:
            rows = _all_clusters(conn, [tab], since)

        cards = _tab_cards(conn, tab, rows, sources)

    cards.sort(key=lambda c: c["last_seen"], reverse=True)
    if tab == "today":
        # "Top reporting clusters across sections": most-covered first, newest
        # as the tiebreak (stable sort keeps the last_seen order above).
        cards.sort(key=lambda c: c["outlets"] + len(c["primary"]), reverse=True)
        return cards[:_TODAY_LIMIT]
    return cards[:_TAB_LIMIT]


def _tab_cards(conn, tab: str, rows: list[dict], sources: dict) -> list[dict]:
    """The rows that belong on this tab's lane, as cards (row order kept)."""
    by_cluster = cluster.members_by_cluster(conn, (r["id"] for r in rows), sources)
    wanted = tab if tab in _LANE_TABS else "reporting"
    cards = []
    for row in rows:
        members = by_cluster.get(row["id"], [])
        if not members:
            continue  # every item pruned; the cluster row hasn't been swept yet
        if cluster.cluster_lane(members) == wanted:
            cards.append(_card(row, members))
    return cards


def _older_cards(tab: str, before: str) -> list[dict]:
    """The "load older" page: the newest _TAB_LIMIT cards of this tab whose
    last_seen is strictly before `before` (the oldest card already shown).
    Lane tabs keep only some rows, so rows are read newest-first in batches
    until the page is full or the cache runs out. Not memoized: it is a
    deliberate click, and one batch is ~20ms through the indexes."""
    sources = _sources_by_id()
    sections = None if tab in _LANE_TABS else [tab]
    cards: list[dict] = []
    with db._cache() as conn:
        cursor = before
        while len(cards) < _TAB_LIMIT:
            where, args = ["last_seen < ?"], [cursor]
            if sections:
                where.append(f"section IN ({', '.join('?' * len(sections))})")
                args += sections
            rows = [dict(r) for r in conn.execute(
                f"SELECT * FROM clusters WHERE {' AND '.join(where)} ORDER BY last_seen DESC LIMIT 600",  # noqa: S608  placeholders only
                args).fetchall()]
            if not rows:
                break
            cards += _tab_cards(conn, tab, rows, sources)
            cursor = rows[-1]["last_seen"]
    return cards[:_TAB_LIMIT]


@bp.route("/api/clusters")
def api_clusters():
    tab = request.args.get("tab", "today")
    if tab not in _VALID_TABS:
        return jsonify({"error": f"unknown tab {tab!r}"}), 400
    before = request.args.get("before")
    if before:
        if tab == "today":  # today is a ranked top 30, not a timeline
            return jsonify({"error": "today has no older page"}), 400
        return jsonify(_older_cards(tab, before))
    return jsonify(_cards_for_tab(tab))


@bp.route("/api/clusters/<int:cluster_id>")
def api_cluster_detail(cluster_id):
    sources = _sources_by_id()
    with db._cache() as conn:
        row = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if row is None:
            return jsonify({"error": "not found"}), 404
        row = dict(row)
        members = cluster.cluster_members(conn, cluster_id, sources)

    detail = []
    for m in members:
        src = sources.get(m["source_id"], {})
        detail.append({
            "item_id": m["item_id"],
            "source_id": m["source_id"],
            "name": m["name"],
            "title": m["title"],
            "url": reader._safe_url(m["url"]),
            "published_at": m["published_at"],
            "lean": m["lean"],
            "factual": src.get("factual"),
            "owner": src.get("owner"),
            "state_affiliation": src.get("state_affiliation"),
            "paywall": bool(src.get("paywall")),
            "readable": reader.eligible(m, src),
        })

    buckets, primary, gap = cluster.bucket_summary(members)
    return jsonify({
        "id": row["id"],
        "title": row["title"],
        "section": row["section"],
        "last_seen": row["last_seen"],
        "buckets": buckets,
        "primary": primary,
        "gap": gap,
        "members": detail,
    })


@bp.route("/api/items/<int:item_id>/move", methods=["POST"])
def api_move_item(item_id):
    data = _json_object()
    if data is None:
        return jsonify({"error": "expected a JSON object"}), 400
    target = data.get("cluster_id")
    try:
        with db._cache() as conn:
            item = conn.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone()
            if item is None:
                return jsonify({"error": "not found"}), 404
            if target is not None:
                exists = conn.execute("SELECT 1 FROM clusters WHERE id = ?", (target,)).fetchone()
                if exists is None:
                    return jsonify({"error": "cluster not found"}), 404
            new_cluster = cluster.move_item(conn, item_id, target)
    except _BAD_INPUT_ERRORS as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"cluster_id": new_cluster})


@bp.route("/api/items/<int:item_id>/read")
def api_read_item(item_id):
    # reader.read() fails open to {"status": "link", ...} for a missing item,
    # a paywalled one, or any fetch/extract failure -- never a 404 here, the
    # reader's whole design is "never show a broken page, only link out."
    return jsonify(reader.read(item_id))


# ── Sources ─────────────────────────────────────────────────────────────────


_ITEM_STALE_FLOOR = timedelta(hours=24)


def _median_gap_minutes(conn, source_id: str, now: datetime) -> float | None:
    """Median gap between this source's own items over the last 7 days, in
    minutes. None when there's fewer than two items to measure a gap from.

    ponytail: recomputed from `items` on every status/sources read rather than
    a maintained rolling stat -- the table this scans is capped by the 30-day
    prune and this endpoint isn't hot. Upgrade to a stored running median if
    the sources list ever gets slow.
    """
    cutoff = (now - timedelta(days=7)).isoformat()
    rows = conn.execute(
        "SELECT published_at FROM items WHERE source_id = ? AND published_at >= ? "
        "ORDER BY published_at",
        (source_id, cutoff),
    ).fetchall()
    times = sorted(t for t in (poll._iso_to_dt(r["published_at"]) for r in rows) if t)
    if len(times) < 2:
        return None
    gaps = sorted((b - a).total_seconds() / 60 for a, b in zip(times, times[1:], strict=False))
    mid = len(gaps) // 2
    return gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2


def _source_is_stale(conn, source_id: str, state: dict | None, now: datetime) -> bool:
    """last_ok_at older than 3h, or last_item_at older than 4x this source's
    own 7-day median item gap (spec: "Stale-feed warning")."""
    if state is None:
        return True  # never successfully polled
    last_ok = poll._iso_to_dt(state.get("last_ok_at"))  # pyright: ignore[reportArgumentType]  _iso_to_dt accepts None at runtime
    if last_ok is None or now - last_ok > timedelta(hours=_STALE_HOURS):
        return True
    last_item = poll._iso_to_dt(state.get("last_item_at"))  # pyright: ignore[reportArgumentType]  _iso_to_dt accepts None at runtime
    median = _median_gap_minutes(conn, source_id, now)
    if last_item and median is not None:
        # Floor at a day: bursty feeds (Reuters posts dozens a minute apart,
        # some share a timestamp) and a cache younger than 7 days both give a
        # median gap near zero, and the bare 4x rule flagged a third of the
        # list within minutes, NYC outlets every evening. A fetch that fails
        # still flags at _STALE_HOURS above.
        return now - last_item > max(timedelta(minutes=median * 4), _ITEM_STALE_FLOOR)
    return False


_STALE_MEMO: dict = {}


def _stale_ids(sources: list[dict]) -> set[str]:
    """Ids of the given sources that read stale. ~100 per-source median scans
    were ~0.5s per page load, so the answer is kept until the db is written or
    five minutes pass (staleness thresholds are hours, so 5 min is invisible)."""
    key = (_db_stamp(), int(time.time() // 300), tuple(sorted(s["id"] for s in sources)))
    if _STALE_MEMO.get("key") == key:
        return _STALE_MEMO["ids"]
    now = datetime.now(timezone.utc)
    with db._cache() as conn:
        state_by_id = {r["source_id"]: dict(r) for r in conn.execute("SELECT * FROM poll_state").fetchall()}
        ids = {s["id"] for s in sources if _source_is_stale(conn, s["id"], state_by_id.get(s["id"]), now)}
    _STALE_MEMO.update(key=key, ids=ids)
    return ids


@bp.route("/api/sources", methods=["GET"])
def api_sources():
    # Excludes placeholder rows poll.py registers for topic feeds (url ''),
    # which exist only so cluster.assign has a section/lane to look up and
    # were never meant to appear as a manageable "source".
    sources = [s for s in db.list_sources() if s.get("url")]
    stale = _stale_ids([s for s in sources if s.get("enabled")])
    return jsonify([dict(s, stale=s["id"] in stale) for s in sources])


@bp.route("/api/sources/<source_id>", methods=["PATCH"])
def api_update_source(source_id):
    data = _json_object()
    if data is None:
        return jsonify({"error": "expected a JSON object"}), 400
    try:
        updated = db.update_source(source_id, data)
    except _BAD_INPUT_ERRORS as exc:
        return jsonify({"error": str(exc)}), 400
    if updated is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(updated)


@bp.route("/api/status")
def api_status():
    sources = [s for s in db.list_sources() if s.get("url") and s.get("enabled")]
    stale_ids = _stale_ids(sources)
    stale = [{"id": s["id"], "name": s["name"]} for s in sources if s["id"] in stale_ids]
    with db._cache() as conn:
        run_row = conn.execute(
            "SELECT last_run_at FROM poll_state WHERE source_id = '_run'"
        ).fetchone()
        has_items = conn.execute("SELECT 1 FROM items LIMIT 1").fetchone() is not None  # COUNT(*) scanned 86k rows
    return jsonify({
        "stale": stale,
        "last_run": run_row["last_run_at"] if run_row else None,
        "polling_machine": _polling_machine(),
        "empty": not has_items,
    })


def _polling_machine() -> str | None:
    try:
        cfg = json.loads(_SCHEDULER_CONFIG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return cfg.get("active_machine")


# ── Topics ──────────────────────────────────────────────────────────────────


@bp.route("/api/topics", methods=["GET", "POST"])
def api_topics():
    if request.method == "POST":
        data = _json_object()
        if data is None:
            return jsonify({"error": "expected a JSON object"}), 400
        try:
            return jsonify(db.add_topic(data)), 201
        except _BAD_INPUT_ERRORS as exc:
            return jsonify({"error": str(exc)}), 400
    return jsonify(db.list_topics())


@bp.route("/api/topics/<int:topic_id>", methods=["PATCH", "DELETE"])
def api_topic(topic_id):
    if request.method == "DELETE":
        if not db.delete_topic(topic_id):
            return jsonify({"error": "not found"}), 404
        return jsonify({"deleted": True})
    data = _json_object()
    if data is None:
        return jsonify({"error": "expected a JSON object"}), 400
    try:
        updated = db.update_topic(topic_id, data)
    except _BAD_INPUT_ERRORS as exc:
        return jsonify({"error": str(exc)}), 400
    if updated is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(updated)


# ── Digest ──────────────────────────────────────────────────────────────────


@bp.route("/api/digest")
def api_digest():
    d = request.args.get("date") or date.today().isoformat()
    row = db.get_digest(d)
    if row is None:
        return jsonify({"markdown": None, "status": "No summary yet today"})
    return jsonify({"date": row["date"], "markdown": row["markdown"]})

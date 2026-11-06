"""Grouping: same story across outlets, by title embeddings (token-Jaccard when
an item or a candidate has no vector).

Two collections meet here without an ATTACH: items/clusters live in
news-cache.db (the `conn` every function here takes), sources/lanes live in
news.db (read through `db.list_sources()`, a small table so one full read per
call is cheap -- see the module docstring in db.py for the split).
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone

from news import db, embed

# ponytail: fallback only. Titles are normally matched by embedding cosine
# (EMBED_*); this word match covers items with no vector (Ollama down) and
# clusters whose members have none. Title-only tokens miss reworded headlines
# ("Fed holds rates" vs "Central bank keeps borrowing costs steady" scores 0),
# so its ceiling is same-words coverage; it is not meant to be tuned further.
JOIN_AT = 0.35
EMBED_JOIN_AT = 0.88
EMBED_ASK_AT = 0.78
# float32 dot products can land a hair under an exact threshold
_EPS = 1e-6

CANDIDATE_WINDOW = timedelta(hours=36)

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "to", "for", "and", "or", "is", "are",
    "as", "at", "by", "with", "from", "after", "before", "over", "into",
    "that", "this", "its", "his", "her", "their", "says", "say", "said",
    "not", "but", "be", "been", "will", "has", "have", "had", "who", "what",
    "when", "where", "why", "how", "it", "amid", "amid,", "than",
}

_LEAN_BUCKET = {
    "left": "L", "lean_left": "L",
    "center": "C",
    "lean_right": "R", "right": "R",
}
_BUCKET_NAME = {"L": "left", "C": "center", "R": "right"}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _strip_outlet_suffix(title: str) -> str:
    """Drop a trailing ' - Reuters' / ' | AP News' style outlet tag.

    Only strips when the tail after the last ' - '/' | ' delimiter is short
    (<=4 words), so a normal headline that happens to contain a dash isn't
    truncated at its own content.
    """
    idx = max(title.rfind(" - "), title.rfind(" | "))
    if idx == -1:
        return title
    tail = title[idx + 3:]
    if len(tail.split()) <= 4:
        return title[:idx]
    return title


def normalize(title: str) -> set[str]:
    """lowercase -> strip outlet suffix -> tokenize -> drop stopwords/short
    tokens -> cut each surviving token to its first 5 characters."""
    t = _strip_outlet_suffix(title.lower())
    out = set()
    for tok in _TOKEN_RE.findall(t):
        if len(tok) < 3 or tok in _STOPWORDS:
            continue
        out.add(tok[:5])
    return out


def score(tokens: set[str], member_token_sets: list[set[str]]) -> float:
    """Best Jaccard of `tokens` against any one member set (not the union)."""
    best = 0.0
    for member in member_token_sets:
        union = tokens | member
        if not union:
            continue
        j = len(tokens & member) / len(union)
        if j > best:
            best = j
    return best


def _lane_compatible(item_lane: str, member_lanes: set[str]) -> bool:
    if not member_lanes:
        return True
    if item_lane in ("opinion", "audience"):
        return member_lanes == {item_lane}
    if item_lane in ("reporting", "primary"):
        return member_lanes <= {"reporting", "primary"}
    return member_lanes <= {item_lane}


def _is_wire(source: dict) -> bool:
    name = (source.get("name") or "").lower()
    return "reuters" in name or "associated press" in name or name.startswith("ap ") or name == "ap"


def _title_priority(item: dict, source: dict) -> tuple:
    """Lower sorts first: primary lane, then wire (Reuters/AP), then earliest."""
    lane = source.get("lane")
    return (
        0 if lane == "primary" else 1,
        0 if _is_wire(source) else 1,
        item.get("published_at") or "",
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def assign(conn: sqlite3.Connection, item_id: int, sources: dict | None = None,
           close_calls: list | None = None) -> int:
    """Assign an item to a cluster, or start a new one. Never reassigns a
    pinned item.

    With a vector the item joins the best-cosine candidate at EMBED_JOIN_AT;
    failing that, the best Jaccard candidate among clusters with no vectored
    members at JOIN_AT; failing that, a best cosine of EMBED_ASK_AT or more
    opens a new cluster and appends a close call to `close_calls` (if a list)
    for the judge. Without a vector it is the Jaccard path alone.

    `sources` is the news.db id->row map this needs; pass one in when a
    caller (poll.py, polling many items in a row) already has it, to avoid
    reloading the whole sources table per item. Omitted (the default), it
    loads its own -- the right call for a one-off caller like move_item/tests."""
    item = dict(conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())
    if item["pinned"]:
        return item["cluster_id"]

    if sources is None:
        sources = {s["id"]: s for s in db.list_sources()}
    source = sources.get(item["source_id"], {})
    section = source.get("section", "")
    lane = source.get("lane", "reporting")

    ref_time = item.get("published_at") or item.get("fetched_at") or _now_iso()
    try:
        since = (datetime.fromisoformat(ref_time.replace("Z", "")) - CANDIDATE_WINDOW).isoformat()
    except ValueError:
        since = ""

    # Any section: outlets carry one fixed section (Reuters is filed under
    # economy, NPR under politics), so a same-section rule kept every wire out
    # of the stories it covers and painted false coverage gaps. The cluster
    # keeps its first member's section. ponytail: scans every cluster seen in
    # the window, fine at a few thousand; index by token if a poll gets slow.
    candidates = conn.execute(
        "SELECT id, title, last_seen FROM clusters WHERE last_seen >= ?",
        (since,),
    ).fetchall()

    tokens = normalize(item["title"])
    compatible = []  # (cluster id, members)
    for cand in candidates:
        members = conn.execute(
            "SELECT id, title, source_id FROM items WHERE cluster_id = ?", (cand["id"],)
        ).fetchall()
        member_lanes = {sources.get(m["source_id"], {}).get("lane", "") for m in members}
        if _lane_compatible(lane, member_lanes):
            compatible.append((cand["id"], members))

    item_vec = embed.load(conn, [item_id]).get(item_id)
    vecs = embed.load(conn, [m["id"] for _, ms in compatible for m in ms]) if item_vec is not None else {}

    best_cluster, best_score = None, 0.0   # Jaccard (non-vectored candidates if item has a vector)
    best_cos_cluster, best_cos, witness = None, 0.0, ""
    for cid, members in compatible:
        cand_vecs = [(m, vecs[m["id"]]) for m in members if m["id"] in vecs]
        if item_vec is not None and cand_vecs:
            for m, v in cand_vecs:
                c = float(item_vec @ v)
                if c > best_cos:
                    best_cos, best_cos_cluster, witness = c, cid, m["title"]
            continue
        s = score(tokens, [normalize(m["title"]) for m in members])
        if s > best_score:
            best_score, best_cluster = s, cid

    target = None
    if item_vec is not None and best_cos_cluster is not None and best_cos >= EMBED_JOIN_AT - _EPS:
        target = best_cos_cluster
    elif best_cluster is not None and best_score >= JOIN_AT:
        target = best_cluster

    if target is not None:
        cluster_id = target
        conn.execute("UPDATE items SET cluster_id = ? WHERE id = ?", (cluster_id, item_id))
        conn.execute(
            "UPDATE clusters SET last_seen = ? WHERE id = ? AND last_seen < ?",
            (ref_time, cluster_id, ref_time),
        )
        _recompute_title(conn, sources, cluster_id)
        return cluster_id

    cur = conn.execute(
        "INSERT INTO clusters (section, title, first_seen, last_seen) VALUES (?, ?, ?, ?)",
        (section, item["title"], ref_time, ref_time),
    )
    cluster_id = cur.lastrowid
    conn.execute("UPDATE items SET cluster_id = ? WHERE id = ?", (cluster_id, item_id))
    if (close_calls is not None and best_cos_cluster is not None
            and best_cos >= EMBED_ASK_AT - _EPS):
        close_calls.append({"item_id": item_id, "new_cluster": cluster_id,
                            "candidate": best_cos_cluster, "score": best_cos,
                            "witness": witness})
    return cluster_id  # pyright: ignore[reportReturnType]  lastrowid is set after an INSERT / key may be None, .get misses cleanly


def _recompute_title(conn: sqlite3.Connection, sources: dict, cluster_id: int) -> None:
    members = conn.execute(
        "SELECT title, source_id, published_at FROM items WHERE cluster_id = ?", (cluster_id,)
    ).fetchall()
    if not members:
        return
    best = min(members, key=lambda m: _title_priority(dict(m), sources.get(m["source_id"], {})))
    conn.execute("UPDATE clusters SET title = ?, section = ? WHERE id = ?",
                 (best["title"], _majority_section(members, sources), cluster_id))


def _majority_section(members, sources: dict) -> str:
    """Most common section among the non-wire members (wires are filed under
    one section but cover everything); ties go to the earliest member."""
    ordered = sorted(members, key=lambda m: m["published_at"] or "")
    picks = [sources.get(m["source_id"], {}) for m in ordered]
    secs = [s.get("section", "") for s in picks if not _is_wire(s)] or [s.get("section", "") for s in picks]
    return max(secs, key=lambda x: (secs.count(x), -secs.index(x)))


def move_item(conn: sqlite3.Connection, item_id: int, cluster_id: int | None) -> int:
    """Manual override: pins the item to `cluster_id`, or to a fresh cluster
    when `cluster_id` is None. Recomputes the old cluster's title/section the
    same way assign()/merge() do, so the item it just lost doesn't linger as
    its headline."""
    item = dict(conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())
    old_cluster_id = item["cluster_id"]
    sources = {s["id"]: s for s in db.list_sources()}
    if cluster_id is None:
        section = sources.get(item["source_id"], {}).get("section", "")
        ref_time = item.get("published_at") or item.get("fetched_at") or _now_iso()
        cur = conn.execute(
            "INSERT INTO clusters (section, title, first_seen, last_seen) VALUES (?, ?, ?, ?)",
            (section, item["title"], ref_time, ref_time),
        )
        cluster_id = cur.lastrowid
    conn.execute(
        "UPDATE items SET cluster_id = ?, pinned = 1 WHERE id = ?", (cluster_id, item_id)
    )
    if old_cluster_id is not None and old_cluster_id != cluster_id:
        if conn.execute("SELECT 1 FROM items WHERE cluster_id = ?", (old_cluster_id,)).fetchone():
            _recompute_title(conn, sources, old_cluster_id)
        else:
            conn.execute("DELETE FROM clusters WHERE id = ?", (old_cluster_id,))
            conn.execute("DELETE FROM alerts WHERE cluster_id = ?", (old_cluster_id,))
    return cluster_id  # pyright: ignore[reportReturnType]  lastrowid is set after an INSERT / key may be None, .get misses cleanly


def merge(conn: sqlite3.Connection, src_cluster: int, dst_cluster: int,
          sources: dict | None = None) -> None:
    """Move every item out of src_cluster into dst_cluster and drop src."""
    conn.execute(
        "UPDATE items SET cluster_id = ? WHERE cluster_id = ?", (dst_cluster, src_cluster)
    )
    src = conn.execute("SELECT last_seen FROM clusters WHERE id = ?", (src_cluster,)).fetchone()
    if src is not None:
        conn.execute(
            "UPDATE clusters SET last_seen = ? WHERE id = ? AND last_seen < ?",
            (src["last_seen"], dst_cluster, src["last_seen"]),
        )
    conn.execute("DELETE FROM clusters WHERE id = ?", (src_cluster,))
    # src_cluster's own alerts row (if it qualified before being merged away)
    # would otherwise point at an id nothing references anymore.
    conn.execute("DELETE FROM alerts WHERE cluster_id = ?", (src_cluster,))
    if sources is None:
        sources = {s["id"]: s for s in db.list_sources()}
    _recompute_title(conn, sources, dst_cluster)


def cluster_members(conn: sqlite3.Connection, cluster_id: int, sources: dict) -> list[dict]:
    """One cluster's items, hydrated with their source's lean/name/lane -- the
    shared shape api.py's cards/detail view and cli.py's digest-input both build
    on, so the source join (news.db, done in Python -- no ATTACH) happens once."""
    rows = conn.execute(
        "SELECT id, source_id, title, url, published_at, pinned FROM items WHERE cluster_id = ?",
        (cluster_id,),
    ).fetchall()
    return [_member(r, sources) for r in rows]


def members_by_cluster(conn: sqlite3.Connection, cluster_ids, sources: dict) -> dict[int, list[dict]]:
    """cluster_members for many clusters, through idx_items_cluster_source in
    chunks under SQLite's bound-variable cap. A full items scan was 3s on
    /mnt/c (86k rows, 2026-11-03); a 48h tab this way is ~20ms."""
    ids = sorted(set(cluster_ids))
    out: dict[int, list[dict]] = {}
    rows = []
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        rows += conn.execute(
            "SELECT id, source_id, title, url, published_at, pinned, cluster_id FROM items "
            f"WHERE cluster_id IN ({', '.join('?' * len(chunk))})", chunk  # noqa: S608  placeholders only
        ).fetchall()
    for r in sorted(rows, key=lambda r: r["id"]):  # member order stays item-id order, as before
        out.setdefault(r["cluster_id"], []).append(_member(r, sources))
    return out


def _member(r, sources: dict) -> dict:
    src = sources.get(r["source_id"], {})
    return {
        "item_id": r["id"], "source_id": r["source_id"], "title": r["title"],
        "url": r["url"], "published_at": r["published_at"], "pinned": r["pinned"],
        "lean": src.get("lean"), "name": src.get("name", r["source_id"]),
        "lane": src.get("lane"),
    }


def cluster_lane(members: list[dict]) -> str | None:
    """The lane group a cluster's members share: 'reporting' covers a
    reporting/primary mix (cluster.assign lets those join each other), or the
    single opinion/audience/community lane every member is confined to. None
    for an empty member list (a cluster whose items were all pruned)."""
    lanes = {m.get("lane") for m in members if m.get("lane")}
    if not lanes:
        return None
    if lanes <= {"reporting", "primary"}:
        return "reporting"
    if len(lanes) == 1:
        return next(iter(lanes))
    return None  # cluster.assign's lane check should make this unreachable


def bucket_summary(members: list[dict]) -> tuple[dict, list[str], str | None]:
    """L/C/R distinct-outlet counts, primary source names, and the gap line.

    Each member needs at least source_id, lean, name. Counts are distinct
    outlets: two items from one outlet count once.
    """
    buckets = {"L": set(), "C": set(), "R": set()}
    primary_names = {}
    for m in members:
        sid = m.get("source_id")
        lean = m.get("lean")
        if lean == "primary":
            primary_names[sid] = m.get("name", sid)
            continue
        # A topic feed (poll.py's virtual `topic:<kind>:<query>` sources --
        # Yahoo ticker RSS chief among them) is never a distinct reporting
        # outlet: 50+ ticker feeds can all mirror the same wire release, and
        # each one counting here would push a cluster past the breaking-alert
        # threshold, or up a ranked list, on Yahoo mirrors rather than
        # independent reporting.
        if isinstance(sid, str) and sid.startswith("topic:"):
            continue
        b = _LEAN_BUCKET.get(lean)  # pyright: ignore[reportArgumentType]  lastrowid is set after an INSERT / key may be None, .get misses cleanly
        if b:
            buckets[b].add(sid)

    counts = {k: len(v) for k, v in buckets.items()}
    primary = sorted(primary_names.values())

    zero = {k for k, v in counts.items() if v == 0}
    if not zero:
        gap = None
    elif len(zero) == 1:
        gap = f"no {_BUCKET_NAME[next(iter(zero))]} coverage"
    elif len(zero) == 2:
        remaining = next(iter({"L", "C", "R"} - zero))
        gap = "no left or right coverage" if remaining == "C" else f"{_BUCKET_NAME[remaining]} only"
    else:
        gap = "primary sources only"

    return counts, primary, gap

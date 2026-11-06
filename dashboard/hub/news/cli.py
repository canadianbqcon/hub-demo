#!/usr/bin/env python3
"""News CLI, run as a plain script from any cwd.

`poll`: a manual, cadence-free `poll_once()` run.
`embed-backfill [--days N]`: embeds items from the last N days (default and max 3) that
lack a current-model vector, one `embed.CHUNK` at a time; a rerun resumes. Stops when
Ollama is down and exits 1 when any title failed.
`digest-input`: the last 24h of reporting clusters as JSON, for the
/news-digest skill; records the cluster ids it printed so `digest-save` can
reject a citation to anything else.
`digest-save --date D`: reads markdown on stdin, rejects (non-zero, message on
stderr) any `- ` bullet with no `[#<id>]` citation or one citing an id outside
the last digest-input's set, else saves it via db.save_digest.

Prepends its own dashboard/hub and dashboard directories to sys.path before
importing, same pattern as workbench/cli.py, so the /news-digest skill can
call this by absolute path without the Hub process running.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_NEWS_DIR = Path(__file__).resolve().parent
_HUB = _NEWS_DIR.parent
sys.path.insert(0, str(_HUB))
sys.path.insert(0, str(_HUB.parent))  # dashboard/, for sqlite_helpers + vault_path

from vault_path import vault_root  # noqa: E402
from news import cluster, db, embed, poll  # noqa: E402

VAULT = vault_root()
NEWS_DB = VAULT / "data" / "news.db"
NEWS_CACHE_DB = VAULT / "data" / "news-cache.db"
# Sidecar recording the cluster ids the last digest-input printed -- gitignored
# like news-cache.db itself, since it's rebuilt by the next digest-input run.
DIGEST_INPUT_IDS = VAULT / "data" / "news-digest-input-ids.json"
DIGEST_SECTIONS = ("economy", "politics", "world", "nyc", "tech", "topics")
DIGEST_PER_SECTION = 15

_CITATION_RE = re.compile(r"\[#(\d+)\]")
_BULLET_RE = re.compile(r"^(-|\*|\d+\.)\s+")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def cmd_poll() -> int:
    db.init(NEWS_DB, NEWS_CACHE_DB)
    # Same non-blocking module lock the scheduler's poll.run() takes, so a
    # manual `cli.py poll` can never race a scheduled run's writes within this
    # process; process_poll_lock() (flock beside news-cache.db) is what stops
    # it racing the scheduler's own, separate process.
    if not poll._lock.acquire(blocking=False):
        print(json.dumps({"skipped": "a poll is already running"}))
        return 0
    try:
        with poll.process_poll_lock() as acquired:
            if not acquired:
                print(json.dumps({"skipped": "a poll is already running"}))
                return 0
            summary = poll.poll_once()
    finally:
        poll._lock.release()
    print(json.dumps(summary))
    return 0


def cmd_embed_backfill(argv: list[str]) -> int:
    days = poll.VECTOR_TTL_DAYS
    if argv:
        try:
            days = int(argv[1]) if argv[0] == "--days" and len(argv) == 2 else 0
        except ValueError:
            days = 0
    if not 1 <= days <= poll.VECTOR_TTL_DAYS:  # older vectors are pruned on the next poll
        print(f"usage: cli.py embed-backfill [--days 1..{poll.VECTOR_TTL_DAYS}]", file=sys.stderr)
        return 2

    db.init(NEWS_DB, NEWS_CACHE_DB)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db._cache() as conn:
        rows = conn.execute("SELECT id, title FROM items WHERE published_at >= ?", (cutoff,)).fetchall()
        have = set(embed.load(conn, [r["id"] for r in rows]))
    todo = [(r["id"], r["title"]) for r in rows if r["id"] not in have]

    embedded = failed = dead = 0
    for i in range(0, len(todo), embed.CHUNK):
        chunk = todo[i:i + embed.CHUNK]
        vecs = embed.embed([t for _, t in chunk])  # network call, outside any write block
        dead = dead + 1 if all(v is None for v in vecs) else 0
        if dead == 2:  # two empty chunks in a row: Ollama is down; one alone may be a bad chunk
            failed += len(todo) - i
            break
        with db._cache() as conn:  # one short write per chunk, so a rerun resumes
            for (item_id, _), vec in zip(chunk, vecs):
                if vec is None:
                    failed += 1
                else:
                    embed.store(conn, item_id, vec)
                    embedded += 1
    print(f"embedded {embedded}, failed {failed}, already {len(have)}")
    return 1 if failed else 0


def build_digest_input() -> list:
    # Returns a list of cluster dicts (what digest-input prints), not a dict.
    db.init(NEWS_DB, NEWS_CACHE_DB)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=24)).isoformat()
    sources = {s["id"]: s for s in db.list_sources()}

    out = []
    with db._cache() as conn:
        clusters = conn.execute(
            "SELECT * FROM clusters WHERE last_seen >= ?", (cutoff,)
        ).fetchall()
        for row in clusters:
            members = cluster.cluster_members(conn, row["id"], sources)
            if not members or cluster.cluster_lane(members) != "reporting":
                continue  # opinion/audience/community never enter the digest
            outlets, seen = [], set()
            for m in members:
                if m["source_id"] in seen:
                    continue
                seen.add(m["source_id"])
                outlets.append({"name": m["name"], "lean": m["lean"]})
            _, _, gap = cluster.bucket_summary(members)
            out.append({
                "id": row["id"], "title": row["title"], "section": row["section"],
                "outlets": outlets, "gap": gap,
            })

    # Biggest stories first, capped per section: the skill writes at most 6
    # bullets a section, and the uncapped list (~800 clusters, 170 KB) was too
    # big for the locked-down run to read without a script.
    order = {s: i for i, s in enumerate(DIGEST_SECTIONS)}
    out.sort(key=lambda o: (order.get(o["section"], len(order)), -len(o["outlets"]), o["id"]))
    per_section: dict[str, int] = {}
    capped = []
    for o in out:
        per_section[o["section"]] = per_section.get(o["section"], 0) + 1
        if per_section[o["section"]] <= DIGEST_PER_SECTION:
            capped.append(o)
    out = capped

    DIGEST_INPUT_IDS.parent.mkdir(parents=True, exist_ok=True)
    DIGEST_INPUT_IDS.write_text(json.dumps([o["id"] for o in out]), encoding="utf-8")
    return out


def cmd_digest_input() -> int:
    print(json.dumps(build_digest_input()))
    return 0


def _valid_date(s: str) -> bool:
    if not _DATE_RE.match(s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _bullet_cites(markdown: str) -> list[tuple[str, list[int]]]:
    """(stripped bullet line, cited ids) for each bullet line."""
    out = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if _BULLET_RE.match(stripped):
            out.append((stripped, [int(m) for m in _CITATION_RE.findall(stripped)]))
    return out


def check_digest(text: str, day: str) -> list[str]:
    """Error lines for a digest the save step would reject; [] when it passes. Never saves."""
    problems = []
    if not _valid_date(day):
        problems.append(f"bad date: {day}")
    try:
        allowed_ids = set(json.loads(DIGEST_INPUT_IDS.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        allowed_ids = set()

    bullets = _bullet_cites(text)
    for stripped, cites in bullets:
        if not cites:
            problems.append(f"no [#id] citation: {stripped[:80]}")
        for cid in cites:
            if cid not in allowed_ids:
                problems.append(f"cites unknown cluster id {cid}: {stripped[:80]}")
    if not bullets:
        problems.append("digest has no bullets")
    return problems


def cmd_digest_save(argv: list[str]) -> int:
    date_val = None
    it = iter(argv)
    for a in it:
        if a == "--date":
            date_val = next(it, None)
    if not date_val or not _valid_date(date_val):
        print("usage: cli.py digest-save --date YYYY-MM-DD  (markdown on stdin)", file=sys.stderr)
        return 2

    markdown = sys.stdin.read()
    problems = check_digest(markdown, date_val)
    if problems:
        print("digest-save: rejected", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    cited_ids = {cid for _, cites in _bullet_cites(markdown) for cid in cites}
    db.init(NEWS_DB, NEWS_CACHE_DB)
    db.save_digest(date_val, markdown)
    print(json.dumps({"date": date_val, "citations": sorted(cited_ids)}))
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["poll"]:
        return cmd_poll()
    if argv[:1] == ["embed-backfill"]:
        return cmd_embed_backfill(argv[1:])
    if argv[:1] == ["digest-input"]:
        return cmd_digest_input()
    if argv[:1] == ["digest-save"]:
        return cmd_digest_save(argv[1:])
    print("usage: cli.py poll|embed-backfill|digest-input|digest-save --date YYYY-MM-DD", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

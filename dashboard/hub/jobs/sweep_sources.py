"""Collects job candidates from Gmail alerts, ATS boards and hand-picked URLs.

One insert path (db.insert_candidate) for every source, so the dedupe rule
is the same whatever found the posting. Board polling and Gmail queries are
Python with no model involved; the `/job-sweep` skill (Task 7) runs WebSearch
and hands every URL it finds to `add-urls`, which goes through this same
dedupe.

CLI:
    python3 sweep_sources.py [--dry-run]     # poll Gmail + every active board
    python3 sweep_sources.py add-urls URL [URL ...]

`--dry-run` hits the live APIs and prints counts, but calls db.init() and
insert_candidate() only when NOT dry-run -- so a dry run cannot write
jobs.db or job-targets.json even by accident.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

_JOBS_DIR = Path(__file__).resolve().parent
_HUB = _JOBS_DIR.parent
_DASHBOARD = _HUB.parent
for _p in (str(_DASHBOARD), str(_HUB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from jobs import db  # noqa: E402
from vault_path import vault_root  # noqa: E402

TARGETS_PATH = vault_root() / "data" / "job-targets.json"

# Senders that put job links in a "match"-style alert. Only these are queried,
# so an unrelated newsletter from the same provider is never swept.
ALERT_SENDERS = [
    "donotreply@match.indeed.com",
    "jobalerts-noreply@linkedin.com",
    "noreply@builtin.com",
    "alerts@glassdoor.com",
    "jobalerts@ziprecruiter.com",
]

_TIMEOUT = 10  # seconds, every network call
_GMAIL_LOOKBACK_DAYS = 2
_DEMOTE_IDLE_DAYS = 60  # matches the design doc's "60 idle days" -> demoted


# ── HTTP ──────────────────────────────────────────────────────────────────────


def _http_get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "job-autopilot/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _resolve_redirect(url: str) -> str:
    """Follow a tracking redirect (e.g. cts.indeed.com) to its final URL.

    Falls back to the original URL on any failure -- canonicalize() still
    works on a tracking URL, it just won't recognize the ATS host.
    """
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "job-autopilot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.geturl()
    except (urllib.error.URLError, OSError, ValueError):
        return url


# ── board parsers (pure) ─────────────────────────────────────────────────────


def parse_greenhouse(data: dict) -> list[dict]:
    """boards-api.greenhouse.io/v1/boards/<slug>/jobs -> [{title, location, posting_id, url, company}]."""
    out = []
    for j in data.get("jobs", []) or []:
        out.append({
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "posting_id": str(j.get("id", "")),
            "url": j.get("absolute_url", ""),
            "company": j.get("company_name", ""),
        })
    return out


def parse_lever(data: list) -> list[dict]:
    """api.lever.co/v0/postings/<slug>?mode=json -> [{title, location, posting_id, url, company}]."""
    out = []
    for j in data or []:
        out.append({
            "title": j.get("text", ""),
            "location": (j.get("categories") or {}).get("location", ""),
            "posting_id": j.get("id", ""),
            "url": j.get("hostedUrl", ""),
            "company": "",  # not carried on the posting itself; caller supplies the slug
        })
    return out


def parse_ashby(data: dict) -> list[dict]:
    """api.ashbyhq.com/posting-api/job-board/<slug> -> [{title, location, posting_id, url, company}]."""
    out = []
    for j in data.get("jobs", []) or []:
        out.append({
            "title": j.get("title", ""),
            "location": j.get("location", ""),
            "posting_id": j.get("id", ""),
            "url": j.get("jobUrl", ""),
            "company": "",
        })
    return out


def _matches_keywords(title: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    t = title.lower()
    return any(kw.lower() in t for kw in keywords)


def filter_by_keywords(postings: list[dict], keywords: list[str]) -> list[dict]:
    """Keep only postings whose title contains one of `keywords` (case-insensitive).

    An empty keyword list keeps everything -- a target list with nothing in it
    is not yet a filter.
    """
    return [p for p in postings if _matches_keywords(p.get("title", ""), keywords)]


# ── alert email parser (pure) ────────────────────────────────────────────────

# Chrome text every alert template carries alongside the real job link (view
# job / learn more / unsubscribe / ...). The real posting link's anchor text
# is the job title, which is never one of these, so blocklisting the chrome
# is enough to isolate the job links without a template-specific selector.
_ALERT_LINK_BLOCKLIST = {
    "view job", "learn more", "edit profile", "pause these emails",
    "help center", "privacy policy", "terms", "unsubscribe", "indeed",
    "this is a bad match", "no", "yes",
}
_TAG_RE = re.compile(r"<[^>]+>")
_ANCHOR_RE = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)


def parse_alert_email(html: str) -> list[str]:
    """Job posting links (still tracking URLs) from a saved alert email's HTML.

    Dedupes by href, so the same job's "View job" / title / "Learn more"
    links (all pointing at the same tracking URL) count once.
    """
    seen = set()
    urls = []
    for m in _ANCHOR_RE.finditer(html):
        href = unescape(m.group(1))
        text = unescape(_TAG_RE.sub("", m.group(2)))
        text = text.replace("​", "").replace("‌", "").replace("﻿", "")
        text = re.sub(r"\s+", " ", text).strip().lower()
        if not text or text in _ALERT_LINK_BLOCKLIST or href in seen:
            continue
        seen.add(href)
        urls.append(href)
    return urls


def _extract_html(payload: dict) -> str:
    """Recurse a Gmail message payload for its text/html part, base64url-decoded."""
    if payload.get("mimeType") == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        html = _extract_html(part)
        if html:
            return html
    return ""


# ── canonicalize (pure) ──────────────────────────────────────────────────────

_GREENHOUSE_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io"}
_LEVER_HOST = "jobs.lever.co"
_ASHBY_HOST = "jobs.ashbyhq.com"
_GH_JOB_PATH = re.compile(r"^/([^/]+)/jobs/(\d+)$")
_UUID_PATH = re.compile(r"^/([^/]+)/([0-9a-fA-F-]{36})(?:/(?:apply|application))?$")


def canonicalize(url: str) -> tuple[str, str, str]:
    """A raw job URL -> (canonical_url, ats_host, ats_posting_id).

    ats_host is a normalized ATS name ("greenhouse" / "lever" / "ashby"), not
    the literal domain -- so a boards.greenhouse.io URL and a company site's
    ?gh_jid= widget URL for the same posting agree. Unrecognized hosts get
    ("", "") and just have query/fragment stripped.
    """
    parts = urlsplit(url)
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    query = parse_qs(parts.query)

    if netloc in _GREENHOUSE_HOSTS:
        m = _GH_JOB_PATH.match(path)
        if m:
            slug, pid = m.group(1), m.group(2)
            return f"https://boards.greenhouse.io/{slug}/jobs/{pid}", "greenhouse", pid

    if "gh_jid" in query:
        pid = query["gh_jid"][0]
        canonical = urlunsplit((parts.scheme or "https", parts.netloc, parts.path, f"gh_jid={pid}", ""))
        return canonical, "greenhouse", pid

    if netloc == _LEVER_HOST:
        m = _UUID_PATH.match(path)
        if m:
            slug, pid = m.group(1), m.group(2)
            return f"https://jobs.lever.co/{slug}/{pid}", "lever", pid

    if netloc == _ASHBY_HOST:
        m = _UUID_PATH.match(path)
        if m:
            slug, pid = m.group(1), m.group(2)
            return f"https://jobs.ashbyhq.com/{slug}/{pid}", "ashby", pid

    stripped = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return stripped, "", ""


# ── job-targets.json ─────────────────────────────────────────────────────────

_ATS_HOSTS = ("greenhouse", "lever", "ashby")


def load_targets() -> dict:
    if TARGETS_PATH.exists():
        data = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
    else:
        data = {}
    data.setdefault("keywords", [])
    data.setdefault("active", {})
    data.setdefault("suggested", {})
    data.setdefault("last_hit", {})
    for host in _ATS_HOSTS:
        data["active"].setdefault(host, [])
        data["suggested"].setdefault(host, [])
    return data


def save_targets(data: dict) -> None:
    TARGETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TARGETS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def promote(host: str, slug: str, targets: dict | None = None) -> dict:
    """Move `slug` from suggested to active under `host`. Idempotent, saves unless
    `targets` is passed in (caller owns the save in that case, e.g. a batch run)."""
    own = targets is None
    data = targets if targets is not None else load_targets()
    suggested = data["suggested"].setdefault(host, [])
    if slug in suggested:
        suggested.remove(slug)
    active = data["active"].setdefault(host, [])
    if slug not in active:
        active.append(slug)
    if own:
        save_targets(data)
    return data


def demote_idle(today: str, targets: dict | None = None) -> dict:
    """Any active slug with a last_hit more than `_DEMOTE_IDLE_DAYS` days old
    moves back to suggested. A slug with no recorded last_hit is left alone --
    ponytail: it just hasn't scored a keyword hit yet, which isn't the same as
    having gone idle, so it is never auto-demoted on that basis alone.
    """
    own = targets is None
    data = targets if targets is not None else load_targets()
    today_d = date.fromisoformat(today)
    last_hit = data.setdefault("last_hit", {})
    for host in _ATS_HOSTS:
        active = data["active"].setdefault(host, [])
        suggested = data["suggested"].setdefault(host, [])
        keep = []
        for slug in active:
            last = last_hit.get(f"{host}:{slug}")
            if last and (today_d - date.fromisoformat(last)).days > _DEMOTE_IDLE_DAYS:
                if slug not in suggested:
                    suggested.append(slug)
                continue
            keep.append(slug)
        data["active"][host] = keep
    if own:
        save_targets(data)
    return data


def _mark_hit(targets: dict, host: str, slug: str, today: str) -> None:
    targets.setdefault("last_hit", {})[f"{host}:{slug}"] = today


# ── sweeps ────────────────────────────────────────────────────────────────────


def _insert(company: str, title: str, location: str, source: str, job_url: str,
            canonical_url: str, ats_host: str, ats_posting_id: str) -> int | None:
    return db.insert_candidate({
        "company": company, "title": title, "location": location,
        "source": source, "job_url": job_url, "canonical_url": canonical_url,
        "ats_host": ats_host, "ats_posting_id": ats_posting_id,
    })


def _sweep_board(host: str, url_fmt: str, parse, targets: dict, dry_run: bool, today: str) -> tuple[int, int]:
    seen = inserted = 0
    keywords = targets.get("keywords", [])
    for slug in list(targets["active"].get(host, [])):
        try:
            data = _http_get_json(url_fmt.format(slug=slug))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f"{host}:{slug} failed: {exc}")
            continue
        matches = filter_by_keywords(parse(data), keywords)
        for job in matches:
            seen += 1
            canonical_url, ats_host, pid = canonicalize(job["url"])
            if ats_host == "greenhouse" and "gh_jid=" in canonical_url:
                # a company-site widget URL (stripe.com/jobs/search?gh_jid=) hides the
                # board slug the form reader needs; the board we just read knows it
                canonical_url = f"https://boards.greenhouse.io/{slug}/jobs/{pid}"
            if not dry_run:
                if _insert(job.get("company") or slug, job["title"], job.get("location", ""),
                           "ats", job["url"], canonical_url, ats_host, pid) is not None:
                    inserted += 1
        if matches:
            _mark_hit(targets, host, slug, today)
    return seen, inserted


def _sweep_gmail(dry_run: bool) -> tuple[int, int]:
    seen = inserted = 0
    try:
        _svc_dir = str(Path.home() / ".config" / "vault-api")
        if _svc_dir not in sys.path:
            sys.path.insert(0, _svc_dir)
        from services import gmail  # noqa: F401  # pyright: ignore[reportMissingImports]
        svc = gmail()
    except Exception as exc:  # pragma: no cover - depends on the machine's own auth
        print(f"gmail failed: {exc}")
        return 0, 0

    since = (date.today() - timedelta(days=_GMAIL_LOOKBACK_DAYS)).strftime("%Y/%m/%d")
    for sender in ALERT_SENDERS:
        try:
            result = svc.users().messages().list(
                userId="me", q=f"from:{sender} after:{since}", maxResults=50,
            ).execute()
        except Exception as exc:
            print(f"gmail:{sender} failed: {exc}")
            continue
        for msg in result.get("messages", []) or []:
            try:
                detail = svc.users().messages().get(userId="me", id=msg["id"], format="full").execute()
            except Exception as exc:
                print(f"gmail:{sender}:{msg['id']} failed: {exc}")
                continue
            html = _extract_html(detail.get("payload", {}))
            for link in parse_alert_email(html):
                seen += 1
                resolved = _resolve_redirect(link)
                canonical_url, ats_host, pid = canonicalize(resolved)
                if not dry_run:
                    if _insert("", "", "", "gmail", resolved, canonical_url, ats_host, pid) is not None:
                        inserted += 1
    return seen, inserted


def add_urls(urls: list[str]) -> int:
    """Insert each URL through the standard dedupe path. Returns count inserted."""
    inserted = 0
    for url in urls:
        canonical_url, ats_host, pid = canonicalize(url)
        if _insert("", "", "", "web", url, canonical_url, ats_host, pid) is not None:
            inserted += 1
    return inserted


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print counts, write nothing")
    sub = parser.add_subparsers(dest="command")
    add_p = sub.add_parser("add-urls", help="insert one or more URLs through the standard dedupe")
    add_p.add_argument("urls", nargs="+")
    args = parser.parse_args(argv)

    if args.command == "add-urls":
        db.init(vault_root() / "data" / "jobs.db")
        n = add_urls(args.urls)
        print(f"add-urls: {n} inserted of {len(args.urls)}")
        return

    if not args.dry_run:
        db.init(vault_root() / "data" / "jobs.db")

    targets = load_targets()
    today = date.today().isoformat()

    gh_seen, gh_ins = _sweep_board(
        "greenhouse", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        parse_greenhouse, targets, args.dry_run, today,
    )
    lv_seen, lv_ins = _sweep_board(
        "lever", "https://api.lever.co/v0/postings/{slug}?mode=json",
        parse_lever, targets, args.dry_run, today,
    )
    ab_seen, ab_ins = _sweep_board(
        "ashby", "https://api.ashbyhq.com/posting-api/job-board/{slug}",
        parse_ashby, targets, args.dry_run, today,
    )
    gm_seen, gm_ins = _sweep_gmail(args.dry_run)

    demote_idle(today, targets)
    if not args.dry_run:
        save_targets(targets)

    print(f"greenhouse: {gh_seen} seen, {gh_ins} inserted")
    print(f"lever: {lv_seen} seen, {lv_ins} inserted")
    print(f"ashby: {ab_seen} seen, {ab_ins} inserted")
    print(f"gmail: {gm_seen} seen, {gm_ins} inserted")
    if args.dry_run:
        print("dry run: nothing written")


if __name__ == "__main__":
    main()

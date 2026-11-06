#!/usr/bin/env python3
"""Bake one champion-identity caption per champion into data/forge-identity.json.

Source: the "3 Minute <Champion> Guide" videos on the 3 Minute League channel.
For each champion the newest such video is picked by title, its English
auto-caption is fetched through yt-dlp, and the guide's opening "Why play"
sentences are stored verbatim. Captions are never parsed into numbers or
traits; a champion with no guide gets no entry (not an empty one).

    python3 bake_identity.py                 # every catalog champion not yet stored
    python3 bake_identity.py --champ Vayne   # one champion: print and store it
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

CHANNEL = "UCbqpZInu-pjnBIy5sbh7Eag"
OUT = vault_root() / "data" / "forge-identity.json"
CACHE = vault_root() / "data" / "forge-identity-channel.json"
CATALOG = Path(__file__).resolve().parent / "frontend" / "static" / "catalog.json"
YTDLP = ["yt-dlp", "--no-update", "--no-warnings"]
QUOTE_WORDS = 80     # an unpunctuated caption is one long "sentence", so this is the real cap
QUOTE_SENTENCES = 5  # the opening is "Why play X?" plus a few sentences before the abilities start
CACHE_AGE = 12 * 3600


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("&", "and"))


def names_for(champion: str) -> set[str]:
    # Titles say "Nunu" where the catalog says "Nunu & Willump".
    return {norm(champion), norm(champion.split(" & ")[0])}


def pick_guide(entries: list[dict], champion: str) -> dict | None:
    """Newest title naming exactly this champion. `entries` are newest first
    (the channel order), so the first hit wins. "Vi" never matches Viktor."""
    want = names_for(champion)
    for e in entries:
        m = re.match(r"3 Minute (.+?) Guide\b", e.get("title") or "")
        if m and norm(m.group(1)) in want:
            return e
    return None


def why_play(caption: str) -> str:
    """The guide's opening sentences, consecutive caption text kept verbatim
    (whitespace collapsed). Starts at "Why play", stops before the first
    sentence that reaches the abilities ("passive") or after QUOTE_SENTENCES."""
    text = re.sub(r"\s+", " ", caption).strip()
    i = text.lower().find("why play")
    text = text[i:] if i >= 0 else text  # ponytail: no "Why play" line falls back to the caption start
    out = []
    for s in re.split(r"(?<=[.?!])\s+", text)[:QUOTE_SENTENCES]:
        if out and "passive" in s.lower():
            break
        out.append(s)
    quote = " ".join(out)
    words = quote.split(" ")
    if len(words) <= QUOTE_WORDS:
        return quote
    cut = next((i for i, w in enumerate(words) if i and "passive" in w.lower()), QUOTE_WORDS)
    return " ".join(words[:min(cut, QUOTE_WORDS)])


def caption_text(json3: dict) -> str:
    parts = ("".join(s.get("utf8", "") for s in ev.get("segs", [])).strip() for ev in json3.get("events", []))
    return " ".join(p for p in parts if p)


def _run(args: list[str], timeout: int = 300) -> str:
    r = subprocess.run(YTDLP + args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp failed ({r.returncode}): {r.stderr.strip()[-200:]}")
    return r.stdout


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def channel_entries(cache: Path = CACHE, max_age: float = CACHE_AGE) -> list[dict]:
    if not cache.exists() or time.time() - cache.stat().st_mtime > max_age:
        out = _run(["--flat-playlist", "-J", f"https://www.youtube.com/channel/{CHANNEL}/videos"], 600)
        entries = [{"id": e["id"], "title": e.get("title")} for e in json.loads(out)["entries"]]
        _write(cache, {"entries": entries})
    return json.loads(cache.read_text(encoding="utf-8"))["entries"]


def fetch_caption(video_id: str) -> tuple[str, str] | None:
    """(upload date ISO, caption text), or None when the video has no English caption."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory() as d:
        try:
            out = _run([
                "--skip-download", "--no-simulate", "--write-auto-subs", "--sub-langs", "en.*", "--sub-format", "json3",
                "--print", "%(upload_date)s", "-o", f"{d}/%(id)s", url,
            ])
        except RuntimeError as ex:
            if "429" not in str(ex):
                raise
            return _upload_date(url), _api_caption(video_id)
        files = sorted(Path(d).glob("*.json3"), key=lambda p: "orig" not in p.name)
        if not files:
            return None
        up = out.strip().splitlines()[-1]
        return f"{up[:4]}-{up[4:6]}-{up[6:]}", caption_text(json.loads(files[0].read_text(encoding="utf-8")))


def _upload_date(url: str) -> str:
    up = _run(["--skip-download", "--print", "%(upload_date)s", url]).strip().splitlines()[-1]
    return f"{up[:4]}-{up[4:6]}-{up[6:]}"


def _api_caption(video_id: str) -> str:
    """yt-dlp's caption URL answers 429 after about 110 fetches; the player API still answers."""
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        got = YouTubeTranscriptApi().fetch(video_id, languages=["en", "en-US"])
    except Exception as ex:  # its own error classes all mean the same here: no caption this run
        raise RuntimeError(f"transcript api: {type(ex).__name__}") from ex
    return " ".join(x.text for x in got.snippets)


def bake_one(champion: str, entries: list[dict]) -> dict | None:
    guide = pick_guide(entries, champion)
    if not guide:
        return None
    got = fetch_caption(guide["id"])
    if not got or not got[1]:
        return None
    uploaded, caption = got
    return {
        "videoId": guide["id"], "title": guide["title"], "uploaded": uploaded,
        "quote": why_play(caption), "url": f"https://www.youtube.com/watch?v={guide['id']}",
    }


PAUSE = 15   # s between captions: YouTube answered 429 after about 110 in a row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--champ", action="append", default=[])
    args = ap.parse_args()
    names = [c["n"] for c in json.loads(CATALOG.read_text(encoding="utf-8"))["champs"]]
    store = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    todo = args.champ or [n for n in names if n not in store]  # resumable: stored champions are skipped
    if not todo:
        return 0
    entries = channel_entries()
    for n in todo:
        if not pick_guide(entries, n):
            print(f"{n}: no guide")
            continue
        time.sleep(PAUSE)   # a failed caption is paced too, or a 429 burns the rest of the list
        try:
            e = bake_one(n, entries)
        except (RuntimeError, subprocess.TimeoutExpired) as ex:
            print(f"{n}: {ex}", file=sys.stderr)
            continue
        if not e:
            print(f"{n}: no guide")
            continue
        store[n] = e
        _write(OUT, store)  # one champion at a time so a stop loses nothing
        print(f"{n}: {e['quote']}\n{e['url']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

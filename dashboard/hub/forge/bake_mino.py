#!/usr/bin/env python3
"""Bake Mino's Viego build guide into data/forge-mino.json.

Mino (its-mino.com) publishes a per-champion scoring table (durability, damage,
CC, shields, reset denial, Mercs and Steelcaps value) and a decision tree that
turns the ten champions in a game into one of 13 Viego builds. The tree lives
in the page's script bundle and is ported by hand to `mino_tree.py`; this bake
re-reads the two tables the tree consumes, once per patch:

  champions  173 rows of 15 fields, off the page's React Server Component
             stream (`self.__next_f.push` chunks), the regex the handoff found
  builds     13 `{id, label, items}` rows from the same stream

Personal use only. The table is Mino's work: it is never republished or served
outside the Hub, and values are never edited here.

Validation runs before the replace: at least MIN_ROWS rows, one row per
championId, every field present with its type. A page that changed shape fails
loudly and the last good file stays, and the Viego build falls back to the
statistics path (build_engine.py says so on the page).

    python3 bake_mino.py                 # fetch and bake
    python3 bake_mino.py --html page.html  # bake from a saved page
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

URL = "https://its-mino.com/guide/build"
OUT = vault_root() / "data" / "forge-mino.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")
# 173 rows on 16.21. A drop below this is a page change, not a champion removal.
MIN_ROWS = 170

# Every field the tree reads, with the types the table has carried (None where
# Mino leaves a champion unscored).
FIELDS = {
    "name": (str,), "championId": (str,), "championIcon": (str,),
    "shields": (str,), "damageType": (str,), "damageThreat": (str,),
    "deniesResets": (bool,), "cc": (str,), "durabilityScore": (int,),
    "damageScore": (int,), "ccScore": (int, type(None)), "shieldScore": (int,),
    "shieldTiming": (str, type(None)), "mercuryTreadsScore": (int,),
    "canBuildSteelcaps": (bool, type(None)),
}
DAMAGE_TYPES = {"AD", "AP", "Mixed"}

_PUSH = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.S)
_ROW = re.compile(r'\{"name":"[^"{}]+","championId"[^{}]*\}')
_BUILD = re.compile(r'\{"id":"([a-z0-9-]+)","label":"([^"]*)","summary":.*?"items":\[(.*?)\]\}', re.S)
_ITEM = re.compile(r'\{"id":(\d+),"name":"')
_PATCH = re.compile(r"/cdn/(\d+\.\d+\.\d+)/img/champion/")


class BakeError(ValueError):
    pass


def decode(html: str) -> str:
    """The RSC stream as one string: every pushed chunk's payload, in order."""
    out = []
    for raw in _PUSH.findall(html):
        try:
            arr = json.loads(raw)
        except ValueError:
            continue
        if len(arr) > 1 and isinstance(arr[1], str):
            out.append(arr[1])
    return "".join(out)


def rows(stream: str) -> list[dict]:
    """The full scoring table's rows. The stream also carries a short 13-field copy
    (`icon`, no `shields` or `deniesResets`) for the picker; the full table is the
    one whose rows carry `championIcon`. Identical repeats collapse."""
    out, seen = [], set()
    for m in _ROW.findall(stream):
        if m in seen:
            continue
        seen.add(m)
        r = json.loads(m)
        if "championIcon" in r:
            out.append(r)
    return out


def builds(stream: str) -> dict:
    out = {}
    for bid, label, items in _BUILD.findall(stream):
        out.setdefault(bid, {"label": label, "items": [int(i) for i in _ITEM.findall(items)]})
    return out


def validate(table: list[dict]) -> dict:
    """Rows to {championId: row}, or BakeError naming what is wrong."""
    if len(table) < MIN_ROWS:
        raise BakeError(f"{len(table)} rows, expected at least {MIN_ROWS}")
    out: dict[str, dict] = {}
    for r in table:
        cid = str(r.get("championId"))
        if cid in out:
            raise BakeError(f"duplicate championId {cid!r}")
        for f, types in FIELDS.items():
            if f not in r:
                raise BakeError(f"{cid}: missing {f}")
            if not isinstance(r[f], types) or (bool not in types and isinstance(r[f], bool)):
                raise BakeError(f"{cid}: {f} is {type(r[f]).__name__}")
        if r["damageType"] not in DAMAGE_TYPES:
            raise BakeError(f"{cid}: damageType {r['damageType']!r}")
        out[cid] = {f: r[f] for f in FIELDS if f != "championIcon"}
    return out


def bake(html: str) -> dict:
    stream = decode(html)
    table = rows(stream)
    champs = validate(table)
    b = builds(stream)
    if len(b) < 10 or any(not v["items"] for v in b.values()):
        raise BakeError(f"{len(b)} builds, or a build with no items")
    m = _PATCH.search(table[0]["championIcon"])
    return {"patch": m.group(1) if m else None,
            "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "champions": champs, "builds": b}


def write(store: dict, out: Path = OUT) -> None:
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, out)


def fetch() -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", type=Path, help="bake from a saved page instead of fetching")
    a = ap.parse_args()
    html = a.html.read_text(encoding="utf-8", errors="replace") if a.html else fetch()
    try:
        store = bake(html)
    except BakeError as exc:
        print(f"bake_mino: {exc}; {OUT.name} left as it was", file=sys.stderr)
        return 1
    write(store, OUT)
    print(f"bake_mino: {len(store['champions'])} champions, {len(store['builds'])} builds, "
          f"patch {store['patch']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

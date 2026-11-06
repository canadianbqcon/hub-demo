#!/usr/bin/env python3
"""Bake the community power-spikes sheet into data/forge-spikes.json.

Source: a public Google Sheet, one row per champion: notable item power spikes,
level spikes, and tips to fight that champion, plus a "Before You Read" tab.
Text is stored verbatim, never parsed into numbers. A row's "(Mid)" / "(Sup)"
qualifier becomes its role. The sheet predates the 2024 item rework, so a row
naming a Mythic is flagged `oldItems` and the page says so.

    python3 bake_spikes.py            # fetch, validate, write
    python3 bake_spikes.py --check    # fetch and validate, print, never write
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

SHEET = "DEMO_SHEET_ID_0"
URL = f"https://docs.google.com/spreadsheets/d/{SHEET}/edit"
OUT = vault_root() / "data" / "forge-spikes.json"
# Rows written by hand for champions the sheet lacks; merged in, marked `authored`, never overwrite a sheet row.
AUTHORED = vault_root() / "data" / "forge-spikes-authored.json"
CATALOG = Path(__file__).resolve().parent / "frontend" / "static" / "catalog.json"
MIN_ROWS = 100  # 121 rows on 2026-11-03; fewer means the sheet changed shape
ROLES = {"top": "top", "jungle": "jungle", "jung": "jungle", "jg": "jungle", "mid": "mid",
         "adc": "bot", "bot": "bot", "sup": "support", "support": "support"}
# Sheet spellings that are not the catalog name once punctuation is dropped.
ALIASES = {"nunu": "Nunu & Willump", "wukong": "Wukong", "monkeyking": "Wukong"}


def tab(name: str) -> list[list[str]]:
    q = urllib.parse.urlencode({"tqx": "out:csv", "sheet": name})
    with urllib.request.urlopen(f"https://docs.google.com/spreadsheets/d/{SHEET}/gviz/tq?{q}",
                                timeout=30) as r:
        return list(csv.reader(io.StringIO(r.read().decode("utf-8"))))


def squash(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def parse(rows: list[list[str]], champs: list[str]) -> tuple[dict, list[str]]:
    """{catalog name: [{role, items, levels, tips, oldItems}]} and the names that matched nothing."""
    by_key = {squash(c): c for c in champs}
    by_key.update({k: v for k, v in ALIASES.items() if v in champs})
    out: dict = {}
    missed = []
    for r in rows:
        r = [c.strip() for c in r] + [""] * 4
        if not r[0] or r[0].lower() == "champion":
            continue
        cell = r[0]
        if len(cell) > 40:  # the sheet's Fizz row has its tip pasted over the name; it opens with the name
            cell = cell.split()[0]
        q = re.search(r"\(([^)]*)\)", cell)
        qual = q.group(1) if q else ""
        base = re.sub(r"\([^)]*\)", "", cell).split("|")[0]  # "Tahm Kench | TK (Top)"
        name = by_key.get(squash(base))
        if name is None:
            missed.append(r[0])
            continue
        items, levels, tips = r[1], r[2], r[3]
        if not (items or levels or tips):
            continue
        out.setdefault(name, []).append({
            "role": ROLES.get(qual.lower()), "label": cell, "items": items, "levels": levels,
            "tips": tips, "oldItems": bool(re.search(r"\bmythic\b", items + " " + tips, re.I))})
    return out, missed


def demo() -> None:
    champs = ["Aatrox", "Akali", "Nunu & Willump", "Kai'Sa"]
    rows = [["Champion", "Notable", "Level", "Tips"], ["Akali (Mid)", "Mythic", "3 / 6", "x"],
            ["Kaisa", "Kraken", "6", "y"], ["Nunu", "", "", ""], ["Nobody", "a", "b", "c"],
            ["Aatrox | Box (Top)", "a", "1", "z"], ["Akali goes in and out of shroud a lot early.", "b", "2", "Akali goes in."]]
    got, missed = parse(rows, champs)
    assert got["Aatrox"][0]["role"] == "top" and got["Akali"][1]["label"] == "Akali", got
    assert got["Akali"][0]["role"] == "mid" and got["Akali"][0]["oldItems"], got
    assert got["Kai'Sa"][0]["role"] is None and not got["Kai'Sa"][0]["oldItems"], got
    assert "Nunu & Willump" not in got and missed == ["Nobody"], (got, missed)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    demo()
    champs = [c["n"] for c in json.loads(CATALOG.read_text(encoding="utf-8"))["champs"]]
    stats = tab("Stats")
    spikes, missed = parse(stats, champs)
    intro = [r[0].strip() for r in tab("Before You Read") if r and r[0].strip()]
    n = sum(len(v) for v in spikes.values())
    print(f"{n} rows over {len(spikes)} champions; unmatched: {missed or 'none'}")
    if n < MIN_ROWS or missed:
        print(f"refusing to write: need >= {MIN_ROWS} rows and every name matched", file=sys.stderr)
        return 1
    if AUTHORED.exists():
        extra = json.loads(AUTHORED.read_text(encoding="utf-8"))["champions"]
        bad = sorted(set(extra) - set(champs))
        if bad:
            print(f"refusing to write: authored rows name no catalog champion: {bad}", file=sys.stderr)
            return 1
        for name, rows in extra.items():
            if name not in spikes:  # the sheet wins once it covers a champion
                spikes[name] = [r | {"authored": True, "oldItems": False} for r in rows]
        print(f"authored rows merged for {sum(1 for n in extra if spikes[n][0].get('authored'))} champions")
    if a.check:
        return 0
    doc = {"source": URL, "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "intro": intro, "champions": spikes}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, OUT)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

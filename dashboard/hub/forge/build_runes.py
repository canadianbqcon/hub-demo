#!/usr/bin/env python3
"""Fetch the rune tree from Data Dragon into frontend/static/runes.json.

The bake stores rune ids only. This is the lookup that turns 8010 into
"Conqueror" with its tree, its row, and an icon URL. Self-hosted pages can hit
ddragon directly, so icons stay as URLs instead of megabytes of base64.

    python3 build_runes.py
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

DDRAGON = "https://ddragon.leagueoflegends.com"
IMG = f"{DDRAGON}/cdn/img/"

# Stat shards are not in runesReforged.json — Riot ships them nowhere on Data
# Dragon — so they come from Community Dragon's perks.json, which carries every
# perk including the seven shards with the client's own names, icon paths and
# descriptions. That file is also where the rune tooltips come from, since Data
# Dragon's shortDesc is a summary and the hover wants the real text.
#
# Do NOT hand-transcribe the shard icons back in. The two health icons are
# crossed against their own filenames: StatModsHealthPlusIcon.png draws a heart
# with an arrow rising off it and belongs to 5001 Health SCALING, while
# StatModsHealthScalingIcon.png draws a bare heart and belongs to 5011 Health.
# Riot's filenames lie, Community Dragon's id→path mapping does not, and reading
# the mapping instead of the name is what keeps the picker matching the client.
CDRAGON = ("https://raw.communitydragon.org/latest/plugins/"
           "rcp-be-lol-game-data/global/default/v1/perks.json")

SHARD_IDS = (5008, 5005, 5007, 5001, 5011, 5013, 5010)

_TAGS = re.compile(r"<[^>]+>")


def clean(text: str) -> str:
    """Riot's description markup down to plain text, with the breaks kept."""
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    return _TAGS.sub("", text).replace(" ", " ").strip()


def fetch(url: str):
    # Community Dragon 403s the default urllib agent; Data Dragon does not care.
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    versions = fetch(f"{DDRAGON}/api/versions.json")
    ver = versions[0]
    trees = fetch(f"{DDRAGON}/cdn/{ver}/data/en_US/runesReforged.json")
    cdragon = {p["id"]: p for p in fetch(CDRAGON)}

    runes: dict[str, dict] = {}
    tree_meta: dict[str, dict] = {}

    for tree in trees:
        tree_meta[str(tree["id"])] = {
            "name": tree["name"],
            "key": tree["key"],
            "icon": IMG + tree["icon"],
        }
        for row_no, row in enumerate(tree["slots"]):
            for rune in row["runes"]:
                cd = cdragon.get(rune["id"], {})
                runes[str(rune["id"])] = {
                    "name": rune["name"],
                    "tree": tree["id"],
                    # row 0 is the keystone row; 1..3 are the minor rows
                    "row": row_no,
                    "icon": IMG + rune["icon"],
                    "short": clean(rune["shortDesc"]),
                    # what the rune actually does, for the hover. Community
                    # Dragon's longDesc is the client's own text with the numbers
                    # in it; Data Dragon's shortDesc is a one-line paraphrase.
                    "long": clean(cd.get("longDesc") or rune.get("longDesc") or ""),
                }

    for rid in SHARD_IDS:
        cd = cdragon.get(rid)
        if not cd:
            print(f"  ! shard {rid} missing from Community Dragon", file=sys.stderr)
            continue
        # ".../v1/perk-images/StatMods/X.png" -> ddragon's "perk-images/StatMods/X.png"
        path = cd["iconPath"].split("/v1/", 1)[-1].lstrip("/")
        runes[str(rid)] = {
            "name": cd["name"], "tree": 0, "row": 4,
            "icon": IMG + path,
            "short": clean(cd.get("shortDesc") or ""),
            "long": clean(cd.get("longDesc") or ""),
        }

    out = {"version": ver, "trees": tree_meta, "runes": runes}
    dest = Path(__file__).parent / "frontend" / "static" / "runes.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")

    keystones = sum(1 for r in runes.values() if r["row"] == 0 and r["tree"])
    print(f"{dest} — ddragon {ver}, {len(runes)} runes ({keystones} keystones), "
          f"{len(tree_meta)} trees")
    return 0


if __name__ == "__main__":
    sys.exit(main())

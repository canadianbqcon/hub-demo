"""Bake the ranked Summoner's Rift item shop into frontend/static/catalog.json.

Ranked-SR-only pool. Data Dragon's map flags are not trustworthy on their own, so the
cull is five rules, each corroborated against lolalytics (whose data IS ranked SR):

  1. map 11, purchasable, in store.
  2. four-digit IDs only. The 6-digit map-11 IDs are two families ranked SR never sees:
     `32xxxx`/`66xxxx` rebalanced twins of real items (same name, different gold and
     stats), and 13 Arena-only items with no SR twin (Atma's Reckoning, Zephyr...).
     Checked: lolalytics references 4-digit IDs exclusively, 0 six-digit.
  3. surviving same-name pairs keep the entry available on the most maps, lowest ID as
     tiebreak. Resolves the jungle pets to 1101/1102/1103.
  4. champion-granted items are dropped: requiredChampion set AND 0 gold means the game
     hands it to you, so there is nothing to put in a set (Scarecrow Effigy, and both
     Kalista's Black Spears, which are one name over two entries for Kalista and Sylas).
  5. BLOCKED, below: items Riot flags map 11 that ranked SR does not sell. Verified
     absent across 20 lolalytics champion pages. Absence there is corroboration, not the
     rule on its own, since lolalytics also omits trinkets, basic boots and elixirs that
     ARE real SR items.

Icons are downscaled and re-encoded to WebP because the artifact CSP blocks the CDN,
so every pixel has to ship inside the page.
"""
import base64
import io
import json
import os
import re
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

# Writes the Forge's catalog directly. The copy this was lifted from lives in
# Downloads/lol-item-set-forge and still writes baked.json for the standalone
# artifact build -- that one is left alone; this one exists so the scheduled
# forge-rebake job can bake the item shop itself instead of reporting that it
# could not. Keep the two in sync by hand if the artifact build is ever revived.
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "frontend", "static", "catalog.json")
DD = "https://ddragon.leagueoflegends.com"
ITEM_PX, QUALITY = 48, 82

BLOCKED = {
    "2051": "Guardian's Horn — ARAM starter, not sold on the Rift",
    "3112": "Guardian's Orb — ARAM starter, not sold on the Rift",
    "3177": "Guardian's Blade — ARAM starter, not sold on the Rift",
    "3184": "Guardian's Hammer — ARAM starter, not sold on the Rift",
    "2141": "Cappa Juice — ARAM consumable",
}

# Shelving is NOT baked here. It reads only `tags`, `from` and `into`, all of which ship in
# this blob, so it lives in template.html and a reclassification costs no icon re-download.
# It used to live here and keyed on Riot's `depth`, which is not the shop's tier: that filed
# Infinity Edge and Rabadon's as components and Gunmetal Greaves as a legendary.

TAG_RE = re.compile(r"<[^>]+>")
BR_RE = re.compile(r"<br\s*/?>", re.I)
HEAD_RE = re.compile(r"<(passive|active)>(.*?)</\1>", re.I | re.S)
STATS_RE = re.compile(r"<stats>(.*?)</stats>", re.I | re.S)
SPELL = {"FlatPhysicalDamageMod": "Attack Damage", "FlatMagicDamageMod": "Ability Power",
         "FlatHPPoolMod": "Health", "FlatMPPoolMod": "Mana", "FlatArmorMod": "Armor",
         "FlatSpellBlockMod": "Magic Resist", "FlatCritChanceMod": "Crit Chance",
         "PercentAttackSpeedMod": "Attack Speed", "PercentMovementSpeedMod": "Move Speed",
         "FlatMovementSpeedMod": "Move Speed", "PercentLifeStealMod": "Life Steal",
         "FlatHPRegenMod": "Health Regen"}


def clean(s):
    return TAG_RE.sub("", BR_RE.sub("\n", s)).replace(" ", " ").strip()


def parse_desc(d):
    """-> (stat lines, [{h: heading, t: body}])"""
    html = d.get("description") or ""
    m = STATS_RE.search(html)
    stat_src, rest = (m.group(1), html[m.end():]) if m else ("", html)
    stats = [ln.strip() for ln in clean(stat_src).split("\n") if ln.strip()]
    if not stats:  # some entries ship an empty <stats>; rebuild from the numeric block
        stats = [
            f"{round(val * 100) if k.startswith('Percent') else round(val)}"
            f"{'%' if k.startswith('Percent') else ''} {SPELL[k]}"
            for k, val in (d.get("stats") or {}).items() if k in SPELL and val
        ]
    parts = HEAD_RE.sub(lambda mm: "\x00" + mm.group(2).strip() + "\x00", rest).split("\x00")
    blocks, lead = [], clean(parts[0])
    if lead:
        blocks.append({"h": "", "t": lead})
    for i in range(1, len(parts) - 1, 2):
        body = clean(parts[i + 1])
        blocks.append({"h": clean(parts[i]), "t": body})
    return stats, [b for b in blocks if b["h"] or b["t"]]


def get_json(url):
    return json.load(urllib.request.urlopen(url))


def icon(url, px):
    im = Image.open(io.BytesIO(urllib.request.urlopen(url).read())).convert("RGB")
    buf = io.BytesIO()
    im.resize((px, px), Image.Resampling.LANCZOS).save(buf, "WEBP", quality=QUALITY, method=6)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


ver = get_json(f"{DD}/api/versions.json")[0]
items_raw = get_json(f"{DD}/cdn/{ver}/data/en_US/item.json")["data"]
champs_raw = get_json(f"{DD}/cdn/{ver}/data/en_US/champion.json")["data"]

pool = {
    iid: d for iid, d in items_raw.items()
    if d.get("maps", {}).get("11")
    and d["gold"].get("purchasable") is not False
    and d.get("inStore") is not False
    and re.fullmatch(r"\d{4}", iid)
    and iid not in BLOCKED
    and not (d.get("requiredChampion") and d["gold"]["total"] == 0)
}

by_name = defaultdict(list)
for iid, d in pool.items():
    by_name[d["name"]].append(iid)
culled = []
for ids in by_name.values():
    if len(ids) < 2:
        continue
    keep = min(ids, key=lambda i: (-sum(bool(v) for v in pool[i].get("maps", {}).values()), int(i)))
    for loser in [i for i in ids if i != keep]:
        culled.append(f"{loser} {pool[loser]['name']}->{keep}")
        del pool[loser]

items = []
for iid, d in pool.items():
    stats, blocks = parse_desc(d)
    items.append({
        "id": iid, "n": d["name"], "g": d["gold"]["total"], "t": d.get("tags", []),
        "st": stats, "ps": blocks,
        "p": (d.get("plaintext") or "").strip(),
        # build path, pruned to items the ranked shop actually sells so the tree
        # never points at an ARAM or Arena node that has no icon in this page
        "f": [c for c in d.get("from", []) if c in pool],
        "to": [c for c in d.get("into", []) if c in pool],
    })
items.sort(key=lambda i: (i["g"], i["n"]))

# "c" is Data Dragon's class tags (Fighter, Tank, Mage...): the draft engine's fallback
# for a role OP.GG's lane meta lists no share for (draft_engine.likely_roles).
champs = sorted(({"k": int(c["key"]), "n": c["name"], "i": c["id"], "c": c.get("tags", [])}
                 for c in champs_raw.values()),
                key=lambda c: c["n"])

with ThreadPoolExecutor(16) as ex:
    for i, u in zip(items, ex.map(lambda i: icon(f"{DD}/cdn/{ver}/img/item/{i['id']}.png", ITEM_PX), items),
                    strict=True):
        i["u"] = u
# Champion portraits are a URL, not a payload. They were baked at 32x32 and the
# Forge draws them at 62px on a landing card and 72px on the champion page, so
# every one of them was upscaled to mush. Data Dragon serves the same art at
# 128x128 off its own CDN, which is where runes.json already points, so pointing
# at it costs nothing, is sharp at both sizes, and takes ~128 KB back out of the
# catalog. Item icons stay baked: they are drawn at 46-48px, which is exactly
# what they are baked at, and there are 200 of them.
for c in champs:
    c["u"] = f"{DD}/cdn/{ver}/img/champion/{c['i']}.png"

# flat stat-tag list: no parent grouping, because tags like OnHit legitimately span
# physical and magic items and burying them under one parent hides half the answer
tags = sorted(({"t": t, "n": sum(1 for i in items if t in i["t"])}
               for t in {t for i in items for t in i["t"]}),
              key=lambda x: (-x["n"], x["t"]))

blob = {"ver": ver, "tags": tags, "items": items, "champs": champs}
with open(OUT, "w") as f:
    json.dump(blob, f, separators=(",", ":"))

size = os.path.getsize(OUT)
assert len({i["n"] for i in items}) == len(items), "a duplicate name survived"
assert all(re.fullmatch(r"\d{4}", i["id"]) for i in items), "a non-four-digit id survived"
assert not (BLOCKED.keys() & {i["id"] for i in items}), "a blocked item survived"
assert all(i["u"].startswith("data:image/webp") for i in items), "an item icon failed to encode"
assert all(c["u"].startswith("https://") for c in champs), "a portrait lost its URL"
assert sum(1 for i in items if i["st"] or i["ps"]) > len(items) * 0.9, "most items should have stats or a passive"
ids = {i["id"] for i in items}
assert all(set(i["f"]) <= ids and set(i["to"]) <= ids for i in items), "build path points outside the shop"
assert sum(1 for i in items if i["f"]) > 80, "most legendaries and epics should have components"
assert size < 12_000_000, f"payload {size} near the 16MB artifact ceiling"
print(f"patch {ver}: {len(items)} ranked-SR items, {len(champs)} champions -> {size/1e6:.2f} MB")
print("culled dupes:", ", ".join(culled) or "none")
print("blocked:", ", ".join(BLOCKED.values()))
print("no stats and no passive:", [i["n"] for i in items if not i["st"] and not i["ps"]] or "none")
print("with components:", sum(1 for i in items if i["f"]), "| that build into something:", sum(1 for i in items if i["to"]))

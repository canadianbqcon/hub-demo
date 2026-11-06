#!/usr/bin/env python3
"""Build data/forge-patch-diff.json: what changed for the pool champions, and
what changed on the items they build.

**Riot's own notes are the source for items; Data Dragon is the fallback.** The
older version of this file read ddragon alone, and that cannot work: Riot
templates the passive numbers out of its item descriptions, so Sterak's Gage
reads "Gain  bonus Attack Damage" with the number simply absent, byte-identical
across 16.15.1 and 16.16.1. Eclipse and Sterak's both changed in 26.16 and a
ddragon diff saw nothing at all; across the whole patch Riot listed 18 item
changes and the diff found 12, three of which carried no number. So
notes_items() reads what bake_patchnotes.py already baked, and diff_items()
covers only what Riot did not write up (a tier-three boot folded into its
tier-two entry, say). Champions are still ddragon-only.

The keep-set is the shop's own catalog — every item the tool will show you.
It used to be narrower: only items a pool champion actually BUYS, read off the
coachless bake. That hid a change to an item you were about to consider on the
grounds that nobody had bought it yet, which is backwards for a strip whose job
is "did anything under my figures move". The catalog is still a filter, because
Data Dragon carries Ornn upgrades, dead ids and modes this tool has no shelf for
— and, since the strip is now icon-only, an entry with no icon is not renderable.

    python3 build_diff.py              # newest patch vs the one before it
    python3 build_diff.py 16.14.1 16.16.1
"""

from __future__ import annotations

import difflib
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

DDRAGON = "https://ddragon.leagueoflegends.com"

# Champion fields worth reporting. Riot's blob carries render junk too.
CHAMP_STATS = {
    "hp": "base health", "hpperlevel": "health per level",
    "mp": "base mana", "mpperlevel": "mana per level",
    "armor": "armor", "armorperlevel": "armor per level",
    "spellblock": "magic resist", "spellblockperlevel": "magic resist per level",
    "attackdamage": "attack damage", "attackdamageperlevel": "attack damage per level",
    "attackspeed": "attack speed", "attackspeedperlevel": "attack speed per level",
    "hpregen": "health regen", "mpregen": "mana regen",
    "movespeed": "move speed", "crit": "crit", "attackrange": "attack range",
}


def fetch(url: str):
    with urllib.request.urlopen(url, timeout=45) as resp:
        return json.loads(resp.read().decode())


def versions() -> list[str]:
    return fetch(f"{DDRAGON}/api/versions.json")


def blob(ver: str, what: str) -> dict:
    return fetch(f"{DDRAGON}/cdn/{ver}/data/en_US/{what}.json")["data"]


def num(v):
    return v if isinstance(v, (int, float)) else None


# Every Data Dragon item stat is "more is better". Gold is the one that inverts:
# a cost going UP is a nerf. Riot's own notes name the same things in words, so
# the check is on the label: a recipe, a price and a cooldown all read backwards.
LOWER_IS_BETTER = ("cost", "recipe", "gold", "price", "cooldown")


def inverted(field: str) -> bool:
    return any(w in field.lower() for w in LOWER_IS_BETTER)


# "45% of Base Attack Damage" -> the number, and everything after it
VALUE = re.compile(r"^([\d.]+)(.*)$")


def measured(row: dict):
    """The (before, after) pair when a row is exactly one number moving.

    Riot writes its notes as prose values, so a row only counts when the two
    sides differ by their leading number and nothing else: `45% of Base Attack
    Damage` -> `50% of Base Attack Damage` is one number, and `20 for 2s` ->
    `[20 Melee || 10 Ranged] for 2s` is a restructure that no single number
    describes. Returns None for the second kind."""
    before, after = row.get("from"), row.get("to")
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return before, after
    if not isinstance(before, str) or not isinstance(after, str):
        return None
    was, now = VALUE.match(before.strip()), VALUE.match(after.strip())
    if was and now and was.group(2) == now.group(2):
        return float(was.group(1)), float(now.group(1))
    return None


def verdict(entry: dict) -> str:
    """buff / nerf / rework for one item entry.

    Two rules, and the second one only became right when Riot's notes became the
    source:

    1. **Measured deltas decide.** All agreeing gives a direction, a disagreement
       is a rework.
    2. **A row we cannot measure forces a rework**, because on the notes path an
       unmeasurable row is a change Riot deliberately wrote down — Sundered Sky
       took Health 400 → 450 alongside a healing cut and a recipe strip, and
       voting on the health alone published a nerfed item as a buff. The one
       exception is a `text` row from the ddragon fallback, which is skipped
       rather than counted: Riot rewrites a tooltip alongside essentially every
       stat change, so on that path it is noise rather than a listed change.

    Added and removed items are reworks by definition, having no before or after
    to compare.
    """
    seen, unquantified = set(), False
    for c in entry.get("changes") or []:
        if c.get("text"):
            continue          # a rewritten tooltip line carries no direction
        pair = measured(c)
        if pair is None:
            unquantified = True
            continue
        before, after = pair
        if before == after:
            continue
        up = after > before
        seen.add("nerf" if up == inverted(c.get("field", "")) else "buff")
    if unquantified or len(seen) != 1:
        return "rework"
    return seen.pop()


TAG = re.compile(r"<[^>]+>")
# "45 Attack Damage", "8% Magic Penetration" — a figure Riot prints as a line
FIGURE = re.compile(r"^([\d.]+)(%?)\s+(.+)$")


def _lines(desc: str) -> list[str]:
    """The description as the tooltip reads it: one line per <br>, tags gone."""
    text = TAG.sub("", re.sub(r"<br\s*/?>", "\n", desc or ""))
    return [x for x in (html.unescape(ln).strip() for ln in text.split("\n")) if x]


def _n(s: str):
    v = float(s)
    return int(v) if v == int(v) else v


def _row(before: str | None, after: str | None) -> dict:
    """One changed line. A "<number> <label>" pair whose label held still is a real
    figure and gets reported as one; anything else is the sentence, before and
    after, which is still the change rather than a note saying there was one."""
    if before and after:
        was, now = FIGURE.match(before), FIGURE.match(after)
        if was and now and was.group(3) == now.group(3) and was.group(2) == now.group(2):
            row = {"field": was.group(3), "from": _n(was.group(1)), "to": _n(now.group(1))}
            return dict(row, unit="%") if was.group(2) else row
    return {"field": "effect", "text": True, "from": before, "to": after}


def desc_changes(before: str, after: str) -> list[dict]:
    """Diff the two descriptions line by line.

    This is where the numbers actually live. Riot's `stats` dict is a subset of
    what the tooltip prints — magic penetration is not in it at all, so
    Spellslinger's Shoes going 18 -> 20 showed up as "the text moved, we cannot
    say how" — and the dict spells its values in engine units (0.3) under engine
    keys (PercentAttackSpeedMod) where the description already says "30% Attack
    Speed". So the description is the source and the dict is the fallback."""
    a, b = _lines(before), _lines(after)
    rows = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            continue
        was, now = a[i1:i2], b[j1:j2]
        for k in range(max(len(was), len(now))):
            rows.append(_row(was[k] if k < len(was) else None,
                             now[k] if k < len(now) else None))
    return rows


def _figures(rows: list[dict]) -> set[tuple]:
    """The number pairs already reported, so the dict fallback does not say the
    same thing twice in engine units (0.25 -> 0.3 beside 25% -> 30%)."""
    seen = set()
    for r in rows:
        was, now = num(r.get("from")), num(r.get("to"))
        if was is None or now is None:
            continue
        seen.add((was, now))
        if r.get("unit") == "%":
            seen.add((was / 100, now / 100))
    return seen


def diff_items(old: dict, new: dict, keep: set[str]) -> list[dict]:
    out = []
    for iid, now in new.items():
        if keep and iid not in keep:
            continue
        was = old.get(iid)
        if was is None:
            out.append({"id": iid, "name": now.get("name", iid), "kind": "added",
                        "changes": [], "verdict": "rework"})
            continue
        changes = []
        if num(was.get("gold", {}).get("total")) != num(now.get("gold", {}).get("total")):
            changes.append({"field": "cost", "from": was["gold"]["total"], "to": now["gold"]["total"]})
        changes += desc_changes(was.get("description"), now.get("description"))
        # anything the tooltip never printed still counts, in its engine spelling
        seen = _figures(changes)
        for stat, after in (now.get("stats") or {}).items():
            before = (was.get("stats") or {}).get(stat)
            if num(before) != num(after) and (num(before), num(after)) not in seen:
                changes.append({"field": stat, "from": before, "to": after})
        if changes:
            entry = {"id": iid, "name": now.get("name", iid), "kind": "changed",
                     "changes": changes}
            out.append(dict(entry, verdict=verdict(entry)))
    for iid, was in old.items():
        if (keep and iid not in keep) or iid in new:
            continue
        out.append({"id": iid, "name": was.get("name", iid), "kind": "removed",
                    "changes": [], "verdict": "rework"})
    return sorted(out, key=lambda d: d["name"])


# Riot writes an item's name the way the designers say it, which is not always
# the name the game ships. Anything unmatched is printed loudly rather than
# dropped, because a silent miss is how an item goes missing from the strip.
NOTE_ALIASES = {"Sunfire Cape": "Sunfire Aegis"}


def _loose(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def notes_items(new_v: str, by_name: dict[str, str]) -> dict[str, dict]:
    """Riot's own item changes for `new_v`, keyed by catalog id.

    This is the source, and the Data Dragon diff below is the fallback. Riot
    templates the passive numbers out of ddragon — Sterak's Gage reads "Gain
    bonus Attack Damage" with the number simply absent, identically on both
    patches — so anything tuned inside a passive is invisible to a diff no matter
    how well it is parsed. Eclipse and Sterak's changed in 26.16 and showed zero
    difference. bake_patchnotes.py already reads the changelog Riot publishes;
    this reads what it baked."""
    path = vault_root() / "data" / "forge-patch-notes.json"
    try:
        notes = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("  ! no baked patch notes — run bake_patchnotes.py", file=sys.stderr)
        return {}
    # The notes describe ONE patch. Reading them onto any other comparison would
    # attribute Riot's changes to the wrong pair of versions.
    if notes.get("ddragon") != new_v:
        print(f"  ! notes are for {notes.get('ddragon')}, diffing to {new_v}"
              " — falling back to Data Dragon alone", file=sys.stderr)
        return {}
    section = next((s for s in notes.get("sections", [])
                    if s.get("name") == "Items"), None)
    out = {}
    loose = {_loose(k): v for k, v in by_name.items()}
    for entry in (section or {}).get("entries", []):
        raw_name = entry.get("name")
        if not isinstance(raw_name, str):
            print(f"  ! malformed patch note entry (no name): {entry}", file=sys.stderr)
            continue
        name = NOTE_ALIASES.get(raw_name, raw_name)
        # spacing and case drift too ("Bastion Breaker" vs the shipped "Bastionbreaker")
        iid = by_name.get(name) or loose.get(_loose(name))
        if iid is None:
            print(f"  ! {raw_name}: no catalog item by that name", file=sys.stderr)
            continue
        # a prose bullet ({"field", "line"}) is an addition, as in the champion rows
        rows = [{"field": c["field"], "from": c.get("from"), "to": c.get("to", c.get("line"))}
                for g in entry.get("groups", []) for c in g.get("changes", [])
                if "from" in c or c.get("line")]
        if not rows:
            continue
        item = {"id": iid, "name": name, "kind": "changed", "changes": rows,
                "source": "notes"}
        if entry.get("context"):
            item["why"] = entry["context"]
        out[iid] = dict(item, verdict=verdict(item))
    return out


# "Q - Conquering Sands" -> "Q". Riot's group headings are the ability they
# belong to, and the label column of the card is narrow.
SPELL_TAG = re.compile(r"^([QWERP])\s*[-\u2013]\s")


def _tag(group: str) -> str:
    if not group:
        return ""
    hit = SPELL_TAG.match(group.strip())
    if hit:
        return hit.group(1)
    return "base" if group.strip().lower() == "base stats" else group.strip()


def _champ_note_rows(entry: dict) -> list[dict]:
    """The change rows for one champion's notes entry, tagged with the ability
    (or "base") each group belongs to."""
    rows = []
    for group in entry.get("groups", []):
        tag = _tag(group.get("name") or "")
        for c in group.get("changes", []):
            field = f"{tag} {c['field']}".strip() if tag else c["field"]
            if "from" in c:
                rows.append({"field": field, "from": c["from"], "to": c["to"]})
            elif c.get("line"):
                # Riot's "NEW" shape: an addition, with nothing before it
                rows.append({"field": field, "from": None, "to": c["line"]})
    return rows


def notes_champs(new_v: str, pool) -> dict[str, dict]:
    """Riot's own champion changes for `new_v`, for the pool only.

    Same source and same reason as notes_items(): ddragon carries a champion's
    base stats and its spell cooldowns, and nothing else. An ability's damage,
    its ratios and every number inside a passive live in a tooltip template that
    reads the same on both patches, so a diff of it is silent."""
    path = vault_root() / "data" / "forge-patch-notes.json"
    try:
        notes = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if notes.get("ddragon") != new_v:
        return {}          # notes_items() already said why, once is enough
    section = next((s for s in notes.get("sections", [])
                    if s.get("name") == "Champions"), None)
    out = {}
    for entry in (section or {}).get("entries", []):
        if entry["name"] not in pool:
            continue
        rows = _champ_note_rows(entry)
        if not rows:
            continue
        champ = {"name": entry["name"], "kind": "changed", "changes": rows,
                 "source": "notes"}
        if entry.get("context"):
            champ["why"] = entry["context"]
        out[entry["name"]] = dict(champ, verdict=verdict(champ))
    return out


def diff_champ(old: dict, new: dict) -> list[dict]:
    changes = []
    for stat, label in CHAMP_STATS.items():
        before, after = (old.get("stats") or {}).get(stat), (new.get("stats") or {}).get(stat)
        if num(before) != num(after):
            changes.append({"field": label, "from": before, "to": after})
    for i, spell in enumerate(new.get("spells") or []):
        was = (old.get("spells") or [])[i] if i < len(old.get("spells") or []) else None
        key = "QWER"[i] if i < 4 else f"spell {i}"
        if was is None:
            continue
        if was.get("cooldownBurn") != spell.get("cooldownBurn"):
            changes.append({"field": f"{key} cooldown", "from": was["cooldownBurn"],
                            "to": spell["cooldownBurn"]})
        if was.get("costBurn") != spell.get("costBurn"):
            changes.append({"field": f"{key} cost", "from": was["costBurn"], "to": spell["costBurn"]})
        # the tooltip is the same HTML idiom as an item description, so it reads
        # the same way — a figure where a labelled number moved, the sentence
        # otherwise. It used to be a flag with no before and no after, which the
        # card then dropped for having nothing in it.
        for row in desc_changes(was.get("tooltip"), spell.get("tooltip")):
            changes.append(dict(row, field=f"{key} {row['field']}"))
    for row in desc_changes((old.get("passive") or {}).get("description") or "",
                            (new.get("passive") or {}).get("description") or ""):
        changes.append(dict(row, field=f"passive {row['field']}"))
    return changes


def main() -> int:
    vers = versions()
    if len(sys.argv) == 3:
        old_v, new_v = sys.argv[1], sys.argv[2]
    else:
        new_v, old_v = vers[0], vers[1]
    print(f"diffing {old_v} -> {new_v}")

    stats_path = vault_root() / "data" / "forge-stats.json"
    try:
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(
            "run bake_stats.py first — the champion pool comes from it") from exc

    pool = stats.get("champions", {})
    # Every item the shop will show, not only the ones somebody has bought.
    cat = json.loads((Path(__file__).parent / "frontend" / "static" / "catalog.json")
                     .read_text(encoding="utf-8"))
    relevant = {str(i["id"]) for i in cat.get("items", [])}
    by_name = {i["n"]: str(i["id"]) for i in cat.get("items", [])}
    print(f"  {len(pool)} champions, {len(relevant)} items in the catalog")

    from_notes = notes_items(new_v, by_name)
    old_items, new_items = blob(old_v, "item"), blob(new_v, "item")
    # Riot's write-up is complete for an item it covers, so the ddragon reading of
    # that item is dropped whole rather than merged — the two spell the same change
    # differently (a recipe step against a total gold cost) and both would show.
    item_changes = sorted(
        list(from_notes.values())
        + [e for e in diff_items(old_items, new_items, relevant)
           if e["id"] not in from_notes],
        key=lambda d: d["name"])
    print(f"  {len(from_notes)} items from Riot's notes, "
          f"{len(item_changes) - len(from_notes)} from Data Dragon alone")

    champ_notes = notes_champs(new_v, pool)
    champ_changes = {}
    # ddragon files are keyed by the champion KEY ("MasterYi"), not the display
    # name ("Master Yi") the pool stores; the list blob is the only mapping.
    keys = {c["name"]: cid for cid, c in blob(new_v, "champion").items()}
    for name in pool:
        if name in champ_notes:
            champ_changes[name] = champ_notes[name]
            print(f"  {name:10} {len(champ_notes[name]['changes'])} changes (notes)")
            continue
        cid = keys.get(name, name)
        try:
            was = blob(old_v, f"champion/{cid}")[cid]
            now = blob(new_v, f"champion/{cid}")[cid]
        except Exception as exc:
            print(f"  ! {name}: {exc}", file=sys.stderr)
            continue
        rows = diff_champ(was, now)
        print(f"  {name:10} {len(rows)} changes")
        if not rows:
            continue          # an unchanged champion is not an entry
        champ = {"name": name, "kind": "changed", "changes": rows, "source": "ddragon"}
        champ_changes[name] = dict(champ, verdict=verdict(champ))

    out = {"from": old_v, "to": new_v, "items": item_changes, "champions": champ_changes}
    dest = vault_root() / "data" / "forge-patch-diff.json"
    dest.write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"\n{dest} — {len(item_changes)} item changes")
    return 0


def demo() -> None:
    """Self-check: the description reader and the vote that reads it are the two
    things here that fail quietly — a bad parse just shows fewer numbers, and a bad
    vote flattens the whole strip to one colour, neither of them loudly."""
    text = {"field": "effect", "text": True,
            "from": "Deals damage.", "to": "Deals more damage."}
    assert verdict({"changes": [{"field": "FlatPhysicalDamageMod", "from": 40, "to": 45},
                                text]}) == "buff", "a tooltip rewrite rides along with every stat change"
    assert verdict({"changes": [{"field": "FlatSpellBlockMod", "from": 30, "to": 25},
                                text]}) == "nerf"
    # gold inverts: paying more for the same item is a nerf
    assert verdict({"changes": [{"field": "cost", "from": 2700, "to": 2800}]}) == "nerf"
    assert verdict({"changes": [{"field": "cost", "from": 2800, "to": 2700}]}) == "buff"
    # power moved sideways, and text-only is unquantified — both are rework
    assert verdict({"changes": [{"field": "FlatHPPoolMod", "from": 400, "to": 450},
                                {"field": "cost", "from": 2700, "to": 2800}]}) == "rework"
    assert verdict({"changes": [text]}) == "rework"
    assert verdict({"changes": []}) == "rework"
    # a field that did not actually move must not vote
    assert verdict({"changes": [{"field": "FlatArmorMod", "from": 30, "to": 30},
                                {"field": "FlatHPPoolMod", "from": 400, "to": 450}]}) == "buff"
    # a figure Riot prints as its own line inverts on cooldown, same as gold
    assert verdict({"changes": [{"field": "second Cooldown", "from": 10, "to": 8}]}) == "buff"

    # ── Riot's notes: prose values, and the rows that cannot be read ──────────
    # one number moving with the tail held still is measured, either side of a unit
    assert measured({"from": "45% of Base Attack Damage",
                     "to": "50% of Base Attack Damage"}) == (45, 50)
    assert measured({"from": "18 + 8%", "to": "20 + 8%"}) == (18, 20)
    # a restructure is not one number moving, whatever numbers are in it
    assert measured({"from": "20 for 2s", "to": "[20 Melee || 10 Ranged] for 2s"}) is None
    assert measured({"from": "20 (+1% bonus Health)",
                     "to": "20 (+1.5% bonus Health)"}) is None
    # THE rule this file exists for: an unreadable row outvotes a clean buff, or
    # Sundered Sky publishes as a buff on its health line while its healing is cut
    assert verdict({"changes": [
        {"field": "Health", "from": "400", "to": "450"},
        {"field": "Healing", "from": "[100% Melee || 50% Ranged] + 6% Missing Health",
         "to": "[90% Melee || 45% Ranged] + 4% Missing Health"}]}) == "rework"
    assert verdict({"changes": [{"field": "Health", "from": "400", "to": "450"}]}) == "buff"
    # a recipe reads backwards, same as a cost: paying more is a nerf
    assert verdict({"changes": [{"field": "Recipe", "from": "600g", "to": "700g"}]}) == "nerf"

    # the reader: a held-still label is a figure, a rewritten clause is the sentence
    stats = ("<mainText><stats><attention>%s</attention> Attack Damage<br>"
             "<attention>8%%</attention> Magic Penetration</stats><br>"
             "<passive>Carve</passive><br>%s</mainText>")
    rows = desc_changes(stats % (40, "Slows the target."), stats % (45, "Roots the target."))
    assert {"field": "Attack Damage", "from": 40, "to": 45} in rows, rows
    assert {"field": "effect", "text": True, "from": "Slows the target.",
            "to": "Roots the target."} in rows, rows
    # the percent figure held still, so it is not a change at all
    assert not any(r["field"] == "Magic Penetration" for r in rows), rows
    # ...and when it does move, the unit rides along so the card can print it
    moved = desc_changes(stats % (40, "x"), (stats % (40, "x")).replace(">8%<", ">10%<"))
    assert moved == [{"field": "Magic Penetration", "from": 8, "to": 10, "unit": "%"}], moved
    # the engine-unit dict must not repeat what the tooltip already said
    assert _figures(rows) >= {(40, 45)}
    assert (0.25, 0.3) in _figures([{"field": "Attack Speed", "from": 25,
                                     "to": 30, "unit": "%"}])
    # ── the champion path ────────────────────────────────────────────────────
    assert _tag("Q - Conquering Sands") == "Q"
    assert _tag("R - Endless Banquet") == "R"
    assert _tag("Base Stats") == "base"
    assert _tag("") == ""
    # Riot's "NEW" shape has no before, and nothing without a before can be measured
    assert verdict({"changes": [{"field": "R True Form Remora Indicator",
                                 "from": None, "to": "Resource bar turns purple"}]}) == "rework"
    # a spell tooltip reads like an item description, prefixed by its letter
    spell = "Deals <physicalDamage>%s</physicalDamage> damage.<br>%s"
    rows = [dict(r, field=f"Q {r['field']}")
            for r in desc_changes(spell % ("60", "Slows for 1s."),
                                  spell % ("60", "Roots for 1s."))]
    assert rows == [{"field": "Q effect", "text": True,
                     "from": "Slows for 1s.", "to": "Roots for 1s."}], rows
    print("ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        sys.exit(main())

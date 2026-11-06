#!/usr/bin/env python3
"""Bake coachless.gg item + rune statistics into data/forge-stats.json.

Coachless publishes WPA (Win Probability Added): the delta between the model's
pre-purchase win estimate and the observed post-purchase result. That is the
number Sam actually builds around, so it is what gets baked.

Two things this script knows that are not obvious from their API:

* ``role`` is an int enum, measured against known one-role champions:
  0 top, 1 jungle, 2 mid, 3 bot, 4 support, 5 = ALL ROLES AGGREGATED.
  Role 5 is not a lane. Baking it as one would silently mix every lane's
  builds into a single list.
* The current patch is paywalled server-side (403). ``GetPatches`` lists every
  patch including the ones that 403, so the bake probes downward from newest
  until one answers 200 and uses that.

Runs in ~2 minutes per three champions. Re-run when a patch drops.

    python3 bake_stats.py            # pool, latest free patch
    python3 bake_stats.py --champ Viego
    python3 bake_stats.py --roster   # every champion-role, resumable
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
from typing import Any
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

API = "https://api.coachless.gg/api/"
HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://coachless.gg",
    # Their own site sends a literal "null" bearer. The API is unauthenticated;
    # this is not a credential and there is nothing to rotate.
    "Authorization": "Bearer null",
    "User-Agent": "Mozilla/5.0",
}

# Riot champion ids. Sam's pool.
POOL = {"Viego": 234, "Shyvana": 102, "Master Yi": 11,
        "Akali": 84, "Yone": 777, "Pyke": 555,
        "Caitlyn": 51, "Lucian": 236, "Sett": 875,
        "Shen": 98, "Kha'Zix": 121}  # Lee Sin dropped 2026-11-05 (Sam)

ROLES = {0: "top", 1: "jungle", 2: "mid", 3: "bot", 4: "support"}
TREES = {8000: "Precision", 8100: "Domination", 8200: "Sorcery",
         8300: "Inspiration", 8400: "Resolve"}

# Emerald+ — the tiers coachless' own site defaults to.
TIERS = [5, 6, 7]

# A champion/role pairing below this many recorded purchases is off-role noise
# (Shyvana "mid" returns a handful of games). Baking it invites reading a WPA
# built on 30 games as if it meant something.
MIN_OCCURRENCE = 500
_missed: list[tuple[str, int]] = []   # non-200 answers since the roster job started
_retry_after: list[int] = []   # seconds the last rate-limit 429 asked for; the roster waits it out


def call(endpoint: str, body: dict | None) -> tuple[int, Any]:
    """POST (or GET when body is None). Returns (status, parsed) — never raises."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + endpoint, data=data, headers=HEADERS,
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        wait = exc.headers.get("Retry-After") if exc.headers else None
        if exc.code == 429 and str(wait).isdigit():
            _retry_after[:] = [int(wait)]
        return exc.code, None
    except Exception as exc:  # network, JSON, timeout
        print(f"    ! {endpoint}: {exc}", file=sys.stderr)
        return 0, None


def _ask(endpoint: str, body: dict | None) -> tuple[int, Any]:
    """call() that remembers every answer that was not a 200 (a refusal, a 429 with
    or without Retry-After, a 5xx, a dead network) so a roster job can tell a failed
    follow-up from a real absence."""
    status, data = call(endpoint, body)
    if status != 200:
        _missed.append((endpoint, status))
    return status, data


def filters(champion_id: int | None, role: int | None, patch: dict) -> dict:
    return {
        "patch": patch,
        "championIds": [champion_id] if champion_id else None,
        "matchupChampionIds": None,
        "leagueTiers": TIERS,
        "regions": None,
        "role": role,
    }


def latest_free_patch() -> dict:
    """Newest patch that is not behind the premium wall."""
    status, patches = call("ChampionWinprob/GetPatches", None)
    if status != 200 or not isinstance(patches, list):
        raise SystemExit("GetPatches failed — cannot determine a patch to bake")

    def key(p):
        return (p.get("major", 0), p.get("patch", 0), p.get("patchAdditions", 0))

    for entry in sorted(patches, key=key, reverse=True):
        patch = {k: entry.get(k, 0) for k in ("major", "patch", "patchAdditions")}
        probe = {
            "commonFilters": filters(None, 5, patch),
            "itemSlots": None, "itemType": 1, "keystone": None, "starterId": None,
            "firstPurchaseId": None, "firstLegendaryId": None,
            "secondLegendaryId": None, "includeSupportItems": False,
        }
        status, body = call("ChampionWinprob/GetGlobalItemStatistics", probe)
        label = f"{patch['major']}.{patch['patch']}"
        if status == 200 and body:
            print(f"  patch {label}: open ({len(body)} items)")
            return patch
        if status in (200, 403):   # the paywall answer is a 403; a 200 with no rows has no data yet
            print(f"  patch {label}: {status}, paywalled or empty, stepping back")
            continue
        # a timeout (0), 429, 5xx: says nothing about the wall, and stepping back would
        # bake an older patch and make bake_roster drop every settled row of the newer one
        raise SystemExit(f"patch {label}: probe answered {status}, not a paywall, nothing baked and no rows dropped")
    raise SystemExit("every patch refused — nothing to bake")


def items_for(champion_id: int, role: int, patch: dict,
              keystone: int | None = None, item_type: int = 1,
              first: int | None = None, second: int | None = None,
              slots: list[int] | None = None) -> list[dict]:
    """Per-item WPA. itemSlots=None means 'any slot', which is the overview.
    ``slots``, e.g. ``[2]``, narrows to games where the item landed in that
    purchase slot specifically — confirmed live, a real filter and not the
    unused parameter it looked like (see ``items_by_slot``).

    ``keystone``, ``first`` and ``second`` send the same filters coachless' own UI
    sends: pass any and the rows come back measured under that condition only. All
    None is the unconditioned aggregate. The bake never sends the keystone with the
    items (see ``items_by_keystone``); the live endpoint in api.py sends ``first``
    and optionally ``second``, never the keystone.

    ``first`` and ``second`` are the first and second LEGENDARY, which is what
    the builder's Core block holds in its first two slots. ``firstPurchaseId`` is
    a different question — the very first thing bought — and returns zero rows for
    a legendary, so it stays null.

    Two is the ceiling and it is the API's, not a choice: ``thirdLegendaryId`` is
    accepted with a 200 and then ignored — measured on Viego jungle 16.15, the
    rows come back byte-identical to the first-only call. A third slot on the wire
    would paint a shop measured under two items while claiming three, which is
    worse than not offering it. The pair still measures: Collector into Immortal
    Shieldbow is 14 rows with 5 over the floor and a 14.3k top line, against 21/9
    for Collector alone. (The keystone cross, by contrast, was 6 rows and none
    over the floor — that is why one is served and the other is not.)

    ``starterId`` stays null forever. Conditioning on what a build opened with
    was its own axis until 2026-08-19; the pet is now an ordinary item that
    carries its own figures (itemType 6) rather than a filter you pick.
    """
    body = {
        "commonFilters": filters(champion_id, role, patch),
        "itemSlots": slots, "itemType": item_type, "keystone": keystone,
        "starterId": None,
        "firstPurchaseId": None, "firstLegendaryId": first,
        "secondLegendaryId": second, "includeSupportItems": True,
    }
    status, data = _ask("ChampionWinprob/GetGlobalItemStatistics", body)
    if status != 200 or not isinstance(data, list):
        return []
    return [
        {
            "id": it.get("itemId"),
            "wpa": it.get("wpaOverall"),
            "wpaSolo": it.get("wpaStandalone"),
            "n": it.get("occurrence"),
            "share": it.get("occurrenceRelative"),
            "wrPre": it.get("winrateExpected"),
            "wrPost": it.get("winrateObserved"),
            "buyAt": it.get("averagePurchaseTime"),
        }
        for it in data
        if it.get("itemId")
    ]


# coachless splits its item statistics into classes on one endpoint, and asking
# for one is asking for a third of the shop. 1 legendaries, 2 boots, 6 jungle
# pets — exactly {1101, 1102, 1103}, measured.
ITEM_CLASSES = (1, 2, 6)

# lolalytics' own per-slot item grid tops out at 5 across the whole pool
# (measured against forge-lolalytics.json); matched here rather than guessed
# so the two sources cover the same ground.
MAX_SLOT = 5


def item_rows(champion_id: int, role: int, patch: dict, **args) -> list[dict]:
    """``items_for`` across every item class, concatenated.

    This exists because it did not: the conditioned reads each called
    ``items_for`` once, took the itemType 1 default, and wrote lists with zero
    boots in them. The shop hides anything without a reading, boots are not in
    the Utility exemption, so picking a keystone emptied the whole Boots shelf.
    One place knows about the classes now; the callers just ask.
    """
    return [row for t in ITEM_CLASSES
            for row in items_for(champion_id, role, patch, item_type=t, **args)]


def items_by_keystone(champion_id: int, role: int, patch: dict,
                      runes: dict) -> dict[str, list[dict]]:
    """Item WPA under each keystone, keyed by keystone id.

    Same reasoning ``runes_for`` already applies to runes, carried across to the
    other half of the build: what Kraken Slayer is worth under Conqueror is not
    what Umbral Glaive is worth under Hail of Blades, and the flat list above
    averages the two into a figure that describes neither. Viego jungle on 16.15
    is the case that forced it — Umbral Glaive reads +4.54 under Hail of Blades
    and does not place at all under Conqueror.

    Gated on the same MIN_OCCURRENCE as the rune breakdown, so a keystone too
    thin to say anything about does not get a list of its own. Whatever is
    missing here falls back to the aggregate on the page.
    """
    out: dict[str, list[dict]] = {}
    for ks in runes.get("keystones", []):
        kid = ks.get("id")
        if not kid or (ks.get("n") or 0) < MIN_OCCURRENCE:
            continue
        rows = item_rows(champion_id, role, patch, keystone=kid)
        if rows:
            out[str(kid)] = rows
        time.sleep(0.05)
    return out


def items_by_slot(champion_id: int, role: int, patch: dict) -> dict[str, list[dict]]:
    """Item WPA broken out by which purchase slot it landed in, keyed 1..MAX_SLOT.

    coachless takes an ``itemSlots`` filter that was sent as ``None`` (any
    slot) everywhere in this file — confirmed live rather than assumed dead,
    since the flat aggregate was the only reading anyone had asked it for.
    This is the same reasoning ``items_by_keystone`` already applies: what
    Immortal Shieldbow is worth bought second is not what it is worth bought
    third, and the flat list averages the two into a figure describing
    neither purchase.

    Ungated by MIN_OCCURRENCE on purpose. A thin slot comes back with fewer
    rows or none, which the frontend reads as "no coachless reading here" and
    falls back to lolalytics for that (item, slot) pair — the gate is where
    the number gets read, not where it gets baked.
    """
    out: dict[str, list[dict]] = {}
    for slot in range(1, MAX_SLOT + 1):
        rows = item_rows(champion_id, role, patch, slots=[slot])
        if rows:
            out[str(slot)] = rows
        time.sleep(0.05)
    return out


def spells_for(champion_id: int, role: int, patch: dict) -> list[dict]:
    """Per summoner spell WPA, in the shape items and runes already bake to.

    Found by recording coachless' own XHRs in a browser — it is not linked off
    any page they publish, and eleven guesses at its name across three
    controllers all missed. ``pairedSpell`` conditions one spell on the other,
    the same axis ``first`` gives items; the bake sends null, because the plan
    page reads a pick against the unconditioned figure and nine conditioned
    passes per role would be nine calls for two rows.

    Thin by nature: a jungler runs Flash and Smite in ~100% of games, so the
    list comes back with two rows and everything else is a dash. That is the
    reading, not a gap.
    """
    body = {"commonFilters": filters(champion_id, role, patch), "pairedSpell": None}
    status, data = call("ChampionWinprob/GetGlobalSummonerSpellStatistics", body)
    if status != 200 or not isinstance(data, list):
        return []
    return [
        {
            "id": s.get("summonerSpell"),
            "wpa": s.get("wpaOverall"),
            "n": s.get("occurrence"),
            "share": s.get("occurrenceRelative"),
            "wrPre": s.get("winrateExpected"),
            "wrPost": s.get("winrateObserved"),
        }
        for s in data
        if s.get("summonerSpell")
    ]


def keystone_trees() -> dict[int, int]:
    """keystone id -> its tree, read from the Data Dragon index build_runes.py writes.

    ``mainTree`` is not decoration: it tells coachless which tree is primary, and
    a secondary tree returns different rows depending on that. Sending a fixed
    8000 for a Domination keystone quietly returns the wrong secondary rows.
    """
    path = Path(__file__).parent / "frontend" / "static" / "runes.json"
    try:
        dex = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(
            "run build_runes.py first — the keystone->tree map comes from it") from exc
    return {
        int(rid): meta["tree"]
        for rid, meta in dex.get("runes", {}).items()
        if meta.get("row") == 0 and meta.get("tree")
    }


KEYSTONE_TREE = keystone_trees()


def runes_for(champion_id: int, role: int, patch: dict) -> dict:
    """Keystones, the runes under each tree, and the stat shards.

    Runes are conditioned on the keystone: what pairs well with Conqueror is
    not what pairs well with Dark Harvest. So each keystone gets its own pass
    over all five trees rather than one keystone-blind aggregate.
    """
    common = filters(champion_id, role, patch)

    status, keystones = _ask("Rune/GetKeystoneData", {"commonFilters": common})
    if status != 200 or not isinstance(keystones, list):
        return {}

    keystones = sorted(keystones, key=lambda k: k.get("occurrence") or 0, reverse=True)
    out = {"keystones": [
        {"id": k.get("rune"), "wpa": k.get("wpaOverall"), "n": k.get("occurrence")}
        for k in keystones
    ], "byKeystone": {}}

    def strip(runes):
        return [
            {"id": r.get("rune"), "wpa": r.get("wpaOverall"), "n": r.get("occurrence")}
            for r in (runes or []) if r.get("rune")
        ]

    for ks in keystones:
        kid = ks.get("rune")
        if not kid or (ks.get("occurrence") or 0) < MIN_OCCURRENCE:
            continue
        main_tree = KEYSTONE_TREE.get(kid, 8000)
        entry: dict = {"tree": main_tree, "secondary": [], "trees": {}, "shards": {}}

        status, sec = _ask("Rune/GetSecondaryTreePlaycount",
                           {"tree": main_tree, "keystone": kid, "commonFilters": common})
        if status == 200 and isinstance(sec, list):
            entry["secondary"] = [
                {"tree": s.get("tree"), "share": s.get("occurrence")} for s in sec
            ]

        for tree in TREES:
            status, rows = _ask("Rune/GetRunesForKeystoneAndTree", {
                "keystone": kid, "mainTree": main_tree, "treeToLoad": tree,
                "commonFilters": common,
            })
            if status != 200 or not isinstance(rows, dict):
                continue
            packed = {
                slot: strip(rows.get(slot))
                for slot in ("rowOnes", "rowTwos", "rowThrees")
            }
            if any(packed.values()):
                entry["trees"][str(tree)] = packed
            time.sleep(0.05)

        status, shards = _ask("Rune/GetShardsForKeystoneAndTree",
                              {"keystone": kid, "commonFilters": common})
        if status == 200 and isinstance(shards, dict):
            entry["shards"] = {k: strip(v) for k, v in shards.items()}

        out["byKeystone"][str(kid)] = entry

    return out


def seeded_champions(prior: dict, label: str) -> dict:
    """What a run starts from. A --champ run bakes one champion into a file that
    holds the whole pool, so it merges into the last good bake instead of
    clobbering the other eight. A patch change starts clean: two patches mixed in
    one file is the thing this bake exists to keep straight."""
    return dict(prior.get("champions") or {}) if prior.get("patch") == label else {}


# --- roster (archetype view) --------------------------------------------------
#
# Every champion-role on lolalytics' job list, not just the pool. Kept in its own
# store and never blended with lolalytics: the page shows it beside, labelled.
# Coachless data is personal-use only and is never republished.
# Resumable: each job lands in a work file at once, the store is written only
# when every job has an entry or a miss. A miss is {"miss": "api"} (the call
# failed or was refused, retried next run) or {"miss": "absent"} (coachless
# answered and has nothing, final).

ROSTER_OUT = vault_root() / "data" / "forge-stats-roster.json"
ROSTER_WORK = vault_root() / "data" / "forge-stats-roster.work.json"
ROLE_IDS = {v: k for k, v in ROLES.items()}
MAX_WAIT = 3600   # s; a longer Retry-After is the daily limit


def roster_job(cid: int, role: str, patch: dict) -> dict:
    """One champion-role: role-wide item and keystone-conditioned rows plus runes.
    Returns {"miss": "api"|"absent"} when there is nothing to store."""
    rid = ROLE_IDS[role]
    _missed.clear()
    body = {
        "commonFilters": filters(cid, rid, patch),
        "itemSlots": None, "itemType": 1, "keystone": None, "starterId": None,
        "firstPurchaseId": None, "firstLegendaryId": None,
        "secondLegendaryId": None, "includeSupportItems": True,
    }
    status, data = _ask("ChampionWinprob/GetGlobalItemStatistics", body)
    if status != 200 or not isinstance(data, list):
        return {"miss": "api"}
    played = sum(it.get("occurrence") or 0 for it in data)
    if played < MIN_OCCURRENCE:
        return {"miss": "absent"}
    items = item_rows(cid, rid, patch)
    runes = runes_for(cid, rid, patch)
    if not items or not runes.get("keystones"):
        return {"miss": "api"}   # the probe answered, so an empty follow-up is a failed call
    by_keystone = items_by_keystone(cid, rid, patch, runes)
    if _missed:
        # a follow-up that failed (any non-200, incl. a 429 with no numeric Retry-After) dropped a
        # key or tree; storing the row would read that as absence and settle it
        return {"miss": "api"}
    return {
        "keystones": runes["keystones"],
        "items": {"role": items, "byKeystone": by_keystone},
        "runes": runes["byKeystone"],
        # what each reading was measured under; a keystone-wide figure is never core-specific
        "conditioning": {"keystones": ["role"], "items": {"role": ["role"], "byKeystone": ["role", "keystone"]},
                         "runes": ["role", "keystone"], "n": played},
    }


def _write_atomic(path: Path, obj: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def bake_roster(jobs: list[tuple[str, str]], ids: dict[str, int], patch: dict,
                work: Path, dest: Path, publish: bool = True) -> dict | None:
    """Resume from the work file, or from the published store when a past run finished,
    write after every job, publish when done. A partial job list (`--champ`) passes
    publish=False and only fills the work file. Another patch's rows are dropped.
    A rate limit holds the run on that job, so a short limit is never recorded as a
    miss: about 55 roles an hour (Retry-After 3600), about 68 a day (86400). A wait
    over MAX_WAIT ends the asking: the rest stay api misses, the store publishes, and
    the next run fills them, so the roster fills over about three days."""
    label = f"{patch['major']}.{patch['patch']}"
    state: dict = {}
    for f in (work, dest):
        try:
            state = json.loads(f.read_text(encoding="utf-8"))
            break
        except (OSError, ValueError):
            state = {}
    if state.get("patch") != label:
        state = {"patch": label, "champions": {}}
    champs = state["champions"]
    capped = False
    for name, role in jobs:
        got = champs.get(name, {}).get(role)
        if got and got.get("miss") != "api":     # api misses are retried, the rest is settled
            continue
        if capped:
            champs.setdefault(name, {})[role] = {"miss": "api"}
            continue
        while True:
            _retry_after.clear()
            row = roster_job(ids[name], role, patch)
            if not _retry_after:
                break
            if _retry_after[0] > MAX_WAIT:
                print(f"  rate limited for {_retry_after[0]} s, stopping here", flush=True)
                row, capped = {"miss": "api"}, True
                break
            print(f"  rate limited, waiting {_retry_after[0]} s", flush=True)
            time.sleep(_retry_after[0] + 30)
        champs.setdefault(name, {})[role] = row
        _write_atomic(work, state)
        miss = champs[name][role].get("miss")
        print(f"  {name} {role}: {'miss ' + miss if miss else 'ok'}")
    if not publish:
        return None
    # every job above has an entry or a miss by now, so there is no completeness check
    store = {"patch": label, "patchFilter": patch, "tiers": TIERS, "source": "coachless.gg",
             "metric": "wpa", "champions": champs}
    _write_atomic(dest, store)
    work.unlink(missing_ok=True)
    return store


def roster_main(only: list[str] | None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bake_lolalytics import matchup_jobs, role_shares   # job list is lolalytics' own
    norm = lambda n: "".join(c for c in n.lower() if c.isalnum())  # noqa: E731
    cat = json.loads((Path(__file__).parent / "frontend" / "static" / "catalog.json")
                     .read_text(encoding="utf-8"))
    by_norm = {norm(c["n"]): (c["n"], c["k"]) for c in cat["champs"]}
    jobs, ids, unmatched = [], {}, set()
    for name, role in matchup_jobs(role_shares()):
        hit = by_norm.get(norm(name))
        if not hit:
            unmatched.add(name)
            continue
        ids[hit[0]] = hit[1]
        jobs.append((hit[0], role))
    if unmatched:
        print(f"  no catalog id for {sorted(unmatched)}; skipped", file=sys.stderr)
    if only:
        wanted = {norm(o) for o in only}
        jobs = [j for j in jobs if norm(j[0]) in wanted]
        if not jobs:
            raise SystemExit(f"no roster job matched {only}")
    print("Resolving the newest patch coachless will serve for free...")
    patch = latest_free_patch()
    print(f"roster: {len(jobs)} champion-roles")
    store = bake_roster(jobs, ids, patch, ROSTER_WORK, ROSTER_OUT, publish=not only)
    if store is None:
        print(f"{ROSTER_WORK} - work file only; a full --roster run publishes")
        return 0
    print(f"{ROSTER_OUT} - patch {store['patch']}, {len(store['champions'])} champions")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--champ", action="append",
                    help="champion name (repeatable); default is the whole pool")
    ap.add_argument("--roster", action="store_true",
                    help="every champion-role on the lolalytics job list, into forge-stats-roster.json")
    args = ap.parse_args()
    if args.roster:
        return roster_main(args.champ)

    pool = POOL
    if args.champ:
        wanted = {c.lower() for c in args.champ}
        pool = {n: i for n, i in POOL.items() if n.lower() in wanted}
        if not pool:
            raise SystemExit(f"no pool champion matched {args.champ}")

    print("Resolving the newest patch coachless will serve for free...")
    patch = latest_free_patch()
    label = f"{patch['major']}.{patch['patch']}"

    store = vault_root() / "data" / "forge-stats.json"
    prior: dict = {}
    if store.exists():
        try:
            prior = json.loads(store.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    out = {
        "patch": label,
        "patchFilter": patch,
        "tiers": TIERS,
        "source": "coachless.gg",
        "metric": "wpa",
        "champions": seeded_champions(prior, label),
    }

    for name, cid in pool.items():
        print(f"\n{name} ({cid})")
        roles: dict[str, dict] = {}
        for role_id, role_name in ROLES.items():
            items = items_for(cid, role_id, patch)
            played = sum(i["n"] or 0 for i in items)
            if not items or played < MIN_OCCURRENCE:
                print(f"  {role_name:8} — skipped ({played} purchases)")
                continue
            # ponytail: boots (2) and jungle pets (6) are separate classes on
            # the same endpoint, not slots. Appended after `played` is summed so
            # the MIN_OCCURRENCE gate still measures legendary purchases only.
            extra = [row for t in ITEM_CLASSES if t != 1
                     for row in items_for(cid, role_id, patch, item_type=t)]
            items = items + extra
            print(f"  {role_name:8} — {len(items)} items "
                  f"({len(extra)} boots/pets), {played} purchases")
            runes = runes_for(cid, role_id, patch)
            by_ks = items_by_keystone(cid, role_id, patch, runes)
            by_slot = items_by_slot(cid, role_id, patch)
            spells = spells_for(cid, role_id, patch)
            print(f"  {'':8}   {len(runes.get('keystones', []))} keystones, "
                  f"{len(by_ks)} with their own item rows, "
                  f"{len(by_slot)}/{MAX_SLOT} slots read, {len(spells)} spells")
            roles[role_name] = {"items": items, "itemsByKeystone": by_ks,
                                "itemsBySlot": by_slot,
                                "runes": runes, "spells": spells, "n": played}
        if roles:
            out["champions"][name] = {"id": cid, "roles": roles}

    store.write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")
    size = store.stat().st_size / 1024
    print(f"\nWrote {store} ({size:.0f} KB) — patch {label}, "
          f"{len(out['champions'])} champions")
    return 0


def demo() -> None:
    """Self-check: the role enum and the paywall step-back are the two things
    that silently produce wrong data rather than an error."""
    assert ROLES[1] == "jungle" and 5 not in ROLES, "role 5 is the all-roles aggregate"
    # A one-champion bake must not clobber the rest of the pool, and must not
    # merge across a patch boundary.
    assert seeded_champions({"patch": "16.16", "champions": {"Viego": 1}}, "16.16") == {"Viego": 1}
    assert seeded_champions({"patch": "16.15", "champions": {"Viego": 1}}, "16.16") == {}
    assert seeded_champions({}, "16.16") == {}
    f = filters(234, 1, {"major": 16, "patch": 15, "patchAdditions": 0})
    assert f["championIds"] == [234] and f["role"] == 1
    assert filters(None, None, {})["championIds"] is None, "null means global"

    # items_by_keystone: the thin-keystone gate is the part that silently bakes
    # a list built on 40 games as if it stood beside one built on 40,000.
    seen = []
    real, globals()["items_for"] = items_for, (
        lambda c, r, p, keystone=None, item_type=1, first=None:
        seen.append((keystone, item_type)) or
        ([{"id": 3078}] if keystone != 9999 else []))
    try:
        got = items_by_keystone(234, 1, {}, {"keystones": [
            {"id": 8010, "n": MIN_OCCURRENCE},        # exactly at the bar: kept
            {"id": 8112, "n": MIN_OCCURRENCE - 1},    # under it: skipped
            {"id": 9999, "n": 50_000},                # answers empty: not stored
            {"id": None, "n": 50_000},                # malformed row: skipped
        ]})
    finally:
        globals()["items_for"] = real
    # every item class asked per keystone: itemType 1 alone is legendaries only,
    # and the boots-shaped hole that leaves is what emptied the shop's Boots shelf
    assert seen == [(k, t) for k in (8010, 9999) for t in ITEM_CLASSES], seen
    assert list(got) == ["8010"], got

    # items_by_slot: itemSlots was sent as None everywhere until now — confirm
    # the filter actually reaches the wire per slot, across every item class,
    # and a slot coachless has nothing for drops out rather than storing an
    # empty list a caller would mistake for "measured, and it's nothing".
    seen_slots = []
    real4, globals()["items_for"] = items_for, (
        lambda c, r, p, keystone=None, item_type=1, first=None, second=None,
               slots=():
        seen_slots.append((tuple(slots), item_type)) or
        ([{"id": 3078}] if slots != [MAX_SLOT] else []))
    try:
        by_slot = items_by_slot(234, 1, {})
    finally:
        globals()["items_for"] = real4
    assert seen_slots == [((s,), t) for s in range(1, MAX_SLOT + 1)
                           for t in ITEM_CLASSES], seen_slots
    assert list(by_slot) == [str(s) for s in range(1, MAX_SLOT)], by_slot

    # the pet class is what makes a jungle pet an ordinary item with its own
    # figures rather than a filter you pick; dropping it from ITEM_CLASSES is a
    # silent return to a shop where three of a jungler's items read as unrated.
    assert ITEM_CLASSES == (1, 2, 6), ITEM_CLASSES

    # starterId is dead and must stay dead: it was its own conditioning axis, and
    # sending it again would cut the sample a second way nobody asked for.
    body_seen = {}
    real2, globals()["call"] = call, (
        lambda ep, body: body_seen.update(body or {}) or (200, []))
    try:
        items_for(234, 1, {}, first=6676)
    finally:
        globals()["call"] = real2
    assert body_seen["starterId"] is None, body_seen
    assert body_seen["firstLegendaryId"] == 6676, body_seen

    # spells_for: the endpoint is undocumented and the only thing standing
    # between a working bake and a silent empty list is the pairedSpell key it
    # refuses the call without.
    sent = {}
    real3, globals()["call"] = call, (
        lambda ep, body: sent.update({"ep": ep}, **(body or {}))
        or (200, [{"summonerSpell": 4, "wpaOverall": 0.5, "occurrence": 9,
                   "occurrenceRelative": 50.0, "winrateExpected": 49.0,
                   "winrateObserved": 49.5},
                  {"summonerSpell": None, "wpaOverall": 9}]))
    try:
        rows = spells_for(234, 1, {})
    finally:
        globals()["call"] = real3
    assert "pairedSpell" in sent and sent["pairedSpell"] is None, sent
    assert sent["ep"].endswith("GetGlobalSummonerSpellStatistics"), sent
    assert rows == [{"id": 4, "wpa": 0.5, "n": 9, "share": 50.0,
                     "wrPre": 49.0, "wrPost": 49.5}], rows
    print("ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        sys.exit(main())

#!/usr/bin/env python3
"""Bake lolalytics rune numbers into data/forge-lolalytics.json.

Why this exists: coachless paywalls the live patch, so every WPA figure in the
Forge trails the game by one. It is also sparse — it only breaks a champion down
by the keystones enough games took, which on Viego jungle is three of them, and
every other rune reads as a dash. lolalytics is on the live patch and carries a
number for every rune in every tree, so the two sit side by side in the picker:
WPA where coachless has one, win rate and pick rate always.

lolalytics' default grid is keystone-blind, but the page takes a `&keystone=<id>`
filter and the readings move a lot under it — Legend: Alacrity is 8.0% pick on
Shyvana jungle under Press the Attack and 80.0% under Conqueror, and the
keystone-blind grid averages the two into a figure describing neither. So runes
are re-scraped per keystone, and only for the keystones the default page already
shows above `KEYSTONE_PICK_FLOOR` — two extra loads on Shyvana jungle, not
seventeen. Items and boots stay role-overall; they were not part of this pass.

lolalytics is a Qwik app. The rune grid is NOT in the server HTML (only the
"highest win build" summary is) — it renders on hydration out of a serialised
state blob, so a urllib fetch gets 22 rune icons and none of the numbers. Hence
a real browser. System Chrome via Playwright's channel, never `playwright
install`.

    python3 bake_lolalytics.py                 # every champion/role in the bake
    python3 bake_lolalytics.py --champ Viego   # one champion
    python3 bake_lolalytics.py --workers 1     # one role at a time, if throttled
    python3 bake_lolalytics.py --archetypes [--mode ranked|aram|arena] [--champ X]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

# coachless' role names on the left, lolalytics' lane slugs on the right.
LANES = {"top": "top", "jungle": "jungle", "mid": "middle",
         "bot": "bottom", "support": "support"}

URL = "https://lolalytics.com/lol/{slug}/build/?lane={lane}&tier=emerald_plus"
# A second page, because the build page renders the counters HEADINGS and never
# the rows - the table lives on /counters/ and only on /counters/. This is what
# the ban card reads: a ban answers "who beats this champion", which is a
# matchup question and has no answer anywhere in the build page or in coachless.
COUNTERS_URL = "https://lolalytics.com/lol/{slug}/counters/?lane={lane}&tier=emerald_plus"

# Which rune ids are keystones, off the same runes.json the picker builds its
# keystone row from, so the two can never disagree about what a keystone is.
RUNE_META = json.loads(
    (Path(__file__).resolve().parent / "frontend" / "static" / "runes.json")
    .read_text(encoding="utf-8"))["runes"]
KEYSTONES = frozenset(k for k, v in RUNE_META.items() if v.get("row") == 0)

# A keystone is only re-scraped if the default grid already shows it taking this
# share of the role's games. Every keystone below it is a page load for a column
# nobody reads, and lolalytics' own sample down there is thin enough that the
# figures would be greyed in the picker anyway.
# ponytail: a flat percentage floor; if a low-sample role starts qualifying
# junk, add a games floor beside it rather than raising this.
KEYSTONE_PICK_FLOOR = 5.0

# One counter card is an <a> whose text is name / win rate / VS / the two deltas
# / a second rate / VS / games. Parsed off that text for the same reason the
# plan block is: the classes around it are generated.
COUNTERS_EXTRACT = r"""() => {
  const num = s => parseFloat(String(s).replace(/,/g, ''));
  const out = [];
  for (const a of document.querySelectorAll('a')) {
    const m = /^([^\n]+)\n([\d.]+)%\nVS\n(?:[^\n]*\n)?([\d.]+)%\nVS\n([\d,]+)\s*Games/
      .exec((a.innerText || '').trim());
    if (!m) continue;
    out.push({ n: m[1].trim(), wr: num(m[2]), wr2: num(m[3]), g: num(m[4]) });
  }
  return out;
}"""

# How many of the worst matchups to keep. lolalytics already floors the table at
# 100 games; twelve is a ban list you would read, and the whole table is ~180
# rows per role across three champions and five roles, which is page weight for
# rows nobody scrolls to.
KEEP_COUNTERS = 12

# One extraction, run inside the page.
#
# Runes: an icon whose src carries the rune id, followed by a sibling div holding
# three numbers in a fixed order — win rate (a coloured span), pick rate, games.
# The summary block at the top of the page reuses the same icons with no numbers
# beside them, so a cell missing any of the three is skipped rather than recorded
# as a zero.
#
# Items: the same shape plus a fourth number, and keyed by BUILD SLOT rather than
# by item. lolalytics publishes the top 24 items for each of the five slots and
# every reading is slot-local: Immortal Shieldbow is 51.9% bought second and
# 54.5% bought third, which is the interesting part and would be destroyed by
# flattening to one figure per item. The slot is in the link (`&item=3_6673`),
# so it is read from there, and the fourth number is the average minute it is
# finished on.
EXTRACT = r"""() => {
  const num = s => parseFloat(String(s).replace(/,/g, ''));
  const runes = {};
  for (const img of document.querySelectorAll('img[src*="/rune68/"], img[src*="/statmod32/"]')) {
    const m = img.getAttribute('src').match(/\/(\d+)\.webp/);
    if (!m) continue;
    let cell = img.parentElement, nums = null;
    for (let k = 0; k < 5 && cell; k++) {
      const span = cell.querySelector(':scope > div > span[style*="color"]');
      if (span) {
        const divs = [...span.parentElement.querySelectorAll('div')].map(d => d.textContent.trim());
        if (divs.length >= 2) nums = [span.textContent, divs[0], divs[1]];
        break;
      }
      cell = cell.parentElement;
    }
    if (!nums) continue;
    const [wr, pick, n] = nums.map(num);
    if (![wr, pick, n].every(isFinite)) continue;
    // Every rune is printed THREE times: once in the summary block up top with
    // no numbers (skipped above), once in the real grid, and once in a small
    // trailing table that reads a couple of hundred games. Plain assignment let
    // the trailing one win, which is how Shyvana's whole Precision minor block
    // came back as 0.2% — Triumph is 98.8% over 93,679 games in the grid and
    // 0.2% over 190 in the table below it. Biggest sample wins.
    if (!runes[m[1]] || n > runes[m[1]].n) runes[m[1]] = { wr, pick, n };
  }

  const items = {};
  for (const a of document.querySelectorAll('a[href*="&item="]')) {
    const key = (a.getAttribute('href').split('&item=')[1] || '').match(/^(\d+)_(\d+)$/);
    if (!key) continue;
    const [slot, id] = [key[1], key[2]];
    const span = a.parentElement.querySelector('span[style*="color"]');
    const divs = [...a.parentElement.querySelectorAll('div')]
      .map(d => d.textContent.trim()).filter(t => t && t !== 'Loading...');
    if (!span || divs.length < 4) continue;
    const [wr, pick, n, at] = [num(span.textContent), num(divs[1]), num(divs[2]), num(divs[3])];
    if (![wr, pick, n].every(isFinite)) continue;
    (items[id] = items[id] || {})[slot] = { wr, pick, n, at: isFinite(at) ? at : null };
  }

  // Boots are the one shelf lolalytics does NOT link. They sit in their own
  // horizontally scrolling strip, every icon a bare <img> with no anchor, so the
  // `a[href*="&item="]` pass above skips the shelf whole and the Forge's second
  // opinion column came back empty for every boot.
  //
  // Found by the strip's own heading, which is the literal word "Boots". Two
  // near-misses that a looser selector picks up instead, both checked: the
  // "Sets With" strip three rows above holds THREE icons per cell sharing one
  // reading (so Trinity Force and Spear of Shojin inherit Plated Steelcaps'
  // numbers), and every "Item N" strip is slot-local. A boots cell carries four
  // numbers — win rate, pick rate, games, average minute finished — where the
  // combo cells carry three, which is the second half of the discriminator.
  //
  // NOT slot-keyed, unlike items: the strip is one table with one reading per
  // boot, because lolalytics does not break boots down by build slot.
  //
  // This also settles the figure that blocked baking these: a hand pull reading
  // 1.03% against coachless' 24.51% was off the "Item 5" strip, where 1.03% means
  // "bought fifth". The boots strip's own pick rates are shares among players who
  // bought boots at all, which is the same denominator coachless uses.
  const boots = {};
  for (const strip of document.querySelectorAll('div.cursor-grab')) {
    const host = strip.parentElement;
    if (!host || !/^Boots\b/.test((host.innerText || '').trim())) continue;
    for (const cell of strip.querySelectorAll(':scope > div > div')) {
      const imgs = cell.querySelectorAll('img[src*="/item64/"]');
      if (imgs.length !== 1) continue;          // 3-icon combo cells are a different table
      const m = imgs[0].getAttribute('src').match(/\/(\d+)\.webp/);
      if (!m) continue;
      const nums = (cell.innerText || '').trim().split('\n')
        .map(s => s.trim()).filter(Boolean).map(num);
      if (nums.length < 3 || !nums.slice(0, 3).every(isFinite)) continue;
      const [wr, pick, n, at] = nums;
      boots[m[1]] = { wr, pick, n, at: isFinite(at) ? at : null };
    }
  }

  // The plan page's three figures: the one top summoner PAIR, the skill
  // priority, and the level-by-level skill order. All three are printed as
  // plain text panels and are read off innerText rather than walked out of the
  // DOM - Qwik generates the markup around them and regenerates it on any
  // deploy, while the text layout is what the page is FOR. A walk-down-from-a
  // -heading querySelector pass was tried first and found zero nodes.
  const T = document.body.innerText;
  const win = s => {
    const m = /([\d.]+)%\s*Win Rate\s*([\d,]+)\s*Games/.exec(s || '');
    return m ? { wr: num(m[1]), n: num(m[2]) } : null;
  };
  const after = (head, span) => {
    const i = T.indexOf(head);
    return i < 0 ? '' : T.slice(i + head.length, i + head.length + span);
  };
  const plan = {};

  const ids = [...document.querySelectorAll('img[src*="/spell64/"]')]
    .map(i => (/\/(\d+)\.webp/.exec(i.getAttribute('src')) || [])[1])
    .filter(Boolean).map(Number);
  const sp = win(after('Summoner Spells', 120));
  // lolalytics publishes the ONE top pair here and no per-spell breakdown, so
  // it is recorded as a pair and must never be rendered in a per-spell lane.
  if (sp && ids.length >= 2) plan.spells = { ids: ids.slice(0, 2), wr: sp.wr, n: sp.n };

  const pr = after('Skill Priority', 200);
  const prw = win(pr);
  const prOrder = pr.split('\n').map(x => x.trim());
  const stop = prOrder.findIndex(x => /Win Rate/.test(x));
  const order = prOrder.slice(0, stop < 0 ? undefined : stop).filter(x => /^[QWER]$/.test(x));
  if (prw && order.length) plan.priority = { order, wr: prw.wr, n: prw.n };

  const so = after('Skill Order', 400);
  const sow = win(so);
  if (sow) {
    const levels = {};
    let key = null;
    for (const tok of so.split('\n').map(x => x.trim())) {
      if (/Win Rate/.test(tok)) break;
      if (/^[QWER]$/.test(tok)) { key = tok; levels[key] = []; }
      else if (key && /^\d{1,2}$/.test(tok)) levels[key].push(+tok);
    }
    // "measured at level 15" is their own note, so R comes back with 6 and 11
    // and no 16. Recorded as published rather than padded to look complete.
    if (Object.keys(levels).length) plan.levels = { levels, wr: sow.wr, n: sow.n };
  }

  return { runes, items, boots, plan, text: T.slice(0, 4000) };
}"""


def _headline(text: str) -> dict:
    """The champion/role's own win rate, games and patch, off the page header.

    The baseline matters: a 51% rune on a 50.1% champion is a different reading
    than the same rune on a 53% one, and the picker colours against it.
    """
    wr = re.search(r"([\d.]+)%\s*\n\s*Win Rate", text)
    games = re.search(r"([\d,]+)\s*\n\s*Games", text)
    patch = re.search(r"Patch\s*\n\s*([\d.]+)", text)
    return {
        "wr": float(wr.group(1)) if wr else None,
        "n": int(games.group(1).replace(",", "")) if games else None,
        "patch": patch.group(1) if patch else None,
    }


SLUG_ALIAS = {"Nunu & Willump": "nunu", "Renata Glasc": "renata"}


def slug(name: str) -> str:
    """lolalytics' champion slug: lowercase, letters and digits only, bar the two
    whose catalog names carry more than lolalytics' URL does."""
    return SLUG_ALIAS.get(name) or re.sub(r"[^a-z0-9]", "", name.lower())


def keystones_worth_scraping(runes: dict) -> list[str]:
    """The keystones the default grid already shows above the pick floor, biggest
    first. Read off the default page rather than off a fixed list, so a champion
    only ever costs a load for a keystone it actually takes."""
    return sorted((k for k, v in runes.items()
                   if k in KEYSTONES and v.get("pick", 0) >= KEYSTONE_PICK_FLOOR),
                  key=lambda k: -runes[k]["pick"])


async def _read(page, url: str, extract: str, wheels: int = 12, step: int = 300):
    """Load a lolalytics page and run one extractor in it. The grid is below the
    fold and Qwik defers it, so it has to be scrolled into existence first."""
    await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    await page.wait_for_timeout(4_000)
    for _ in range(wheels):
        await page.mouse.wheel(0, 3_000)
        await page.wait_for_timeout(step)
    await page.wait_for_timeout(1_500)
    return await page.evaluate(extract)


async def scrape(pw, name: str, role: str) -> dict | None:
    lane = LANES.get(role)
    if not lane:
        return None
    url = URL.format(slug=slug(name), lane=lane)
    browser = await pw.chromium.launch(channel="chrome", headless=True)
    try:
        page = await (await browser.new_context()).new_page()
        got = await _read(page, url, EXTRACT)

        # Same page again, once per keystone that cleared the floor. The headline
        # comes along because the picker colours a rune against the win rate of
        # the population it was measured in, and under a keystone that is the
        # keystone's own win rate, not the role's.
        by_ks: dict[str, dict] = {}
        for kid in keystones_worth_scraping(got.get("runes") or {}):
            one = await _read(page, f"{url}&keystone={kid}", EXTRACT)
            # A real absence, not a scrape fault, and the same one an off-role lane
            # hits: below roughly two thousand games lolalytics serves the page and
            # the items but publishes no rune grid at all. Viego top is 2,461 games
            # and its Conqueror slice is 1,504, which comes back with 41 items and
            # zero runes. Those roles keep the role-overall lane in the picker.
            if not one.get("runes"):
                continue
            head = _headline(one.get("text") or "")
            by_ks[kid] = {"wr": head["wr"], "n": head["n"], "runes": one["runes"]}

        # Same browser, second page. A counters miss is not a scrape failure -
        # an off-role lane has no counters table either - so it degrades to an
        # empty list rather than sinking the runes and items that did land.
        counters: list[dict] = []
        try:
            rows = await _read(page, COUNTERS_URL.format(slug=slug(name), lane=lane),
                               COUNTERS_EXTRACT, wheels=8, step=250)
            # Worst first: a ban list is the bottom of this table, not the top.
            counters = sorted(rows, key=lambda r: r["wr"])[:KEEP_COUNTERS]
        except Exception as exc:                      # noqa: BLE001
            print(f"    ! counters: {exc}", file=sys.stderr)
    finally:
        await browser.close()

    runes = got.get("runes") or {}
    items = got.get("items") or {}
    boots = got.get("boots") or {}
    if not runes and not items:
        return None
    return dict(_headline(got.get("text") or ""), runes=runes, runesByKeystone=by_ks,
                items=items, boots=boots, plan=got.get("plan") or {},
                counters=counters, url=url)


def carry_runes_forward(one: dict, was: dict | None) -> bool:
    """Keep the last good rune block when this run's role landed without one.

    A role that returns items but an empty rune grid is usually lolalytics briefly
    unpublishing the grid, not a lane that genuinely has none - Viego top read 59
    runes at 13:1x on 2026-08-22 and 0 an hour later off the same page. Writing the
    empty grid through replaces a good block (and its keystone slices) with nothing.

    Mutates `one` and returns whether anything was carried, so the caller can say so
    in its progress line instead of printing a silent "0 runes".
    """
    if one.get("runes") or not (was or {}).get("runes"):
        return False
    assert was is not None  # (was or {}).get("runes") was truthy, so was has runes
    one["runes"] = was["runes"]
    one["runesByKeystone"] = was.get("runesByKeystone") or {}
    return True


def _read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def build_jobs(stats: dict, shares: dict) -> list[tuple[str, str]]:
    """Every role coachless measured for his pool, plus every champion-role at or
    above ROLE_FLOOR (the matchups store's OP.GG shares), so a draft build exists for
    any champion he locks, not only the pool (Sam, 2026-11-04)."""
    pool = {(n, r) for n, c in (stats.get("champions") or {}).items() for r in c.get("roles") or {}}
    return sorted(pool | set(matchup_jobs(shares)))


async def main_async(only: str | None, workers: int) -> int:
    from playwright.async_api import async_playwright

    stats = json.loads((vault_root() / "data" / "forge-stats.json").read_text(encoding="utf-8"))
    jobs = build_jobs(stats, _read_json(MATCHUPS_OUT).get("roleShares") or {})
    jobs = [j for j in jobs if not only or j[0].lower() == only.lower()]
    if not jobs:
        print(f"no champion matching {only!r} in the coachless bake or the matchups store", file=sys.stderr)
        return 1

    dest = vault_root() / "data" / "forge-lolalytics.json"
    out: dict = {"champions": {}}
    if dest.exists():                       # a failed leg keeps the last good one
        try:
            out = json.loads(dest.read_text(encoding="utf-8"))
            out.setdefault("champions", {})
        except ValueError:
            out = {"champions": {}}
    # The file as it stood before this run, kept whole. `out` is edited in place
    # below (a champion is cleared on its first landing role), so by the time a
    # later role needs to look back at what was there, `out` no longer has it.
    prev: dict = json.loads(json.dumps(out.get("champions") or {}))
    seen: set[str] = set()

    # Every role is an independent scrape in its own browser, so they run
    # concurrently rather than one after another. Measured on the nine-champion
    # pool, 33 roles, with the keystone pass in: 18m51s one at a time, 4m52s at
    # --workers 4, same output. No throttling or dropped loads at 4.
    #
    # ponytail: a flat semaphore, not a worker pool. Each permit is a whole Chrome
    # (~300MB) pointed at one site, so the ceiling is lolalytics' patience and this
    # box's memory, not scheduling cleverness. Raise --workers if both allow.
    sem = asyncio.Semaphore(workers)

    async with async_playwright() as pw:
        async def run(name: str, role: str):
            async with sem:
                return await scrape(pw, name, role)
        # return_exceptions: a flaky load on one role must not discard the other
        # thirty-two. It is reported and skipped, which is what the sequential
        # version did for a counters miss and never did for the build page.
        done = await asyncio.gather(*(run(n, r) for n, r in jobs),
                                    return_exceptions=True)

    patch: str | None = None
    last = None
    for (name, role), one in zip(jobs, done, strict=True):
        if name != last:
            print(name)
            last = name
        if isinstance(one, BaseException):
            print(f"  {role:8} - ! {one}", file=sys.stderr)
            continue
        if not one:
            # lolalytics only publishes the breakdown for lanes with enough
            # games; an off-role one (Viego top) serves the summary and
            # nothing else. That is a real absence, not a scrape fault.
            print(f"  {role:8} - nothing published for this lane")
            continue
        patch = patch or one.get("patch")
        # A role that lands its items but no rune grid is usually lolalytics
        # briefly unpublishing the grid, not a lane that has none - Viego top read
        # 59 runes at 13:1x and 0 an hour later, same games, same page. Writing the
        # empty one through replaces a good block with nothing. Carry the last good
        # block forward instead, and say so rather than printing a silent "0 runes".
        carried = (" (carried forward - this run published none)"
                   if carry_runes_forward(one, (prev.get(name) or {}).get(role))
                   else "")
        print(f"  {role:8} - {len(one['runes'])} runes{carried} "
              f"(+{len(one['runesByKeystone'])} keystones), {len(one['items'])} items, "
              f"{len(one['boots'])} boots, {len(one['counters'])} counters, "
              f"{len(one['plan'])}/3 plan figures, "
              f"{one['wr']}% over {one['n']:,} games")
        # A champion is replaced wholesale on its FIRST landing role, so a lane
        # that returns nothing this run drops out of the file rather than keeping
        # a stale reading from the last one.
        if name not in seen:
            seen.add(name)
            out["champions"][name] = {}
        out["champions"][name][role] = one

    out["patch"] = patch
    out["fetched"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dest.write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")
    n = sum(len(r) for r in out["champions"].values())
    print(f"{dest} - patch {patch}, {len(out['champions'])} champions, {n} roles")
    return 0


# --- matchups (Draft page) ----------------------------------------------------
#
# Every champion-role above ROLE_FLOOR, against every lane: the counters page
# takes `&vslane=` and renders one table per opponent lane. Kept apart from the
# rune bake above because it is ~40x the page loads (5 per role, ~240 roles) and
# must survive being interrupted: progress goes to a work file per champion-role,
# and the store is only replaced when every job has an entry or a failure.

MATCHUPS_OUT = vault_root() / "data" / "forge-matchups.json"
MATCHUPS_WORK = vault_root() / "data" / "forge-matchups.work.json"
ROLE_FLOOR = 0.05      # share of a champion's games in a role; below it the role is skipped
# His pool roles are baked whatever their share: Shen jungle is ~2% of Shen.
POOL_ROLES = (("Viego", "jungle"), ("Shen", "jungle"), ("Kha'Zix", "jungle"))
OPGG_LANES = {"top": "top", "jungle": "jungle", "mid": "mid", "adc": "bot", "support": "support"}

# Raw card text; parsed in Python so the parse is testable without a browser.
COUNTER_TEXTS = r"""() => [...document.querySelectorAll('a')]
  .map(a => (a.innerText || '').trim()).filter(t => /Games$/.test(t))"""
_COUNTER = re.compile(r"^([^\n]+)\n([\d.]+)%\nVS\n(?:([^\n]*)\n)?([\d.]+)%\nVS\n([\d,]+)\s*Games$")
_DELTA = re.compile(r"Δ1\s*(-?[\d.]+).*?Δ2\s*(-?[\d.]+)")


def parse_counter(text: str) -> dict | None:
    """One counters card: name, WR vs, opponent's WR, Delta 1, Delta 2, games.
    Delta 2 (WR vs this champion minus the candidate's own role WR) is the
    draft score's counter term; it is None when the card carries no deltas."""
    m = _COUNTER.match(text.strip())
    if not m:
        return None
    d = _DELTA.search(m.group(3) or "")
    return {"n": m.group(1).strip(), "wr": float(m.group(2)), "wr2": float(m.group(4)),
            "d1": float(d.group(1)) if d else None, "d2": float(d.group(2)) if d else None,
            "g": int(m.group(5).replace(",", ""))}


def role_shares() -> dict:
    """{champion: {role: share of its games}} from OP.GG's lane meta, five calls."""
    hub = str(Path(__file__).resolve().parents[1])   # run as a script too
    if hub not in sys.path:
        sys.path.insert(0, hub)
    from forge import opgg_me
    out: dict = {}
    for lane, role in OPGG_LANES.items():
        r = opgg_me.call("lol_list_lane_meta_champions", position=lane,
                         desired_output_fields=[f"data.positions.{lane}[].{{champion,role_rate}}"])
        for row in r["data"]["positions"][lane]:
            out.setdefault(row["champion"], {})[role] = row["role_rate"]
    return out


def live_patch() -> str | None:
    """The catalog's patch as lolalytics writes it (16.21.1 -> 16.21)."""
    cat = Path(__file__).resolve().parent / "frontend" / "static" / "catalog.json"
    ver = json.loads(cat.read_text(encoding="utf-8")).get("ver") if cat.exists() else None
    return ".".join(ver.split(".")[:2]) if ver else None


def matchup_jobs(shares: dict) -> list[tuple[str, str]]:
    jobs = {(n, r) for n, rs in shares.items() for r, v in rs.items() if v >= ROLE_FLOOR}
    return sorted(jobs | set(POOL_ROLES))


async def scrape_matchups(pw, name: str, role: str) -> dict:
    """Five counters pages, one per opponent lane: {vs: {lane: {name: {wr, delta, games}}}}."""
    browser = await pw.chromium.launch(channel="chrome", headless=True)
    try:
        page = await (await browser.new_context()).new_page()
        vs, head = {}, None
        for opp, vslane in LANES.items():
            url = COUNTERS_URL.format(slug=slug(name), lane=LANES[role]) + f"&vslane={vslane}"
            texts = await _read(page, url, COUNTER_TEXTS, wheels=8, step=250)
            rows = [r for r in map(parse_counter, texts) if r]
            vs[opp] = {r["n"]: {"wr": r["wr"], "delta": r["d2"], "games": r["g"]} for r in rows}
            if head is None:
                head = _headline(await page.evaluate("() => document.body.innerText"))
    finally:
        await browser.close()
    if not any(vs.values()):
        raise RuntimeError("no counters rows on any lane")
    # wr is the role's own headline win rate, the engine's synergy baseline
    return {"vs": vs, "patch": head["patch"], "wr": head["wr"]}


async def bake_matchups(jobs, fetch, work: Path, dest: Path, workers: int = 3,
                        publish: bool = True, shares: dict | None = None,
                        patch: str | None = None) -> dict | None:
    """Resumable: jobs already in the work file are skipped; each landing job is
    written through at once. The store is replaced only when every job has an
    entry or a recorded failure; an interrupt leaves it as it was. A partial job
    list (`--champ`) passes publish=False: it only fills the work file, which the
    next full run resumes from. A work file left by an older patch is dropped, so a
    new store never mixes two patches' rows."""
    state = json.loads(work.read_text(encoding="utf-8")) if work.exists() else {}
    if patch and state.get("patch", patch) != patch:
        state = {}
    if patch:
        state["patch"] = patch
    state.setdefault("champions", {})
    state.setdefault("failed", {})
    if shares:
        state["roleShares"] = shares
    todo = [(n, r) for n, r in jobs if r not in state["champions"].get(n, {})]
    sem = asyncio.Semaphore(workers)

    def save():
        work.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")

    async def one(name, role):
        async with sem:
            try:
                got = await fetch(name, role)
            except Exception as exc:                  # noqa: BLE001 - recorded, not fatal
                state["failed"][f"{name}/{role}"] = str(exc)
                print(f"  ! {name} {role}: {exc}", file=sys.stderr)
            else:
                state["failed"].pop(f"{name}/{role}", None)
                state["champions"].setdefault(name, {})[role] = got
                print(f"  {name} {role}: {sum(len(v) for v in got['vs'].values())} pairs")
            save()

    await asyncio.gather(*(one(n, r) for n, r in todo))
    if not publish:
        return None
    patches = [r.get("patch") for c in state["champions"].values() for r in c.values() if r.get("patch")]
    store = {"patch": max(set(patches), key=patches.count) if patches else None,
             "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "roleShares": state.get("roleShares") or {},
             "champions": state["champions"], "failed": state["failed"]}
    dest.write_text(json.dumps(store, separators=(",", ":")) + "\n", encoding="utf-8")
    work.unlink(missing_ok=True)
    return store


async def matchups_main(only: list[str] | None, workers: int) -> int:
    from playwright.async_api import async_playwright
    shares = role_shares()
    jobs = matchup_jobs(shares)
    if only:
        jobs = [j for j in jobs if j[0].lower() in {o.lower() for o in only}]
    print(f"matchups: {len(jobs)} champion-roles, {len(jobs) * 5} pages")
    async with async_playwright() as pw:
        store = await bake_matchups(jobs, lambda n, r: scrape_matchups(pw, n, r),
                                    MATCHUPS_WORK, MATCHUPS_OUT, workers, publish=not only,
                                    shares=shares, patch=live_patch())
    if store is None:
        print(f"{MATCHUPS_WORK} - work file only; a full --matchups run publishes")
        return 0
    print(f"{MATCHUPS_OUT} - patch {store['patch']}, {len(store['champions'])} champions, "
          f"{len(store['failed'])} failed")
    return 0


# --- synergy (Draft page) -----------------------------------------------------
#
# Teammate pairs, beside `vs` in the same store. There is no /synergy/ page; the
# build page's Synergy > Common Teammates view draws one strip per ally lane, and
# each strip is horizontally virtualised (about 24 cards drawn of ~165), so every
# strip is scrolled end to end and the cards unioned. OP.GG's synergy tool stops
# at its top 10 per lane, which is why it alone left most allies unread.

SYNERGY_CARDS = r"""() => {
  const out = {};
  for (const row of document.querySelectorAll('div.flex.mb-2')) {
    const lab = row.firstElementChild;
    if (!lab || !/^Synergy/m.test(lab.innerText || '')) continue;
    const lane = ((lab.querySelector('img[alt$=" lane"]') || {}).alt || '').replace(' lane', '');
    if (!lane) continue;
    const cards = out[lane] = out[lane] || {};
    for (const a of row.querySelectorAll('a[href^="/lol/"]')) {
      const img = a.querySelector('img[alt]');
      if (img) cards[img.alt] = (a.parentElement.innerText || '').trim();
    }
  }
  return out;
}"""
SYNERGY_SCROLL = r"""(x) => [...document.querySelectorAll('div.flex.mb-2 > .overflow-x-scroll')]
  .map(s => { s.scrollLeft = x; return s.scrollWidth; })"""
_SYN = re.compile(r"^(-?[\d.]+)\n(-?[\d.]+)\n(-?[\d.]+)\n([\d.]+)\n([\d,]+)$")


def parse_synergy(text: str) -> dict | None:
    """One teammate card: win rate together, Delta 1, Delta 2 (normalised synergy
    delta, the draft score's synergy term), pick rate, games."""
    m = _SYN.match(text.strip())
    if not m:
        return None
    return {"wr": float(m.group(1)), "delta": float(m.group(3)),
            "games": int(m.group(5).replace(",", ""))}


async def scrape_synergy(pw, name: str, role: str) -> dict:
    """{ally role: {ally: {wr, delta, games}}} for the four other lanes."""
    lane_role = {v: k for k, v in LANES.items()}
    browser = await pw.chromium.launch(channel="chrome", headless=True)
    try:
        page = await (await browser.new_context(viewport={"width": 1400, "height": 1000})).new_page()
        await _read(page, URL.format(slug=slug(name), lane=LANES[role]), "() => 0", wheels=10, step=250)
        await page.locator("[data-type=common_synergy]").click()
        await page.wait_for_timeout(2_000)
        texts: dict = {}
        x, width = 0, 1
        while x <= width:
            width = max(await page.evaluate(SYNERGY_SCROLL, x), default=0)
            await page.wait_for_timeout(250)
            for lane, cards in (await page.evaluate(SYNERGY_CARDS)).items():
                texts.setdefault(lane, {}).update(cards)
            x += 800
    finally:
        await browser.close()
    out = {lane_role[lane]: {n: r for n, r in ((n, parse_synergy(t)) for n, t in cards.items()) if r}
           for lane, cards in texts.items() if lane in lane_role}
    if not any(out.values()):
        raise RuntimeError("no synergy cards on any lane")
    return out


async def synergy_main(only: list[str] | None, workers: int) -> int:
    """Adds `with` to every champion-role already in the matchup store, writing the
    store through after each one, so a rerun resumes where it stopped."""
    from playwright.async_api import async_playwright
    store = json.loads(MATCHUPS_OUT.read_text(encoding="utf-8"))
    jobs = [(n, r) for n, rs in store["champions"].items() for r, row in rs.items()
            if "with" not in row and (not only or n.lower() in {o.lower() for o in only})]
    print(f"synergy: {len(jobs)} champion-roles")
    sem = asyncio.Semaphore(workers)
    async with async_playwright() as pw:
        async def one(name, role):
            async with sem:
                try:
                    got = await scrape_synergy(pw, name, role)
                except Exception as exc:              # noqa: BLE001 - reported, rerun retries
                    print(f"  ! {name} {role}: {exc}", file=sys.stderr)
                    return
                store["champions"][name][role]["with"] = got
                # the Hub reads this file live: swap it whole, never half-written
                tmp = MATCHUPS_OUT.with_suffix(".tmp")
                tmp.write_text(json.dumps(store, separators=(",", ":")) + "\n", encoding="utf-8")
                tmp.replace(MATCHUPS_OUT)
                print(f"  {name} {role}: {sum(len(v) for v in got.values())} teammates")
        await asyncio.gather(*(one(n, r) for n, r in jobs))
    left = sum("with" not in row for rs in store["champions"].values() for row in rs.values())
    print(f"{MATCHUPS_OUT} - {left} champion-roles without synergy")
    return 0


# --- archetypes (Draft page) --------------------------------------------------
#
# Per champion-role, 1 to 4 (keystone, ordered core pair) builds read off the
# build page: the Actually Built tab `a_2` (two items, no boots) is the
# popularity count, filtered per keystone with `&keystone=`. `x_2` (exact item
# count) is stored beside it and never used to rank. Probe: docs/plans/
# 2026-10-30-forge-champion-archetypes-probe.md sections 4 and 5.

TIER = "emerald_plus"
ARCH_MIN_SHARE = 0.08           # of the role's games
ARCH_MIN_KEYSTONE_SHARE = 0.25  # of the keystone's games, valid from ARCH_THIN_SHARE of the role
ARCH_THIN_SHARE = 0.05
ARCH_MIN_GAMES = 500
ARCH_MAX = 4
MAX_FAILED = 0.05               # failure share above which nothing is published
TRIES = 3
ARCH_OUT = vault_root() / "data" / "forge-archetypes.next.json"
ARCH_WORK = vault_root() / "data" / "forge-archetypes.work.json"

# Arena: DOES NOT FIT. Probed 2026-10-30 (probe file, section 5): no rune grid and
# no keystone tab so (keystone, core) pairs cannot form, no Highest Win / Most
# Common tabs, spacer images with empty alt and id on 89 cards, no game-length
# state. Arena would be its own schema (item cores, augments, no keystone).
# ARAM: the build page has the same tabs, `?keystone=` links and rune grid.
MODE_URL = {
    "aram": "https://lolalytics.com/lol/{slug}/aram/build/?tier=" + TIER,
    "arena": "https://lolalytics.com/lol/{slug}/arena/build/",
}

# The active tab's cards. Scrolls its virtualised strip (about 24 cards drawn at
# once) end to end and unions the cards. An image with an empty alt or data-id is a
# lazy placeholder: its id is "" so parse_set_card drops the card. The tab itself is
# clicked from Python (read_sets); a synthetic el.click() left the strip empty.
ITEM_SETS = r"""async (step) => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const scroller = () => document.querySelector('[data-type="a"]')
    .closest('div.mb-1.select-none').nextElementSibling.nextElementSibling
    .querySelector('.overflow-x-scroll');
  const seen = {};
  let x = 0, width = 1;
  while (x <= width) {
    const sc = scroller();
    sc.scrollIntoView({block: 'center'});   // lazy images only load for a strip in view
    sc.scrollLeft = x; width = sc.scrollWidth;
    await wait(250);
    for (const c of scroller().firstElementChild.children) {
      // item64 only: a card that has been hovered or hydrated also holds tooltip
      // images (item72, no alt, no data-id) which are not part of the set
      const ids = [...c.querySelectorAll('img[src*="/item64/"]')].map(
        i => (i.alt && i.getAttribute('data-id')) ? i.getAttribute('data-id') : '');
      const card = {ids, text: (c.innerText || '').trim()};
      seen[JSON.stringify(card)] = card;
    }
    x += step;
  }
  return Object.values(seen);
}"""
# Skill order table (tab `skill15`): one row per order, innerText is 15 letters then
# win rate, pick rate, games. Rows come sorted by pick.
SKILL_ROWS = r"""() => {
  const blk = document.querySelector('[data-type="skill15"]').parentElement.parentElement;
  return [...blk.children[1].querySelectorAll('.overflow-y-scroll > div')]
    .map(r => (r.innerText || '').trim());
}"""
# the numbers close the text; a hovered card also carries its tooltip text first
_CARD = re.compile(r"(?:^|\n)([\d.]+)\n([\d.]+)\n([\d,]+)$")
_ID = re.compile(r"^(\d+)_(\d+)$")


async def read_sets(page, tabs: list[str], step: int = 800) -> dict:
    """{tab: [raw {ids, text} cards]}. The page lands on `ab_3` (boots), so every tab
    is clicked on every load; the filter does not persist across a goto."""
    out = {}
    for tab in tabs:
        await page.locator(f"[data-type={tab}]").click()
        await page.wait_for_timeout(2_000)
        out[tab] = await page.evaluate(ITEM_SETS, step)
    return out


def parse_set_card(ids: list[str], text: str) -> dict | None:
    """One item-set card: img data-ids (`<position>_<itemId>`, "" for a placeholder
    with an empty alt or id) and its text (win rate, pick rate, games). None for a
    card with any placeholder image or a text that is not those three numbers."""
    parts = [_ID.match(i or "") for i in ids]
    m = _CARD.search(text.strip())
    if not ids or not m or not all(parts):
        return None
    items = [int(p.group(2)) for p in sorted(parts, key=lambda p: int(p.group(1)))]
    return {"items": items, "wr": float(m.group(1)), "pick": float(m.group(2)),
            "games": int(m.group(3).replace(",", ""))}


def parse_cards(raw: list[dict]) -> list[dict]:
    """Raw {ids, text} cards from one tab, scroll snapshots already unioned, to
    parsed cards. Placeholders drop; the same ordered set seen twice keeps the
    bigger sample. A > B and B > A are different keys, so both stay."""
    best: dict[tuple, dict] = {}
    for c in raw or []:
        card = parse_set_card(c["ids"], c["text"])
        if card and card["games"] >= best.get(tuple(card["items"]), {"games": -1})["games"]:
            best[tuple(card["items"])] = card
    return sorted(best.values(), key=lambda c: -c["games"])


def full_path(core: list, paths: list) -> list[dict]:
    """The most-played chain from the core to five items: at each length the most-played
    card extending the previous step. `path` keeps the top three of any length, where
    3-item cards always outnumber 5-item ones, so it never reached five (2026-11-03)."""
    out, prev = [], core
    for n in range(len(core) + 1, 6):
        step = [p for p in paths if len(p["items"]) == n and p["items"][:len(prev)] == prev]
        if not step:
            break
        p = max(step, key=lambda p: p["games"])
        out.append({"items": p["items"], "wr": p["wr"], "games": p["games"]})
        prev = p["items"]
    return out


def derive(role_games: int, by_keystone: dict) -> list[dict]:
    """The role's archetypes from per-keystone tab reads.

    by_keystone: {keystone id: {"games": keystone games, "cards": parsed a_2,
    "x2": parsed x_2, "paths": parsed a_3..a_5}}. The popularity count is a_2 only.
    A (keystone, core) qualifies at 8% of the role, or at 25% of its keystone from
    5% of the role, and always needs 500 games. The role's most-played pair is kept
    regardless as `sparse`, so a thin role still has one. At most ARCH_MAX, by games.
    """
    cands = []
    for kid, ks in by_keystone.items():
        kg = ks.get("games") or 0
        x2 = {tuple(c["items"]): c for c in ks.get("x2") or []}
        for c in ks.get("cards") or []:
            core = c["items"]
            # an unread total is None, never 0: a share built on it is unknown
            share = None if role_games is None else c["games"] / role_games if role_games else 0.0
            kshare = None if ks.get("games") is None else c["games"] / kg if kg else 0.0
            x = x2.get(tuple(core))
            path = sorted((p for p in ks.get("paths") or []
                           if len(p["items"]) > len(core) and p["items"][:len(core)] == core),
                          key=lambda p: -p["games"])[:3]
            cands.append({
                "id": "-".join(str(i) for i in [int(kid), *core]),
                "keystone": int(kid), "core": core,
                "share": None if share is None else round(share, 4),
                "keystoneShare": None if kshare is None else round(kshare, 4),
                "wr": c["wr"], "games": c["games"],
                "x2": {"wr": x["wr"], "games": x["games"]} if x else None,
                # ponytail: an unknown share cannot qualify, so it reads sparse rather than ok
                "state": "ok" if share is not None and c["games"] >= ARCH_MIN_GAMES and (
                    share >= ARCH_MIN_SHARE
                    or (share >= ARCH_THIN_SHARE and kshare is not None and kshare >= ARCH_MIN_KEYSTONE_SHARE)) else "sparse",
                "path": [{"items": p["items"], "wr": p["wr"], "games": p["games"]} for p in path],
                "full": full_path(core, ks.get("paths") or [])})
    cands.sort(key=lambda a: -a["games"])
    keep = [a for a in cands if a["state"] == "ok"][:ARCH_MAX]
    return keep or cands[:1]


def parse_skill_order(text: str, slug: str = "") -> dict | None:
    """One `skill15` row: 15 letters, then win rate, pick rate, games."""
    tok = [t.strip() for t in re.split(r"[\n|]", text) if t.strip()]
    if len(tok) < 18 or not all(t in "QWER" and len(t) == 1 for t in tok[:15]):
        return None
    try:
        wr, games = float(tok[15]), int(tok[17].replace(",", ""))
    except ValueError:
        return None
    order = complete_order("".join(tok[:15]), slug)
    levels: dict[str, list[int]] = {}
    for lvl, ch in enumerate(order, 1):
        levels.setdefault(ch, []).append(lvl)
    return {"order": order, "levels": levels, "wr": wr, "n": games}


# Max ranks Q W E R off Data Dragon's spells[].maxrank, where they are not 5 5 5 3.
CAPS = {"aphelios": (6, 6, 6, 3), "jayce": (6, 6, 6, 1), "udyr": (6, 6, 6, 6),
        "yuumi": (6, 5, 5, 3)}
# Champions whose rows carry evolve or augment picks among the level-ups: for them a
# letter taken before the level allows that rank is dropped too. Everyone else is read
# as one letter per level (Zeri's row puts R at 5 and is right as read).
EVOLVES = {"khazix", "kaisa", "viktor"}


def _legal(out: str, s: str, caps: tuple, level_rule: bool) -> bool:
    k = "QWER".index(s)
    rank, lvl = out.count(s) + 1, len(out) + 1
    if rank > caps[k]:
        return False
    if not level_rule:
        return True
    if s == "R" and caps[3] == 3:
        return lvl >= (6, 11, 16)[rank - 1]
    return rank <= (lvl + 1) // 2


def complete_order(order: str, slug: str = "") -> str:
    """lolalytics' 15 letters to 18 levels (marks 2026-11-05-024817:1). A letter past an
    ability's rank cap, or before the level allows that rank, is an evolve or augment
    pick (Kha'Zix, Kai'Sa, Viktor), not a level-up, so it is dropped. Levels left are
    forced by the caps: R at 6/11/16, the rest to the basic with more ranks still open.
    ponytail: a dropped evolve shifts the later points one level early; lolalytics does
    not say which letter was the evolve, only the cap does."""
    caps = CAPS.get(slug, (5, 5, 5, 3))
    rule = slug in EVOLVES
    out = ""
    for s in order:
        if s in "QWER" and _legal(out, s, caps, rule):
            out += s
    while len(out) < 18:
        if caps[3] == 3 and _legal(out, "R", caps, rule):
            out += "R"
            continue
        open_ = [s for s in "QWE" if _legal(out, s, caps, rule)]
        if not open_:
            break
        out += max(open_, key=lambda s: (out.count(s), -"QWE".index(s)))
    return out


def opgg_skill_order(builds: list | None, slug: str) -> dict | None:
    """op.gg's most-played order whose second R is at 11 (marks 2026-11-05-024817:1,
    Sam picked it 2026-11-05). For EVOLVES lolalytics counts evolve picks as
    level-ups, so its orders put R late; op.gg tags the evolve on the R ('R-Q'), so the
    tag is cut and each letter is one level. Completed to 18 like any other row."""
    for b in sorted(builds or [], key=lambda b: -(b.get("play") or 0)):
        order = "".join(str(t)[:1] for t in b.get("order") or [])
        if len(order) < 11 or order[5] != "R" or order[10] != "R" or set(order) - set("QWER"):
            continue
        full = complete_order(order, slug)
        levels: dict[str, list[int]] = {}
        for lvl, ch in enumerate(full, 1):
            levels.setdefault(ch, []).append(lvl)
        play = b.get("play") or 0
        return {"order": full, "levels": levels, "n": play,
                "wr": round(100 * (b.get("win") or 0) / play, 1) if play else None,
                "source": "op.gg", "scope": "role-wide"}
    return None


def fetch_opgg_builds(slug: str, role: str) -> list:
    """op.gg's skill orders for one champion-role (five most played)."""
    hub = str(Path(__file__).resolve().parents[1])   # run as a script too
    if hub not in sys.path:
        sys.path.insert(0, hub)
    from forge import opgg_me
    lane = {v: k for k, v in OPGG_LANES.items()}[role]
    r = opgg_me.call("lol_get_champion_analysis", game_mode="ranked", champion=slug.upper(),
                     position=lane, desired_output_fields=["data.skill_masteries.builds[].{order[],play,win}"])
    return ((r.get("data") or {}).get("skill_masteries") or {}).get("builds") or []


def apply_skills(row: dict, sk: dict | None) -> int:
    """Put one op.gg order on every archetype of a role row; returns how many changed."""
    if not sk:
        return 0
    n = 0
    for a in row.get("archetypes") or []:
        if a.get("skills") != sk:
            a["skills"], n = dict(sk), n + 1
    return n


def game_length_buckets(html: str) -> dict | None:
    """{bucket 1..7: (games, wins)} off the page's Qwik state: the entry that is
    exactly {time, timeWin}, each a dict keyed "1".."7" of refs to numbers."""
    m = re.search(r'<script type="qwik/json">(.*?)</script>', html or "", re.S)
    if not m:
        return None
    try:
        objs = json.loads(m.group(1))["objs"]
        ref = lambda x: objs[int(x, 36)] if isinstance(x, str) else x  # noqa: E731
        for o in objs:
            if isinstance(o, dict) and set(o) == {"time", "timeWin"}:
                t, w = ref(o["time"]), ref(o["timeWin"])
                return {i: (ref(t[str(i)]), ref(w[str(i)])) for i in range(1, 8)}
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return None


def parse_game_length(html: str) -> dict | None:
    """Win rate by game length (buckets 0-15, 15-20, 20-25, 25-30, 30-35, 35-40,
    40+ minutes). early = buckets 1-2, mid = 3-5, late = 6-7, games-weighted. The
    page draws only the games distribution; a page without the state gives None."""
    b = game_length_buckets(html)
    if not b:
        return None

    def wr(ks):
        g = sum(b[k][0] for k in ks)
        return round(100 * sum(b[k][1] for k in ks) / g, 1) if g else None
    out = {"early": wr((1, 2)), "mid": wr((3, 4, 5)), "late": wr((6, 7))}
    return out if all(v is not None for v in out.values()) else None


def pick_rune_page(runes: dict, keystone: int) -> list[int] | None:
    """One legal page under the keystone: the most-picked rune in each of the
    keystone tree's rows 1-3, then two runes from distinct rows of the other tree
    whose runes carry the most picks. [keystone, p1, p2, p3, s1, s2], or None when
    the grid does not cover it (unknown stays unknown)."""
    meta = RUNE_META.get(str(keystone))
    if not meta:
        return None

    def best(tree, row):
        c = [(v["pick"], int(k)) for k, v in runes.items()
             if RUNE_META.get(k, {}).get("tree") == tree and RUNE_META[k]["row"] == row]
        return max(c) if c else None
    prim = [best(meta["tree"], r) for r in (1, 2, 3)]
    if not all(prim):
        return None
    score: dict[int, float] = {}
    for k, v in runes.items():
        rm = RUNE_META.get(k)
        if rm and rm["row"] in (1, 2, 3) and rm["tree"] != meta["tree"]:
            score[rm["tree"]] = score.get(rm["tree"], 0.0) + v["pick"]
    if not score:
        return None
    tree = max(score, key=score.get)
    sec = sorted(filter(None, (best(tree, r) for r in (1, 2, 3))), reverse=True)[:2]
    return [keystone, *(p[1] for p in prim), *(p[1] for p in sec)] if len(sec) == 2 else None


def _most_bought_boots(boots: dict) -> dict | None:
    if not boots:
        return None
    bid, b = max(boots.items(), key=lambda kv: kv[1]["n"])
    # the shelf's own pick rate is a share among players who bought boots
    return {"id": int(bid), "pick": b["pick"], "n": b["n"], "scope": "players who bought boots"}


def build_row(raw: dict, patch: str | None = None) -> dict:
    """A role row from one capture (the shape the scrape returns, and the fixture):
    {url, headline, earlyLate, runes, keystones: {kid: {headline, runes, boots,
    skills, sets: {tab: [raw cards]}}}}. Pure, so it is tested without a browser."""
    head = raw["headline"]
    role_games = head["n"]
    if role_games is None:
        raise NoCards("no game count in the role headline")
    by_ks, extra = {}, {}
    for kid, ks in raw["keystones"].items():
        sets = ks.get("sets") or {}
        by_ks[kid] = {"games": (ks.get("headline") or {}).get("n"),
                      "cards": parse_cards(sets.get("a_2")), "x2": parse_cards(sets.get("x_2")),
                      "paths": [c for t in ("a_3", "a_4", "a_5") for c in parse_cards(sets.get(t))]}
        extra[kid] = ks
    archs = derive(role_games, by_ks)
    if not archs:
        raise NoCards("no cards read")
    for a in archs:
        ks = extra[str(a["keystone"])]
        slug = (re.search(r"/lol/([^/]+)/", raw.get("url") or "") or [None, ""])[1]
        rows = [parse_skill_order(t, slug) for t in ks.get("skills") or []]
        sk = next((r for r in rows if r), None)
        page = pick_rune_page(ks.get("runes") or {}, a["keystone"])
        a.update({
            "patch": head.get("patch") or patch, "url": f"{raw['url']}&keystone={a['keystone']}",
            "boots": _most_bought_boots(ks.get("boots") or {}),
            "runes": {"page": page, "scope": "keystone-wide"} if page else None,
            "skills": dict(sk, scope="keystone-wide") if sk else None})
    return {"roleGames": role_games, "roleWr": head["wr"], "patch": head.get("patch") or patch,
            "state": "ok" if any(a["state"] == "ok" for a in archs) else "sparse",
            "earlyLate": raw.get("earlyLate"), "archetypes": archs}


class NoRuneGrid(RuntimeError):
    """The default page came back without a rune grid. lolalytics briefly unpublishes
    it (and one scrape under three workers returned none for Viego), so this is a
    failed read to retry, never a role with no keystones."""


class NoCards(NoRuneGrid):
    """The page loaded but no item-set card or role headline was read: a failed read
    to retry and record, never a `sparse` role with no archetypes."""


async def capture_role(pw, name: str, role: str, mode: str = "ranked") -> dict:
    """Everything build_row needs, off the live pages: the unfiltered role page
    (headline, game length, rune grid), then one load per keystone above the pick
    floor (rune grid, boots, skill order, the item-set tabs)."""
    if mode == "ranked":
        url = URL.format(slug=slug(name), lane=LANES[role])
    elif mode in MODE_URL and mode != "arena":
        url = MODE_URL[mode].format(slug=slug(name))
    else:
        raise RuntimeError(f"no archetype shape for mode {mode}")
    browser = await pw.chromium.launch(channel="chrome", headless=True)
    try:
        page = await (await browser.new_context(viewport={"width": 1400, "height": 1000})).new_page()
        got = await _read(page, url, EXTRACT)
        if not got.get("runes"):
            raise NoRuneGrid("no rune grid")
        head = _headline(got.get("text") or "")
        out = {"url": url, "headline": head, "earlyLate": parse_game_length(await page.content()),
               "runes": got["runes"], "keystones": {}}
        for kid in keystones_worth_scraping(got["runes"]):
            one = await _read(page, f"{url}&keystone={kid}", EXTRACT)
            ks = {"headline": _headline(one.get("text") or ""), "runes": one.get("runes") or {},
                  "boots": one.get("boots") or {}, "sets": {}, "skills": []}
            ks["sets"] = await read_sets(page, ["a_2", "x_2"])
            single = derive(head["n"], {kid: {
                "games": ks["headline"]["n"], "cards": parse_cards(ks["sets"].get("a_2"))}})
            if any(a["state"] == "ok" for a in single):      # paths only for a keystone that can qualify
                ks["sets"].update(await read_sets(page, ["a_3", "a_4", "a_5"]))
            await page.locator("[data-type=skill15]").click()
            await page.wait_for_timeout(2_000)
            ks["skills"] = await page.evaluate(SKILL_ROWS)
            out["keystones"][kid] = ks
    finally:
        await browser.close()
    return out


async def scrape_archetypes(pw, name: str, role: str, mode: str = "ranked") -> dict:
    row = build_row(await capture_role(pw, name, role, mode))
    s = slug(name)
    if s in EVOLVES and mode == "ranked":
        try:
            sk = opgg_skill_order(await asyncio.to_thread(fetch_opgg_builds, s, role), s)
        except Exception:   # ponytail: op.gg down keeps lolalytics' order, never fails the bake
            sk = None
        apply_skills(row, sk)
    return row


def fingerprint(patch: str | None) -> str:
    """A work file is only resumed under the same patch, tier and qualifying rule."""
    return "|".join(str(x) for x in (patch, TIER, ARCH_MIN_SHARE, ARCH_MIN_KEYSTONE_SHARE,
                                     ARCH_THIN_SHARE, ARCH_MIN_GAMES, ARCH_MAX))


def _write_atomic(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(tmp, path)


async def bake_archetypes(jobs, fetch, work: Path, dest: Path, workers: int = 3,
                          publish: bool = True, patch: str | None = None,
                          mode: str = "ranked") -> dict | None:
    """Resumable like bake_matchups: jobs already in the work file are skipped, each
    landing job is written through at once, a work file from another fingerprint is
    dropped. An empty rune grid is retried TRIES times, then recorded in `failed`;
    a row whose patch is not `patch` is a failure too. The store is staged at `dest`
    only when every job has an entry or a failure and failures are at or under
    MAX_FAILED; otherwise `dest` is left alone and None comes back. `--champ` runs
    pass publish=False and only fill the work file."""
    fp = fingerprint(patch)
    state = json.loads(work.read_text(encoding="utf-8")) if work.exists() else {}
    if state.get("fingerprint") != fp:
        state = {}
    state.update(fingerprint=fp, patch=patch)
    state.setdefault("generation", f"{patch}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    state.setdefault("failed", {})
    state.setdefault("modes", {}).setdefault(mode, {})
    done = state["modes"][mode]
    todo = [(n, r) for n, r in jobs if r not in done.get(n, {})]
    sem = asyncio.Semaphore(workers)

    async def one(name, role):
        key = f"{name}/{role}"
        async with sem:
            try:
                for attempt in range(1, TRIES + 1):
                    try:
                        got = await fetch(name, role)
                        break
                    except NoRuneGrid as exc:
                        if attempt == TRIES:
                            raise RuntimeError(f"{exc} after {TRIES} tries") from None
                if patch and got.get("patch") != patch:
                    raise RuntimeError(f"page is patch {got.get('patch')}, live is {patch}")
            except Exception as exc:                  # noqa: BLE001 - recorded, not fatal
                state["failed"][key] = str(exc)
                print(f"  ! {key}: {exc}", file=sys.stderr)
            else:
                state["failed"].pop(key, None)
                done.setdefault(name, {})[role] = got
                print(f"  {key}: {len(got['archetypes'])} archetypes")
            _write_atomic(work, state)

    await asyncio.gather(*(one(n, r) for n, r in todo))
    if not publish:
        return None
    wanted = {f"{n}/{r}" for n, r in jobs}
    failed = {k: v for k, v in state["failed"].items() if k in wanted}
    if len(failed) / max(len(wanted), 1) > MAX_FAILED:
        print(f"  {len(failed)}/{len(wanted)} failed, over {MAX_FAILED:.0%}: not staged", file=sys.stderr)
        return None
    store = json.loads(dest.read_text(encoding="utf-8")) if dest.exists() else {}
    if store.get("fingerprint") != fp:
        store = {}
    store.update(generation=state["generation"], patch=patch, fingerprint=fp,
                 fetched=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    # a failure from an earlier run of this fingerprint goes once its job has a row
    store["failed"] = {k: v for k, v in (store.get("failed") or {}).items()
                       if not any(k == f"{n}/{r}" and r in done.get(n, {}) for n, r in jobs)}
    store["failed"].update(failed)
    store.setdefault("modes", {"ranked": {}, "aram": {}, "arena": {}})[mode] = done
    _write_atomic(dest, store)
    del state["modes"][mode]
    if state["modes"]:
        _write_atomic(work, state)
    else:
        work.unlink(missing_ok=True)
    return store


def mode_jobs(mode: str, shares: dict | None = None) -> list[tuple[str, str]]:
    """Ranked: the matchup jobs. ARAM: every catalog champion once, role `aram`.
    Arena: none, the shape does not fit (see MODE_URL's comment)."""
    if mode == "ranked":
        return matchup_jobs(shares or {})
    if mode == "aram":
        cat = Path(__file__).resolve().parent / "frontend" / "static" / "catalog.json"
        return sorted((c["n"], "aram") for c in json.loads(cat.read_text(encoding="utf-8"))["champs"])
    return []


def _label(a: dict, items: dict, rune_names: dict) -> str:
    core = " + ".join(items.get(str(i), str(i)) for i in a["core"])
    return (f"{rune_names.get(str(a['keystone']), a['keystone'])} {core}: share {a['share']:.1%}, "
            f"keystone share {a['keystoneShare']:.1%}, wr {a['wr']}, {a['games']:,} games, {a['state']}")


async def archetypes_main(only: list[str] | None, workers: int, mode: str) -> int:
    from playwright.async_api import async_playwright
    if mode == "arena":
        print("arena: no archetype shape (see MODE_URL comment); nothing to bake")
        return 0
    shares = role_shares() if mode == "ranked" else None
    jobs = mode_jobs(mode, shares)
    if only:
        jobs = [j for j in jobs if j[0].lower() in {o.lower() for o in only}]
    if not jobs:
        print(f"no jobs for mode {mode}" + (f" and champion {only}" if only else ""), file=sys.stderr)
        return 1
    print(f"archetypes ({mode}): {len(jobs)} champion-roles")
    async with async_playwright() as pw:
        store = await bake_archetypes(jobs, lambda n, r: scrape_archetypes(pw, n, r, mode),
                                      ARCH_WORK, ARCH_OUT, workers, publish=not only,
                                      patch=live_patch(), mode=mode)
    if only:
        cat = json.loads((Path(__file__).resolve().parent / "frontend" / "static" / "catalog.json")
                         .read_text(encoding="utf-8"))
        items = {i["id"]: i["n"] for i in cat["items"]}
        rune_names = {k: v["name"] for k, v in RUNE_META.items()}
        work = json.loads(ARCH_WORK.read_text(encoding="utf-8"))
        for n, r in jobs:
            row = work["modes"].get(mode, {}).get(n, {}).get(r)
            if not row:
                print(f"{n} {r}: {work['failed'].get(f'{n}/{r}', 'no row')}")
                continue
            print(f"{n} {r}: {row['roleGames']:,} games, wr {row['roleWr']}, earlyLate {row['earlyLate']}")
            for a in row["archetypes"]:
                print("  " + _label(a, items, rune_names))
        print(f"{ARCH_WORK} - work file only; a full --archetypes run stages {ARCH_OUT.name}")
        return 0
    print(f"{ARCH_OUT} - " + ("staged" if store else "not staged"))
    return 0 if store else 1


def demo() -> None:
    """Self-check on the two things that silently produce a wrong file: the lane
    rename (coachless says mid/bot, lolalytics says middle/bottom) and the header
    parse the colouring baseline comes from."""
    assert LANES["mid"] == "middle" and LANES["bot"] == "bottom", "lane slugs differ"
    assert slug("Rek'Sai") == "reksai" and slug("Viego") == "viego" and slug("Nunu & Willump") == "nunu"
    head = _headline("Patch\n16.16\nRanked\n50.11%\nWin Rate\n1.74%\n51,025\nGames\n")
    assert head == {"wr": 50.11, "n": 51025, "patch": "16.16"}, head
    assert _headline("nothing here") == {"wr": None, "n": None, "patch": None}
    # keystone picking: keystones only, floor applied, biggest first. The numbers
    # are Shyvana jungle's - Press the Attack, Conqueror, and a third that is real
    # but too thin to be worth a page load. 9111 is Triumph, a minor rune at 98.8%,
    # and must never be mistaken for a keystone by pick rate alone.
    picked = keystones_worth_scraping({
        "8010": {"pick": 21.4}, "8005": {"pick": 76.2},
        "9923": {"pick": 1.2}, "9111": {"pick": 98.8},
    })
    assert picked == ["8005", "8010"], picked
    assert "8005" in KEYSTONES and "9111" not in KEYSTONES and len(KEYSTONES) == 17
    # teammate card text, as Viego jungle + Malphite top reads
    assert parse_synergy("53.99\n1.71\n1.11\n3.89\n5,718") == {"wr": 53.99, "delta": 1.11, "games": 5718}
    assert parse_synergy("0.00\n-35.75\n-19.30\n0.00\n1") == {"wr": 0.0, "delta": -19.3, "games": 1}
    assert parse_synergy("53.99\n1.71\n3.89\n5,718") is None
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--champ", action="append", help="just this champion (repeatable)")
    ap.add_argument("--matchups", action="store_true",
                    help="bake data/forge-matchups.json (every role, every lane; ~hours)")
    ap.add_argument("--synergy", action="store_true",
                    help="add teammate synergy to data/forge-matchups.json (one page per role)")
    ap.add_argument("--archetypes", action="store_true",
                    help="bake data/forge-archetypes.next.json (--champ fills the work file only)")
    ap.add_argument("--mode", choices=("ranked", "aram", "arena"), default="ranked",
                    help="queue the archetype bake reads (default ranked)")
    ap.add_argument("--workers", type=int, default=4,
                    help="roles scraped at once, each in its own Chrome (default 4)")
    ap.add_argument("--demo", action="store_true", help="run the self-check and exit")
    args = ap.parse_args()
    if args.demo:
        demo()
        sys.exit(0)
    if args.archetypes:
        sys.exit(asyncio.run(archetypes_main(args.champ, max(1, args.workers), args.mode)))
    if args.synergy:
        sys.exit(asyncio.run(synergy_main(args.champ, max(1, args.workers))))
    if args.matchups:
        sys.exit(asyncio.run(matchups_main(args.champ, max(1, args.workers))))
    if args.champ and len(args.champ) > 1:
        ap.error("the rune bake takes one --champ")
    sys.exit(asyncio.run(main_async(args.champ[0] if args.champ else None, max(1, args.workers))))

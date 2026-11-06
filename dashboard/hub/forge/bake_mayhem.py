"""ARAM: Mayhem (queue 2400) build and augments per champion -> data/forge-mayhem.json.

Source: metasrc's Mayhem page, checked 2026-11-05 against its plain ARAM page: real
Mayhem data (Viego 135,703 games against 4,595, a different item order, builds per
augment style). It shows tiers only, no win rates, so the build and the top three
augments per rarity are metasrc's recommended ones, read as they stand.
Not used: OP.GG's Mayhem build is a copy of its ARAM build (same items in the same
order, no game counts), and its augment feed returns only tier 3 to 5 augments.

A champion metasrc will not serve (Cloudflare 403s some loads) keeps no build here;
the Draft page then falls back to the lolalytics ARAM build and says so.

    python -m forge.bake_mayhem [--champ Viego ...] [--demo]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge.build_engine import shop_id  # noqa: E402
from forge.draft_engine import vault_root  # noqa: E402

STATIC = Path(__file__).resolve().parent / "frontend" / "static"
OUT = "forge-mayhem.json"
URL = "https://www.metasrc.com/lol/mayhem/champions/{slug}/build"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
RARITIES = ("Silver", "Gold", "Prismatic")

# Headings and images in page order; parse() reads sections off it.
EXTRACT = """() => [...document.querySelectorAll('h2,img,p')].map(e =>
  e.tagName === 'IMG' ? ['img', e.alt || '', e.getAttribute('src') || '']
                      : [e.tagName, e.textContent.replace(/\\s+/g, ' ').trim().slice(0, 300)])"""


def slug(name: str, ddid: str) -> str:
    """metasrc's champion slug: a two-word name is hyphenated (aurelion-sol, dr-mundo),
    one word is the ddragon id lowercased (kaisa, ksante). Nunu & Willump reads nunu."""
    if ddid in ("MonkeyKing", "Nunu"):
        return {"MonkeyKing": "wukong", "Nunu": "nunu"}[ddid]
    if " " in name:
        return re.sub(r"[^a-z ]", "", name.lower()).replace(" ", "-")
    return ddid.lower()


def _item_id(src: str) -> int | None:
    m = re.search(r"/static/items/[^/]*?-(\d+)\.png", src)
    return int(m.group(1)) if m else None


def parse(seq: list, catalog: dict) -> dict | None:
    """The page sequence as {games, starting, items, order, augments}, or None when
    the build sections are missing (a challenge page, a renamed layout)."""
    sec, out = None, {"starting": [], "items": [], "order": [], "augments": {r: [] for r in RARITIES}}
    games, rarity = None, None
    for row in seq:
        kind = row[0]
        if kind == "P" and games is None:
            m = re.search(r"analyzed ([\d,]+)", row[1])
            if m:
                games = int(m.group(1).replace(",", ""))
        if kind == "H2":
            t = row[1]
            sec = ("starting" if t == "Starting Items" else "items" if t.endswith(" Items") and t != "Starting Items"
                   else "order" if t == "Item Build Order" else "augments" if t.endswith(" Augments") else None)
            continue
        if kind != "img" or not sec:
            continue
        if sec == "augments":
            m = re.search(r"/static/augments/", row[2])
            n = sum(len(v) for v in out["augments"].values())
            if m and row[1] and n < 9:
                # metasrc lists three per rarity, in Silver, Gold, Prismatic order;
                # the augment tables further down repeat them
                rarity = RARITIES[min(n // 3, 2)]
                out["augments"][rarity].append(row[1])
            continue
        iid = _item_id(row[2])
        iid = iid and shop_id(iid, catalog)
        if iid and str(iid) in catalog:
            out[sec].append(iid)
    if not out["items"] or games is None:
        return None
    del out["order"]        # ponytail: "Viego Items" already lists the finished build in order
    out["games"] = games
    return out


async def scrape(names: list[str], ddid: dict, catalog: dict) -> tuple[dict, list]:
    from playwright.async_api import async_playwright
    got, failed = {}, []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="chrome", headless=True)
        for n in names:
            row = None
            for attempt in range(3):
                # a fresh context per load: a reused one draws Cloudflare's 403 from the second page on
                ctx = await browser.new_context(user_agent=UA)
                page = await ctx.new_page()
                try:
                    r = await page.goto(URL.format(slug=slug(n, ddid[n])), wait_until="domcontentloaded", timeout=45000)
                    await page.wait_for_timeout(8000 + 6000 * attempt)
                    if r and r.status == 200:
                        row = parse(await page.evaluate(EXTRACT), catalog)
                        if row:
                            break
                except Exception as e:  # a timeout on one champion never stops the run
                    print(f"  {n}: {e}", file=sys.stderr)
                finally:
                    await ctx.close()
            if row:
                got[n] = row
            else:
                failed.append(n)
            print(f"{n}: {'ok' if row else 'FAILED'}", file=sys.stderr)
        await browser.close()
    return got, failed


def main(only: list[str] | None) -> int:
    cat = json.loads((STATIC / "catalog.json").read_text(encoding="utf-8"))
    catalog = {str(i["id"]): i for i in cat["items"]}
    ddid = {c["n"]: c["i"] for c in cat["champs"]}
    names = only or sorted(ddid)
    out_p = vault_root() / "data" / OUT
    old = json.loads(out_p.read_text(encoding="utf-8")) if out_p.exists() else {"champions": {}}
    champs = old.get("champions") or {}
    builds, failed = asyncio.run(scrape(names, ddid, catalog))
    for n in names:
        row = dict(champs.get(n) or {})
        if n in builds:
            row["build"] = builds[n]
        row.pop("augments", None)
        champs[n] = row
    out_p.write_text(json.dumps({"patch": cat.get("ver"), "fetched": time.strftime("%Y-%m-%d"),
                                 "failed": failed, "champions": champs}, indent=1), encoding="utf-8")
    print(f"{len(builds)}/{len(names)} builds, {len(failed)} failed: {failed}")
    return 0


def demo():
    catalog = {"6676": {"g": 3000}, "6672": {"g": 3000}, "1001": {"g": 300}, "1037": {"g": 875}, "6697": {}}
    seq = [["P", "We've analyzed 135,703 Viego games to compile"],
           ["H2", "Viego Augments"], *[["img", f"A{i}", f"https://x/static/augments/a{i}.png"] for i in range(9)],
           ["H2", "Starting Items"], ["img", "Boots", "https://x/static/items/boots-1001.png?v=1"],
           ["H2", "Viego Items"], ["img", "gold coin", "https://x/web/img/icons/coin.png"],
           ["img", "The Collector", "https://x/static/items/the-collector-6676.png"],
           ["img", "Kraken Slayer", "https://x/static/items/kraken-slayer-6672.png"],
           ["img", "Hubris", "https://x/static/items/hubris-126697.png"],
           ["H2", "Item Build Order"], ["img", "Pickaxe", "https://x/static/items/pickaxe-1037.png"],
           ["img", "The Collector", "https://x/static/items/the-collector-6676.png"]]
    r = parse(seq, catalog)
    assert r is not None
    assert r["games"] == 135703 and r["starting"] == [1001] and r["items"] == [6676, 6672, 6697], r
    assert r["augments"]["Prismatic"] == ["A6", "A7", "A8"], r["augments"]
    assert parse([["H2", "Viego Items"]], catalog) is None   # no games line: a challenge page
    assert slug("Wukong", "MonkeyKing") == "wukong" and slug("K'Sante", "KSante") == "ksante"
    assert slug("Dr. Mundo", "DrMundo") == "dr-mundo" and slug("Nunu & Willump", "Nunu") == "nunu"
    print("demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--champ", action="append")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        demo()
        sys.exit(0)
    sys.exit(main(a.champ))

"""Build styles per champion: crit, lethality, on-hit, bruiser, tank, burst AP, burn AP,
AP bruiser, enchanter. Read off the lolalytics item tables (every completed item with
its pick rate per build slot, every role baked), not the archetype list, which keeps
only each role's top builds and so misses the off-builds a style chip is for.

A style's score is the expected number of its items among the first three completed
items, in the champion's role where it is highest: `main` at MAIN or more, `common` at
STYLE_FLOOR or more. Below that it is `niche` when its items were still bought early in
NICHE_GAMES games or more, ranked roles plus ARAM archetype chains: the chips list what
is possible on the champion, not only what is popular (Sam, 2026-11-05).
"""
from __future__ import annotations

STYLE_FLOOR = 0.15   # about one build in seven carrying one of its items early
MAIN = 1.0           # one or more of its items in a typical first three: a main style
NICHE_GAMES = 40     # MF burn AP is 47 on 16.21; a stray one-off item is under 20
SLOTS = ("1", "2", "3")
ORDER = ("crit", "lethality", "on-hit", "bruiser", "tank", "burst AP", "burn AP", "AP bruiser", "enchanter")

# ponytail: the three sets the item stats cannot tell apart, by id; a new on-hit or burn
# item reads under its stat style until it is added here.
ON_HIT = {6672, 3153, 3091, 3124, 3115, 3302, 3087, 2510, 6675}  # Navori: on-attack, not a crit build
BURN = {6653, 2503, 3118}           # Liandry's, Blackfire Torch, Malignance
BRUISER_NO_HP = {6333, 6692}        # Death's Dance, Eclipse


def item_styles(item: dict) -> set[str]:
    """Styles one catalog item ({id, g, t, st}) counts toward; components and boots none."""
    tags, iid = set(item.get("t") or []), int(item["id"])
    if "Boots" in tags or (item.get("g") or 0) < 2000:
        return set()
    stats = {s.split(" ", 1)[1] for s in item.get("st") or [] if " " in s}
    ad, ap, hp = "Attack Damage" in stats, "Ability Power" in stats, "Health" in stats
    out = set()
    if iid in ON_HIT:
        out.add("on-hit")
    elif "CriticalStrike" in tags:
        out.add("crit")
    if "Lethality" in stats:
        out.add("lethality")
    if "Base Mana Regen" in stats:
        return out | {"enchanter"}
    if iid in BURN:
        out.add("burn AP")
    elif ap:
        out.add("AP bruiser" if hp else "burst AP")
    if ad and not out & {"crit", "lethality", "on-hit"} and (hp or iid in BRUISER_NO_HP):
        out.add("bruiser")
    if not (ad or ap) and "AttackSpeed" not in tags and (hp or stats & {"Armor", "Magic Resist"}):
        out.add("tank")
    return out


def champion_styles(roles: dict, styles_by_item: dict, aram: list | None = None) -> list[dict]:
    """[{style, score, games, tier}] for one champion's lolalytics roles plus its ARAM
    archetypes ({games, full}), main and common by score, niche by games."""
    best: dict[str, float] = {}
    games: dict[str, int] = {}
    for entry in roles.values():
        score: dict[str, float] = {}
        for iid, slots in ((entry or {}).get("items") or {}).items():
            picked = sum(((slots or {}).get(k) or {}).get("pick") or 0 for k in SLOTS) / 100
            n = sum(((slots or {}).get(k) or {}).get("n") or 0 for k in SLOTS)
            for s in styles_by_item.get(str(iid), ()):
                score[s] = score.get(s, 0) + picked
                games[s] = games.get(s, 0) + n
        for s, v in score.items():
            best[s] = max(best.get(s, 0), v)
    for a in aram or []:
        chain = ((a.get("full") or [{}])[-1].get("items") or a.get("core") or [])[:len(SLOTS)]
        for iid in chain:
            for s in styles_by_item.get(str(iid), ()):
                games[s] = games.get(s, 0) + (a.get("games") or 0)
    out = []
    for s in ORDER:
        v, n = best.get(s, 0), games.get(s, 0)
        tier = "main" if v >= MAIN else "common" if v >= STYLE_FLOOR else "niche" if n >= NICHE_GAMES else None
        if tier:
            out.append({"style": s, "score": round(v, 2), "games": n, "tier": tier})
    return sorted(out, key=lambda r: (-r["score"], -r["games"]))


def all_styles(lola: dict, catalog: dict, archetypes: dict | None = None) -> dict:
    """{champion: [style rows]} for every champion in the lolalytics bake or the ARAM store."""
    by_item = {str(i["id"]): item_styles(i) for i in catalog.get("items") or []}
    aram = ((archetypes or {}).get("modes") or {}).get("aram") or {}
    champs = set(lola.get("champions") or {}) | set(aram)
    return {c: champion_styles((lola.get("champions") or {}).get(c) or {}, by_item,
                               [a for e in (aram.get(c) or {}).values() for a in (e or {}).get("archetypes") or []])
            for c in champs}


# --- counters -----------------------------------------------------------------
# Counter tags by mechanic, each item placed by reading its stats and passive text (sweep
# approved by Sam 2026-11-05). bake_traits.py --items writes these onto the item store;
# the build engine scores them. A name that leaves the shop fails `check_counters`.
COUNTERS = {
    "anti-crit": ("Randuin's Omen",),
    "anti-auto": ("Plated Steelcaps", "Armored Advance", "Thornmail", "Frozen Heart", "Randuin's Omen",
                  "Warden's Mail", "Bramble Vest"),
    "anti-attack-speed": ("Frozen Heart",),
    "anti-burst": ("Kaenic Rookern", "Death's Dance", "Guardian Angel", "Maw of Malmortius", "Zhonya's Hourglass",
                   "Sterak's Gage", "Immortal Shieldbow", "Protoplasm Harness", "Chainlaced Crushers",
                   "Armored Advance", "Hexdrinker", "Seeker's Armguard", "Celestial Opposition"),
    "anti-heal": ("Thornmail", "Mortal Reminder", "Chempunk Chainsword", "Morellonomicon", "Bramble Vest",
                  "Executioner's Calling", "Oblivion Orb"),
    "anti-shield": ("Serpent's Fang",),
    "anti-kite": ("Stridebreaker", "Randuin's Omen", "Iceborn Gauntlet", "Rylai's Crystal Scepter",
                  "Blade of The Ruined King", "Hextech Gunblade", "Serylda's Grudge", "Zeke's Convergence",
                  "Celestial Opposition", "Dead Man's Plate", "Boots of Swiftness", "Swiftmarch",
                  "Youmuu's Ghostblade", "Phantom Dancer", "Trinity Force", "Stormrazor", "Black Cleaver",
                  "Cosmic Drive", "Experimental Hexplate", "Hextech Rocketbelt", "Phage", "Solstice Sleigh"),
    "anti-HP": ("Lord Dominik's Regards", "Blade of The Ruined King", "Voltaic Cyclosword", "Liandry's Torment",
                "Redemption"),
    "anti-armor": ("Lord Dominik's Regards", "Serylda's Grudge", "Mortal Reminder", "Black Cleaver", "Terminus"),
    "anti-MR": ("Void Staff", "Cryptbloom", "Bloodletter's Curse", "Abyssal Mask", "Malignance", "Terminus"),
    "anti-burn": ("Force of Nature",),
    "tenacity": ("Mercury's Treads", "Chainlaced Crushers", "Sterak's Gage", "Wit's End", "Endless Hunger",
                 "Protoplasm Harness", "Elixir of Iron"),
    "cleanse": ("Quicksilver Sash", "Mercurial Scimitar", "Mikael's Blessing"),
    "anti-invisibility": ("Control Ward", "Horizon Focus"),
    "anti-vision": ("Umbral Glaive", "Control Ward", "Oracle Lens"),
    "magic amp": ("Abyssal Mask", "Bloodletter's Curse", "Malignance"),
    "physical amp": ("Black Cleaver",),
    "attack-speed buff": ("Ardent Censer", "Bandlepipes"),
    "AP buff": ("Staff of Flowing Water", "Dream Maker"),
    "move-speed buff": ("Shurelya's Battlesong", "Solstice Sleigh", "Elixir of Iron"),
}
MAGIC_ONLY = {"Kaenic Rookern", "Maw of Malmortius", "Chainlaced Crushers", "Hexdrinker"}  # anti-burst vs magic
PHYS_ONLY = {"Armored Advance"}                                                           # anti-burst vs physical
# ponytail: placed wards and traps Oracle Lens and Control Wards clear, by name; no trait reads it.
TRAPS = {"Teemo", "Shaco", "Caitlyn", "Jhin", "Nidalee", "Maokai", "Zyra"}
ALLY_TAGS = {"magic amp", "physical amp", "attack-speed buff", "AP buff", "move-speed buff"}


def counter_tags(name: str) -> list[str]:
    return [t for t, names in COUNTERS.items() if name in names]


def check_counters(catalog_names: set[str]) -> list[str]:
    """Names in COUNTERS the shop no longer sells."""
    return sorted({n for names in COUNTERS.values() for n in names} - catalog_names)


def _sum(rows, t):
    vals = [r.get(t) for r in rows]
    return sum(v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)), \
        all(isinstance(v, (int, float)) for v in vals)


def _clip(x):
    return max(0.0, min(1.0, x))


# ponytail: every scale below is a heuristic read off the traits store's spread on 16.21
# (bonusHp 75th pct 500, armor median 72, mr median 46, autoReliance median 2; tenacityCC
# on 16.22 median 3.1 s, 90th pct 7.5 s per champion, so a median team already sums 15.6 s). An average
# draft reads near 0 and a heavily skewed one 1 (Sam, 2026-11-05: counters are for
# skewed drafts, never average ones). Retune here when a scored draft reads wrong.
def threats(enemies: list[dict], allies: list[dict]) -> dict[str, tuple[float, str]]:
    """{tag: (0..1, why)} from per-champion trait rows ({name, <trait>: value})."""
    n = len(enemies) or 1
    out: dict[str, tuple[float, str]] = {}
    count = lambda rows, f: sum(1 for r in rows if f(r))  # noqa: E731
    crit = count(enemies, lambda r: r.get("scaling") == "crit")
    out["anti-crit"] = (_clip(crit / 3), f"{crit} enemy crit carr{'y' if crit == 1 else 'ies'}")
    auto, _ = _sum(enemies, "autoReliance")
    out["anti-auto"] = (_clip((auto / n - 2) / 1.5), f"enemy auto-attack reliance {auto:g} across {n}")
    asp = count(enemies, lambda r: r.get("attackSpeedScaling") is True or r.get("scaling") == "on-hit")
    out["anti-attack-speed"] = (_clip((asp - 2) / 2), f"{asp} enemy attack-speed scaler{'s' * (asp != 1)}")
    burst = sum(r.get("burstShare") or 0 for r in enemies) / n
    out["anti-burst"] = (_clip((burst - 0.35) / 0.3), f"enemy burst share {burst:.0%}")
    heal = sum((r.get("selfHeal") or 0) + (r.get("allyHeal") or 0) for r in enemies)
    out["anti-heal"] = (_clip(heal / 800), f"enemy heals {heal:.0f} HP per 10 s")
    sh = sum((r.get("selfShield") or 0) + (r.get("allyShield") or 0) for r in enemies)
    out["anti-shield"] = (_clip(sh / 800), f"enemy shields {sh:.0f} HP per 10 s")
    ranged = count(enemies, lambda r: (r.get("attackRange") or 0) >= 500)
    dashes = sum(r.get("dashes") or 0 for r in enemies)
    out["anti-kite"] = (_clip((ranged - 2) / 2 * 0.6 + dashes / 8 * 0.4), f"{ranged} ranged, {dashes} dashes on the enemy team")
    bhp = sum(r.get("bonusHp") or 0 for r in enemies)
    out["anti-HP"] = (_clip(bhp / 2500), f"enemy bonus health {bhp:.0f}")
    arm = sum(r.get("armor") or 0 for r in enemies) / n
    out["anti-armor"] = (_clip((arm - 60) / 60), f"enemy average armor {arm:.0f}")
    mr = sum(r.get("mr") or 0 for r in enemies) / n
    out["anti-MR"] = (_clip((mr - 40) / 30), f"enemy average MR {mr:.0f}")
    mag = sum((r.get("magicShare") or 0) * (1 - (r.get("burstShare") or 0)) for r in enemies) / n
    out["anti-burn"] = (_clip((mag - 0.2) / 0.25), f"enemy sustained magic share {mag:.0%}")
    ten, read = _sum(enemies, "tenacityCC")
    out["tenacity"] = (_clip((ten / n - 3) / 4), f"enemy CC tenacity shortens {ten:.1f} s per 10 s" if read else
                       "the CC split (tenacityCC) is not baked yet, so tenacity is not scored")
    sup, _ = _sum(enemies, "suppressCC")
    out["cleanse"] = (_clip(((ten + sup) / n - 3) / 4), f"enemy cleansable CC {ten + sup:.1f} s per 10 s" if read else
                      "the CC split is not baked yet, so cleanse is not scored")
    st = [r["name"] for r in enemies if r.get("stealth") is True]
    out["anti-invisibility"] = (_clip(len(st) / 1.5), f"stealth: {', '.join(st)}" if st else "no enemy stealth")
    # The traits store's `vision` flag means "grants vision" (123 of 173 champions), not ward
    # reliance, so anti-vision reads trap setters by name plus stealth.
    vis = [r["name"] for r in enemies if r["name"] in TRAPS]
    out["anti-vision"] = (_clip((len(vis) + len(st) / 2) / 1.5), f"traps or stealth: {', '.join(vis + st)}"
                          if vis or st else "no enemy traps or stealth")
    m = len(allies) or 1
    am = sum(r.get("magicShare") or 0 for r in allies) / m
    out["magic amp"] = (_clip((am - 0.3) / 0.3), f"your team's magic share {am:.0%}")
    ap_ = sum(r.get("physicalShare") or 0 for r in allies) / m
    out["physical amp"] = (_clip((ap_ - 0.4) / 0.3), f"your team's physical share {ap_:.0%}")
    aa, _ = _sum(allies, "autoReliance")
    out["attack-speed buff"] = (_clip((aa / m - 2) / 1.5), f"your team's auto-attack reliance {aa:g}")
    apc = count(allies, lambda r: r.get("scaling") == "ap")
    out["AP buff"] = (_clip(apc / 3), f"{apc} AP carr{'y' if apc == 1 else 'ies'} on your team")
    eng = count(allies, lambda r: (r.get("engage") or 0) >= 4)
    out["move-speed buff"] = (_clip(eng / 3), f"{eng} strong engager{'s' * (eng != 1)} on your team")
    return out


def item_score(item: dict, th: dict, phys: float, magic: float) -> tuple[float, list[str]]:
    """Counter score of one catalog item: resist and health stats against the enemy damage
    mix, then each counter tag's threat. Returns (score, why lines)."""
    st = {s.split(" ", 1)[1]: float(s.split(" ", 1)[0].rstrip("%")) for s in item.get("st") or []
          if " " in s and s.split(" ", 1)[0].rstrip("%").replace(".", "").isdigit()}
    score, why = 0.0, []
    if st.get("Armor"):
        v = st["Armor"] / 60 * phys
        score += v
        why.append(f"{st['Armor']:g} armor vs {phys:.0%} physical enemy damage")
    if st.get("Magic Resist"):
        v = st["Magic Resist"] / 60 * magic
        score += v
        why.append(f"{st['Magic Resist']:g} MR vs {magic:.0%} magic enemy damage")
    if st.get("Health"):
        score += st["Health"] / 800
    for t in counter_tags(item["n"]):
        v, w = th.get(t, (0.0, ""))
        if t == "anti-burst" and item["n"] in MAGIC_ONLY:
            v, w = v * magic, f"{w}, magic only"
        elif t == "anti-burst" and item["n"] in PHYS_ONLY:
            v, w = v * phys, f"{w}, physical only"
        if v > 0.05:
            score += v
            why.append(f"{t}: {w}")
    return round(score, 2), why


def demo():
    it = lambda i, g, t, st: {"id": i, "g": g, "t": t, "st": st}  # noqa: E731
    ie = it(3031, 3500, ["CriticalStrike", "Damage"], ["75 Attack Damage", "25% Critical Strike Chance"])
    ss = it(6610, 3100, ["Health", "Damage"], ["40 Attack Damage", "400 Health"])
    lia = it(6653, 3000, ["Health", "SpellDamage"], ["60 Ability Power", "300 Health"])
    js = it(6665, 3200, ["Health", "Armor"], ["350 Health", "45 Armor", "45 Magic Resist"])
    wit = it(3091, 2800, ["SpellBlock", "AttackSpeed", "OnHit"], ["50% Attack Speed", "45 Magic Resist"])
    assert item_styles(ie) == {"crit"} and item_styles(ss) == {"bruiser"}
    assert item_styles(lia) == {"burn AP"} and item_styles(js) == {"tank"} and item_styles(wit) == {"on-hit"}
    assert item_styles(it(1001, 300, ["Boots"], ["25 Move Speed"])) == set()
    by = {"3031": {"crit"}, "6610": {"bruiser"}, "6653": {"burn AP"}}
    roles = {"bot": {"items": {"3031": {"1": {"pick": 60, "n": 600}, "2": {"pick": 50, "n": 500}},
                               "6653": {"1": {"pick": 1, "n": 10}}}},
             "top": {"items": {"6610": {"1": {"pick": 20, "n": 200}, "4": {"pick": 90, "n": 900}}}}}
    got = champion_styles(roles, by)
    assert [(r["style"], r["tier"]) for r in got] == [("crit", "main"), ("bruiser", "common")], got
    assert got[1]["score"] == 0.2 and got[1]["games"] == 200        # slot 4 not counted
    got = champion_styles(roles, by, [{"games": 35, "full": [{"items": [6653, 3031]}]}])
    assert got[-1] == {"style": "burn AP", "score": 0.01, "games": 45, "tier": "niche"}, got  # ARAM lifts it
    assert champion_styles({"x": None}, by) == []
    # counters: Randuin's beats Maw against an all-crit physical team; tenacity is zero
    # against a J4 whose hard CC is all knockup (Sam, 2026-11-05)
    crit = {"name": "MF", "scaling": "crit", "autoReliance": 3, "physicalShare": 1, "burstShare": 0.4, "tenacityCC": 0}
    j4 = {"name": "J4", "scaling": "bruiser", "physicalShare": 1, "burstShare": 0.5, "tenacityCC": 0.0,
          "airborneCC": 2.25, "suppressCC": 0.0}
    th = threats([crit, crit, crit, j4], [])
    rand = {"n": "Randuin's Omen", "st": ["350 Health", "75 Armor"]}
    maw = {"n": "Maw of Malmortius", "st": ["60 Attack Damage", "40 Magic Resist"]}
    merc = {"n": "Mercury's Treads", "st": ["20 Magic Resist", "45 Move Speed"]}
    assert item_score(rand, th, 1.0, 0.0)[0] > item_score(maw, th, 1.0, 0.0)[0]
    assert th["tenacity"][0] == 0 and not any("tenacity" in w for w in item_score(merc, th, 1.0, 0.0)[1])
    assert threats([crit, j4], [])["anti-crit"][0] < 0.5       # one crit carry is an average draft
    assert th["anti-crit"][0] == 1.0 and "anti-crit" in " ".join(item_score(rand, th, 1.0, 0.0)[1])
    assert threats([{"name": "X"}], [])["tenacity"][1].startswith("the CC split")  # unbaked reads as unscored
    assert check_counters({"Thornmail"}) and "Thornmail" not in check_counters({"Thornmail"})
    print("build_styles ok")


if __name__ == "__main__":
    demo()

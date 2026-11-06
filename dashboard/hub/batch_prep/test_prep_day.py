"""Standalone test of the Phase C-v2 prep-day engine (db.create_prep_day + helpers).

Builds a minimal jc-like schema in a temp file and seeds synthetic recipes that
exercise the ground-up reshape in the cards' OWN units: the raw stage pooling every
smallest part across batches AND full prep batches (juice + dry/wet goods) in
original units, combined mixed-unit totals on one line (R1 — grams in the chip,
quarts/oz kept verbatim, never converted), build-up steps reproducing each card
recipe + its method line, and assemble steps with the full pull-together + method.
Run: `python3 test_prep_day.py`.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import db as prep  # the module under test (run from its own folder)

_SCHEMA = """
CREATE TABLE recipes (
    id INTEGER PRIMARY KEY, kind TEXT, name TEXT, method TEXT,
    yield_qty REAL, yield_unit TEXT, category TEXT, menu TEXT,
    lead_minutes INTEGER, lead_label TEXT
);
CREATE TABLE recipe_ingredients (
    id INTEGER PRIMARY KEY, recipe_id INTEGER, ingredient TEXT, amount TEXT,
    sort_order INTEGER DEFAULT 0, qty REAL, unit TEXT,
    scalable INTEGER DEFAULT 1, produces_recipe_id INTEGER
);
CREATE TABLE prep_day (
    id INTEGER PRIMARY KEY,
    started TEXT NOT NULL DEFAULT (datetime('now')),
    cleared TEXT
);
CREATE TABLE prep_day_selection (
    prep_day_id INTEGER NOT NULL, recipe_id INTEGER NOT NULL,
    stage INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (prep_day_id, recipe_id)
);
CREATE TABLE prep_day_step (
    id INTEGER PRIMARY KEY, prep_day_id INTEGER NOT NULL, seq INTEGER NOT NULL,
    phase TEXT NOT NULL, label TEXT NOT NULL, qty_g REAL,
    note TEXT, qty_extra TEXT, lead_label TEXT,
    stage INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE prep_day_step_component (
    id INTEGER PRIMARY KEY, step_id INTEGER NOT NULL, seq INTEGER NOT NULL,
    name TEXT NOT NULL, qty_g REAL, unit TEXT, label TEXT,
    checked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE ingredient_tier (
    name TEXT PRIMARY KEY, tier INTEGER NOT NULL, note TEXT
);
"""


def _seed(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    recipes = [
        # id, kind, name, method, yield_qty, lead_minutes, lead_label
        (100, "batch", "Alpha", "Alpha method", 5000.0, None, None),
        (101, "batch", "Beta", None, 4000.0, None, None),
        # two depth-1 preps with different brew times → build-up sorts longest-first:
        # Cordial (3 hr) must precede Tea (10 min) even though it's later alphabetically
        (200, "prep", "Citrus Cordial", None, None, 180, "macerate 3 hr"),
        (300, "prep", "Jasmine Tea", "Steep 10 min", None, 10, "steep 10 min"),
    ]
    conn.executemany(
        "INSERT INTO recipes (id, kind, name, method, yield_qty, lead_minutes, lead_label, yield_unit) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'g')",
        recipes,
    )
    ings = [
        # recipe_id, ingredient, amount, qty, unit, scalable, produces_recipe_id
        # Alpha: direct gram juice + two made preps + to-taste + gram milk
        (100, "lemon juice", "1000g", 1000.0, "g", 1, None),
        (100, "citrus cordial", None, 500.0, "g", 1, 200),
        (100, "jasmine tea", None, 800.0, "g", 1, 300),
        (
            100,
            "Demerara",
            "to taste",
            None,
            None,
            0,
            None,
        ),  # to-taste → no raw, but a component
        (100, "whole milk", "800g", 800.0, "g", 1, None),
        # Beta: more lemon juice (aggregates) + milk in QUARTS (R1 mixed-unit raw)
        (101, "lemon juice", "250g", 250.0, "g", 1, None),
        (101, "whole milk", "2 quart", 2.0, "quart", 1, None),
        # Citrus Cordial (200) full batch — juices in quarts, sugar in oz
        (200, "lemon juice", "2 QT (64 oz)", 2.0, "quart", 1, None),
        (200, "lime juice", "2 QT (64 oz)", 2.0, "quart", 1, None),
        (200, "orange juice", "1 QT (32 oz)", 1.0, "quart", 1, None),
        (200, "sugar", "64 oz", 64.0, "oz", 1, None),
        # Jasmine Tea (300) full batch — amount left NULL to test the qty/unit fallback
        (300, "hot water", None, 128.0, "oz", 1, None),
        (300, "tea leaves", None, 2.0, "oz", 1, None),
    ]
    conn.executemany(
        "INSERT INTO recipe_ingredients "
        "(recipe_id, ingredient, amount, qty, unit, scalable, produces_recipe_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ings,
    )
    # reasoned tier classification (migration 008 / seed) for the synthetic raws
    tiers = [
        ("lemon juice", 0),
        ("lime juice", 0),
        ("orange juice", 0),
        ("sugar", 1),
        ("hot water", 1),
        ("tea leaves", 1),
        ("whole milk", 3),
    ]
    conn.executemany("INSERT INTO ingredient_tier (name, tier) VALUES (?, ?)", tiers)
    conn.commit()
    conn.close()


def _approx(a, b, tol=0.05):
    return a is not None and b is not None and abs(a - b) <= tol


def run() -> None:
    passed = 0
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "jc_test.db"
        _seed(path)
        prep.init(path)
        out = prep.create_prep_day([100, 101])
        steps = out["steps"]

        def step(phase, label_contains):
            for s in steps:
                if s["phase"] == phase and label_contains in s["label"]:
                    return s
            return None

        def comp(s, name_contains):
            for c in s.get("components") or []:
                if name_contains.lower() in c["name"].lower():
                    return c
            return None

        # ── raw stage: name on the LEFT (label), all quantities on the RIGHT ──
        # lemon juice: Alpha 1000 g + Beta 250 g (gram chip) + Cordial 2 quart (extra)
        lemon = step("raw", "lemon juice")
        assert lemon and lemon["label"] == "lemon juice", (
            f"lemon label: {lemon}"
        )  # no unit in title
        assert _approx(lemon["qty_g"], 1250.0) and "2 quart" in lemon["qty_extra"], (
            f"lemon: {lemon}"
        )
        passed += 1

        # R1 mixed non-juice raw: whole milk = 800 g (Alpha) + 2 quart (Beta), never crossed;
        # gram part in qty_g, the quart part in qty_extra
        milk = step("raw", "whole milk")
        assert (
            milk and milk["label"] == "whole milk" and _approx(milk["qty_g"], 800.0)
        ), f"milk: {milk}"
        assert "2 quart" in milk["qty_extra"], f"milk extra: {milk}"
        passed += 1

        # full-batch prep raws pooled in original units (cordial quarts, sugar oz);
        # count units pluralise on the right
        lime = step("raw", "lime juice")
        assert lime and lime["qty_g"] is None and lime["qty_extra"] == "2 quarts", (
            f"lime: {lime}"
        )
        passed += 1
        sugar = step("raw", "sugar")
        assert sugar and sugar["qty_g"] is None and sugar["qty_extra"] == "64 oz", (
            f"sugar: {sugar}"
        )
        passed += 1
        water = step("raw", "hot water")
        assert water and water["qty_extra"] == "128 oz", f"water: {water}"
        passed += 1

        # to-taste (Demerara) is not pre-gathered → no raw line
        assert not any(
            s["phase"] == "raw" and "demerara" in s["label"].lower() for s in steps
        )
        passed += 1

        # ── build-up stage (full card recipe + method) ──
        cordial = step("build-up", "Citrus Cordial")
        assert (
            cordial and _approx(cordial["qty_g"], 500.0) and cordial["note"] is None
        ), f"cordial: {cordial}"
        passed += 1
        assert len(cordial["components"]) == 4, (
            f"cordial comps: {cordial['components']}"
        )
        passed += 1
        # verbatim card text preserved (original units, not grams)
        clem = comp(cordial, "lemon juice")
        assert clem and clem["label"] == "2 QT (64 oz)" and clem["qty_g"] is None, (
            f"cordial lemon: {clem}"
        )
        passed += 1
        csugar = comp(cordial, "sugar")
        assert csugar and csugar["label"] == "64 oz", f"cordial sugar: {csugar}"
        passed += 1

        tea = step("build-up", "Jasmine Tea")
        assert tea and tea["note"] == "Steep 10 min", f"tea note: {tea}"
        passed += 1
        # amount NULL → fallback renders qty + original unit, not grams
        thw = comp(tea, "hot water")
        assert thw and thw["label"] == "128 oz", f"tea hot water: {thw}"
        passed += 1

        # ── brew-time priority: build-up sorts longest-wait first within a depth ──
        # Cordial (180 min) precedes Tea (10 min) though it sorts later alphabetically;
        # each build-up step carries its lead_label; raw/assemble carry None.
        assert cordial["lead_label"] == "macerate 3 hr", f"cordial lead: {cordial}"
        assert tea["lead_label"] == "steep 10 min", f"tea lead: {tea}"
        bu_seq = [s["label"] for s in steps if s["phase"] == "build-up"]
        assert bu_seq.index("Citrus Cordial") < bu_seq.index("Jasmine Tea"), bu_seq
        assert all(s.get("lead_label") is None for s in steps if s["phase"] == "raw"), (
            "raw steps must carry no lead_label"
        )
        passed += 1

        # ── phase ordering: raw < build-up < assemble ──
        order = {"raw": 0, "build-up": 1, "assemble": 2}
        phases_in_seq = [s["phase"] for s in steps]
        assert phases_in_seq == sorted(phases_in_seq, key=lambda p: order[p]), (
            phases_in_seq
        )
        passed += 1

        # ── raw tiers come from the reasoned ingredient_tier table (Sam 2026-06-06) ──
        # lookup helper: case-insensitive, and any unclassified name → pantry default
        with sqlite3.connect(path) as tc:
            tc.row_factory = sqlite3.Row
            tmap = prep._load_tier_map(tc)
        assert tmap == {
            "lemon juice": 0,
            "lime juice": 0,
            "orange juice": 0,
            "sugar": 1,
            "hot water": 1,
            "tea leaves": 1,
            "whole milk": 3,
        }, tmap
        assert (
            prep._tier_of("Whole Milk", tmap) == 3
            and prep._tier_of("LEMON JUICE", tmap) == 0
        ), "case-insensitive"
        assert (
            prep._tier_of("never-seen ingredient", tmap) == prep._DEFAULT_TIER == 1
        ), "unknown → pantry default"
        passed += 1

        # raw step sequence honours the gradient: fresh juice < pantry < refrigerated
        raw_seq = [s["label"] for s in steps if s["phase"] == "raw"]
        assert (
            raw_seq.index("lemon juice")
            < raw_seq.index("sugar")
            < raw_seq.index("whole milk")
        ), raw_seq
        passed += 1

        # raw steps carry a human tier label (drives the UI sub-headers); non-raw
        # steps carry none. Labels match _TIER_LABEL exactly.
        assert (
            lemon["tier"] == "Fresh"
            and sugar["tier"] == "Pantry"
            and milk["tier"] == "Refrigerated"
        ), f"tiers: {lemon['tier']}, {sugar['tier']}, {milk['tier']}"
        assert all(s.get("tier") is None for s in steps if s["phase"] != "raw"), (
            "non-raw tier must be None"
        )
        passed += 1

        # ── assemble stage (full pull-together + method) ──
        a = step("assemble", "Alpha")
        b = step("assemble", "Beta")
        assert a and _approx(a["qty_g"], 5000.0) and a["note"] == "Alpha method", (
            f"alpha: {a}"
        )
        passed += 1
        assert b and _approx(b["qty_g"], 4000.0) and b["note"] is None, f"beta: {b}"
        passed += 1
        # Alpha pulls 5 lines incl. the made preps (by produced name) + the to-taste
        assert len(a["components"]) == 5, f"alpha comps: {a['components']}"
        passed += 1
        assert (
            comp(a, "Citrus Cordial") is not None and comp(a, "Jasmine Tea") is not None
        )
        dem = comp(a, "Demerara")
        assert dem and dem["label"] == "to taste", f"alpha demerara: {dem}"
        passed += 1
        # earliest completion = parallel-brews critical path. Alpha's slowest prep is
        # Cordial (180 min) → "~3 hr"; Beta has no preps → no ETA.
        assert a["lead_label"] == "earliest ready ~3 hr", (
            f"alpha eta: {a['lead_label']}"
        )
        assert b["lead_label"] is None, f"beta eta: {b['lead_label']}"
        passed += 1

        # ── persistence: active fetch round-trips (components + note), toggle, reset ──
        active = prep.get_active_prep_day()
        assert (
            active and active["id"] == out["id"] and len(active["steps"]) == len(steps)
        )
        tea2 = None
        for s in active["steps"]:
            if s["phase"] == "build-up" and "Jasmine Tea" in s["label"]:
                tea2 = s
        assert (
            tea2 and tea2["note"] == "Steep 10 min" and len(tea2["components"]) == 2
        ), f"reloaded tea: {tea2}"
        passed += 1
        # lead_label round-trips through the persisted day
        cordial2 = next(
            (
                s
                for s in active["steps"]
                if s["phase"] == "build-up" and "Citrus Cordial" in s["label"]
            ),
            None,
        )
        assert cordial2 and cordial2["lead_label"] == "macerate 3 hr", (
            f"reloaded cordial lead: {cordial2}"
        )
        passed += 1

        # the checkable unit is a component (build-up/assemble sub-item), not the step
        # header — toggle one on, off, and confirm a bad id returns None (→404).
        cid = next(c["id"] for s in active["steps"] for c in s["components"])
        assert (t := prep.toggle_component(cid)) is not None and t["checked"] == 1
        assert (t := prep.toggle_component(cid)) is not None and t["checked"] == 0
        assert prep.toggle_component(999999) is None
        passed += 1

        out2 = prep.create_prep_day([100])
        assert out2["id"] != out["id"]
        assert (a := prep.get_active_prep_day()) is not None and a["id"] == out2["id"]
        passed += 1

        assert prep.reset_prep_day()["cleared"] is True
        assert prep.get_active_prep_day() is None
        assert prep.reset_prep_day()["cleared"] is False
        passed += 1

        # ── list_recipes enrichment: the recipes-area list rows carry yield +
        #    the two counts that drive the meta line and the prep-vs-direct tag ──
        batches = prep.list_recipes("batch")
        by_name = {r["name"]: r for r in batches}
        alpha = by_name["Alpha"]
        for key in ("yield_qty", "yield_unit", "ingredient_count", "sub_count"):
            assert key in alpha, f"list row missing {key}: {alpha}"
        assert alpha["ingredient_count"] == 5 and alpha["sub_count"] == 2, (
            f"alpha counts: {alpha}"
        )
        assert by_name["Beta"]["sub_count"] == 0, f"beta sub_count: {by_name['Beta']}"
        preps = prep.list_recipes("prep")
        assert {r["name"] for r in preps} == {"Citrus Cordial", "Jasmine Tea"}, preps
        passed += 1

    print(f"OK — {passed}/{passed} prep-day assertions passed")


def run_lead_depth() -> None:
    """Dependency depth beats brew time: a deeper input prep is still made before a
    shallower long-brew prep it doesn't feed. Sort key (-depth, -lead_minutes, name):
    Inner (depth 2, 10 min) < Long (depth 1, 1440 min) < Outer (depth 1, 10 min).
    """
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "lead_depth.db"
        conn = sqlite3.connect(path)
        conn.executescript(_SCHEMA)
        conn.executemany(
            "INSERT INTO recipes (id, kind, name, method, yield_qty, lead_minutes, lead_label, yield_unit) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'g')",
            [
                (100, "batch", "B", None, 1000.0, None, None),
                (200, "prep", "Long", None, 1.0, 1440, "sous vide 24 hr"),
                (300, "prep", "Outer", None, 1.0, 10, "steep 10 min"),
                (400, "prep", "Inner", None, 1.0, 10, "steep 10 min"),
            ],
        )
        conn.executemany(
            "INSERT INTO recipe_ingredients "
            "(recipe_id, ingredient, amount, qty, unit, scalable, produces_recipe_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    100,
                    "Long",
                    None,
                    1.0,
                    "g",
                    1,
                    200,
                ),  # B uses Long (shallow, long brew)
                (
                    100,
                    "Outer",
                    None,
                    1.0,
                    "g",
                    1,
                    300,
                ),  # B uses Outer (shallow, short brew)
                (
                    300,
                    "Inner",
                    None,
                    1.0,
                    "g",
                    1,
                    400,
                ),  # Outer uses Inner (deeper, short brew)
                (200, "longraw", None, 1.0, "g", 1, None),
                (400, "innerraw", None, 1.0, "g", 1, None),
            ],
        )
        conn.commit()
        conn.close()
        prep.init(path)
        steps = prep.create_prep_day([100])["steps"]
        bu = [s["label"] for s in steps if s["phase"] == "build-up"]
        assert bu == ["Inner", "Long", "Outer"], bu
        # critical path: Long chain (1440) beats Outer+Inner (10+10=20) → B ready ~1 day
        b = next(s for s in steps if s["phase"] == "assemble")
        assert b["lead_label"] == "earliest ready ~1 day", f"B eta: {b['lead_label']}"
    print("OK — depth-beats-brew-time ordering + critical-path ETA verified")


def run_staged_additions() -> None:
    """add_to_prep_day appends a standalone stage without touching the original.

    Stage 0 is the initial build; an add appends stage 1 as its own self-contained
    raw → build-up → assemble block after every existing step, with seq continuing
    from the max. Prior steps + their check state are preserved byte-for-byte.
    """
    passed = 0
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "staged.db"
        _seed(path)
        prep.init(path)

        # stage 0 — Alpha only
        s0 = prep.create_prep_day([100])
        assert all(st["stage"] == 0 for st in s0["steps"]), (
            "initial build must be stage 0"
        )
        assert all(sel["stage"] == 0 for sel in s0["selection"]), (
            "initial selection stage 0"
        )
        passed += 1

        # snapshot stage 0, and check a stage-0 component off
        before = [(st["id"], st["seq"], st["label"], st["phase"]) for st in s0["steps"]]
        max_seq0 = max(st["seq"] for st in s0["steps"])
        checked_cid = next(c["id"] for st in s0["steps"] for c in st["components"])
        assert (t := prep.toggle_component(checked_cid)) is not None and t["checked"] == 1
        passed += 1

        # add Beta → a new stage 1 appended after everything
        s1 = prep.add_to_prep_day([101])
        by_stage = {}
        for st in s1["steps"]:
            by_stage.setdefault(st["stage"], []).append(st)
        assert set(by_stage) == {0, 1}, f"stages present: {set(by_stage)}"
        passed += 1

        # stage-0 steps are unchanged: same ids, seq, labels, phases — and the check survived
        after0 = [(st["id"], st["seq"], st["label"], st["phase"]) for st in by_stage[0]]
        assert after0 == before, f"stage 0 mutated:\n{before}\n{after0}"
        survived = next(
            c for st in by_stage[0] for c in st["components"] if c["id"] == checked_cid
        )
        assert survived["checked"] == 1, "a stage-0 component check must survive an add"
        passed += 1

        # stage 1 is a full ground-up block (its own raw/build-up/assemble), seq continues
        s1_phases = [st["phase"] for st in by_stage[1]]
        assert "raw" in s1_phases and "assemble" in s1_phases, (
            f"stage 1 phases: {s1_phases}"
        )
        assert min(st["seq"] for st in by_stage[1]) == max_seq0 + 1, (
            "seq must continue from the max"
        )
        assert [st["seq"] for st in s1["steps"]] == sorted(
            st["seq"] for st in s1["steps"]
        ), "seq monotonic"
        # Beta assembles in stage 1; its selection carries stage 1
        assert any(
            st["phase"] == "assemble" and "Beta" in st["label"] for st in by_stage[1]
        )
        beta_sel = next(sel for sel in s1["selection"] if sel["recipe_id"] == 101)
        assert beta_sel["stage"] == 1, f"beta selection stage: {beta_sel}"
        passed += 1

        # no repeat batches: re-adding a recipe already in the day is rejected
        try:
            prep.add_to_prep_day([100])
            raise AssertionError("re-adding an in-plan recipe should raise")
        except ValueError as e:
            assert "already" in str(e), f"unexpected message: {e}"
        passed += 1
        # a mixed pick drops the in-plan id and adds only the new one (stage 2)
        s2 = prep.add_to_prep_day([100, 200])
        sel200 = next(sel for sel in s2["selection"] if sel["recipe_id"] == 200)
        assert sel200["stage"] == 2, f"cordial selection stage: {sel200}"
        assert sum(1 for sel in s2["selection"] if sel["recipe_id"] == 100) == 1, (
            "no duplicate id 100"
        )
        passed += 1

        # add with no active day raises
        prep.reset_prep_day()
        try:
            prep.add_to_prep_day([100])
            raise AssertionError("add with no active day should raise")
        except ValueError as e:
            assert "no active" in str(e), f"unexpected message: {e}"
        passed += 1

    print(f"OK — {passed}/{passed} staged-addition assertions passed")


def run_component_checks() -> None:
    """The check lives on the recipe sub-item (Stage B), not the step header.

    toggle_component flips a single composition row's `checked`, it round-trips
    through get_active_prep_day, and it's independent of every other component.
    """
    passed = 0
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "comp_checks.db"
        _seed(path)
        prep.init(path)

        prep.create_prep_day([100])  # Alpha — build-up + assemble carry components
        active = prep.get_active_prep_day()
        assert active is not None
        # pick a build-up step that actually has composition rows
        step = next(
            s
            for s in active["steps"]
            if s["phase"] in ("build-up", "assemble") and s["components"]
        )
        comps = step["components"]
        assert all("id" in c and c["checked"] == 0 for c in comps), (
            f"fresh comps: {comps}"
        )
        passed += 1

        cid = comps[0]["id"]
        assert prep.toggle_component(cid) == {"id": cid, "checked": 1}
        assert prep.toggle_component(cid) == {"id": cid, "checked": 0}
        assert (tc := prep.toggle_component(cid)) is not None and tc["checked"] == 1  # leave it checked
        assert prep.toggle_component(999999) is None
        passed += 1

        # the check round-trips through a fresh read, and ONLY that component flipped
        reread = prep.get_active_prep_day()
        assert reread is not None
        rstep = next(s for s in reread["steps"] if s["id"] == step["id"])
        target = next(c for c in rstep["components"] if c["id"] == cid)
        assert target["checked"] == 1, f"check did not persist: {target}"
        others = [c for c in rstep["components"] if c["id"] != cid]
        assert all(c["checked"] == 0 for c in others), (
            f"sibling components flipped: {others}"
        )
        passed += 1

        prep.reset_prep_day()
    print(f"OK — {passed}/{passed} component-check assertions passed")


if __name__ == "__main__":
    run()
    run_lead_depth()
    run_staged_additions()
    run_component_checks()

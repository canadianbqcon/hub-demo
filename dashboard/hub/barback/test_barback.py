"""pytest for the barback module db layer.

Runs from anywhere, including a whole-tree `pytest` from the repo root.

The import below is load-bearing, not boilerplate. Ten modules under
dashboard/hub/ are named db.py, so a bare `import db` binds whichever one
reached sys.modules first -- the repo-root `db/` migration directory (as an
empty namespace package) when this file runs alone, and finances/db.py when it
runs after the finances tests. Both produced `module 'db' has no attribute ...`
rather than an ImportError naming the cause, and the wreckage cascaded into
tests/test_earnings_api.py and tests/test_google_auth.py. Importing through the
`barback` package is what makes the name unambiguous.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_BARBACK = Path(__file__).resolve().parent           # dashboard/hub/barback/
sys.path.insert(0, str(_BARBACK.parent))             # dashboard/hub/, for `barback`
sys.path.insert(1, str(_BARBACK.parent.parent))      # dashboard/, for sqlite_helpers

from barback import db as barback_db   # noqa: E402  # pyright: ignore[reportMissingImports]
assert Path(barback_db.__file__).parent == _BARBACK, (
    f"imported the wrong db module: {barback_db.__file__}"
)


def test_bar_date_before_5am_is_previous_day():
    # 01:30 on the 19th is still the bar-day that started on the 18th.
    assert barback_db.bar_date(datetime(2026, 6, 19, 1, 30)) == "2026-06-18"


def test_bar_date_at_0459_is_previous_day():
    assert barback_db.bar_date(datetime(2026, 6, 19, 4, 59)) == "2026-06-18"


def test_bar_date_at_0500_is_same_day():
    assert barback_db.bar_date(datetime(2026, 6, 19, 5, 0)) == "2026-06-19"


def test_bar_date_afternoon_is_same_day():
    assert barback_db.bar_date(datetime(2026, 6, 19, 17, 0)) == "2026-06-19"


import importlib
import sqlite3 as _sqlite3

import pytest


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """A work.db copy with migration-014 tables + seeds applied, pointed at by db."""
    # Build a throwaway db carrying only the tables this module owns.
    p = tmp_path / "work.db"
    conn = _sqlite3.connect(p)
    conn.executescript(_SCHEMA_014)  # defined at bottom of this test file
    conn.commit()
    conn.close()
    barback_db.init(p)
    from barback import seed_checklists, seed_stock_raw
    importlib.reload(seed_checklists)
    importlib.reload(seed_stock_raw)
    seed_checklists.run()
    seed_stock_raw.run()
    return p


def test_seed_creates_four_templates(seeded_db):
    with barback_db._conn() as conn:
        rows = conn.execute("SELECT key, kind FROM checklist_template").fetchall()
    keys_kinds = {r[0]: r[1] for r in rows}
    assert sorted(keys_kinds.keys()) == [
        "closing_barback", "lowboy_fill", "opening_barback", "stock_check",
    ]
    assert keys_kinds["stock_check"] == "stock"
    assert keys_kinds["opening_barback"] == "duty"
    assert keys_kinds["closing_barback"] == "duty"
    # Counted since migration 017 — a re-seed must not flip it back to 'duty'.
    assert keys_kinds["lowboy_fill"] == "fill"


def test_opening_template_has_items_with_deadlines(seeded_db):
    with barback_db._conn() as conn:
        rows = conn.execute(
            "SELECT i.text, i.deadline, i.priority, i.detail FROM checklist_template_item i "
            "JOIN checklist_template t ON t.id=i.template_id "
            "WHERE t.key='opening_barback' ORDER BY i.sort_order"
        ).fetchall()
    texts = [r[0] for r in rows]
    deadlines = [r[1] for r in rows]
    assert any("Ice in all the wells" in t for t in texts)
    assert any(r[1] == "17:00" for r in rows)  # 5:00 pm deadline chip present
    assert len(rows) == 13
    non_empty_deadlines = {d for d in deadlines if d}
    assert non_empty_deadlines == {"17:00", "17:30", "17:45"}
    # The bar gets married and set up BEFORE ice goes in the wells — Sam's
    # own order (2026-07-29). Ice-on-arrival is the shape this replaced, so a
    # revert to it fails here.
    assert texts.index("Marry the bottles") < texts.index("Ice in all the wells")
    # Alcohol is stocked straight after beverages, upstairs — not left to the
    # downstairs leg where it used to sit.
    assert texts.index("Stock alcohol") == texts.index("Stock beverages") + 1
    # Going downstairs is gated on the bar being fully stocked, so the gate
    # rides the first downstairs step.
    gate_item = next(r for r in rows if r[0].startswith("Slice the cucumbers"))
    assert "fully stocked before you go down" in gate_item["detail"]
    assert gate_item["priority"] == "red"


def test_stock_check_template_has_no_template_items(seeded_db):
    with barback_db._conn() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM checklist_template_item i "
            "JOIN checklist_template t ON t.id=i.template_id WHERE t.key='stock_check'"
        ).fetchone()[0]
    assert n == 0


def test_closing_template_sections(seeded_db):
    with barback_db._conn() as conn:
        rows = conn.execute(
            "SELECT i.text, i.section, i.deadline FROM checklist_template_item i "
            "JOIN checklist_template t ON t.id=i.template_id "
            "WHERE t.key='closing_barback' ORDER BY i.sort_order"
        ).fetchall()
    assert len(rows) > 0  # closing template has items
    sections = [r["section"] for r in rows]
    # Phases in Sam's run order (2026-08-02), not topic groups. A revert to
    # the old flat Bar/Downstairs/Safety shape fails here.
    assert dict.fromkeys(sections) == dict.fromkeys([
        "During service", "Downstairs · by 10pm", "Service ends",
        "Everyone's gone", "Safety",
    ])
    texts = [r["text"] for r in rows]
    # Most of the close happens during service; the after-hours block is short.
    assert texts.index("Burn extra ice") < texts.index("Finish the glassware")
    # The downstairs leg is the only one with a hard clock on it.
    assert {r["deadline"] for r in rows if r["deadline"]} == {"22:00"}
    # Enforced duties his walkthrough didn't name must survive the reorder.
    for enforced in ("Clean inside dishwasher", "Bleach down drains",
                     "Kitchen garbage + gas off", "Overnight soak / strain handled"):
        assert enforced in texts


def _add_lowboy_tree(db_path, items):
    """Minimal Bar Room > Lowboy > Bottom storage tree holding `items`."""
    conn = _sqlite3.connect(db_path)
    conn.executescript("""
CREATE TABLE IF NOT EXISTS storage_area (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS storage_unit (id INTEGER PRIMARY KEY, area_id INTEGER, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS storage_section (id INTEGER PRIMARY KEY, unit_id INTEGER, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS storage_item (id INTEGER PRIMARY KEY, section_id INTEGER, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS storage_item_cover (item_id INTEGER NOT NULL, product TEXT NOT NULL,
    PRIMARY KEY (item_id, product));
INSERT INTO storage_area(id, name) VALUES (1, 'Bar Room');
INSERT INTO storage_unit(id, area_id, name) VALUES (1, 1, 'Lowboy');
INSERT INTO storage_section(id, unit_id, name) VALUES (1, 1, 'Bottom');
""")
    conn.executemany("INSERT INTO storage_item(section_id, text) VALUES (1, ?)",
                     [(t,) for t in items])
    conn.commit()
    conn.close()


def test_covers_link_grouped_shelf_to_individual_products(seeded_db):
    """A grouped storage_item stands for the products the fill checklist counts."""
    from barback import seed_checklists
    _add_lowboy_tree(seeded_db, ["Service bottles", "Clarified Drinks", "Canisters"])
    seed_checklists.run()
    with barback_db._conn() as conn:
        rows = conn.execute(
            "SELECT i.text, c.product FROM storage_item_cover c "
            "JOIN storage_item i ON i.id = c.item_id"
        ).fetchall()
        products = {
            r[0] for r in conn.execute(
                "SELECT i.text FROM checklist_template_item i "
                "JOIN checklist_template t ON t.id = i.template_id "
                "WHERE t.key = 'lowboy_fill'")
        }
    covered = {}
    for label, product in rows:
        covered.setdefault(label, set()).add(product)
    assert covered["Canisters"] == {
        "Salted Coconut Foam", "Condensed Milk Cold Foam", "Boba Foam"}
    assert covered["Service bottles"] == {
        "Peachy River", "Chrysanthemum Kiss", "Pandan Colada", "Pretty in Pink"}
    # No members invented for the shelf whose contents aren't established.
    assert "Clarified Drinks" not in covered
    # Every link resolves to a real checklist row — this is what catches a rename
    # on either side, which is the whole reason the link exists.
    assert {p for _, p in rows} <= products
    # Idempotent: a re-seed replaces its own rows rather than duplicating them.
    seed_checklists.run()
    with barback_db._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM storage_item_cover").fetchone()[0] == 7


def test_covers_skipped_when_storage_tree_absent(seeded_db):
    """The fixture db has no storage tables; seeding must not blow up."""
    from barback import seed_checklists
    seed_checklists.run()
    with barback_db._conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'storage_item_cover'"
        ).fetchone()[0] == 0


def test_seeds_are_idempotent(seeded_db):
    from barback import seed_checklists, seed_stock_raw
    seed_checklists.run()  # second run
    seed_stock_raw.run()
    with barback_db._conn() as conn:
        templates = conn.execute("SELECT COUNT(*) FROM checklist_template").fetchone()[0]
        items_first = conn.execute("SELECT COUNT(*) FROM checklist_template_item").fetchone()[0]
        raws_first = conn.execute("SELECT COUNT(*) FROM stock_raw_item").fetchone()[0]
    seed_checklists.run()  # third run
    seed_stock_raw.run()
    with barback_db._conn() as conn:
        items_second = conn.execute("SELECT COUNT(*) FROM checklist_template_item").fetchone()[0]
        raws_second = conn.execute("SELECT COUNT(*) FROM stock_raw_item").fetchone()[0]
    assert templates == 4
    assert items_first == items_second  # checklist_template_item count stable
    assert raws_first == raws_second  # no duplication


def _add_recipes(rows):
    with barback_db._conn() as conn:
        for rid, kind, name, category in rows:
            conn.execute(
                "INSERT INTO recipes (id, kind, name, category) VALUES (?,?,?,?)",
                (rid, kind, name, category),
            )


def test_generate_stock_includes_batches_and_preps_not_cocktails(seeded_db):
    _add_recipes([
        (1, "batch", "Negroni Batch", "House Batch"),
        (2, "prep", "Citrus Cordial", "Cordial"),
        (3, "cocktail", "Old Fashioned", "Classics"),  # must NOT appear
    ])
    items = barback_db.generate_stock_items()
    texts = [i["text"] for i in items]
    assert "Negroni Batch" in texts
    assert "Citrus Cordial" in texts
    assert "Old Fashioned" not in texts


def test_generate_stock_applies_boba_alias(seeded_db):
    _add_recipes([(4, "prep", "Boba H2O", "Foam")])
    items = barback_db.generate_stock_items()
    texts = [i["text"] for i in items]
    assert "Boba foam" in texts
    assert "Boba H2O" not in texts


def test_generate_stock_appends_raw_goods_with_section(seeded_db):
    items = barback_db.generate_stock_items()
    limes = [i for i in items if i["text"] == "Lime"]
    assert limes and limes[0]["section"] == "Fresh juice"


def test_generate_stock_section_is_category(seeded_db):
    _add_recipes([(5, "batch", "Test Batch", "House Shot")])
    items = barback_db.generate_stock_items()
    tb = [i for i in items if i["text"] == "Test Batch"][0]
    assert tb["section"] == "House Shot"


def test_start_run_snapshots_duty_items(seeded_db):
    run = barback_db.start_run("opening_barback", datetime(2026, 6, 19, 17, 0))
    assert run["template_key"] == "opening_barback"
    assert run["kind"] == "duty"
    assert any("Ice in all" in i["text"] for i in run["items"])
    assert all(i["state"] == "open" for i in run["items"])


def test_start_run_is_idempotent_per_bar_day(seeded_db):
    a = barback_db.start_run("opening_barback", datetime(2026, 6, 19, 17, 0))
    b = barback_db.start_run("opening_barback", datetime(2026, 6, 19, 23, 0))  # same bar-day
    assert a["id"] == b["id"]  # resumed, not duplicated


def test_start_run_new_run_on_new_bar_day(seeded_db):
    a = barback_db.start_run("opening_barback", datetime(2026, 6, 19, 17, 0))
    b = barback_db.start_run("opening_barback", datetime(2026, 6, 20, 17, 0))
    assert a["id"] != b["id"]


def test_start_stock_run_uses_generated_items(seeded_db):
    _add_recipes([(1, "batch", "Negroni Batch", "House Batch")])
    run = barback_db.start_run("stock_check", datetime(2026, 6, 19, 17, 0))
    assert run["kind"] == "stock"
    texts = [i["text"] for i in run["items"]]
    assert "Negroni Batch" in texts
    assert "Lime" in texts


def test_reseed_does_not_mutate_active_run(seeded_db):
    run = barback_db.start_run("opening_barback", datetime(2026, 6, 19, 17, 0))
    original = [i["text"] for i in run["items"]]
    from barback import seed_checklists
    seed_checklists._TEMPLATES[0][3].append(("NEW LATER ITEM", "", "", "", ""))
    try:
        seed_checklists.run()  # template now has an extra item
        again = barback_db.get_run(run["id"])
        assert again is not None
        assert [i["text"] for i in again["items"]] == original  # run frozen
    finally:
        seed_checklists._TEMPLATES[0][3].pop()  # restore module state
        seed_checklists.run()


def test_set_item_state_duty(seeded_db):
    run = barback_db.start_run("opening_barback", datetime(2026, 6, 19, 17, 0))
    item_id = run["items"][0]["id"]
    updated = barback_db.set_item_state(item_id, "done")
    assert updated is not None
    assert updated["state"] == "done"
    assert updated["state_at"] is not None


def test_set_item_state_rejects_invalid_for_kind(seeded_db):
    run = barback_db.start_run("opening_barback", datetime(2026, 6, 19, 17, 0))
    with pytest.raises(ValueError):
        barback_db.set_item_state(run["items"][0]["id"], "low")  # stock state on a duty


def test_set_item_state_stock_three_state(seeded_db):
    _add_recipes([(1, "batch", "Negroni Batch", "House Batch")])
    run = barback_db.start_run("stock_check", datetime(2026, 6, 19, 17, 0))
    item_id = run["items"][0]["id"]
    low = barback_db.set_item_state(item_id, "low")
    out = barback_db.set_item_state(item_id, "out")
    assert low is not None and low["state"] == "low"
    assert out is not None and out["state"] == "out"


def test_completed_at_set_when_all_items_left_open(seeded_db):
    run = barback_db.start_run("opening_barback", datetime(2026, 6, 19, 17, 0))
    for it in run["items"]:
        barback_db.set_item_state(it["id"], "done")
    reloaded = barback_db.get_run(run["id"])
    assert reloaded is not None
    assert reloaded["completed_at"] is not None


def test_completed_at_cleared_when_item_reopened(seeded_db):
    run = barback_db.start_run("opening_barback", datetime(2026, 6, 19, 17, 0))
    for it in run["items"]:
        barback_db.set_item_state(it["id"], "done")
    reloaded = barback_db.get_run(run["id"])
    assert reloaded is not None
    assert reloaded["completed_at"] is not None
    barback_db.set_item_state(run["items"][0]["id"], "open")  # reopen one
    reloaded2 = barback_db.get_run(run["id"])
    assert reloaded2 is not None
    assert reloaded2["completed_at"] is None


# The owned-table subset of migration 014, inlined so tests need no real work.db.
_SCHEMA_014 = """
CREATE TABLE checklist_template (id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL, kind TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0) STRICT;
CREATE TABLE checklist_template_item (id INTEGER PRIMARY KEY,
  template_id INTEGER NOT NULL REFERENCES checklist_template(id) ON DELETE CASCADE,
  text TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', section TEXT NOT NULL DEFAULT '',
  deadline TEXT NOT NULL DEFAULT '', priority TEXT NOT NULL DEFAULT '',
  sort_order INTEGER NOT NULL DEFAULT 0) STRICT;
CREATE TABLE checklist_run (id INTEGER PRIMARY KEY,
  template_id INTEGER NOT NULL REFERENCES checklist_template(id), bar_date TEXT NOT NULL,
  started_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', completed_at TEXT) STRICT;
CREATE TABLE checklist_run_item (id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES checklist_run(id) ON DELETE CASCADE,
  text_snapshot TEXT NOT NULL, detail_snapshot TEXT NOT NULL DEFAULT '',
  section TEXT NOT NULL DEFAULT '', deadline TEXT NOT NULL DEFAULT '',
  priority TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'open',
  state_at TEXT, sort_order INTEGER NOT NULL DEFAULT 0) STRICT;
CREATE TABLE stock_raw_item (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  category TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0) STRICT;
CREATE TABLE recipes (id INTEGER PRIMARY KEY, kind TEXT, name TEXT, category TEXT);
CREATE TABLE recipe_ingredients (id INTEGER PRIMARY KEY, recipe_id INTEGER,
  ingredient TEXT, produces_recipe_id INTEGER);
CREATE TABLE ingredient_location (name TEXT PRIMARY KEY, location TEXT NOT NULL,
  note TEXT) STRICT;
"""


def test_lazy_archival_archives_prior_day_run(seeded_db):
    run = barback_db.start_run("opening_barback", datetime(2026, 6, 19, 17, 0))
    barback_db.set_item_state(run["items"][0]["id"], "done")  # partial
    # Starting any run on a later bar-day archives the stale one. Archival hangs
    # off start_run since the Today summary read (its old trigger) was deleted.
    barback_db.start_run("closing_barback", datetime(2026, 6, 21, 17, 0))
    archived = barback_db.get_run(run["id"])
    assert archived is not None
    assert archived["status"] == "archived"
    # Partial state preserved; the run is "incomplete" (some items still open).
    states = [i["state"] for i in archived["items"]]
    assert "done" in states and "open" in states


def test_new_bar_day_run_is_not_the_stale_one(seeded_db):
    """Re-opening the same template on a later bar-day must build a fresh run,
    not resume yesterday's — the archival pass is what makes that true."""
    stale = barback_db.start_run("opening_barback", datetime(2026, 6, 19, 17, 0))
    fresh = barback_db.start_run("opening_barback", datetime(2026, 6, 21, 17, 0))
    assert fresh["id"] != stale["id"]
    stale_after = barback_db.get_run(stale["id"])
    assert stale_after is not None
    assert stale_after["status"] == "archived"
    assert fresh["status"] == "active"


def test_lowout_summary_lists_low_and_out(seeded_db):
    _add_recipes([(1, "batch", "Negroni Batch", "House Batch")])
    run = barback_db.start_run("stock_check", datetime(2026, 6, 19, 17, 0))
    items = run["items"]
    barback_db.set_item_state(items[0]["id"], "low")
    barback_db.set_item_state(items[1]["id"], "out")
    summary = barback_db.lowout_summary(run["id"])
    assert items[0]["text"] in summary["low"]
    assert items[1]["text"] in summary["out"]
    assert items[0]["text"] in summary["text"]
    assert "Out" in summary["text"] and "Low" in summary["text"]


def test_lowout_summary_all_good(seeded_db):
    _add_recipes([(1, "batch", "Negroni Batch", "House Batch")])
    run = barback_db.start_run("stock_check", datetime(2026, 6, 19, 17, 0))
    for it in run["items"]:
        barback_db.set_item_state(it["id"], "good")
    summary = barback_db.lowout_summary(run["id"])
    assert summary["low"] == [] and summary["out"] == []
    assert "stocked" in summary["text"].lower()


def test_lowboy_fill_is_its_own_template_not_folded_into_opening(seeded_db):
    """The item-level low-boy restock stays off the opening checklist, and its
    sections mirror the physical low-boy map (four doors, lettered zones)."""
    with barback_db._conn() as conn:
        rows = conn.execute(
            "SELECT t.key, i.text, i.section, i.detail FROM checklist_template_item i "
            "JOIN checklist_template t ON t.id=i.template_id "
            "WHERE t.key IN ('opening_barback','lowboy_fill')"
        ).fetchall()
    opening = [r for r in rows if r[0] == "opening_barback"]
    lowboy = [tuple(r) for r in rows if r[0] == "lowboy_fill"]

    # No individual product ever lands on the opening checklist.
    for _, text, _, _ in opening:
        assert text not in ("Coke", "Tsingtao", "Olives", "Egg White", "Prosecco")

    # Sections ARE shelf positions, so the fill runs door by door.
    # Sections mirror the live storage map's shelves verbatim. Fridge 3 · Bottom
    # sat out from 2026-07-29 to 2026-08-02, while the only wording for it was
    # the map's "Service bottles / Clarified Drinks" — a shelf of things, not a
    # product. It came back once Sam named the four bottles that actually get
    # filled there. Fridge 4 · Bottom still holds a grouped row ("Canisters"), so
    # its members stay off the checklist and are reached through storage_item_cover.
    assert {r[2] for r in lowboy} == {
        "Fridge 1 · Top", "Fridge 1 · Middle",
        "Fridge 1 · Bottom · Syrups", "Fridge 1 · Bottom · Non-Alcoholic Batches",
        "Fridge 1 · Bottom · Fresh Quarts",
        "Fridge 2 · Top", "Fridge 2 · Bottom",
        "Fridge 3 · Top", "Fridge 3 · Bottom",
        "Fridge 4 · Top", "Fridge 4 · Bottom",
    }
    assert "Canisters" not in {r[1] for r in lowboy}
    assert {r[1] for r in lowboy if r[2] == "Fridge 3 · Bottom"} == {
        "Peachy River", "Chrysanthemum Kiss", "Pandan Colada", "Pretty in Pink"}
    assert not {r[1] for r in lowboy} & {
        "Service bottles", "Clarified Drinks", "Bottled Batches"}

    # Every row is one countable product. A grouped row ("Cold Foams",
    # "Lucky Ox Sparkler", "Can Sodas") could not say WHICH of its members was
    # short, which is the whole point of counting.
    texts = {r[1] for r in lowboy}
    assert not texts & {"Cold Foams", "Cold Foam Canisters", "Lucky Ox Sparkler", "Can Sodas"}
    assert {"Salted Coconut Foam", "Condensed Milk Cold Foam", "Boba Foam"} <= texts
    assert {"Matcha Lemonade", "Pandan Coconut", "Salted Lemonade"} <= texts
    assert {"Coke", "Diet Coke", "Sprite", "Canada Dry"} <= texts

    by_text = {r[1]: r[3] for r in lowboy}
    # Brands stay attached; can-art shorthand never becomes the stored descriptor.
    details = " ".join(r[3] for r in lowboy)
    assert "Kraken" not in details and "santa" not in details.lower()
    assert by_text["Super Hero Sidekicks"].startswith("KCBC")
    assert by_text["Oolong Kolsh"] == "OEC Brewing"
    assert by_text["Baby Jasmine Lager"] == "Master Gao"
    assert by_text["Ginger Beer"] == "Topo Chico"
    assert by_text["Athletic"] == "Athletic Brewing - non-alcoholic"
    assert by_text["Coconut Water"] == "C2O or Vita Coco"

    # Some products are genuinely stocked on TWO shelves — the map says so, and
    # a dedupe pass would silently drop one of them. The service bottle in the
    # well and its backup are separate things to be short of.
    assert {r[2] for r in lowboy if r[1] == "Egg White"} == {
        "Fridge 1 · Middle", "Fridge 1 · Bottom · Fresh Quarts"}
    assert {r[2] for r in lowboy if r[1] == "Peachy River"} == {
        "Fridge 3 · Bottom", "Fridge 4 · Bottom"}
    assert {r[2] for r in lowboy if r[1] == "Pretty in Pink"} == {
        "Fridge 3 · Bottom", "Fridge 4 · Top"}
    # Onions was on two shelves until the 2026-09-02 sweep took it off Fridge 1.
    assert {r[2] for r in lowboy if r[1] == "Onions"} == {"Fridge 4 · Top"}
    # Added by the same sweep.
    assert {r[2] for r in lowboy if r[1] == "Yuzu"} == {"Fridge 1 · Bottom · Fresh Quarts"}
    assert {"Vina AB", "Lillet", "Dry Vermouth", "Sweet Vermouth", "Dirty Martini"} <= texts

    # The low boy carries six door-1 syrups. work.db lists 12 syrups + 3 cordials;
    # the rest are bar-prep only and live downstairs — a "helpful" re-seed off the
    # recipes table is a bug.
    assert not {r[1] for r in lowboy} & {
        "Pandan Syrup", "Stout Syrup", "Vanilla Syrup", "Nouc Cham",
        "Citrus Cordial", "Lemongrass Syrup", "Red Bean Orgeat",
    }


# ── Counted low boy fill (kind='fill', migration 017) ──────────────────────────
def test_next_fill_state_adds_one_and_never_wraps():
    """Tapping adds one. The old 0-1-2-3-0 cycle made a row needing 8 units
    untappable and cost three more taps to walk one back down to 0."""
    assert barback_db.next_fill_state("0") == "1"
    assert barback_db.next_fill_state("2") == "3"
    assert barback_db.next_fill_state("3") == "4"  # the regression this guards
    assert barback_db.next_fill_state("7") == "8"


def test_next_fill_state_clamps_at_cap():
    cap = barback_db._FILL_MAX
    assert barback_db.next_fill_state(str(cap)) == str(cap)
    assert barback_db.next_fill_state(str(cap - 1)) == str(cap)


def test_next_fill_state_unrecognized_starts_the_count_at_one():
    # A row left over from the pre-017 binary model must not wedge the counter.
    # The tap meant "add one", so it starts counting rather than resting at 0.
    assert barback_db.next_fill_state("done") == "1"
    assert barback_db.next_fill_state("") == "1"
    # A legacy row's `state` column can genuinely be NULL at runtime even
    # though the signature says str; that is exactly what this test guards.
    assert barback_db.next_fill_state(None) == "1"  # pyright: ignore[reportArgumentType]


def test_fill_run_items_rest_at_zero_not_open(seeded_db):
    run = barback_db.start_run("lowboy_fill", datetime(2026, 6, 19, 17, 0))
    assert run["kind"] == "fill"
    assert {i["state"] for i in run["items"]} == {"0"}


def test_fill_item_accepts_counts_and_rejects_duty_states(seeded_db):
    run = barback_db.start_run("lowboy_fill", datetime(2026, 6, 19, 17, 0))
    item = barback_db.set_item_state(run["items"][0]["id"], "2")
    assert item is not None
    assert item["state"] == "2"
    # Counts past the old ceiling of 3 are now valid — that is the whole point.
    bumped = barback_db.set_item_state(run["items"][0]["id"], "8")
    assert bumped is not None
    assert bumped["state"] == "8"
    with pytest.raises(ValueError):
        barback_db.set_item_state(run["items"][0]["id"], "done")
    with pytest.raises(ValueError):
        barback_db.set_item_state(run["items"][0]["id"], str(barback_db._FILL_MAX + 1))


def test_sweep_includes_counts_above_three(seeded_db):
    """The grab list filtered on state IN ('1','2','3'), so once tapping stopped
    wrapping at 3 a row needing 8 vanished from the sweep entirely — counted on
    screen, never collected."""
    run = barback_db.start_run("lowboy_fill", datetime(2026, 6, 19, 17, 0))
    barback_db.set_item_state(run["items"][0]["id"], "8")
    sweep = barback_db.grab_sweep(run["id"])
    assert sweep["units"] == 8
    assert sweep["rows"] == 1
    counts = [i["count"] for a in sweep["areas"] for s in a["stops"] for i in s["items"]]
    assert counts == [8]


def test_clear_fill_run_zeroes_every_row(seeded_db):
    run = barback_db.start_run("lowboy_fill", datetime(2026, 6, 19, 17, 0))
    barback_db.set_item_state(run["items"][0]["id"], "8")
    barback_db.set_item_state(run["items"][1]["id"], "3")
    assert barback_db.clear_fill_run(run["id"]) == 2  # only the non-zero rows
    after = barback_db.get_run(run["id"])
    assert after is not None
    assert {i["state"] for i in after["items"]} == {"0"}
    # Idempotent: clearing an already-clear run changes nothing.
    assert barback_db.clear_fill_run(run["id"]) == 0


def test_clear_fill_run_refuses_non_fill_runs(seeded_db):
    """Zeroing a duty run would wipe the shift's progress, not a grab list."""
    run = barback_db.start_run("opening_barback", datetime(2026, 6, 19, 17, 0))
    with pytest.raises(ValueError):
        barback_db.clear_fill_run(run["id"])


def test_fill_run_never_stamps_completed(seeded_db):
    """A fill run is a survey: rows rest at "0" and never leave an 'open' state,
    so the all-items-left-open completion rule must not fire on it."""
    run = barback_db.start_run("lowboy_fill", datetime(2026, 6, 19, 17, 0))
    barback_db.set_item_state(run["items"][0]["id"], "3")
    after = barback_db.get_run(run["id"])
    assert after is not None
    assert after["completed_at"] is None


def _place(name: str, location: str) -> None:
    with barback_db._conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO ingredient_location (name, location, note) "
            "VALUES (?,?,NULL)", (name, location),
        )


def _fill_run_with(seeded, counts: dict[str, str]):
    """Start a fill run and set the named products to the given counts."""
    run = barback_db.start_run("lowboy_fill", datetime(2026, 6, 19, 17, 0))
    by_text = {}
    for i in run["items"]:
        by_text.setdefault(i["text"], i["id"])
    for text, state in counts.items():
        barback_db.set_item_state(by_text[text], state)
    return run


def test_area_for_maps_shelf_to_walkable_area():
    assert barback_db._area_for("Right fridge · bottom row") == "Front room"
    assert barback_db._area_for("Lowboy · top left") == "Back room"
    assert barback_db._area_for("Bar well") == "Bar"
    assert barback_db._area_for("Some room nobody mapped") == "Unsorted"
    assert barback_db._area_for(None) == "Unsorted"


def test_grab_sweep_groups_by_area_in_walk_order(seeded_db):
    _place("Tsingtao", "Right fridge · bottom row")       # Front room
    _place("Sesame Brittle", "Lowboy · top left")         # Back room
    _place("Club Soda", "Bar well")                       # Bar
    run = _fill_run_with(seeded_db, {
        "Sesame Brittle": "1", "Club Soda": "2", "Tsingtao": "3",
    })
    sweep = barback_db.grab_sweep(run["id"])
    assert [a["area"] for a in sweep["areas"]] == ["Front room", "Back room", "Bar"]
    assert sweep["rows"] == 3
    assert sweep["units"] == 6
    front = sweep["areas"][0]
    assert front["units"] == 3
    assert front["stops"][0]["location"] == "Right fridge · bottom row"
    item = front["stops"][0]["items"][0]
    assert {k: v for k, v in item.items() if k != "item_id"} == {
        # section = the shelf the storage map puts it on. It was "2A. Beers, Sodas
        # & Sparklers" until the 2026-07-29 rebuild made lowboy_fill a mirror of
        # the map; this assert was left behind by that rename.
        "text": "Tsingtao", "detail": "", "section": "Fridge 2 · Top",
        "count": 3,
    }
    assert isinstance(item["item_id"], int)


def test_grab_sweep_groups_multiple_products_under_one_stop(seeded_db):
    _place("Tsingtao", "Right fridge · bottom row")
    _place("Prosecco", "Right fridge · bottom row")
    run = _fill_run_with(seeded_db, {"Tsingtao": "1", "Prosecco": "2"})
    sweep = barback_db.grab_sweep(run["id"])
    stops = sweep["areas"][0]["stops"]
    assert len(stops) == 1  # one shelf, one stop — that IS the sweep
    assert {i["text"] for i in stops[0]["items"]} == {"Tsingtao", "Prosecco"}
    assert sweep["areas"][0]["units"] == 3


def test_grab_sweep_unplaced_product_lands_in_unsorted_last(seeded_db):
    """An unmapped product is never guessed at and never dropped — it collects in
    a visible Unsorted bucket, which sorts after every real area."""
    _place("Tsingtao", "Right fridge · bottom row")
    run = _fill_run_with(seeded_db, {"Tsingtao": "1", "Lemon": "2"})
    sweep = barback_db.grab_sweep(run["id"])
    assert [a["area"] for a in sweep["areas"]] == ["Front room", "Unsorted"]
    unsorted = sweep["areas"][-1]
    assert unsorted["stops"][0]["location"] == "Not on the storage map"
    assert unsorted["stops"][0]["items"][0]["text"] == "Lemon"
    assert sweep["units"] == 3  # the unplaced row still counts toward the total


def test_sweep_item_id_clears_the_line_off_the_sweep(seeded_db):
    """The sweep carries the run-item id, which is what lets a grabbed line be
    cleared from the grab list itself instead of tapping its row back around to 0."""
    _place("Tsingtao", "Right fridge · bottom row")
    _place("Prosecco", "Right fridge · bottom row")
    run = _fill_run_with(seeded_db, {"Tsingtao": "2", "Prosecco": "1"})
    sweep = barback_db.grab_sweep(run["id"])
    by_text = {i["text"]: i["item_id"]
               for a in sweep["areas"] for s in a["stops"] for i in s["items"]}

    barback_db.set_item_state(by_text["Tsingtao"], "0")

    after = barback_db.grab_sweep(run["id"])
    assert [i["text"] for a in after["areas"] for s in a["stops"] for i in s["items"]] \
        == ["Prosecco"]
    assert after["units"] == 1


def test_grab_sweep_excludes_zero_rows(seeded_db):
    _place("Tsingtao", "Right fridge · bottom row")
    run = _fill_run_with(seeded_db, {"Tsingtao": "0"})
    sweep = barback_db.grab_sweep(run["id"])
    assert sweep == {"areas": [], "units": 0, "rows": 0}


# ── /sweep endpoint ────────────────────────────────────────────────────────────
# api.py imports its db as `barback.db` (package-relative), a distinct module
# object from the flat `db` the rest of this file drives — so the client fixture
# points that one at the same throwaway file.
@pytest.fixture
def client(seeded_db):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # hub/
    from flask import Flask

    import barback.api as barback_api
    import barback.db as pkg_db

    pkg_db.init(seeded_db)
    app = Flask(__name__)
    app.register_blueprint(barback_api.bp)
    return app.test_client()


def test_sweep_endpoint_returns_grouped_areas(client):
    _place("Tsingtao", "Right fridge · bottom row")
    run = _fill_run_with(None, {"Tsingtao": "2"})
    resp = client.get(f"/barback/api/barback/run/{run['id']}/sweep")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["data"]["units"] == 2
    assert body["data"]["areas"][0]["area"] == "Front room"


def test_sweep_endpoint_unknown_run_is_404(client):
    resp = client.get("/barback/api/barback/run/99999/sweep")
    assert resp.status_code == 404
    assert resp.get_json()["status"] == "error"


def test_every_seeded_location_maps_to_a_walk_area():
    """A location string whose prefix is missing from _AREA_BY_PREFIX falls to
    Unsorted, which is indistinguishable from the product never having been
    placed at all. That silently swallowed 18 of the placed products between the
    2026-08-17 "Back fridge" -> "Keg fridge" rename and 2026-09-02."""
    from barback import seed_lowboy_location

    for name, loc in seed_lowboy_location.LOCATIONS.items():
        assert barback_db._area_for(loc) != "Unsorted", f"{name} -> {loc}"

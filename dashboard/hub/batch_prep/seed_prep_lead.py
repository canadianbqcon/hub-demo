"""Seed per-prep brew/lead times into work.db `recipes.lead_minutes` + `lead_label`.

One row per prep (kind='prep'), keyed by lowercased name. `lead_minutes` is the
passive wait until the prep is usable (the prep-day build-up sort key); `lead_label`
is the exact text shown on the step. "Lead time" = time from starting the prep until
it's usable, driven by PASSIVE unattended waits (infuse / steep / rest / chill /
freeze / dehydrate / sous-vide). Active simmering counts only when there's no passive
wait, so the quick-simmer syrups land near the bottom.

Values are CARD-STATED where the method gives a time; WEB-RESEARCHED (with a note on
the row) where the card says "make ahead"/"freeze"/"refrigerate" but no duration.

Re-runnable: UPDATEs by name, so editing a value here and re-running corrects the row.
Run from this folder:  PYTHONPATH=<repo>/dashboard python3 seed_prep_lead.py

overnight is encoded as 720 (12 hr); a prep with no meaningful wait is (0, None).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2])
)  # dashboard/, for vault_path
from vault_path import vault_root

_WORK_DB = vault_root() / "data" / "work.db"

# name (lowercased, must match recipes.name) -> (lead_minutes, lead_label, note)
LEADS: dict[str, tuple[int, str | None, str | None]] = {
    # ── no meaningful wait (instant / pour-together) ──
    "simple syrup": (0, None, None),
    "demerara syrup": (0, None, None),
    "pandan syrup": (0, None, None),
    "vanilla syrup": (0, None, None),
    "citrus cordial": (0, None, None),
    "nouc cham": (0, None, None),
    "tamarind agave": (0, None, None),
    "cookie rim": (0, None, None),
    # ── short active cook, no passive wait (counts only because nothing passive) ──
    "lemongrass syrup": (10, "simmer 10 min", None),
    "black sesame syrup": (10, "simmer 10 min", None),
    "coconut syrup": (10, "simmer 10 min", None),
    "star anise and vanilla syrup": (10, "simmer 10 min", None),
    "ginger scallion syrup": (10, "simmer 10 min", None),
    "toasted coconut milk": (10, "simmer 10 min", None),
    "basil oil": (10, "blanch + blend ~10 min", None),
    "stout syrup": (20, "simmer 20 min", None),
    "chocolate truffle": (20, "cook + cool ~20 min", None),
    "boba h2o": (35, "boil + cool ~35 min", None),
    "red bean orgeat": (40, "simmer 40 min", None),
    # ── steeps (card-stated) ──
    "chrysanthemum tea": (10, "steep 10 min", None),
    "jasmine green tea": (10, "steep 10 min", None),
    "jasmine green tea five spice stout": (10, "steep 10 min", None),
    # ── hours (card-stated) ──
    "chrysanthemum honey": (180, "sit 3 hr", None),
    "thai chili mezcal": (180, "infuse 3 hr (no more)", None),
    # ── researched gaps (card gives no time) ──
    "salted coconut foam": (
        120,
        "chill ~2 hr",
        "RESEARCHED: card says 'make ahead to chill', no time; cold foam chills cold in ~2 hr (overnight safe)",
    ),
    "condensed milk cold foam": (
        120,
        "chill ~2 hr",
        "RESEARCHED: card says 'make ahead to chill', no time; ~2 hr to chill (overnight safe)",
    ),
    "yogurt spoon garnish": (
        240,
        "freeze ~4 hr",
        "RESEARCHED: card says 'mold & freeze', no time; yogurt molds set solid in ~3-4 hr (overnight safe)",
    ),
    "che ba mau layered jello": (
        180,
        "set ~3 hr (3 layers)",
        "RESEARCHED: card says harden each layer then refrigerate, no time; agar ~1 hr/layer + chill -> ~3 hr",
    ),
    # ── overnight, ~12 hr (card-stated) ──
    "coffee": (720, "steep overnight", None),
    "chrysanthemum vodka": (720, "infuse overnight", None),
    "oolong tequila": (720, "infuse overnight", None),
    "peanut butter whiskey": (720, "infuse overnight", None),
    "ginseng pu'er remy rye": (720, "infuse overnight", None),
    "pho spiced ten to one white rum": (720, "infuse overnight", None),
    "brown butter tullamore dew": (720, "freeze overnight (fat-wash)", None),
    "coconut balls": (720, "freeze overnight", None),
    # ── 12 hr dehydrate (card-stated) ──
    "dehydrated lemon & lime": (720, "dehydrate 12 hr", None),
    "dehydrated bitter melon": (720, "dehydrate 12 hr", None),
    "sorrel stencil": (720, "dehydrate 12 hr", None),
    "plum powder": (720, "dehydrate 12 hr", None),
    # ── 24 hr (card-stated) ──
    "wine float": (1440, "sous vide 24 hr", None),
    # ── 1 week — the longest in the set (card-stated) ──
    "jackfruit infused ten to one dark rum": (
        10080,
        "infuse 1 week",
        "card: freeze overnight + thaw 1 hr + sit 1 week; the week dominates",
    ),
}

# Batches (kind='batch'). Every value below is read straight off the batch's own
# `method` text in work.db — the wait was always recorded there ("stir, sit overnight,
# strain cone filter"), it just never reached the lead_minutes column, because this
# seeder originally scoped to kind='prep'. Nothing here is invented.
# The house batches are pour-and-label with no passive wait, so they are honestly 0.
BATCH_LEADS: dict[str, tuple[int, str | None, str | None]] = {
    # ── overnight clarification (method-stated) ──
    "one inch punch": (720, "sit overnight", None),
    "passion express": (720, "leave overnight", None),
    "teakillah": (720, "sit overnight", None),
    "che ba mau": (720, "sit overnight", "30 min bean simmer runs first, then the wait"),
    "thairish tea": (720, "sit overnight", "10 min tea steep runs first, then the wait"),
    "lychee martini": (720, "sit overnight", None),
    "ube daiquiri": (720, "sit overnight", None),
    "juniper tea shot": (720, "sit overnight", None),
    "bitter sweet": (
        720,
        "clarify overnight",
        "method says 'clarify' with no duration; matched to its sibling HH clarified batches",
    ),
    # ── no passive wait: combine, stir, QT, label ──
    "the juniper": (0, None, None),
    "the sorrel": (0, None, None),
    "chrysanthemum kiss": (0, None, None),
    "golden hour": (0, None, None),
    "leaf me alone": (0, None, None),
    "macau flip": (0, None, None),
    "pandan colada": (0, None, None),
    "peachy river": (0, None, None),
    "pretty in pink": (0, None, None),
    "temple run": (0, None, None),
    "irish breakfast": (0, None, "5 min active simmer, nothing passive after it"),
}


def _apply(conn, table: dict, kind: str) -> int:
    """UPDATE lead columns for one kind. Never touches rows absent from `table`."""
    updated = 0
    for name, (mins, label, _note) in table.items():
        cur = conn.execute(
            "UPDATE recipes SET lead_minutes = ?, lead_label = ? "
            "WHERE lower(name) = ? AND kind = ?",
            (mins, label, name, kind),
        )
        if cur.rowcount == 0:
            print(f"  WARN: no {kind} matched '{name}'")
        updated += cur.rowcount
    return updated


def seed() -> None:
    conn = sqlite3.connect(_WORK_DB)
    try:
        updated = _apply(conn, LEADS, "prep")
        updated += _apply(conn, BATCH_LEADS, "batch")
        conn.commit()
        # anything we did NOT classify? Discontinued rows are off-menu, so exempt.
        missing = [
            (r[0], r[1])
            for r in conn.execute(
                "SELECT kind, name FROM recipes "
                "WHERE kind IN ('prep','batch') AND lead_minutes IS NULL "
                "AND category NOT LIKE 'Discontinued%' ORDER BY kind, name"
            ).fetchall()
        ]
    finally:
        conn.close()
    print(
        f"seeded lead times on {updated} row(s); "
        f"{len(LEADS)} prep + {len(BATCH_LEADS)} batch entries in table."
    )
    if missing:
        print(f"\nUNCLASSIFIED (no lead_minutes) — {len(missing)}:")
        for kind, name in missing:
            print(f"  - [{kind}] {name}")
    else:
        print("full coverage — every on-menu prep and batch has a lead time.")


if __name__ == "__main__":
    seed()

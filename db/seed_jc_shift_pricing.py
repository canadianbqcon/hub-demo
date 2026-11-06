#!/usr/bin/env python3
"""Seed the facts the calendar cannot know, then calibrate and price.

The calendar gives a date, a window and a title. It does not say what role he
works, that Aug 2 is a buyout, or that Aug 21 has no second barback. Those three
come from Sam and live here so a resync cannot lose them.

    python3 db/seed_jc_shift_pricing.py            # seed + calibrate + price
    python3 db/seed_jc_shift_pricing.py --no-calibrate

Idempotent: re-running rewrites the same rows.
"""

import argparse
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "dashboard"))
sys.path.insert(0, str(_REPO / "dashboard" / "hub"))

from vault_path import vault_root                       # noqa: E402
from hub.finances import db, shift_pricing as sp        # noqa: E402

SOURCE = "juniper-and-co"

# Every rostered shift is a barback shift; bar prep is untipped and is not
# rostered on the calendar as a J&Co — Barback event.
DEFAULT_ROLE = "barback"

# Sam 2026-07-29: "the long 12hour sunday solo barback shift is a buyout",
# and "only me and boartender during buyout".
BUYOUTS = {"2026-08-02"}

# Crew overrides, keyed by date. Only nights that differ from the day-type
# template need an entry. Sam 2026-07-29: "aug 21 is solo" -- he covers both
# barback slots himself, 4:30pm-3am, so the counterpart barback the Friday
# template would otherwise add must not be there.
CREW_OVERRIDES: dict[str, list[tuple[str, str, str, str]]] = {
    # date: [(role, start_at, end_at, label)]
    "2026-08-21": [
        ("bartender",   "16:30", "00:30", ""),
        ("bar_captain", "19:00", "03:00", ""),
        ("server",      "17:30", "00:30", ""),
        ("server",      "20:00", "03:00", ""),
        ("host",        "18:00", "02:30", ""),
        ("host",        "18:00", "02:30", ""),
        # no barback -- solo across the whole span
    ],
    # Posted schedule, week of Aug 10 (screenshot). Kept verbatim even though it
    # matches the Friday template, so a template edit cannot silently move a
    # night we actually have the roster for.
    "2026-08-14": [
        ("bartender",   "16:30", "00:30", "Bianco, Mable"),
        ("bar_captain", "19:00", "03:00", "Vega, Daniel"),
        ("server",      "17:30", "00:30", "Zheng, Wendy Amber"),
        ("server",      "20:00", "03:00", "Tran, Kate"),
        ("host",        "18:00", "02:30", "Banh, Kevin Kai"),
        ("host",        "18:00", "02:30", "Wong, Jasmine"),
        ("barback",     "16:30", "23:30", "Ordonez, Lukas"),
        ("bar_prep",    "15:00", "21:00", "Ordonez, Matisse"),
    ],
}


def seed() -> None:
    with db._conn() as conn:
        conn.execute(
            "UPDATE earnings_scheduled_shifts SET role=COALESCE(role, ?) "
            "WHERE source=?", (DEFAULT_ROLE, SOURCE))
        conn.execute(
            "UPDATE earnings_scheduled_shifts SET shift_kind='regular' "
            "WHERE source=? AND shift_kind IS NULL", (SOURCE,))
        for d in BUYOUTS:
            conn.execute(
                "UPDATE earnings_scheduled_shifts SET shift_kind='buyout' "
                "WHERE source=? AND shift_date=?", (SOURCE, d))
        for d, crew in CREW_OVERRIDES.items():
            row = conn.execute(
                "SELECT id FROM earnings_scheduled_shifts WHERE source=? AND shift_date=?",
                (SOURCE, d)).fetchone()
            if not row:
                print(f"  ! no scheduled shift on {d}; crew override skipped")
                continue
            conn.execute("DELETE FROM earnings_shift_crew WHERE shift_id=?", (row["id"],))
            conn.executemany(
                "INSERT INTO earnings_shift_crew (shift_id, role, start_at, end_at, label) "
                "VALUES (?,?,?,?,?)",
                [(row["id"], *c) for c in crew])
        conn.commit()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-calibrate", action="store_true",
                    help="keep the stored densities instead of re-solving them")
    args = ap.parse_args()

    db.init(vault_root() / "data" / "earnings.db")
    seed()
    print(f"seeded role/kind + {len(CREW_OVERRIDES)} crew roster(s)")

    if not args.no_calibrate:
        points = sp.load_points(SOURCE)
        actuals = sp.actual_shifts(SOURCE)
        solved = sp.calibrate(actuals, points)
        with db._conn() as conn:
            for k, v in solved.items():
                conn.execute(
                    "UPDATE earnings_pricing_params SET value=? "
                    "WHERE source=? AND key=?", (v, SOURCE, k))
            conn.commit()
        print(f"calibrated from {len(actuals)} paid shifts:")
        for k, v in sorted(solved.items()):
            print(f"  {k:22} {v:>8.2f} /hr pool")

    print(f"priced {sp.price_all(SOURCE)} scheduled shifts")


if __name__ == "__main__":
    main()

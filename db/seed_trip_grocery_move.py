#!/usr/bin/env python3
"""One-shot: move every trips.db `grocery` row into checklists.db.

Run once, before db/migrations/trips/020 drops the table it reads. Idempotent — a
trip whose list is already there is skipped, so a half-finished run can be repeated.

    python db/seed_trip_grocery_move.py [--dry-run]

The cross-database copy cannot be a .sql migration: the runner opens one database per
module and a migration file has no way to reach the other one.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))
sys.path.insert(0, str(ROOT / "dashboard" / "hub"))
from vault_path import vault_root  # noqa: E402
from checklists import db as cdb  # noqa: E402

SOURCE = "trips:{}:grocery"


def main(dry_run: bool = False) -> int:
    data = vault_root() / "data"
    cdb.init(data / "checklists.db")
    trips = sqlite3.connect(data / "trips.db")
    trips.row_factory = sqlite3.Row
    rows = trips.execute(
        "SELECT g.*, t.name AS trip_name FROM grocery g"
        " JOIN trips t ON t.id = g.trip_id ORDER BY g.trip_id, g.sort_order, g.id"
    ).fetchall()
    trips.close()

    by_trip: dict[int, list[sqlite3.Row]] = {}
    for r in rows:
        by_trip.setdefault(r["trip_id"], []).append(r)

    moved = 0
    for trip_id, items in by_trip.items():
        source = SOURCE.format(trip_id)
        name = f"{items[0]['trip_name']} — Grocery"
        existing = cdb.find_source_list(source)
        if existing and existing["items"]:
            print(f"skip trip {trip_id}: {len(existing['items'])} item(s) already there")
            continue
        print(f"{'would move' if dry_run else 'moving'} {len(items)} item(s) "
              f"for trip {trip_id} → {name!r} ({source})")
        if dry_run:
            continue
        cl = cdb.ensure_source_list(source, name, category="trip",
                                    description="Shown on the trip's grocery tab.")
        cdb.add_items_bulk(cl["id"], [
            {"text": r["item"], "qty": r["qty"] or "", "note": r["note"] or ""}
            for r in items
        ])
        # `got` is not carried by add_items_bulk — set it after, so a half-shopped
        # list arrives half-shopped rather than silently resetting to nothing bought.
        got = [r for r in items if r["got"]]
        if got:
            fresh = cdb.get_checklist(cl["id"])
            assert fresh is not None, f"checklist {cl['id']} vanished right after creation"
            by_text = {i["text"]: i["id"] for i in fresh["items"]}
            for r in got:
                if r["item"] in by_text:
                    cdb.update_item(cl["id"], by_text[r["item"]], {"checked": 1})
        moved += len(items)
    print(f"{'would move' if dry_run else 'moved'} {moved} item(s) across "
          f"{len(by_trip)} trip list(s)")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    sys.exit(main(**vars(p.parse_args())))

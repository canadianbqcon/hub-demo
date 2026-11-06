#!/usr/bin/env python3
"""Seed/refresh card payment-due rows in data/cards.db.

Idempotent: INSERT OR REPLACE keyed on card name, so re-running updates due days
without duplicating rows. Run after `python data/migrate.py up cards`.

    python data/seed_cards.py

Add a card by appending to CARDS, or update a due day in place, then re-run.
"""

import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "dashboard"))
from vault_path import vault_root

DB = vault_root() / "data" / "cards.db"

PRAGMA_SCRIPT = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
PRAGMA temp_store   = MEMORY;
"""

# Names must match the YNAB account name exactly (the merge in
# dashboard/hub/cards.py matches case-insensitively by name). Verified against
# the live YNAB accounts 2026-06-06 — note "Discover It Chrome", not "Discover Chrome".
#
# Balances are NOT seeded for cards: YNAB is the live source and the debt tab reads
# it directly. Everything here is the terms YNAB's API does not expose — due day,
# APR, promo window, credit limit — sourced from wiki/facts/financial-snapshot-2026.md.
# Re-run after any rate change, limit increase, or new promo.
CARDS = [
    dict(name="Chase Freedom Unlimited", due_day=14, apr=26.24, credit_limit=10400),
    dict(name="Chase Sapphire Preferred", due_day=13, apr=27.49, credit_limit=12500),
    # 0% promo expires 2026-12-25 ("the December cliff"), then reverts to ~27%.
    dict(name="Discover It Chrome", due_day=22, apr=27.00,
         promo_apr=0.0, promo_end="2026-12-25"),
    # Maxed at its $2,000 limit; 0% for 21 months from the 2026-06-18 transfer.
    dict(name="CitiBank Diamond Preferred", due_day=27, apr=29.24, credit_limit=2000,
         promo_apr=0.0, promo_end="2028-03-18"),
    # Installment loan drawn against the Sapphire line, so its principal is already
    # inside that card's YNAB balance — `parent` tells the projection to carve it out
    # rather than count the money twice. `balance` is the ORIGINAL principal and
    # start_date its origination; the engine amortizes forward to get today's figure,
    # so this row never needs hand-refreshing.
    dict(name="My Chase Loan", due_day=13, kind="loan",
         parent="Chase Sapphire Preferred", apr=10.99, balance=4261.00,
         fixed_payment=198.48, term_months=24, start_date="2026-06-15"),
]

_COLS = ("due_day", "kind", "apr", "promo_apr", "promo_end", "credit_limit",
         "min_payment", "fixed_payment", "term_months", "parent", "balance",
         "start_date")


def main():
    conn = sqlite3.connect(DB)
    conn.executescript(PRAGMA_SCRIPT)
    for card in CARDS:
        row = {c: card.get(c) for c in _COLS}
        row["kind"] = row["kind"] or "card"  # NOT NULL; explicit bind skips the DEFAULT
        row["name"] = card["name"]
        cols = ", ".join(("name",) + _COLS)
        ph = ", ".join(f":{c}" for c in ("name",) + _COLS)
        sets = ", ".join(f"{c} = excluded.{c}" for c in _COLS)
        conn.execute(
            f"INSERT INTO card ({cols}) VALUES ({ph}) "
            f"ON CONFLICT(name) DO UPDATE SET {sets}, updated = datetime('now')",
            row,
        )
    # Drop any row no longer in CARDS (e.g. a renamed card) so the table mirrors the list.
    placeholders = ",".join("?" for _ in CARDS)
    conn.execute(
        f"DELETE FROM card WHERE name NOT IN ({placeholders})",
        [c["name"] for c in CARDS],
    )
    conn.commit()
    rows = conn.execute(
        "SELECT name, due_day, kind, apr, promo_apr, promo_end FROM card ORDER BY kind, due_day"
    ).fetchall()
    conn.close()
    print(f"Seeded {len(rows)} card(s):")
    for name, due_day, kind, apr, promo_apr, promo_end in rows:
        rate = f"{promo_apr:.2f}% until {promo_end}" if promo_end else f"{apr:.2f}%"
        print(f"  {name} [{kind}]: due day {due_day}, {rate}")


if __name__ == "__main__":
    main()

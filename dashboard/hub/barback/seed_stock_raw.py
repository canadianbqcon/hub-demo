"""Seed the raw-goods rows for the stock check (the non-made items: fresh juice,
produce, dry garnish, bottled & canned). Made items (batches/preps) are generated
live from work.db at run start, not seeded here. Idempotent: clears + reinserts.

Run standalone:  cd dashboard/hub/barback && PYTHONPATH=../.. python seed_stock_raw.py
"""
from __future__ import annotations

# `from . import db` binds THIS package's db. A bare `import db` does not: ten
# modules in dashboard/hub/ are named db.py, so under a whole-tree pytest run
# whichever one loaded first wins from sys.modules. The fallback keeps the
# standalone `python seed_*.py` entry point in the docstring working, where
# there is no package to be relative to.
try:
    from . import db as barback_db
except ImportError:  # pragma: no cover - standalone script path
    import db as barback_db  # pyright: ignore[reportMissingImports]

# (name, category). Sourced from the opening-duties stock lists + Sam's list.
_RAW = [
    ("Lime", "Fresh juice"),
    ("Lemon", "Fresh juice"),
    ("Pineapple", "Fresh juice"),
    ("Wakamomo peaches", "Produce"),
    ("Cucumber", "Produce"),
    ("Fresh fruit", "Produce"),
    ("Dehydrated chili", "Dry garnish"),
    ("Dehydrated lemon / lime", "Dry garnish"),
    ("Nutmeg", "Dry garnish"),
    ("Sesame brittle", "Dry garnish"),
    ("Coconut water", "Bottled & canned"),
    ("Tonic water", "Bottled & canned"),
    ("Canned beers", "Bottled & canned"),
    ("Sodas", "Bottled & canned"),
    ("Still & sparkling water", "Bottled & canned"),
]


def run() -> None:
    with barback_db._conn() as conn:
        conn.execute("DELETE FROM stock_raw_item")
        for i, (name, category) in enumerate(_RAW):
            conn.execute(
                "INSERT INTO stock_raw_item (name, category, sort_order) VALUES (?,?,?)",
                (name, category, i),
            )


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # dashboard/
    from vault_path import vault_root
    barback_db.init(vault_root() / "data" / "work.db")
    run()
    print("seed_stock_raw: done")

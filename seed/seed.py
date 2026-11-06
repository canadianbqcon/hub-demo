#!/usr/bin/env python3
"""Fill demo-vault/pristine/ with one fake persona's month. Stdlib only.

  seed.py --out <demo-vault>

Copies the freshly migrated <out>/data/*.db into <out>/pristine/, then runs
every module in MODULES. A module has:
  DB      the database it fills ("jobs" -> pristine/jobs.db), a tuple of
          names (then seed gets {name: con}), or None
  EXPECT  {table: minimum rows} the test checks ("db.table" when DB is a tuple)
  seed(con, rnd, persona)            writes rows (con is None when DB is None)
  files(root, rnd, persona)          optional: writes files under <out>/pristine/
                                     (wiki/ there is re-copied on every reset)
  check(con)                         optional: extra asserts the test runs
Each module gets its own random.Random, so adding one never shifts another.
"""
import argparse
import importlib
import random
import shutil
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import persona  # noqa: E402

MODULES = [
    "s_tasks", "s_home", "s_jobs", "s_trips", "s_purchases", "s_checklists",
    "s_finance", "s_news", "s_food", "s_recipes", "s_work", "s_system", "s_mail",
]


def load_modules():
    return [importlib.import_module(name) for name in MODULES]


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys=ON")
    return con


def run(out: Path) -> None:
    out = out.resolve()
    pristine = out / "pristine"
    if pristine.exists():
        shutil.rmtree(pristine)
    pristine.mkdir(parents=True)
    for db in sorted((out / "data").glob("*.db")):
        src, dst = sqlite3.connect(db), sqlite3.connect(pristine / db.name)
        src.backup(dst)
        src.close()
        dst.close()
    for mod in load_modules():
        rnd = random.Random(f"{persona.SEED}-{mod.__name__}")
        names = (mod.DB,) if isinstance(mod.DB, str) else tuple(mod.DB or ())
        cons = {n: connect(pristine / f"{n}.db") for n in names}
        try:
            mod.seed(cons[mod.DB] if isinstance(mod.DB, str) else (cons or None), rnd, persona)
            for c in cons.values():
                c.commit()
        finally:
            for c in cons.values():
                c.close()
        if hasattr(mod, "files"):
            mod.files(pristine, rnd, persona)
    for db in sorted(pristine.glob("*.db")):
        con = sqlite3.connect(db)
        bad = con.execute("PRAGMA foreign_key_check").fetchall()
        con.execute("PRAGMA journal_mode=DELETE")
        con.execute("VACUUM")
        con.close()
        if bad:
            raise SystemExit(f"seed: foreign key check failed in {db.name}: {bad[:5]}")
    import links
    broken = links.check(pristine)
    if broken:
        raise SystemExit(f"seed: broken cross-database links: {broken[:5]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    run(ap.parse_args(argv).out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

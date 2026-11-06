#!/usr/bin/env python3
"""Schema migration helper for the vault's SQLite databases.

Usage:
    python db/migrate.py current   [<module>]   Show applied version per database
    python db/migrate.py list      [<module>]   List migration files + applied state
    python db/migrate.py baseline  [<module>]   Record 001 as applied without running SQL
    python db/migrate.py up        [<module>]   Apply all pending migrations
    python db/migrate.py down      [<module>]   Roll back the most recent migration

`up` takes a WAL-safe pre-migration backup of any database that already holds data
(data/<module>.db.bak-pre-migration-NNN-YYYY-MM-DD) before applying, then — only on
a fully successful run — prunes older pre-migration backups so at most one survives
per database (the warehouse-contract retention invariant). A failed run leaves its
backup in place. Ad-hoc bak-<reason> backups are never auto-pruned.

`<module>` is the database name without the .db suffix (e.g. `jobs`). Omit
to run the command on every module discovered under db/migrations/ (DBs live in the vault's data/).
"""

import argparse
import datetime
import pathlib
import re
import sqlite3
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "dashboard"))
from vault_path import vault_root

# Databases live in the vault's data/; migration SQL lives here in the repo.
DATA_DIR = vault_root() / "data"
MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent / "migrations"

PRAGMA_SCRIPT = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
PRAGMA temp_store   = MEMORY;
"""

MIGRATION_FILENAME_RE = re.compile(r"^(\d{3})_([a-z0-9_-]+)\.sql$")


def list_modules():
    if not MIGRATIONS_DIR.is_dir():
        return []
    return sorted(p.name for p in MIGRATIONS_DIR.iterdir() if p.is_dir())


def db_path(module):
    return DATA_DIR / f"{module}.db"


def migrations_for(module):
    folder = MIGRATIONS_DIR / module
    out = []
    for path in sorted(folder.glob("*.sql")):
        m = MIGRATION_FILENAME_RE.match(path.name)
        if not m:
            raise ValueError(
                f"Bad migration filename: {path}. "
                f"Expected NNN_label.sql (zero-padded, lowercase)."
            )
        out.append((int(m.group(1)), m.group(2), path))
    return out


def connect(module):
    conn = sqlite3.connect(db_path(module))
    conn.executescript(PRAGMA_SCRIPT)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            label      TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def applied_versions(conn):
    cur = conn.execute("SELECT version FROM schema_migrations ORDER BY version")
    return [row[0] for row in cur.fetchall()]


def has_user_tables(conn):
    # schema_migrations gets created on every connect; ignore it when checking.
    cur = conn.execute(
        "SELECT COUNT(*) FROM sqlite_schema "
        "WHERE type='table' "
        "  AND name NOT LIKE 'sqlite_%' "
        "  AND name != 'schema_migrations'"
    )
    return cur.fetchone()[0] > 0


def parse_migration(path):
    text = path.read_text()
    up = re.search(
        r"--\s*\+migrate\s+up\s*\n(.*?)(?=--\s*\+migrate\s+down|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    down = re.search(
        r"--\s*\+migrate\s+down\s*\n(.*?)\Z",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    return (up.group(1).strip() if up else "", down.group(1).strip() if down else "")


def is_effectively_empty(sql):
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return False
    return True


def backup_db(module, version):
    """WAL-safe pre-migration backup of an existing database.

    Returns the backup Path written, named per the warehouse contract
    (data/<module>.db.bak-pre-migration-NNN-YYYY-MM-DD), or None when there's no
    source file to protect. Uses the sqlite online-backup API rather than a file
    copy so the snapshot is consistent even in WAL mode with the dashboard holding
    a live connection (a plain `cp` would miss un-checkpointed WAL frames).
    """
    src = db_path(module)
    if not src.exists():
        return None
    dest = DATA_DIR / f"{module}.db.bak-pre-migration-{version:03d}-{datetime.date.today().isoformat()}"
    source_conn = sqlite3.connect(src)
    dest_conn = sqlite3.connect(dest)
    try:
        with dest_conn:
            source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()
    return dest


def prune_backups(module, keep):
    """Retention: delete every pre-migration backup for `module` except `keep`.

    Enforces the contract invariant "at most one .bak per database (the most
    recent migration's backup)". Only touches `bak-pre-migration-*` files — ad-hoc
    `bak-<reason>` backups are intentional and left alone. Returns the names removed.
    """
    keep_name = keep.name if keep else None
    removed = []
    for path in sorted(DATA_DIR.glob(f"{module}.db.bak-pre-migration-*")):
        if path.name != keep_name:
            path.unlink()
            removed.append(path.name)
    return removed


def cmd_current(module):
    conn = connect(module)
    versions = applied_versions(conn)
    conn.close()
    if not versions:
        print(f"{module}: version 0 (no migrations applied)")
    else:
        print(f"{module}: version {versions[-1]} (applied: {versions})")
    return 0


def cmd_list(module):
    conn = connect(module)
    applied = set(applied_versions(conn))
    conn.close()
    migs = migrations_for(module)
    if not migs:
        print(f"{module}: no migration files in db/migrations/{module}/")
        return 0
    for version, label, path in migs:
        mark = "applied" if version in applied else "pending"
        print(f"{module}: [{mark}] {version:03d}_{label}  ({path.name})")
    return 0


def cmd_baseline(module):
    conn = connect(module)
    applied = applied_versions(conn)
    migs = migrations_for(module)
    if not migs:
        print(f"{module}: no migration files found. Aborted.")
        conn.close()
        return 1
    if applied:
        print(
            f"{module}: already has migrations recorded ({applied}). "
            f"Baseline is a one-shot operation. Aborted."
        )
        conn.close()
        return 1
    if not has_user_tables(conn):
        print(
            f"{module}: database has no user tables — looks fresh. "
            f"Use `up` instead of `baseline`. Aborted."
        )
        conn.close()
        return 1
    version, label, _ = migs[0]
    conn.execute(
        "INSERT INTO schema_migrations (version, label) VALUES (?, ?)",
        (version, label),
    )
    conn.commit()
    conn.close()
    print(f"{module}: recorded version {version:03d}_{label} — SQL skipped.")
    return 0


def _guard_needs_baseline(module, conn, pending):
    """If 001 is pending AND user tables already exist, the user almost
    certainly meant to baseline, not up. Block before clobbering anything."""
    if 1 in {v for v, _, _ in pending} and has_user_tables(conn):
        print(
            f"{module}: refusing to apply 001 against a database that "
            f"already has tables. Run `baseline {module}` first."
        )
        return 1
    return None


def _guard_backdated(module, applied, pending):
    """Forward-only guard: refuse a pending migration whose version precedes the
    highest already-applied version. pending is sorted ascending, so a
    back-dated file (e.g. 002 added after 003 was applied) would otherwise run
    out of order, against a schema it never anticipated. There's no legitimate
    reason to apply a lower version after a higher one — re-number it, or use
    `baseline` to start partway."""
    if not applied:
        return None
    max_applied = max(applied)
    backdated = sorted(v for v, _, _ in pending if v < max_applied)
    if backdated:
        shown = ", ".join(f"{v:03d}" for v in backdated)
        print(
            f"{module}: refusing to apply back-dated migration(s) [{shown}] — "
            f"they precede the current version {max_applied:03d}. "
            f"Forward-only is enforced; re-number the migration or use `baseline`."
        )
        return 1
    return None


def _apply_pending(conn, module, pending):
    for version, label, path in pending:
        up_sql, _ = parse_migration(path)
        if not up_sql or is_effectively_empty(up_sql):
            print(f"{module}: {version:03d}_{label} has empty up section — skipping.")
            continue
        try:
            conn.executescript(up_sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, label) VALUES (?, ?)",
                (version, label),
            )
            conn.commit()
            print(f"{module}: applied {version:03d}_{label}")
        except sqlite3.Error as e:
            conn.rollback()
            # executescript() is deliberately non-atomic here (table-rebuild
            # migrations like jobs/004 need PRAGMA foreign_keys toggled in
            # autocommit mode), so a failure partway through a multi-statement
            # file can leave the schema partially applied — rollback() above only
            # undoes work since the last implicit commit. Surface that loudly so
            # the operator inspects the DB rather than blindly retrying.
            print(
                f"{module}: FAILED at {version:03d}_{label}: {e}\n"
                f"  WARNING: {version:03d} was NOT recorded as applied, but a "
                f"multi-statement migration may have partially run. Inspect the "
                f"database state before retrying."
            )
            return 1
    return 0


def cmd_up(module):
    conn = connect(module)
    applied = set(applied_versions(conn))
    migs = migrations_for(module)
    pending = [(v, lbl, p) for (v, lbl, p) in migs if v not in applied]

    if not pending:
        max_v = max(applied) if applied else 0
        print(f"{module}: nothing to do (current at version {max_v}).")
        conn.close()
        return 0

    for guard_result in (
        _guard_needs_baseline(module, conn, pending),
        _guard_backdated(module, applied, pending),
    ):
        if guard_result is not None:
            conn.close()
            return guard_result

    # Pre-migration backup of any database that already holds applied schema (a
    # fresh db on its first `up` has nothing worth a restore point). Taken AFTER
    # the guards above so a blocked run never leaves a stray backup, and BEFORE any
    # SQL runs so the snapshot is the true pre-migration state.
    backup = None
    if applied:
        backup = backup_db(module, pending[0][0])
        if backup:
            print(f"{module}: backed up → {backup.name}")

    result = _apply_pending(conn, module, pending)
    if result != 0:
        conn.close()
        return result

    # Whole run succeeded — retention: keep only the backup just made, drop older
    # pre-migration backups. A failed run returned above with its backup intact.
    if backup:
        removed = prune_backups(module, backup)
        if removed:
            print(f"{module}: pruned old backup(s): {', '.join(removed)}")

    conn.close()
    return 0


def cmd_down(module):
    conn = connect(module)
    applied = applied_versions(conn)
    if not applied:
        print(f"{module}: nothing to roll back.")
        conn.close()
        return 0

    latest = applied[-1]
    migs = {v: (lbl, p) for (v, lbl, p) in migrations_for(module)}
    if latest not in migs:
        print(
            f"{module}: applied version {latest} has no migration file. "
            f"Cannot generate a down script."
        )
        conn.close()
        return 1

    label, path = migs[latest]
    _, down_sql = parse_migration(path)

    if not down_sql or is_effectively_empty(down_sql):
        print(
            f"{module}: {latest:03d}_{label} has no real down script "
            f"(no-op or empty). Refusing to proceed."
        )
        conn.close()
        return 1

    print(f"{module}: about to roll back {latest:03d}_{label}.")
    resp = input("  Type 'yes' to continue: ").strip().lower()
    if resp != "yes":
        print("  Aborted.")
        conn.close()
        return 1

    try:
        conn.executescript(down_sql)
        conn.execute("DELETE FROM schema_migrations WHERE version = ?", (latest,))
        conn.commit()
        print(f"  Rolled back {latest:03d}_{label}.")
    except sqlite3.Error as e:
        conn.rollback()
        print(f"  FAILED: {e}")
        conn.close()
        return 1

    conn.close()
    return 0


COMMANDS = {
    "current": cmd_current,
    "list": cmd_list,
    "baseline": cmd_baseline,
    "up": cmd_up,
    "down": cmd_down,
}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Migration helper for vault SQLite databases.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument(
        "module",
        nargs="?",
        help="Module name (e.g. jobs). Omit to run on all modules.",
    )
    args = parser.parse_args(argv)

    modules = [args.module] if args.module else list_modules()
    if not modules:
        print(
            "No modules found under db/migrations/ (DBs live in the vault's data/). Nothing to do."
        )
        return 1

    rc = 0
    for module in modules:
        if not (MIGRATIONS_DIR / module).is_dir():
            print(f"{module}: no migrations folder.")
            rc = 1
            continue
        result = COMMANDS[args.command](module) or 0
        if result and not rc:
            rc = result
    return rc


if __name__ == "__main__":
    sys.exit(main())

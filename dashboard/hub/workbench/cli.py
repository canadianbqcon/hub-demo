#!/usr/bin/env python3
"""Workbench CLI: reads data/workbench.db directly, no Hub process needed.

`status <slug> <kind>` prints the current verdict: one of approved,
sent_back, not_applicable, abandoned, none. On sent_back, the comment
on a second line; on an approved design pick, the picked letter, then the picked card's title
(recorded by the page since 2026-09-29; older picks have no title line),
then a "note: " line when he typed a note with the pick (since 2026-10-15). This is what the build skill polls (background until-loop)
to get an approval click back into the session; see spec §3.

Exit 0 always, except exit 3 when the DB file is missing: this CLI never
creates it (that's db/migrate.py's job), so a fresh checkout with no
migration run yet fails loud instead of silently reporting "none".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store  # noqa: E402


def cmd_status(slug: str, kind: str) -> int:
    path = store.db_path()
    if not path.exists():
        print(f"workbench db not found: {path}", file=sys.stderr)
        return 3
    return _print_row(store.current(slug, kind))


def _print_row(row) -> int:
    if row is None:
        print("none")
        return 0
    print(row["verdict"])
    if row["verdict"] == "sent_back":
        print(row["comment"] or "")
    elif row["verdict"] == "approved" and row["choice"]:
        print(row["choice"])
        # the letter is a position that re-letters after a delete or fork; the
        # page records the picked card's title as a "title: " comment, and that is
        # the pick. Other writers (import_rig) leave notes without the prefix.
        # A note he typed with the pick rides on its own "note: " line, printed as is.
        lines = (row["comment"] or "").split("\n")
        if lines[0].startswith("title: "):
            print(lines[0][len("title: "):])
        for line in lines:
            if line.startswith("note: "):
                print(line)
    return 0


def cmd_seq(slug: str, kind: str) -> int:
    """Newest decision seq for this slug/kind, hash-blind (0 if none). A waiter
    snapshots it at handoff and wakes when it grows: `status` alone cannot tell
    a second fork or send-back from the first, since both read `sent_back`."""
    path = store.db_path()
    if not path.exists():
        print(f"workbench db not found: {path}", file=sys.stderr)
        return 3
    with store._conn(None) as conn:
        r = conn.execute(
            "SELECT MAX(seq) FROM decisions WHERE build_slug = ? AND kind = ?", (slug, kind)
        ).fetchone()
    print(r[0] or 0)
    return 0


def cmd_wait(slug: str, kind: str, since: int | None = None) -> int:
    """Block until a decision row newer than `since` lands for slug/kind, then
    print `status`. Keyed on rows, not on status text, so a second fork or
    send-back wakes it too. Pass `since` (the `seq` read BEFORE the round's
    first file write): a click made while the files were still being edited
    is then caught; a self-snapshot taken later would swallow it (2026-10-11)."""
    import contextlib
    import io
    import time

    # picks are filed under the option set's folder name: a design wait on a
    # build slug would sleep forever (2026-10-17), so refuse it up front
    if kind == "design" and not (store._roots()["design"] / slug).is_dir():
        print(f"no option set named {slug!r}: a design wait takes the set's folder name, not the build slug", file=sys.stderr)
        return 2

    def newest() -> int:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_seq(slug, kind)
        return int(buf.getvalue().strip() or 0)

    start = newest() if since is None else since
    while newest() <= start:
        time.sleep(20)
    # print the row that woke us, not the hash-matched current one: an edit
    # after the click changes the folder hash and `status` would say none.
    import sqlite3
    with store._conn(None) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM decisions WHERE build_slug = ? AND kind = ? ORDER BY seq DESC LIMIT 1",
            (slug, kind),
        ).fetchone()
    return _print_row(row)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 3 and argv[0] == "status":
        return cmd_status(argv[1], argv[2])
    if len(argv) == 3 and argv[0] == "seq":
        return cmd_seq(argv[1], argv[2])
    if len(argv) in (3, 4) and argv[0] == "wait":
        return cmd_wait(argv[1], argv[2], int(argv[3]) if len(argv) == 4 else None)
    print("usage: cli.py status|seq <slug> <kind> | wait <slug> <kind> [since]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

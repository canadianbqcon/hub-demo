#!/usr/bin/env python3
"""
Bootstrap the structured storage tree (migration 015) from the legacy free-text
storage_note blob (migration 003).

One-time-ish: parses the markdown map into storage_area / storage_unit /
storage_section / storage_item rows. Re-runnable, but it REBUILDS from the blob,
so once you've edited the tree in the UI, re-running clobbers those edits. Guarded:
refuses to run when the tree already has rows unless you pass --force.

  python -m batch_prep.seed_storage_map            # dry-run: print the parsed tree
  python -m batch_prep.seed_storage_map --seed     # write (only if tree is empty)
  python -m batch_prep.seed_storage_map --seed --force   # wipe + rebuild from blob

Run from dashboard/hub/ with PYTHONPATH=dashboard, or:
  cd dashboard/hub && python -m batch_prep.seed_storage_map --seed

Markdown grammar (the blob's actual shape):
  ## X            -> area (room)
  ### X           -> unit (fixture in the current room)
  **X**           -> section (shelf/row in the current unit)
  Foo:            -> section too (a non-bold label line, e.g. "Dried items:")
  - item          -> item in the current section
A line that begins a list with no preceding ### gets a blank passthrough unit; an
item with no preceding ** gets a blank passthrough section. The leading "# Title"
line is ignored.
"""

from __future__ import annotations

import pathlib
import re
import sqlite3
from contextlib import closing
import sys
from typing import Callable

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2])
)  # dashboard/, for vault_path
from vault_path import vault_root

DB_PATH = vault_root() / "data" / "work.db"

_AREA_RE = re.compile(r"^##\s+(?!#)(.+?)\s*$")        # "## Front room"
_UNIT_RE = re.compile(r"^###\s+(.+?)\s*$")            # "### Right fridge"
_BOLD_RE = re.compile(r"^\*\*(.+?)\*\*\s*$")          # "**Top row**"
_ITEM_RE = re.compile(r"^[-*]\s+(.+?)\s*$")           # "- Bitter melon"
_LABEL_RE = re.compile(r"^([A-Za-z].*?):\s*$")        # "Dried items:"


class _ParseState:
    """Mutable cursor (current area/unit/section) threaded through parse_blob's line rules."""

    def __init__(self) -> None:
        self.areas: list[dict] = []
        self.area: dict | None = None
        self.unit: dict | None = None
        self.section: dict | None = None

    def new_area(self, name: str = "") -> None:
        self.area = {"name": name, "units": []}
        self.areas.append(self.area)
        self.unit = None
        self.section = None

    def ensure_unit(self) -> dict:
        """Current unit, creating a blank passthrough one if items appear bare."""
        if self.area is None:  # item before any "##" — shouldn't happen, but be safe
            self.new_area()
        assert self.area is not None
        if self.unit is None:
            self.unit = {"name": "", "sections": []}
            self.area["units"].append(self.unit)
            self.section = None
        return self.unit

    def ensure_section(self) -> dict:
        """Current section, creating a blank passthrough one if items appear bare."""
        self.ensure_unit()
        assert self.unit is not None
        if self.section is None:
            self.section = {"name": "", "items": []}
            self.unit["sections"].append(self.section)
        return self.section

    def handle_area(self, m: re.Match) -> None:
        self.new_area(m.group(1).strip())

    def handle_unit(self, m: re.Match) -> None:
        if self.area is None:
            self.new_area()
        assert self.area is not None
        self.unit = {"name": m.group(1).strip(), "sections": []}
        self.area["units"].append(self.unit)
        self.section = None

    def handle_section_header(self, m: re.Match) -> None:
        self.ensure_unit()
        assert self.unit is not None
        self.section = {"name": m.group(1).strip(), "items": []}
        self.unit["sections"].append(self.section)

    def handle_item(self, m: re.Match) -> None:
        self.ensure_section()["items"].append(m.group(1).strip())

    def handle_stray(self, line: str) -> None:
        # any other stray prose line — attach as an item so nothing is dropped
        self.ensure_section()["items"].append(line.strip())


# first regex to match a line wins; BOLD and LABEL both open a new section header
_LINE_RULES: list[tuple[re.Pattern, Callable[[_ParseState, re.Match], None]]] = [
    (_AREA_RE, _ParseState.handle_area),
    (_UNIT_RE, _ParseState.handle_unit),
    (_BOLD_RE, _ParseState.handle_section_header),
    (_ITEM_RE, _ParseState.handle_item),
    (_LABEL_RE, _ParseState.handle_section_header),
]


def parse_blob(body: str) -> list[dict]:
    """Markdown blob -> ordered list of area dicts.

    area  = {"name", "units": [unit]}
    unit  = {"name", "sections": [section]}    name "" = passthrough fixture
    section = {"name", "items": [str]}         name "" = passthrough shelf
    """
    state = _ParseState()

    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("# ") and not line.startswith("## "):
            continue  # title

        for pattern, handler in _LINE_RULES:
            m = pattern.match(line)
            if m:
                handler(state, m)
                break
        else:
            state.handle_stray(line)

    return state.areas


def _tree_is_empty(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM storage_area").fetchone()[0] == 0


def write_tree(conn: sqlite3.Connection, areas: list[dict]) -> tuple[int, int]:
    """Insert the parsed tree. Returns (area_count, item_count)."""
    item_count = 0
    for ai, area in enumerate(areas):
        acur = conn.execute(
            "INSERT INTO storage_area(name, sort_order) VALUES(?,?)",
            (area["name"], ai),
        )
        area_id = acur.lastrowid
        for ui, unit in enumerate(area["units"]):
            ucur = conn.execute(
                "INSERT INTO storage_unit(area_id, name, sort_order) VALUES(?,?,?)",
                (area_id, unit["name"], ui),
            )
            unit_id = ucur.lastrowid
            for si, section in enumerate(unit["sections"]):
                scur = conn.execute(
                    "INSERT INTO storage_section(unit_id, name, sort_order) VALUES(?,?,?)",
                    (unit_id, section["name"], si),
                )
                section_id = scur.lastrowid
                for ii, item in enumerate(section["items"]):
                    conn.execute(
                        "INSERT INTO storage_item(section_id, text, sort_order) VALUES(?,?,?)",
                        (section_id, item, ii),
                    )
                    item_count += 1
    conn.commit()
    return len(areas), item_count


def print_tree(areas: list[dict]) -> None:
    items = 0
    for area in areas:
        print(f"\n## {area['name'] or '(unnamed area)'}")
        for unit in area["units"]:
            print(f"  ### {unit['name'] or '(loose — no fixture)'}")
            for section in unit["sections"]:
                label = section["name"] or "(loose — no shelf)"
                print(f"      {label}")
                for it in section["items"]:
                    print(f"        - {it}")
                    items += 1
    print(f"\n{len(areas)} areas · {items} items\n")


def main() -> None:
    seed = "--seed" in sys.argv
    force = "--force" in sys.argv
    # One closing() block instead of a conn.close() at each of the four early
    # returns: a fifth return added later would have silently leaked, and any
    # exception in parse_blob()/write_tree() leaked already.
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute("SELECT body FROM storage_note WHERE id = 1").fetchone()
        if row is None or not (row[0] or "").strip():
            print("storage_note is empty — nothing to seed from.")
            return
        areas = parse_blob(row[0])

        if not seed:
            print_tree(areas)
            print("(dry run — pass --seed to write)")
            return

        if not _tree_is_empty(conn) and not force:
            n = conn.execute("SELECT COUNT(*) FROM storage_area").fetchone()[0]
            print(
                f"storage tree already has {n} area(s); refusing to clobber. "
                "Pass --force to wipe and rebuild from the blob."
            )
            return

        if force:
            conn.execute("DELETE FROM storage_item")
            conn.execute("DELETE FROM storage_section")
            conn.execute("DELETE FROM storage_unit")
            conn.execute("DELETE FROM storage_area")
        a, i = write_tree(conn, areas)
        print(f"Seeded {a} areas · {i} items into the storage tree.")


if __name__ == "__main__":
    main()

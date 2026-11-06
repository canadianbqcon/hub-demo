"""Trip members, the cross-trip roster, and the identity key a guest code
links to.

Split out of trips/db.py (Task 2). `_MEMBER_FIELDS` and `NAME_KEY` stay on the
facade (Rule 1) and are reached here as `db.<name>`. `member_key`/`_key_where`
moved here from db_guests.py (2026-09-24) to keep that file under the
500-line bar — they resolve a person's identity against `members`, which fits
this file's domain as well as the gate's.
"""

from __future__ import annotations

from . import db


def member_key(name: str, contact_slug: str) -> str:
    """The identity a guest code links to.

    Most crew members carry a contact_slug pointing at their wiki contact node,
    and that stays the key. Plenty of people were typed straight into a trip and
    have no node at all, though, and they are still crew — so their key is their
    name behind a `name:` prefix. A real slug is kebab-case and never holds a
    colon, so the two spaces cannot collide.
    """
    slug = (contact_slug or "").strip()
    return slug if slug else db.NAME_KEY + (name or "").strip().lower()


def _key_where(key: str) -> tuple[str, str]:
    """SQL predicate + bind value for matching `members` rows against a key."""
    if key.startswith(db.NAME_KEY):
        return "LOWER(TRIM(name))=?", key[len(db.NAME_KEY):]
    return "contact_slug=?", key


def add_member(trip_id, data):
    return db._add("members", trip_id, data, db._MEMBER_FIELDS)


def update_member(trip_id, mid, data):
    return db._update("members", mid, trip_id, data, db._MEMBER_FIELDS)


def delete_member(trip_id, mid):
    return db._delete("members", mid, trip_id)


def trip_members(trip_id: int) -> list[dict] | None:
    """Just the crew. None means the trip itself doesn't exist.

    /preferences used get_full_trip for this and threw away six other tables'
    worth of rows: 79ms against 22ms, nearly all of which is opening a
    connection to a database that lives on /mnt/c. One connection, two queries.
    """
    with db._conn() as conn:
        if not conn.execute("SELECT 1 FROM trips WHERE id=?", (trip_id,)).fetchone():
            return None
        return db._rows(
            conn.execute(
                "SELECT * FROM members WHERE trip_id=? ORDER BY id", (trip_id,)
            ).fetchall()
        )


def roster(exclude_trip_id: int | None = None) -> list[dict]:
    """Every distinct person who has ever been on a trip, newest trip first.

    There is no separate `people` table and there does not need to be: `members`
    already stores one row per person per trip carrying the `contact_slug` that
    links to their wiki contact node, so the roster IS a DISTINCT over it.

    Identity resolves on both axes, because either alone splits a real person in
    two: keying on contact_slug misses the trip where they were typed in by hand
    with no slug, and keying on name misses the trip where the name was written
    differently. So a slug claims the first name it is seen with, and every row
    then resolves through that claim.

    ponytail: grouping in Python rather than a window function — the members
    table is a few dozen rows. Push it into SQL if it ever isn't.
    """
    with db._conn() as conn:
        rows = db._rows(conn.execute(
            """SELECT m.name, m.email, m.contact_slug, m.trip_id,
                      t.name AS trip_name, t.start_date
                 FROM members m JOIN trips t ON t.id = m.trip_id
                ORDER BY t.start_date DESC, m.name"""
        ))

    slug_claim: dict[str, str] = {}
    for r in rows:
        slug = (r["contact_slug"] or "").strip().lower()
        if slug:
            slug_claim.setdefault(slug, r["name"].strip().lower())

    def _key(r):
        slug = (r["contact_slug"] or "").strip().lower()
        return slug_claim.get(slug) or r["name"].strip().lower()

    excluded = {_key(r) for r in rows if r["trip_id"] == exclude_trip_id} if exclude_trip_id is not None else set()

    out: dict[str, dict] = {}
    for r in rows:
        key = _key(r)
        if key in excluded:
            continue
        entry = out.get(key)
        if entry is None:
            entry = out[key] = {
                "name": r["name"],
                "email": r["email"] or "",
                "contact_slug": r["contact_slug"] or "",
                "trips": [],
            }
        # first non-empty value wins for each field. The name is the exception: a
        # row carrying a contact_slug is the one tied to a real contact node, so
        # its spelling beats whatever a hand-typed row happened to use.
        if not entry["email"] and r["email"]:
            entry["email"] = r["email"]
        if not entry["contact_slug"] and r["contact_slug"]:
            entry["contact_slug"] = r["contact_slug"]
            entry["name"] = r["name"]
        entry["trips"].append({"id": r["trip_id"], "name": r["trip_name"], "start_date": r["start_date"] or ""})
    return list(out.values())

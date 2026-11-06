"""Data layer for the food-places research store.

Reads and writes data/food.db. Schema comes from db/migrations/food/, never from
this file: init() only records the path.

Two rules are enforced here rather than in SQL, because neither is expressible as
a CHECK constraint:

1. Both confidence labels are derived from a COUNT over another table.
2. A score is NULL when the ledger it summarises is empty. Depth reads the literate
   cohort, execution reads every cohort. That is an empty set, not a quality gate:
   one row is enough to write a score, and the count only decides the label. See
   the spec section "Evidence disclosure, not gating".
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from sqlite_helpers import connect as sqlite_connect, row as _row
from sqlite_helpers import row_strict as _row_strict, rows as _rows

_db_path: Path | None = None

# "This level is not filtered", which is a different thing from "this level is empty".
# get_places used to conflate them: it built its WHERE under `if val`, so borough=None and
# borough="" both meant unfiltered, and a Denver-proper neighborhood could not be selected
# at all — its places carry borough IS NULL, so the only honest filter for them is one the
# old signature had no way to express. Now: ANY = no clause, None = COALESCE(...)='' , a
# string = equality.
ANY = object()


class AmbiguousArea(LookupError):
    """Two areas rows describe the same place. Better to fail than to pick one."""


def fold(name: str | None) -> str:
    """Canonical form of an area name: accent- and case-insensitive.

    Slugs are lossy (`Café` and `Cafe` collapse), so identity is compared on this rather
    than on the slug. Two different names that fold together are a real collision and the
    caller raises; two spellings of one name folding together is the point.
    """
    s = unicodedata.normalize("NFKD", name or "")
    return "".join(c for c in s if not unicodedata.combining(c)).casefold().strip()


def slugify(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-")


def _no_boro(value) -> bool:
    """The one read-time rule for 'has no borough'.

    places.borough is NULL for a city's own neighborhoods; areas.borough is ''. Neither
    side may be tested directly or half the data disappears.
    """
    return not (value or "").strip()


# Containment, level by level. The old version matched `p.neighborhood = a.name OR
# p.borough = a.name OR p.city = a.name`, which is level-agnostic and keys on a display
# name: `Englewood` is both a Denver suburb and a neighborhood name in the live data, so an
# Englewood area counted itself twice. Every count, filter and membership test now routes
# through this one predicate.
_AREA_PLACES_SQL = """(
    p.city = a.city AND (
        a.level = 'city'
     OR (a.level = 'borough' AND p.borough = a.name)
     OR (a.level = 'neighborhood' AND p.neighborhood = a.name
         AND COALESCE(p.borough, '') = COALESCE(a.borough, ''))
    )
)"""


def init(db_path: Path) -> None:
    """Point the module at a database file. Creates no schema; migrations do that."""
    global _db_path
    _db_path = db_path


def _conn():
    return sqlite_connect(_db_path, "food")


def depth_confidence_label(literate_rows: int) -> str:
    """How much evidence stands behind a score.

    A label, never a gate. 0 is the one case with no score, because an average over
    an empty set is not a number.
    """
    if literate_rows <= 0:
        return "none"
    if literate_rows <= 2:
        return "thin"
    if literate_rows <= 5:
        return "moderate"
    return "strong"


def upsert_area(slug, level, name, city, borough, country, lat, lng) -> int:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO areas (slug, level, name, city, borough, country, lat, lng)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(slug) DO UPDATE SET
                 name=excluded.name, city=excluded.city, borough=excluded.borough,
                 country=excluded.country, lat=excluded.lat, lng=excluded.lng,
                 updated=datetime('now')""",
            (slug, level, name, city, borough, country, lat, lng),
        )
        return conn.execute(
            "SELECT id FROM areas WHERE slug = ?", (slug,)
        ).fetchone()[0]


def set_scene(area_slug: str, scene, researched: str) -> None:
    """Store the scene rundown.

    `scene` is a list of {"label", "items":[{"k","v"}]} sections, stored as JSON in
    the same TEXT column prose used to live in. The frontend parses it and falls
    back to paragraphs when the parse fails, so an area written before the format
    change still renders. A plain string is passed through unchanged for that reason
    — not as a supported input for new runs.
    """
    if isinstance(scene, (list, dict)):
        scene = json.dumps(scene, ensure_ascii=False)
    with _conn() as conn:
        conn.execute(
            """UPDATE areas SET scene = ?, scene_researched = ?, updated = datetime('now')
               WHERE slug = ?""",
            (scene, researched, area_slug),
        )


_PLACE_COLS = (
    "slug", "name", "address", "neighborhood", "borough", "city", "country",
    "lat", "lng", "cuisine_broad", "cuisine_specific", "cuisines_extra",
    "discovery", "summary", "pros", "cons", "order_this", "price_band",
    "practical", "practical_checked", "status", "researched",
)


def upsert_place(**fields) -> int:
    """Insert or update a place by slug. Scores are set separately by finalize_scores."""
    for key in ("cuisines_extra", "pros", "cons", "order_this", "practical"):
        if isinstance(fields.get(key), (list, dict)):
            fields[key] = json.dumps(fields[key], ensure_ascii=False)
    cols = [c for c in _PLACE_COLS if c in fields]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "slug")
    with _conn() as conn:
        conn.execute(
            f"""INSERT INTO places ({', '.join(cols)}) VALUES ({placeholders})
                ON CONFLICT(slug) DO UPDATE SET {updates}, updated=datetime('now')""",
            tuple(fields[c] for c in cols),
        )
        return conn.execute(
            "SELECT id FROM places WHERE slug = ?", (fields["slug"],)
        ).fetchone()[0]


def add_evidence(place_id: int, source: str, url: str, quote: str, cohort: str,
                 cohort_reason: str, polarity: str, axis: str,
                 author: str = "", dated: str | None = None) -> int:
    """Store one quote. A row with no source url is refused.

    This is the only write-time refusal in the module, and it is about provenance,
    not volume: an unsourced quote cannot be checked by eye, and an evidence ledger
    whose quotes cannot be checked is decoration.
    """
    if not url or not url.strip():
        raise ValueError("evidence requires a source url")
    if not quote or not quote.strip():
        raise ValueError("evidence requires a quote")
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO evidence
                 (place_id, source, url, author, dated, quote, cohort,
                  cohort_reason, polarity, axis)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (place_id, source, url.strip(), author, dated, quote.strip(),
             cohort, cohort_reason, polarity, axis),
        )
        return cur.lastrowid


def finalize_scores(place_id: int, depth_score: float | None,
                    execution_score: float | None) -> dict:
    """Stamp scores and derive both confidence labels from the ledger.

    A score is dropped only when its own ledger is empty: depth reads the literate
    cohort, execution reads every cohort. Both axes behave the same way on purpose.
    An asymmetry here would read as an oversight, and the reason is identical on
    both sides: a score over an empty set is an absence, not a number.
    """
    with _conn() as conn:
        literate = conn.execute(
            "SELECT COUNT(*) FROM evidence WHERE place_id = ? AND cohort = 'literate'",
            (place_id,),
        ).fetchone()[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM evidence WHERE place_id = ?", (place_id,)
        ).fetchone()[0]
        depth_label = depth_confidence_label(literate)
        execution_label = depth_confidence_label(total)
        if depth_label == "none":
            depth_score = None
        if execution_label == "none":
            execution_score = None
        conn.execute(
            """UPDATE places SET depth_score = ?, depth_confidence = ?,
                                 execution_score = ?, execution_confidence = ?,
                                 updated = datetime('now')
               WHERE id = ?""",
            (depth_score, depth_label, execution_score, execution_label, place_id),
        )
        return _row_strict(conn.execute(
            "SELECT * FROM places WHERE id = ?", (place_id,)
        ).fetchone())


def get_areas() -> list[dict]:
    """Areas with their coverage counts, most recently researched first.

    `cuisines` is what makes coverage honest: an area researched for one tradition
    must not present as a finished area, and a place count alone cannot say that.

    `parent_slug` is derived, not stored. Containment is already fully described by
    the city/borough columns every area carries, so a parent column would be a second
    copy of that fact that can disagree with it. The lookup prefers a borough parent
    over a city one, which is what makes a city with no boroughs researched hold its
    neighborhoods directly: the borough branch finds nothing and the city branch
    catches them.
    """
    with _conn() as conn:
        return _rows(conn.execute(
            """SELECT a.*,
                      (SELECT pa.slug FROM areas pa
                        WHERE pa.id <> a.id AND pa.city = a.city
                          AND pa.country = a.country
                          AND ((a.level = 'borough' AND pa.level = 'city')
                            OR (a.level = 'neighborhood' AND pa.level = 'borough'
                                AND pa.name = COALESCE(a.borough, ''))
                            OR (a.level = 'neighborhood' AND pa.level = 'city'))
                        ORDER BY CASE pa.level WHEN 'borough' THEN 0 ELSE 1 END
                        LIMIT 1) AS parent_slug,
                      (SELECT COUNT(*) FROM places p
                        WHERE """ + _AREA_PLACES_SQL + """) AS place_count,
                      (SELECT group_concat(c, char(31)) FROM (
                          SELECT DISTINCT p.cuisine_specific AS c FROM places p
                           WHERE """ + _AREA_PLACES_SQL + """
                             AND p.cuisine_specific <> ''
                           ORDER BY p.cuisine_specific)) AS cuisines
               FROM areas a ORDER BY a.scene_researched DESC NULLS LAST, a.name"""
        ))


def get_places(city=None, borough=ANY, neighborhood=ANY, cuisine_broad=None,
               cuisine_specific=None, discovery=None, min_depth=None,
               price_band=None) -> list[dict]:
    """Places under a filter. `borough`/`neighborhood` are three-state, see ANY.

    They have to be, and the reason is live in the data: `East Colfax` exists twice, once
    under Denver proper (borough IS NULL) and once under Aurora. Selecting the first one
    means asking for "this neighborhood, in no borough" — a query the old two-state
    signature could not express, so both rows came back on both pages.
    """
    clauses, params = [], []
    for col, val in (("borough", borough), ("neighborhood", neighborhood)):
        if val is ANY:
            continue
        if _no_boro(val):
            clauses.append(f"COALESCE({col}, '') = ''")
        else:
            clauses.append(f"{col} = ?")
            params.append(val)
    for col, val in (("city", city), ("cuisine_broad", cuisine_broad),
                     ("cuisine_specific", cuisine_specific), ("discovery", discovery),
                     ("price_band", price_band)):
        if val:
            clauses.append(f"{col} = ?")
            params.append(val)
    if min_depth is not None:
        clauses.append("depth_score >= ?")
        params.append(min_depth)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _conn() as conn:
        # The two counts ride along because the list view has to render a thin score
        # WITH the number of sources under it ("8, thin evidence: 2 sources"). Without
        # them the list can only say "thin", which is the abstract-label failure the
        # confidence label exists to avoid. One correlated subquery each, on a table
        # indexed by place_id.
        return _rows(conn.execute(
            f"""SELECT p.*,
                       (SELECT COUNT(*) FROM evidence e
                         WHERE e.place_id = p.id AND e.cohort = 'literate') AS literate_count,
                       (SELECT COUNT(*) FROM evidence e
                         WHERE e.place_id = p.id) AS evidence_count
                  FROM places p {where}
                 ORDER BY depth_score DESC NULLS LAST, name""",
            tuple(params),
        ))


def _member(level: str, city: str, borough=None, neighborhood=None) -> dict:
    """The tuple that says which places belong to an area, as get_places kwargs.

    Only levels at or above the area's own grain appear. A key that is present and None
    means "no borough"; a key that is absent means "any", which is why a city keeps all its
    boroughs and a borough keeps all its neighborhoods. Constraining every level would make
    a city page show only the places filed directly on the city.

    The client selects a child's places with this and nothing else. Not the name (there are
    two East Colfaxes), and not the slug — a real row's slug is an independent identifier
    with no tuple in it, `brooklyn-nyc` says nothing about Brooklyn.
    """
    member: dict = {"city": city}
    if level in ("borough", "neighborhood"):
        member["borough"] = None if _no_boro(borough) else borough
    if level == "neighborhood":
        member["neighborhood"] = neighborhood
    return member


def _derived(parent_slug: str, name: str, level: str, member: dict) -> dict:
    """An area that exists because places point at it, not because a run wrote a row."""
    return {
        "slug": f"{parent_slug}/{slugify(name)}", "level": level, "name": name,
        "city": member["city"], "borough": member["borough"] or "", "country": "",
        "lat": None, "lng": None, "scene": "", "scene_researched": None,
        "derived": True, "member": member,
    }


def _real_children(conn, area: dict) -> list[dict]:
    """Rows in `areas` that sit one level inside this area.

    Deliberately NOT `parent_slug`. That lookup falls back to the city when no borough row
    exists, so a Cobble Hill row written before a Brooklyn one reports the city as its
    parent and would render in the New York grid beside a derived Brooklyn, double-counting
    its places. Position is read from the columns instead.
    """
    if area["level"] == "city":
        sql = """SELECT * FROM areas WHERE city = ? AND slug <> ? AND (
                    level = 'borough'
                 OR (level = 'neighborhood' AND COALESCE(borough, '') = ''))"""
        params = (area["city"], area["slug"])
    elif area["level"] == "borough":
        sql = """SELECT * FROM areas WHERE city = ? AND slug <> ?
                  AND level = 'neighborhood' AND borough = ?"""
        params = (area["city"], area["slug"], area.get("borough") or area["name"])
    else:
        return []
    return _rows(conn.execute(sql, params))


def _places_for_children(conn, area: dict) -> list:
    if area["level"] == "city":
        return conn.execute(
            "SELECT borough, neighborhood, cuisine_specific FROM places WHERE city = ?",
            (area["city"],),
        ).fetchall()
    return conn.execute(
        """SELECT borough, neighborhood, cuisine_specific FROM places
            WHERE city = ? AND borough = ?""",
        (area["city"], area.get("borough") or area["name"]),
    ).fetchall()


def _kids_from_places(area: dict, rows: list) -> dict[str, dict]:
    kids: dict[str, dict] = {}
    for boro, hood, cuisine in rows:
        if area["level"] == "city" and not _no_boro(boro):
            name, level = boro, "borough"
            member = _member("borough", area["city"], boro)
        elif not _no_boro(hood):
            name, level = hood, "neighborhood"
            member = _member("neighborhood", area["city"], boro, hood)
        else:
            continue          # a place filed straight on the city, no child to make
        kid = kids.setdefault(fold(name), {
            **_derived(area["slug"], name, level, member),
            "place_count": 0, "_cuisines": set(),
        })
        kid["place_count"] += 1
        if cuisine:
            kid["_cuisines"].add(cuisine)
    return kids


def _merge_real_children(conn, area: dict, kids: dict[str, dict]) -> None:
    """A real row takes the derived one's place entirely: its slug, its research stamp."""
    for real in _real_children(conn, area):
        key = fold(real["name"])
        kid = kids.get(key)
        if kid is not None and kid.get("derived") is False:
            # Two rows describing one place. Picking either would make the page's
            # identity depend on row order, so refuse instead.
            raise AmbiguousArea(
                f"{real['name']!r} under {area['slug']} is claimed by both "
                f"{kid['slug']!r} and {real['slug']!r}")
        if kid is None:
            kid = kids[key] = {**real, "derived": False, "place_count": 0,
                               "_cuisines": set()}
            kid["member"] = _member(
                real["level"], real["city"],
                real["name"] if real["level"] == "borough" else real["borough"],
                None if real["level"] == "borough" else real["name"],
            )
        else:
            kid.update(slug=real["slug"], derived=False, level=real["level"],
                       name=real["name"], lat=real["lat"], lng=real["lng"],
                       scene=real["scene"], scene_researched=real["scene_researched"])


def _finalize_children(kids: dict[str, dict]) -> list[dict]:
    out = []
    for kid in kids.values():
        cuisines = sorted(kid.pop("_cuisines"))
        out.append({**kid, "cuisines": "\x1f".join(cuisines)})
    out.sort(key=lambda k: (-k["place_count"], fold(k["name"])))
    return out


def get_children(area: dict) -> list[dict]:
    """The areas one level inside this one, derived from places, real rows merged in.

    A city holds its boroughs plus the neighborhoods that sit in no borough — one tier
    holding two levels, which is the shape Denver actually has (Aurora is a suburb in the
    borough column while LoHi hangs off the city directly).
    """
    if area["level"] == "neighborhood":
        return []
    with _conn() as conn:
        rows = _places_for_children(conn, area)
        kids = _kids_from_places(area, rows)
        _merge_real_children(conn, area, kids)
    return _finalize_children(kids)


def resolve_area(path: str, _depth: int = 0) -> dict | None:
    """Resolve a page path to an area, real or derived.

    Recursive on purpose. `denver-co/aurora/east-colfax` has the parent `denver-co/aurora`,
    which is itself derived and has no row, so one split-on-the-last-slash would 404 every
    two-deep page.
    """
    segments = [s for s in path.split("/") if s]     # eats trailing slashes and '//'
    if not segments or _depth > 4:
        return None
    with _conn() as conn:
        row = _row(conn.execute(
            "SELECT * FROM areas WHERE slug = ?", ("/".join(segments),)).fetchone())
    if row is not None:
        return {**row, "derived": False, "member": _member(
            row["level"], row["city"],
            row["name"] if row["level"] == "borough" else row["borough"],
            row["name"] if row["level"] == "neighborhood" else None,
        )}
    if len(segments) == 1:
        return None
    parent = resolve_area("/".join(segments[:-1]), _depth + 1)
    if parent is None:
        return None
    tail = segments[-1]
    matches = [k for k in get_children(parent)
               if slugify(k["name"]) == tail or fold(k["name"]) == fold(tail)]
    if len(matches) > 1:
        raise AmbiguousArea(f"{tail!r} matches {len(matches)} areas under {parent['slug']}")
    return matches[0] if matches else None


def ancestors_of(area: dict, _depth: int = 0) -> list[dict]:
    """Outermost first. Derived areas carry their parent in the slug; real ones don't."""
    if _depth > 4:
        return []
    if area.get("derived"):
        parent_path = "/".join(area["slug"].split("/")[:-1])
        parent = resolve_area(parent_path) if parent_path else None
    else:
        with _conn() as conn:
            slug = _row(conn.execute(
                """SELECT (SELECT pa.slug FROM areas pa
                            WHERE pa.id <> a.id AND pa.city = a.city
                              AND pa.country = a.country
                              AND ((a.level = 'borough' AND pa.level = 'city')
                                OR (a.level = 'neighborhood' AND pa.level = 'borough'
                                    AND pa.name = COALESCE(a.borough, ''))
                                OR (a.level = 'neighborhood' AND pa.level = 'city'))
                            ORDER BY CASE pa.level WHEN 'borough' THEN 0 ELSE 1 END
                            LIMIT 1) AS s
                     FROM areas a WHERE a.slug = ?""", (area["slug"],)).fetchone())
        parent = resolve_area(slug["s"]) if slug and slug["s"] else None
    return (ancestors_of(parent, _depth + 1) + [parent]) if parent else []


def get_place(slug: str) -> dict | None:
    with _conn() as conn:
        return _row(conn.execute(
            "SELECT * FROM places WHERE slug = ?", (slug,)
        ).fetchone())


def get_evidence(place_id: int) -> list[dict]:
    """Ledger for one place, literate cohort first."""
    with _conn() as conn:
        return _rows(conn.execute(
            """SELECT * FROM evidence WHERE place_id = ?
               ORDER BY CASE cohort WHEN 'literate' THEN 0 WHEN 'general' THEN 1
                                    ELSE 2 END, dated DESC NULLS LAST""",
            (place_id,),
        ))


def start_run(area_slug: str, cuisines: list[str]) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO runs (area_slug, cuisines, started) VALUES (?, ?, datetime('now'))",
            (area_slug, json.dumps(cuisines)),
        )
        return cur.lastrowid


def finish_run(run_id: int, candidates_found: int, places_written: int,
               sources_worked: dict, notes: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            """UPDATE runs SET finished = datetime('now'), candidates_found = ?,
                               places_written = ?, sources_worked = ?, notes = ?
               WHERE id = ?""",
            (candidates_found, places_written,
             json.dumps(sources_worked, ensure_ascii=False), notes, run_id),
        )

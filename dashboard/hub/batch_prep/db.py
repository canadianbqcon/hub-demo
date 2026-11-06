from __future__ import annotations

from pathlib import Path

from sqlite_helpers import connect as sqlite_connect

# Batch-prep reads the J&Co work store. work.db is NOT owned by this module — its
# schema lives in data/migrations/work/ (warehouse contract). This module only
# opens connections and runs queries; it never CREATEs or migrates. (Renamed from
# jc.db on 2026-06-06 when it became the "work" domain db — see
# wiki/decisions/onboard-work-module.md.)
_db_path: Path | None = None


def init(db_path: Path) -> None:
    """Point the module at work.db. Called once at app startup with data/work.db.

    Unlike jobs/vault_map, this module does NOT bootstrap a schema here — work.db
    already exists and is migrated via `python data/migrate.py up work`.
    """
    global _db_path
    if not db_path.exists():
        raise FileNotFoundError(
            f"work.db not found at {db_path}; run data/migrate.py up work"
        )
    _db_path = db_path


def _conn():
    return sqlite_connect(_db_path, "batch_prep.db")


# ── Query layer ───────────────────────────────────────────────────────────────
# Phase B: read recipes for the scalable viewer + the textual storage map.
# Scaling itself is client-side and never touches this layer. BOM explosion and
# prep-day persistence (Phase C) land in a later pass.

_LIST_LIMIT = 500


def list_recipes(kind: str = "batch") -> list[dict]:
    """List recipes of one kind (default 'batch'), alpha by name.

    Each row carries enough to render a list card without a per-recipe detail
    fetch: the header fields plus the yield and two counts. `ingredient_count`
    drives the at-a-glance complexity readout; `sub_count` (ingredients that are
    themselves made preps) drives the prep-vs-direct tag — >0 means the recipe
    depends on sub-recipes you build first.
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT r.id, r.name, r.category, r.menu, r.yield_qty, r.yield_unit, "
            "  (SELECT COUNT(*) FROM recipe_ingredients ri "
            "     WHERE ri.recipe_id = r.id) AS ingredient_count, "
            "  (SELECT COUNT(*) FROM recipe_ingredients ri "
            "     WHERE ri.recipe_id = r.id "
            "       AND ri.produces_recipe_id IS NOT NULL) AS sub_count "
            "FROM recipes r "
            "WHERE r.kind = ? ORDER BY r.name COLLATE NOCASE LIMIT ?",
            (kind, _LIST_LIMIT),
        ).fetchall()
    return [dict(r) for r in rows]


def get_recipe(recipe_id: int) -> dict | None:
    """Full recipe for the viewer: header, yield, and structured ingredients.

    Each ingredient carries the machine-scalable fields (qty/unit/scalable) plus
    the original free-text `amount` for provenance, and — when the ingredient is
    itself a made prep/batch — the produced recipe's id and name (the BOM link).
    """
    with _conn() as conn:
        rec = conn.execute(
            "SELECT id, kind, name, category, method, notes, yield_qty, yield_unit "
            "FROM recipes WHERE id = ?",
            (recipe_id,),
        ).fetchone()
        if rec is None:
            return None
        ingredients = conn.execute(
            "SELECT ri.id, ri.ingredient, ri.amount, ri.qty, ri.unit, "
            "       ri.scalable, ri.produces_recipe_id, "
            "       pr.name AS produces_name "
            "FROM recipe_ingredients ri "
            "LEFT JOIN recipes pr ON pr.id = ri.produces_recipe_id "
            "WHERE ri.recipe_id = ? "
            "ORDER BY ri.sort_order, ri.id LIMIT ?",
            (recipe_id, _LIST_LIMIT),
        ).fetchall()
    out = dict(rec)
    out["ingredients"] = [dict(i) for i in ingredients]
    return out


def get_storage() -> dict:
    """The textual storage map (single-row storage_note). Empty body if unseeded."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT body, updated FROM storage_note WHERE id = 1"
        ).fetchone()
    if row is None:
        return {"body": "", "updated": None}
    return dict(row)


def set_storage(body: str) -> dict:
    """Overwrite the storage map text, stamping `updated`. Upserts the id=1 row."""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO storage_note (id, body, updated) "
            "VALUES (1, ?, datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET body = excluded.body, "
            "                              updated = excluded.updated",
            (body,),
        )
        row = conn.execute(
            "SELECT body, updated FROM storage_note WHERE id = 1"
        ).fetchone()
    return dict(row)


# ── Structured storage map (Phase D, revived 2026-06-20) ───────────────────────
# A four-level tree (area → unit → section → item) replacing the free-text blob on
# the map view. The blob (storage_note) is kept as the seed source + archive; this
# layer is the live one. `get_storage_tree` reads the whole thing in four ordered
# queries (assembled in Python — the tree is tiny); the CRUD helpers are generic
# over the four levels via _LEVELS so add/rename/delete/reorder isn't written four
# times. Reordering is sort_order swap with the adjacent same-parent sibling
# (the up/down arrows). Every mutation returns the full tree so the frontend always
# re-renders from authoritative state.

# kind → (table, parent column or None for the root, label column). The parent
# column ties a row to its container and scopes both "next sort_order" and the
# reorder sibling set. Whitelisted here so table/column names never come from input.
_LEVELS = {
    "area": ("storage_area", None, "name"),
    "unit": ("storage_unit", "area_id", "name"),
    "section": ("storage_section", "unit_id", "name"),
    # a subsection IS a section — same table, hung off another section instead of
    # off the unit. The separate kind exists so add/reorder scope to the right
    # parent column; nesting depth is unbounded (migration 018).
    "subsection": ("storage_section", "parent_id", "name"),
    "item": ("storage_item", "section_id", "text"),
}

# kind → the table its parent lives in (FK existence checks). Not derivable by
# index any more, since section and subsection share a table.
_PARENT_TABLE = {
    "unit": "storage_area",
    "section": "storage_unit",
    "subsection": "storage_section",
    "item": "storage_section",
}


def get_storage_tree() -> dict:
    """The whole storage tree as nested areas → units → sections → items.

    Each node carries its id + label; items also carry `note`. Empty branches are
    kept (a unit with no sections, a section with no items) so the editor can show
    and fill them. Blank-named units/sections are passthroughs — the frontend draws
    them without a sub-header but still lets you name them.
    """
    with _conn() as conn:
        areas = [
            {"id": r["id"], "name": r["name"], "units": []}
            for r in conn.execute(
                "SELECT id, name FROM storage_area ORDER BY sort_order, id"
            ).fetchall()
        ]
        units = {
            r["id"]: {"id": r["id"], "name": r["name"], "area_id": r["area_id"], "sections": []}
            for r in conn.execute(
                "SELECT id, area_id, name FROM storage_unit ORDER BY sort_order, id"
            ).fetchall()
        }
        sections = {
            r["id"]: {
                "id": r["id"], "name": r["name"], "unit_id": r["unit_id"],
                "parent_id": r["parent_id"], "items": [], "sections": [],
            }
            for r in conn.execute(
                "SELECT id, unit_id, parent_id, name FROM storage_section"
                " ORDER BY sort_order, id"
            ).fetchall()
        }
        items = conn.execute(
            "SELECT id, section_id, text, note FROM storage_item ORDER BY sort_order, id"
        ).fetchall()

    for it in items:
        sec = sections.get(it["section_id"])
        if sec is not None:
            sec["items"].append({"id": it["id"], "text": it["text"], "note": it["note"]})
    area_by_id = {a["id"]: a for a in areas}
    # preserve query order (already sort_order, id) when threading children up.
    # Sections nest (migration 018): a row with a parent_id hangs off that
    # section, one without hangs off its unit. The dicts are threaded in place,
    # so a child appended here is already visible inside its parent's payload.
    for sec in sections.values():
        node = {k: sec[k] for k in ("id", "name", "items", "sections")}
        sec["payload"] = node
    for sec in sections.values():
        parent = sections.get(sec["parent_id"]) if sec["parent_id"] else None
        if parent is not None:
            parent["payload"]["sections"].append(sec["payload"])
            continue
        unit = units.get(sec["unit_id"])
        if unit is not None:
            unit["sections"].append(sec["payload"])
    for unit in units.values():
        area = area_by_id.get(unit["area_id"])
        if area is not None:
            area["units"].append({k: unit[k] for k in ("id", "name", "sections")})
    return {"areas": areas}


def _level(kind: str):
    """Resolve a kind to (table, parent_col, label_col); raise on an unknown kind."""
    if kind not in _LEVELS:
        raise ValueError(f"unknown storage level: {kind}")
    return _LEVELS[kind]


def add_node(kind: str, parent_id: int | None, label: str = "") -> dict:
    """Append a node of `kind` under `parent_id` (None for an area). Returns
    {"tree": ..., "new_id": id}. sort_order is max(sibling)+1 so it lands last."""
    table, parent_col, label_col = _level(kind)
    with _conn() as conn:
        if parent_col is None:
            nxt = conn.execute(
                f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {table}"
            ).fetchone()[0]
            cur = conn.execute(
                f"INSERT INTO {table}({label_col}, sort_order) VALUES(?, ?)",
                (label, nxt),
            )
        else:
            if conn.execute(
                f"SELECT 1 FROM {_parent_table(kind)} WHERE id = ?", (parent_id,)
            ).fetchone() is None:
                raise ValueError(f"{kind} parent {parent_id} not found")
            nxt = conn.execute(
                f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {table} WHERE {parent_col} = ?",
                (parent_id,),
            ).fetchone()[0]
            if kind == "subsection":
                # unit_id is NOT NULL and stays populated on nested rows too — it
                # is what scopes a whole branch to its fixture. Inherit the
                # parent section's.
                unit_id = conn.execute(
                    "SELECT unit_id FROM storage_section WHERE id = ?", (parent_id,)
                ).fetchone()["unit_id"]
                cur = conn.execute(
                    f"INSERT INTO {table}(unit_id, {parent_col}, {label_col}, sort_order)"
                    " VALUES(?, ?, ?, ?)",
                    (unit_id, parent_id, label, nxt),
                )
            else:
                cur = conn.execute(
                    f"INSERT INTO {table}({parent_col}, {label_col}, sort_order) VALUES(?, ?, ?)",
                    (parent_id, label, nxt),
                )
        new_id = cur.lastrowid
    return {"tree": get_storage_tree(), "new_id": new_id}


def _parent_table(kind: str) -> str:
    """The table of `kind`'s parent level (for FK existence checks)."""
    return _PARENT_TABLE[kind]


def rename_node(kind: str, node_id: int, label: str) -> dict:
    """Set a node's label (name, or `text` for an item). Returns the full tree."""
    table, _parent_col, label_col = _level(kind)
    with _conn() as conn:
        cur = conn.execute(
            f"UPDATE {table} SET {label_col} = ? WHERE id = ?", (label, node_id)
        )
        if cur.rowcount == 0:
            raise ValueError(f"{kind} {node_id} not found")
    return {"tree": get_storage_tree()}


def set_item_note(item_id: int, note: str) -> dict:
    """Set an item's note field. Returns the full tree."""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE storage_item SET note = ? WHERE id = ?", (note, item_id)
        )
        if cur.rowcount == 0:
            raise ValueError(f"item {item_id} not found")
    return {"tree": get_storage_tree()}


def delete_node(kind: str, node_id: int) -> dict:
    """Delete a node; children cascade (FK ON DELETE CASCADE). Returns the tree."""
    table, _parent_col, _label_col = _level(kind)
    with _conn() as conn:
        cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (node_id,))
        if cur.rowcount == 0:
            raise ValueError(f"{kind} {node_id} not found")
    return {"tree": get_storage_tree()}


def move_node(kind: str, node_id: int, direction: str) -> dict:
    """Reorder a node up/down by swapping sort_order with its adjacent same-parent
    sibling. No-op (still returns the tree) at the end of the list. Returns the tree."""
    if direction not in ("up", "down"):
        raise ValueError("direction must be 'up' or 'down'")
    table, parent_col, _label_col = _level(kind)
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, sort_order"
            + (f", {parent_col}" if parent_col else "")
            + f" FROM {table} WHERE id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"{kind} {node_id} not found")
        my_order = row["sort_order"]
        # the adjacent sibling: nearest smaller sort_order (up) or larger (down),
        # scoped to the same parent. ties on sort_order break by id in the same
        # direction so repeated taps always make progress.
        if direction == "up":
            cmp, order_dir = "<", "DESC"
        else:
            cmp, order_dir = ">", "ASC"
        where = f"(sort_order {cmp} ? OR (sort_order = ? AND id {cmp} ?))"
        params: list = [my_order, my_order, node_id]
        if parent_col:
            where = f"{parent_col} = ? AND " + where
            params = [row[parent_col]] + params
        if kind == "section":
            # top-level sections only — a unit's nested rows share its unit_id but
            # are not siblings of the shelves hanging directly off it.
            where = "parent_id IS NULL AND " + where
        sib = conn.execute(
            f"SELECT id, sort_order FROM {table} WHERE {where} "
            f"ORDER BY sort_order {order_dir}, id {order_dir} LIMIT 1",
            params,
        ).fetchone()
        if sib is not None:
            # swap their sort_order values
            conn.execute(
                f"UPDATE {table} SET sort_order = ? WHERE id = ?",
                (sib["sort_order"], node_id),
            )
            conn.execute(
                f"UPDATE {table} SET sort_order = ? WHERE id = ?",
                (my_order, sib["id"]),
            )
    return {"tree": get_storage_tree()}


def reparent_item(item_id: int, section_id: int) -> dict:
    """Move an item to another section, appended at the end. Returns the tree."""
    with _conn() as conn:
        if conn.execute(
            "SELECT 1 FROM storage_item WHERE id = ?", (item_id,)
        ).fetchone() is None:
            raise ValueError(f"item {item_id} not found")
        if conn.execute(
            "SELECT 1 FROM storage_section WHERE id = ?", (section_id,)
        ).fetchone() is None:
            raise ValueError(f"section {section_id} not found")
        nxt = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM storage_item WHERE section_id = ?",
            (section_id,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE storage_item SET section_id = ?, sort_order = ? WHERE id = ?",
            (section_id, nxt, item_id),
        )
    return {"tree": get_storage_tree()}


# ── Prep-day planner (Phase C-v2) ──────────────────────────────────────────────
# Select the batches you're making → get a ground-up plan that reads like building
# each batch from scratch, in the recipe cards' OWN units (never gram-converted):
#
#   raw      — every smallest part gathered first, ONE combined line per name: all
#              juices + raw dry/wet goods (sugar, milk, spirits, sugar cane …).
#              Preps are made as whole card batches, so a prep's hidden raws are
#              pooled in at full-batch size. Once the raw stage is in front of you,
#              you never touch raw again.
#   build-up — each made sub-recipe shown WITH its full card recipe verbatim (every
#              ingredient in its original units + the method line), deepest first.
#   assemble — each selected batch shown WITH its full card pull-together + method.
#
# Walk: each selected batch's raws pool into the raw totals; each prep it consumes
# is recorded as a build-up step AND has one full batch of ITS raws pooled in too
# (nested preps recurse). Aggregation keeps each unit separate — a name needed in
# grams AND quarts is one line summing each independently ("lemon juice — 2 quart"
# with the gram part in the g/oz-toggleable chip). The quart↔gram conversion is
# unknown and must NOT be assumed (Sam weighs a quart on a real batch); the
# cards' juices are stored in quarts, sugars/waters in oz, spirits in ml — that is
# what shows. Composition lines (the card recipes) persist as
# prep_day_step_component rows; the method rides in prep_day_step.note.

# Floating-point grams: round to this many decimals so aggregated totals read
# cleanly (0.1 g is far below bar-measurable precision).
_GRAM_DP = 1


def _fmt_count(value: float) -> str:
    """Render a container count without a trailing '.0' (3.0 → '3', 1.5 → '1.5')."""
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return str(rounded)


def _explode_selection(conn, recipe_ids: list[int]):
    """Walk the BOM for the selected batches; return (raw, preps).

    raw   -- {name_lower: {"name", "units": {unit: amt}}} every raw leaf, pooled in
             ORIGINAL units across the selected batches AND one full batch of each
             needed prep (juice AND dry/wet goods).
    preps -- {pid: {"name", "need": {unit: amt}, "depth": int}} each made sub-recipe
             the selection consumes; `need` is how much the batches draw (in the
             batch's own unit), `depth` orders build-up deepest-first.

    Preps are made as whole card batches: a prep's raws enter `raw` at full batch
    size (its stored qty, unscaled), so the raw stage matches the recipe you'll
    actually make. One batch per distinct prep (preps are bulk-made).
    """
    raw: dict[str, dict] = {}
    preps: dict[int, dict] = {}

    def scan(rid: int, prep_depth: int) -> list[int]:
        """Route `rid`'s ingredients into raw / preps; return the prep ids found."""
        found: list[int] = []
        for r in conn.execute(
            "SELECT ingredient, qty, unit, scalable, produces_recipe_id "
            "FROM recipe_ingredients WHERE recipe_id = ? ORDER BY sort_order, id",
            (rid,),
        ).fetchall():
            if not r["scalable"] or r["qty"] is None:
                continue  # to-taste / unquantified — grabbed at assembly, not pre-gathered
            unit = r["unit"] or "g"
            amt = r["qty"]
            pid = r["produces_recipe_id"]
            if pid is not None:
                slot = preps.setdefault(
                    pid, {"name": _recipe_name(conn, pid), "need": {}, "depth": 0}
                )
                slot["need"][unit] = slot["need"].get(unit, 0.0) + amt
                slot["depth"] = max(slot["depth"], prep_depth)
                found.append(pid)
            else:
                slot = raw.setdefault(
                    r["ingredient"].lower(), {"name": r["ingredient"], "units": {}}
                )
                slot["units"][unit] = slot["units"].get(unit, 0.0) + amt
        return found

    # pass 1 — selected batches: their direct raws + the preps they need (depth 1)
    queue: list[int] = []
    for rid in recipe_ids:
        queue += scan(rid, 1)
    # pass 2 — each distinct needed prep contributes ONE full batch of its raws;
    # nested preps land one level deeper for ordering
    processed: set[int] = set()
    while queue:
        pid = queue.pop()
        if pid in processed:
            continue
        processed.add(pid)
        queue += scan(pid, preps[pid]["depth"] + 1)
    return raw, preps


def _recipe_name(conn, rid: int) -> str:
    row = conn.execute("SELECT name FROM recipes WHERE id = ?", (rid,)).fetchone()
    return row["name"] if row else f"recipe {rid}"


_PLURAL = {"bottle", "can", "gallon", "quart", "bag", "tub"}


def _plural(unit: str, qty: float) -> str:
    """Pluralise count nouns when qty != 1 (bottle→bottles); leave g/oz/ml as-is."""
    if unit in _PLURAL and abs(qty - 1.0) > 1e-9:
        return unit + "s"
    return unit


def _combine_units(name: str, units: dict, verb: str = ""):
    """Split a (name, {unit: amt}) total into (qty_g, qty_extra, label).

    The NAME is the title (left column) — label is just `verb + name`, never a unit.
    Every quantity goes on the right: the gram part rides in qty_g (drives the g/oz
    chip); every non-gram unit is summed independently and joined into qty_extra
    (`2 quart`, `18 bottles`, `8 oz + 2 quart`) — units never cross (R1).
    """
    gram = units.get("g")
    others = [
        f"{_fmt_count(amt)} {_plural(unit, amt)}"
        for unit, amt in sorted(units.items())
        if unit != "g"
    ]
    qty_g = round(gram, _GRAM_DP) if gram is not None else None
    qty_extra = " + ".join(others) if others else None
    return qty_g, qty_extra, f"{verb}{name}"


def _recipe_card(conn, rid: int):
    """Reproduce recipe `rid`'s card verbatim → (components, method).

    Each component is {name, qty_g, unit, label} where `label` is the ORIGINAL
    printed amount ("2 QT (64 oz)", "128 oz", "9000ml (12x750ml)", "to taste") — no
    gram conversion, original units kept. A made sub-recipe shows the produced
    recipe's name (the BOM link). `method` is the card's method line (may be None).
    Components carry no qty_g — the card text is the source of truth for the recipe;
    the g/oz toggle drives only the raw-stage gram chips, not these lines.
    """
    rec = conn.execute("SELECT method FROM recipes WHERE id = ?", (rid,)).fetchone()
    method = (rec["method"] if rec else None) or None
    rows = conn.execute(
        "SELECT ri.ingredient, ri.amount, ri.qty, ri.unit, "
        "       ri.produces_recipe_id, pr.name AS produces_name "
        "FROM recipe_ingredients ri "
        "LEFT JOIN recipes pr ON pr.id = ri.produces_recipe_id "
        "WHERE ri.recipe_id = ? ORDER BY ri.sort_order, ri.id",
        (rid,),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        name = r["produces_name"] or r["ingredient"]
        amount = (r["amount"] or "").strip()
        if not amount:
            # no printed card text — fall back to the machine fields, units intact
            amount = (
                f"{_fmt_count(r['qty'])} {r['unit'] or 'g'}"
                if r["qty"] is not None
                else "to taste"
            )
        out.append({"name": name, "qty_g": None, "unit": None, "label": amount})
    return out, method


# Raw-stage prep order (Sam, 2026-06-06): juices/produce → pantry → alcohol →
# refrigerated. NOT strict perishability — the fridge tier sits LAST even though it
# spoils, because it's grabbed at the end of a build (kept cold until then). Tiers:
# 0 fresh (juices + produce + herbs), 1 pantry (dry / canned / shelf-stable non-alcohol,
# incl. teas, coffee, coconut milk, condensed + evaporated milk), 2 alcohol (every
# spirit, liqueur, wine, beer, bitters, n/a spirit), 3 refrigerated (cold-stored, added
# last — dairy + eggs + fresh-pressed sugarcane juice; Sam 2026-06-06: dairy and
# sugarcane only, the other fresh juices stay in tier 0). Within a tier: alphabetical.
#
# Classification is REASONED, not keyword-matched (Sam, 2026-06-06): each distinct
# raw ingredient is judged individually and stored in the `ingredient_tier` table
# (migration 008, seeded by seed_ingredient_tiers.py) — so a new ingredient is
# classified deliberately instead of being silently bucketed by whether its name
# happens to contain "milk" or "gin". The earlier substring classifier (_ALC/_FRESH/
# _PANTRY_FORM/_ALC_WORD) is gone; this is a table lookup keyed by lowercased name.
# An unclassified ingredient degrades to pantry AND is surfaced by missing_tiers().

# Human tier labels for the raw-stage sub-headers (frontend renders one per group).
# Index matches the stored tier value.
_TIER_LABEL = ("Fresh", "Pantry", "Alcohol", "Refrigerated")

# Tier for any ingredient not in the table — pantry, the shelf-stable catch-all.
_DEFAULT_TIER = 1


def _load_tier_map(conn) -> dict[str, int]:
    """Read the full reasoned classification: lowercased ingredient name → tier."""
    return {
        r["name"]: r["tier"]
        for r in conn.execute("SELECT name, tier FROM ingredient_tier").fetchall()
    }


def _tier_of(name: str, tier_map: dict[str, int]) -> int:
    """Look up a raw ingredient's tier; unknown names degrade to pantry (_DEFAULT_TIER)."""
    return tier_map.get(name.lower(), _DEFAULT_TIER)


def missing_tiers() -> list[str]:
    """Distinct raw ingredient names present in recipes but absent from ingredient_tier.

    These render in the raw stage at the default pantry tier; this surfaces them so a
    new ingredient gets a deliberate classification instead of staying silently pantry.
    """
    with _conn() as conn:
        return [
            r["k"]
            for r in conn.execute(
                "SELECT DISTINCT lower(ingredient) AS k FROM recipe_ingredients "
                "WHERE produces_recipe_id IS NULL "
                "  AND lower(ingredient) NOT IN (SELECT name FROM ingredient_tier) "
                "ORDER BY 1"
            ).fetchall()
        ]


def _load_lead_map(conn) -> dict[int, tuple]:
    """Read each recipe's brew/lead time: id → (lead_minutes, lead_label).

    lead_minutes is the passive wait until usable (the build-up sort key); lead_label
    is the human text shown on the step. Both NULL for recipes with no meaningful wait
    (and for batches/cocktails, which never appear as build-up preps). Seeded by
    seed_prep_lead.py — card-stated times where the card gives one, web-researched
    otherwise.
    """
    return {
        r["id"]: (r["lead_minutes"], r["lead_label"])
        for r in conn.execute(
            "SELECT id, lead_minutes, lead_label FROM recipes"
        ).fetchall()
    }


def _critical_path(conn, rid: int, lead_map: dict, cache: dict) -> int:
    """Longest cumulative brew-time path beneath `rid`, in minutes (the parallel-brews
    critical path). For each prep `rid` consumes, the path through it is that prep's own
    lead_minutes + the critical path beneath IT; the answer is the max over children
    (brews run in parallel, so the slowest chain governs). 0 when `rid` consumes no
    preps. Memoised; the `cache[rid]=0` pre-seed also guards against a BOM cycle.
    """
    if rid in cache:
        return cache[rid]
    cache[rid] = 0
    best = 0
    for r in conn.execute(
        "SELECT produces_recipe_id FROM recipe_ingredients "
        "WHERE recipe_id = ? AND produces_recipe_id IS NOT NULL",
        (rid,),
    ).fetchall():
        pid = r["produces_recipe_id"]
        lead = lead_map.get(pid, (None, None))[0] or 0
        chain = lead + _critical_path(conn, pid, lead_map, cache)
        if chain > best:
            best = chain
    cache[rid] = best
    return best


def _humanize_eta(minutes: int) -> str | None:
    """Brew-time critical path → the assemble step's "earliest ready" text. None when
    there's no brew gate (0). Rounds to the coarsest sensible unit since this is an
    estimate driven by fuzzy waits like "overnight". Excludes active assembly time.
    """
    if not minutes:
        return None
    if minutes < 60:
        return f"earliest ready {int(minutes)} min"
    if minutes < 1440:
        return f"earliest ready ~{round(minutes / 60)} hr"
    if minutes < 10080:
        days = round(minutes / 1440)
        return f"earliest ready ~{days} day" + ("s" if days != 1 else "")
    weeks = round(minutes / 10080)
    return f"earliest ready ~{weeks} week" + ("s" if weeks != 1 else "")


def _build_steps(conn, recipe_ids: list[int]) -> list[dict]:
    """Generate the ordered raw → build-up → assemble step list for the selection.

    Each step is {phase, label, qty_g, components, note, lead_label}; seq is assigned
    by the caller. Raw steps have no components (they ARE the smallest parts); build-up
    and assemble steps carry the full card recipe (components) + its method (note).
    qty_g is the gram part of a raw total or the amount a prep is needed in; non-gram
    units ride in the label, never converted. lead_label is the brew-time text on a
    build-up step (None for raw/assemble).
    """
    raw, preps = _explode_selection(conn, recipe_ids)
    tier_map = _load_tier_map(conn)
    lead_map = _load_lead_map(conn)
    steps: list[dict] = []

    # raw — every smallest part, one combined line per name; sorted fresh → stable
    # by prep order (juices/produce → pantry → alcohol → dairy, see the reasoned
    # ingredient_tier table), alpha within each tier. Original units, summed
    # independently.
    def _raw_key(item):
        name_lower, slot = item
        return (_tier_of(name_lower, tier_map), slot["name"].lower())

    for _name_lower, slot in sorted(raw.items(), key=_raw_key):
        qty_g, qty_extra, label = _combine_units(slot["name"], slot["units"])
        steps.append(
            {
                "phase": "raw",
                "label": label,
                "qty_g": qty_g,
                "qty_extra": qty_extra,
                "components": [],
                "note": None,
                "lead_label": None,
            }
        )

    # build-up — needed preps. Dependency depth stays primary (an input prep is made
    # before the prep it feeds); within a depth level, longest brew first (Sam:
    # "things that need time to brew come first, longest first"); name breaks the
    # remaining ties. Each reproduces its full card recipe + method line, and carries
    # its brew-time text.
    def _prep_key(item):
        pid, slot = item
        mins, _label = lead_map.get(pid, (None, None))
        return (-slot["depth"], -(mins or 0), slot["name"].lower())

    for pid, slot in sorted(preps.items(), key=_prep_key):
        qty_g, qty_extra, label = _combine_units(slot["name"], slot["need"])
        components, method = _recipe_card(conn, pid)
        _mins, lead_label = lead_map.get(pid, (None, None))
        steps.append(
            {
                "phase": "build-up",
                "label": label,
                "qty_g": qty_g,
                "qty_extra": qty_extra,
                "components": components,
                "note": method,
                "lead_label": lead_label,
            }
        )

    # assemble — the selected batches last, alpha by name, each with its full card
    # pull-together + method.
    sel = conn.execute(
        "SELECT id, name, yield_qty FROM recipes WHERE id IN (%s) "
        "ORDER BY name COLLATE NOCASE" % ",".join("?" * len(recipe_ids)),
        recipe_ids,
    ).fetchall()
    cp_cache: dict[int, int] = {}
    for r in sel:
        components, method = _recipe_card(conn, r["id"])
        # earliest completion = parallel-brews critical path through this batch's preps,
        # rendered as "earliest ready ~N hr" (None when the batch has no brew gate). Reuses
        # the lead_label field — for an assemble step it carries the ETA, not a brew wait.
        eta = _humanize_eta(_critical_path(conn, r["id"], lead_map, cp_cache))
        steps.append(
            {
                "phase": "assemble",
                "label": r["name"],
                "qty_g": round(r["yield_qty"], _GRAM_DP)
                if r["yield_qty"] is not None
                else None,
                "qty_extra": None,
                "components": components,
                "note": method,
                "lead_label": eta,
            }
        )

    return steps


def create_prep_day(recipe_ids: list[int]) -> dict:
    """Start a prep day from selected recipe ids; generate + persist the steps.

    Clears any currently-active day first (you only prep one day at a time), then
    inserts the new day, its selection, the ordered step list, and each step's
    composition rows. Returns the active-day payload (same shape as
    get_active_prep_day).
    """
    ids = [int(r) for r in recipe_ids]
    if not ids:
        raise ValueError("select at least one recipe")
    with _conn() as conn:
        found = {
            row["id"]
            for row in conn.execute(
                "SELECT id FROM recipes WHERE id IN (%s)" % ",".join("?" * len(ids)),
                ids,
            ).fetchall()
        }
        missing = [i for i in ids if i not in found]
        if missing:
            raise ValueError(f"unknown recipe id(s): {missing}")

        # one active day at a time — retire the current one before opening a new
        conn.execute(
            "UPDATE prep_day SET cleared = datetime('now') WHERE cleared IS NULL"
        )
        cur = conn.execute("INSERT INTO prep_day DEFAULT VALUES")
        day_id = cur.lastrowid
        assert day_id is not None  # row just inserted above
        # the initial build is stage 0 — the original plan. Later adds append
        # stage 1, 2, … as standalone blocks (see add_to_prep_day).
        _insert_steps(conn, day_id, ids, stage=0, seq_start=1)
    day = get_active_prep_day()
    assert day is not None  # active row just created/modified above
    return day


def _insert_steps(
    conn, day_id: int, recipe_ids: list[int], stage: int, seq_start: int
) -> None:
    """Append a stage's selection + generated steps (+ components) to a prep day.

    Shared by create_prep_day (stage 0) and add_to_prep_day (stage 1+). Generates a
    self-contained raw → build-up → assemble block for `recipe_ids` only, numbering
    steps from `seq_start` and tagging everything with `stage`. Does NOT touch any
    existing rows, so prior steps and their check state are preserved by construction.
    """
    conn.executemany(
        "INSERT INTO prep_day_selection (prep_day_id, recipe_id, stage) VALUES (?, ?, ?)",
        [(day_id, i, stage) for i in recipe_ids],
    )
    for seq, s in enumerate(_build_steps(conn, recipe_ids), start=seq_start):
        step_cur = conn.execute(
            "INSERT INTO prep_day_step "
            "(prep_day_id, seq, stage, phase, label, qty_g, qty_extra, note, lead_label) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                day_id,
                seq,
                stage,
                s["phase"],
                s["label"],
                s["qty_g"],
                s.get("qty_extra"),
                s.get("note"),
                s.get("lead_label"),
            ),
        )
        components = s.get("components") or []
        if components:
            conn.executemany(
                "INSERT INTO prep_day_step_component "
                "(step_id, seq, name, qty_g, unit, label) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        step_cur.lastrowid,
                        cseq,
                        c["name"],
                        c["qty_g"],
                        c["unit"],
                        c["label"],
                    )
                    for cseq, c in enumerate(components, start=1)
                ],
            )


def add_to_prep_day(recipe_ids: list[int]) -> dict:
    """Append recipes to the active prep day as a new standalone stage (a queue).

    The added recipes become the next stage — a self-contained raw → build-up →
    assemble block appended after every existing step, checkable immediately. The
    original plan (and any other stage) is untouched, so progress is preserved.

    Recipes already in the day are skipped (no repeat batches; the selection key is
    (prep_day_id, recipe_id)). Raises ValueError when there's no active day, an id is
    unknown, or every picked recipe is already present.
    """
    ids = [int(r) for r in recipe_ids]
    if not ids:
        raise ValueError("select at least one recipe")
    with _conn() as conn:
        day = conn.execute(
            "SELECT id FROM prep_day WHERE cleared IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if day is None:
            raise ValueError("no active prep day")
        day_id = day["id"]

        found = {
            row["id"]
            for row in conn.execute(
                "SELECT id FROM recipes WHERE id IN (%s)" % ",".join("?" * len(ids)),
                ids,
            ).fetchall()
        }
        missing = [i for i in ids if i not in found]
        if missing:
            raise ValueError(f"unknown recipe id(s): {missing}")

        # skip anything already in this day — no repeat batches of the same recipe
        already = {
            row["recipe_id"]
            for row in conn.execute(
                "SELECT recipe_id FROM prep_day_selection WHERE prep_day_id = ?",
                (day_id,),
            ).fetchall()
        }
        new_ids = [i for i in dict.fromkeys(ids) if i not in already]
        if not new_ids:
            raise ValueError("already in this prep day")

        agg = conn.execute(
            "SELECT COALESCE(MAX(stage), 0) AS s, COALESCE(MAX(seq), 0) AS q "
            "FROM prep_day_step WHERE prep_day_id = ?",
            (day_id,),
        ).fetchone()
        _insert_steps(conn, day_id, new_ids, stage=agg["s"] + 1, seq_start=agg["q"] + 1)
    day = get_active_prep_day()
    assert day is not None  # active row just created/modified above
    return day


def get_active_prep_day() -> dict | None:
    """The active prep day (latest with cleared IS NULL), its selection + steps.

    Returns None when no day is active. Steps come back ordered by seq, each with
    its composition rows under `components`; selection carries recipe id + name so
    the UI can echo what's being made.
    """
    with _conn() as conn:
        day = conn.execute(
            "SELECT id, started FROM prep_day WHERE cleared IS NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if day is None:
            return None
        selection = conn.execute(
            "SELECT s.recipe_id, s.stage, r.name "
            "FROM prep_day_selection s JOIN recipes r ON r.id = s.recipe_id "
            "WHERE s.prep_day_id = ? ORDER BY s.stage, r.name COLLATE NOCASE",
            (day["id"],),
        ).fetchall()
        steps = [
            dict(s)
            for s in conn.execute(
                "SELECT id, seq, stage, phase, label, qty_g, qty_extra, note, lead_label "
                "FROM prep_day_step WHERE prep_day_id = ? ORDER BY seq",
                (day["id"],),
            ).fetchall()
        ]
        # attach each step's composition rows (raw steps have none)
        by_step: dict[int, list] = {s["id"]: [] for s in steps}
        if steps:
            comp_rows = conn.execute(
                "SELECT id, step_id, name, qty_g, unit, label, checked "
                "FROM prep_day_step_component WHERE step_id IN (%s) "
                "ORDER BY step_id, seq" % ",".join("?" * len(steps)),
                [s["id"] for s in steps],
            ).fetchall()
            for cr in comp_rows:
                by_step[cr["step_id"]].append(
                    {
                        "id": cr["id"],
                        "name": cr["name"],
                        "qty_g": cr["qty_g"],
                        "unit": cr["unit"],
                        "label": cr["label"],
                        "checked": cr["checked"],
                    }
                )
        tier_map = _load_tier_map(conn)
        for s in steps:
            s["components"] = by_step[s["id"]]
            # raw steps carry their prep-order tier so the UI can sub-header them
            # (Fresh · Pantry · Alcohol · Refrigerated). The label IS the bare ingredient
            # name, looked up in the reasoned ingredient_tier table; non-raw → None.
            s["tier"] = (
                _TIER_LABEL[_tier_of(s["label"], tier_map)]
                if s["phase"] == "raw"
                else None
            )
    return {
        "id": day["id"],
        "started": day["started"],
        "selection": [dict(s) for s in selection],
        "steps": steps,
    }


def toggle_component(component_id: int) -> dict | None:
    """Flip a component's checked state. Returns {id, checked} or None if no such row.

    The checkable unit is the recipe sub-item — a build-up/assemble composition line —
    not the step header (Stage B, 2026-06-07). Step headers are derived (done/total of
    their components), so there is no step-level check: `prep_day_step` has no `checked`
    column (dropped in migration 016).
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, checked FROM prep_day_step_component WHERE id = ?",
            (component_id,),
        ).fetchone()
        if row is None:
            return None
        new_checked = 0 if row["checked"] else 1
        conn.execute(
            "UPDATE prep_day_step_component SET checked = ? WHERE id = ?",
            (new_checked, component_id),
        )
    return {"id": component_id, "checked": new_checked}


def reset_prep_day() -> dict:
    """Clear the active day (set cleared) so the next create starts fresh.

    Returns {cleared: bool} — False when there was no active day to clear.
    """
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE prep_day SET cleared = datetime('now') WHERE cleared IS NULL"
        )
        cleared = cur.rowcount > 0
    return {"cleared": cleared}

"""Reads recipes/*.md from the vault. The notes are the source of truth; there is no DB.

A database here would be a second copy of content Obsidian can edit, i.e. a drift
generator (see wiki/problems/wiki-implementation-drift). At 123 notes a parse is cheap
enough that the copy buys nothing.

Freshness is TTL'd rather than per-request, and that is not a micro-optimisation. Measured
on this machine with the vault on /mnt/c (WSL DrvFs): a full stat sweep of the folder costs
119.6 ms and a cold parse 268 ms. Statting per request would put 120 ms of filesystem I/O
on every page load. The sweep runs at most once every SWEEP_TTL seconds instead.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

from . import scale  # noqa: E402

SWEEP_TTL = 2.0  # seconds; the most staleness an Obsidian edit can see before a refresh

_lock = threading.Lock()
_cache: dict[str, dict] = {}      # slug -> parsed recipe
_stamps: dict[str, tuple] = {}    # slug -> (mtime_ns, size)
_last_sweep = 0.0

_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
_SECTION = re.compile(r"^##\s+(.+?)\s*$\r?\n(.*?)(?=^##\s+|\Z)", re.M | re.S)
_EMBED = re.compile(r"!\[\[recipes/photos/([^\]]+)\]\]")
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
# 17 of the 123 notes carry the label inside the value ("Servings: 2", "serves 6"), which
# the detail page then rendered as "Serves Servings 2". Stripped once here so every reader
# gets the bare count.
_SERVES_LABEL = re.compile(r"(?i)^\s*(?:serves|servings)\b[:\s]*")


def recipes_dir() -> Path:
    return vault_root() / "recipes"


def _load_dish_titles() -> dict[str, str]:
    """slug -> the dish's actual name, for the index card.

    The raw titles are Paprika and YouTube captures: "ABSOLUTE BEST CHICKEN CAPRESE
    SANDWICH", "🍣 Air Fryer Firecracker Salmon Bites ❤️", "The BEST Garbanzo Bean Stew of
    Your Life | Spanish Potaje De Garbanzos". A grid of those has no parity. The note's own
    `title` is never touched and the detail page still shows it, so this only decides what
    the front page says. Missing slug -> the raw title, i.e. it degrades to today's
    behaviour rather than to a blank. Read once at import; restart the Hub after editing.
    """
    try:
        raw = json.loads((Path(__file__).with_name("dish-titles.json")).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, str)}


_DISH = _load_dish_titles()


def _parse_frontmatter(block: str) -> dict:
    """Enough YAML for this corpus: scalars and flow lists. Never raises on a bad note."""
    out: dict = {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            items = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",")]
            out[key] = [v for v in items if v]
        else:
            out[key] = val.strip('"').strip("'")
    return out


def _clean(text: str) -> str:
    """Strip Obsidian-only syntax so the body renders as plain text.

    88 of the 123 notes embed their photo as ![[recipes/photos/x.jpg]], which no standard
    markdown renderer understands and which would otherwise show as literal brackets.
    """
    text = _EMBED.sub("", text)
    return _WIKILINK.sub(lambda m: m.group(2) or m.group(1).split("/")[-1], text)


def _parse(path: Path) -> dict | None:
    """Parse one note. Returns None for non-recipe files; never raises on a malformed one."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm_match = _FM.match(raw)
    fm = _parse_frontmatter(fm_match.group(1)) if fm_match else {}
    if fm.get("type") != "recipe":
        return None          # CLAUDE.md and _index.md live here too
    body = raw[fm_match.end():] if fm_match else raw
    sections = {k.lower(): _clean(v).strip() for k, v in _SECTION.findall(body)}

    ingredient_lines = [
        ln.strip()[2:].strip()
        for ln in sections.get("ingredients", "").splitlines()
        if ln.strip().startswith("- ")
    ]
    parsed_ingredients = [scale.parse_ingredient(ln) for ln in ingredient_lines]

    slug = path.stem  # unique by filesystem: 0 collisions, 0 non-ASCII across the corpus
    title = fm.get("title") or slug.replace("-", " ").title()
    photo = fm.get("photo") or ""
    cats = fm.get("categories") or []
    if isinstance(cats, str):
        cats = [cats]

    return {
        "slug": slug,
        "title": title,
        "dish": _DISH.get(slug, title),
        "rating": fm.get("rating", ""),
        "servings_raw": _SERVES_LABEL.sub("", str(fm.get("servings", ""))).strip(),
        "servings": scale.parse_servings(fm.get("servings")),
        "prep_time": fm.get("prep_time", ""),
        "cook_time": fm.get("cook_time", ""),
        "total_time": fm.get("total_time", ""),
        "difficulty": fm.get("difficulty", ""),
        "categories": cats,
        "source": fm.get("source", ""),
        "source_url": fm.get("source_url", ""),
        "photo": f"/recipes/photo/{photo}" if photo else "",
        "created": fm.get("created", ""),
        "ingredients": ingredient_lines,
        "ingredient_names": sorted({
            n for n in (scale.normalize_name(p["name"]) for p in parsed_ingredients) if n
        }),
        "directions": sections.get("directions", ""),
        "notes": sections.get("notes", ""),
        # Search haystack built once at parse time rather than per keystroke.
        "haystack": " ".join([
            title, _DISH.get(slug, ""), " ".join(ingredient_lines),
            sections.get("notes", ""), str(fm.get("source", "")),
            " ".join(cats),
        ]).lower(),
    }


def _sweep_locked() -> None:
    """Re-stat the folder and reparse only what changed. Caller holds _lock."""
    global _last_sweep
    seen = set()
    for path in recipes_dir().glob("*.md"):   # glob, so a NEW note is found without a restart
        try:
            st = path.stat()
        except OSError:
            continue
        slug = path.stem
        seen.add(slug)
        stamp = (st.st_mtime_ns, st.st_size)   # size too: mtime alone can miss a replacement
        if _stamps.get(slug) == stamp:
            continue
        rec = _parse(path)
        if rec is None:
            _stamps[slug] = stamp
            _cache.pop(slug, None)
            continue
        _cache[slug] = rec
        _stamps[slug] = stamp
    for gone in set(_stamps) - seen:           # evict notes deleted in Obsidian
        _stamps.pop(gone, None)
        _cache.pop(gone, None)
    _last_sweep = time.monotonic()


def _fresh() -> None:
    if time.monotonic() - _last_sweep < SWEEP_TTL:
        return
    with _lock:
        if time.monotonic() - _last_sweep < SWEEP_TTL:
            return
        _sweep_locked()


def all_recipes() -> list[dict]:
    _fresh()
    return sorted(_cache.values(), key=lambda r: r["dish"].lower())


def get(slug: str) -> dict | None:
    _fresh()
    return _cache.get(slug)


def categories() -> list[dict]:
    """Category -> count, largest first. Recipes carry several and appear under each."""
    counts: dict[str, int] = {}
    for r in all_recipes():
        for c in r["categories"]:
            counts[c] = counts.get(c, 0) + 1
    return [{"name": k, "count": v}
            for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))]


def photo_path(filename: str) -> Path | None:
    """Resolve a photo, refusing anything that escapes the photos directory."""
    if not filename or "/" in filename or "\\" in filename:
        return None
    if Path(filename).suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return None
    base = (recipes_dir() / "photos").resolve()
    target = (base / filename).resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        return None
    return target


def match_pantry(have: list[str]) -> list[dict]:
    """Rank recipes by how much of their ingredient list `have` covers.

    Loose substring matching on normalized tokens: 'lentils' should hit 'yellow split peas
    or *Red Lentils'. A false positive costs a glance; a false negative hides a recipe he
    could have cooked.
    """
    tokens = [scale.normalize_name(h) for h in have if h.strip()]
    tokens = [t for t in tokens if t]
    results = []
    for r in all_recipes():
        names = r["ingredient_names"]
        if not names:
            continue  # e.g. chinese-steamed-eggs has no ## Ingredients — not a 0-divide
        matched = [n for n in names if any(t in n or n in t for t in tokens)]
        results.append({
            "slug": r["slug"], "title": r["title"], "dish": r["dish"], "photo": r["photo"],
            "coverage": round(len(matched) / len(names), 3),
            "matched": matched,
            "missing": [n for n in names if n not in matched],
        })
    results.sort(key=lambda x: -x["coverage"])
    return results

"""Quantity parsing, scaling, and consolidation for recipe ingredient lines.

The only genuinely non-trivial logic in the module, and the only place a bug produces a
wrong number in a real kitchen. Everything here errs toward refusing to scale over
scaling wrongly: a line the parser cannot fully account for is flagged and passed through,
never silently half-transformed.

Design decisions and the corpus evidence behind them:
docs/archive/specs/2026-08-22-recipes-hub-module-design.md
"""

from __future__ import annotations

import re
from fractions import Fraction

# Denominators a cook can actually measure. The eighths are here because the 1/8 cup and
# 1/8 tsp measures exist, so 3/8 is three of one — halving a quarter-cup recipe lands
# there constantly and "0.38 c" is not something anyone writes on a card. 1/6 is
# deliberately absent — no standard measuring spoon carries it — which is why snapping
# still needs the error budget below.
KITCHEN_DENOMINATORS = (Fraction(1, 8), Fraction(1, 4), Fraction(1, 3),
                        Fraction(3, 8), Fraction(1, 2), Fraction(5, 8),
                        Fraction(2, 3), Fraction(3, 4), Fraction(7, 8))

# Past this, snapping to a kitchen fraction distorts the recipe more than an awkward
# decimal does. Measured: 1/6 -> 1/8 is 25% low, 0.4 -> 1/3 is 16.7% low.
SNAP_ERROR_BUDGET = 0.05

UNICODE_FRACTIONS = {
    "¼": Fraction(1, 4), "½": Fraction(1, 2), "¾": Fraction(3, 4),
    "⅐": Fraction(1, 7), "⅑": Fraction(1, 9), "⅒": Fraction(1, 10),
    "⅓": Fraction(1, 3), "⅔": Fraction(2, 3),
    "⅕": Fraction(1, 5), "⅖": Fraction(2, 5), "⅗": Fraction(3, 5), "⅘": Fraction(4, 5),
    "⅙": Fraction(1, 6), "⅚": Fraction(5, 6),
    "⅛": Fraction(1, 8), "⅜": Fraction(3, 8), "⅝": Fraction(5, 8), "⅞": Fraction(7, 8),
}

_NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+|[" + "".join(UNICODE_FRACTIONS) + r"])"
# A leading quantity, optionally a range, optionally a unit token.
_LEAD = re.compile(
    rf"^\s*(?P<q1>{_NUM})\s*(?:(?:-|–|—|\bto\b)\s*(?P<q2>{_NUM})\s*)?(?P<rest>.*)$",
    re.IGNORECASE,
)
# A second, independent quantity later in the line: the `1/4 Cup 125 grams Rice` and
# `2 C dashi (480 grams)` shapes. Both are real in this corpus.
_TRAILING_QTY = re.compile(rf"(?<![\w/]){_NUM}\s*(?:g|kg|ml|l|oz|lb|lbs|grams?|cups?|"
                           r"tsp|tbsp|teaspoons?|tablespoons?|pounds?|ounces?)\b", re.IGNORECASE)

UNIT_ALIASES = {
    "tablespoons": "tbsp", "tablespoon": "tbsp", "tbsps": "tbsp", "tbs": "tbsp", "t": "tbsp",
    "teaspoons": "tsp", "teaspoon": "tsp", "tsps": "tsp",
    "cups": "cup", "c": "cup",
    "pounds": "lb", "pound": "lb", "lbs": "lb",
    "ounces": "oz", "ounce": "oz",
    "grams": "g", "gram": "g", "kilograms": "kg", "kilogram": "kg",
    "milliliters": "ml", "millilitres": "ml", "liters": "l", "litres": "l",
    "cloves": "clove", "cans": "can", "packages": "package", "pkg": "package",
    "bunches": "bunch", "slices": "slice", "sprigs": "sprig", "handfuls": "handful",
}
_UNIT_RE = re.compile(r"^([A-Za-z]+)\.?\b")


def parse_number(text: str) -> Fraction | None:
    """'1 1/2' -> 3/2, '½' -> 1/2, '.5' -> 1/2, '3' -> 3. None if it is not a number."""
    text = text.strip()
    if not text:
        return None
    if text in UNICODE_FRACTIONS:
        return UNICODE_FRACTIONS[text]
    m = re.fullmatch(r"(\d+)\s+(\d+)/(\d+)", text)      # mixed: 1 1/2
    if m:
        whole, num, den = (int(g) for g in m.groups())
        return Fraction(whole) + Fraction(num, den) if den else None
    m = re.fullmatch(r"(\d+)/(\d+)", text)               # vulgar: 1/2
    if m:
        num, den = int(m.group(1)), int(m.group(2))
        return Fraction(num, den) if den else None
    try:
        return Fraction(text)                            # 3, 1.5
    except (ValueError, ZeroDivisionError):
        return None


def format_quantity(value: Fraction) -> str:
    """Render a scaled quantity the way a cook can measure it.

    Snaps the fractional part to a kitchen denominator, but only while the distortion
    stays inside the error budget; past that a decimal is more honest than a fraction
    that is 25% wrong.
    """
    if value <= 0:
        return "0"
    whole, frac = divmod(value, 1)
    whole = int(whole)
    if frac == 0:
        return str(whole)
    best = min(KITCHEN_DENOMINATORS, key=lambda d: abs(d - frac))
    if abs(best - frac) / frac <= SNAP_ERROR_BUDGET:
        frac_txt = f"{best.numerator}/{best.denominator}"
        return f"{whole} {frac_txt}" if whole else frac_txt
    dec = round(float(value), 2)
    return f"{dec:g}"


def _unit_of(rest: str) -> str:
    m = _UNIT_RE.match(rest.strip())
    if not m:
        return ""
    word = m.group(1).lower()
    return UNIT_ALIASES.get(word, word)


def parse_ingredient(line: str) -> dict:
    """Split one ingredient line into quantity / unit / name, with honesty flags.

    Returns keys: raw, qty (Fraction|None), qty2 (Fraction|None for ranges), unit, name,
    has_unscaled (a second quantity elsewhere in the line that scaling will not touch).
    """
    raw = line.strip().lstrip("-").strip()
    out = {"raw": raw, "qty": None, "qty2": None, "unit": "", "name": raw,
           "has_unscaled": False}
    m = _LEAD.match(raw)
    if not m:
        return out
    q1 = parse_number(m.group("q1"))
    if q1 is None:
        return out
    rest = m.group("rest")
    out["qty"] = q1
    out["qty2"] = parse_number(m.group("q2")) if m.group("q2") else None
    out["unit"] = _unit_of(rest)
    name = rest.strip()
    if out["unit"]:
        name = _UNIT_RE.sub("", name, count=1).strip()
    out["name"] = name or raw
    out["has_unscaled"] = bool(_TRAILING_QTY.search(rest))
    return out


def scale_line(line: str, factor: Fraction) -> dict:
    """Scale one ingredient line. Returns {text, scaled, flagged}.

    `flagged` means the line carries a quantity the scaler did not touch, so the cook
    must resolve it. That is a visible caveat, never a silent approximation.
    """
    p = parse_ingredient(line)
    if p["qty"] is None or factor == 1:
        return {"text": p["raw"], "scaled": False, "flagged": False}
    q1 = format_quantity(p["qty"] * factor)
    qty_txt = q1 if p["qty2"] is None else f"{q1}-{format_quantity(p['qty2'] * factor)}"
    tail = p["raw"]
    m = _LEAD.match(tail)
    rest = m.group("rest") if m else tail
    text = f"{qty_txt} {rest.strip()}".strip()
    return {"text": text, "scaled": True, "flagged": p["has_unscaled"]}


# ── servings ──────────────────────────────────────────────────────────────────
#
# Only 30 of the 123 notes carry a bare integer; 43 have no servings field at all and the
# rest are prose. Measured, not assumed — see the spec. Where no base can be read the UI
# falls back to a plain multiplier, which needs no base.

# `Yield: 1 cup` / `4 waffles` / `1 loaf` are yields, not serving counts. Reading them as
# servings would scale a six-person dinner by 6x.
_NOT_SERVINGS = re.compile(
    r"\b(cups?|quarts?|pints?|loaf|loaves|waffles?|pancakes?|cookies?|"
    r"muffins?|inch|flatbread|pie|dozen|tbsp|tsp|ml|liters?|oz|pounds?|lbs?)\b",
    re.IGNORECASE,
)
_SERVINGS_NUM = re.compile(rf"({_NUM})(?:\s*(?:-|–|to)\s*({_NUM}))?")


def parse_servings(text: str | None) -> int | None:
    """Extract a serving count from the corpus's real forms, or None.

    Handles: '4', 'Serves 4', '6 servings', 'Servings: 8', 'Yield 5 servings',
    '8 kid-size servings', and ranges ('3-4', '6 to 8', 'Serves 2 to 4' -> low end;
    scaling up from the smaller base never under-feeds anyone).

    Returns None for yields that are not servings, so the caller offers a multiplier
    instead of computing a wrong target.
    """
    if not text:
        return None
    s = str(text).strip()
    if not s:
        return None
    if _NOT_SERVINGS.search(s) and not re.search(r"\bservings?\b", s, re.IGNORECASE):
        return None
    m = _SERVINGS_NUM.search(s)
    if not m:
        return None
    low = parse_number(m.group(1))
    if low is None or low <= 0:
        return None
    return int(low)


# ── normalization, consolidation, matching ────────────────────────────────────

_NOISE = re.compile(
    r"\b(chopped|minced|sliced|diced|grated|finely|freshly|ground|large|small|medium|"
    r"optional|divided|to taste|peeled|washed|rinsed|soaked|drained|plus more|for serving|"
    r"fresh|dried|whole|halved|quartered|beaten|melted|softened|room temperature)\b",
    re.IGNORECASE,
)


def normalize_name(name: str) -> str:
    """Reduce an ingredient name to comparable tokens.

    One normalizer, two consumers: grocery consolidation and fridge matching. An exact-key
    lookup fails on the real corpus ('1 large onion red', '2 cloves garlic, sliced'), so
    everything downstream matches on these tokens rather than the raw string.
    """
    s = name.lower()
    s = re.sub(r"\([^)]*\)", " ", s)          # drop parentheticals
    s = s.split(",")[0]                        # 'garlic, sliced' -> 'garlic'
    s = _NOISE.sub(" ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    words = [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in s.split()]
    return " ".join(words)


def consolidate(entries: list[dict]) -> list[dict]:
    """Merge ingredient entries from several recipes into one grocery list.

    Rules, each earned from the corpus:
      - same normalized name AND same unit -> quantities sum.
      - different or absent unit -> separate lines. No density table; merging '1 lb' with
        '2 cups' of the same thing needs one, and a wrong number in a kitchen is worse
        than two lines.
      - a line carrying an unscaled second quantity is never merged; it is flagged.
      - unquantified staples ('black pepper', 'salt to taste') merge BY NAME and do not
        get the recipe name welded into their text — that is what would stop three
        recipes' pepper from ever collapsing into one line.

    Each entry: {raw, qty, unit, name, has_unscaled, recipe}.
    """
    merged: dict[tuple, dict] = {}
    out: list[dict] = []
    for e in entries:
        key_name = normalize_name(e.get("name") or e.get("raw", ""))
        if e.get("has_unscaled"):
            out.append({"text": e["raw"], "sources": [e.get("recipe", "")],
                        "flagged": True, "name": key_name})
            continue
        if e.get("qty") is None:
            key = (key_name, "__unquantified__")
            if key in merged:
                _add_source(merged[key], e.get("recipe"))
                continue
            merged[key] = {"text": key_name or e["raw"], "qty": None, "unit": "",
                           "sources": [e.get("recipe", "")], "flagged": False,
                           "name": key_name}
            out.append(merged[key])
            continue
        key = (key_name, e.get("unit", ""))
        if key in merged:
            merged[key]["qty"] += e["qty"]
            _add_source(merged[key], e.get("recipe"))
        else:
            merged[key] = {"text": "", "qty": e["qty"], "unit": e.get("unit", ""),
                           "sources": [e.get("recipe", "")], "flagged": False,
                           "name": key_name}
            out.append(merged[key])
    for item in out:
        if item.get("qty") is not None:
            unit = f" {item['unit']}" if item["unit"] else ""
            item["text"] = f"{format_quantity(item['qty'])}{unit} {item['name']}".strip()
            item.pop("qty", None)
    return out


def _add_source(item: dict, recipe: str | None) -> None:
    if recipe and recipe not in item["sources"]:
        item["sources"].append(recipe)


# Head-noun -> aisle. Matched against normalized tokens, never as an exact key: the real
# names are '1 large onion red' and '2 cloves garlic, sliced', which no exact lookup hits.
AISLE_MAP = {
    "produce": ("onion", "garlic", "tomato", "pepper bell", "carrot", "celery", "potato",
                "lettuce", "spinach", "kale", "cabbage", "broccoli", "cucumber", "lemon",
                "lime", "ginger", "cilantro", "parsley", "scallion", "mushroom", "eggplant",
                "zucchini", "squash", "apple", "banana", "avocado", "herb", "basil", "mint"),
    "protein": ("chicken", "beef", "pork", "lamb", "turkey", "salmon", "shrimp", "fish",
                "tofu", "egg", "bacon", "sausage"),
    "dairy": ("milk", "butter", "cheese", "cream", "yogurt", "parmesan", "mozzarella",
              "pecorino", "ricotta"),
    "pantry": ("flour", "sugar", "rice", "pasta", "noodle", "bean", "lentil", "oil",
               "vinegar", "stock", "broth", "sauce", "soy", "tomato canned", "coconut milk",
               "chickpea", "oat", "bread", "honey", "cornstarch", "yeast", "pea split"),
    "spices": ("salt", "pepper", "cumin", "coriander", "paprika", "turmeric", "cinnamon",
               "chili", "curry", "sumac", "oregano", "thyme", "bay", "clove", "cardamom",
               "nutmeg", "adobo", "bouillon", "aleppo", "urfa"),
}


def aisle_for(name: str) -> str:
    """Best-guess aisle from normalized tokens. 'other' is a legible answer, not a failure."""
    norm = normalize_name(name)
    tokens = set(norm.split())
    best, best_len = "other", 0
    for aisle, keys in AISLE_MAP.items():
        for key in keys:
            parts = key.split()
            if all(p in tokens for p in parts) and len(key) > best_len:
                best, best_len = aisle, len(key)
    return best

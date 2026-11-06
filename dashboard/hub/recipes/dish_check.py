"""Self-check for dish-titles.json.

    python3 -m recipes.dish_check      # from dashboard/hub

Catches the one way a slug-keyed override file rots: a note renamed in Obsidian leaves
its key stranded, and the card silently falls back to the loud raw title with nothing
saying why. Also flags any recipe still showing a title with the tells this file exists
to remove, so a newly-imported Paprika recipe surfaces here instead of on the grid.

Exits non-zero on a stranded key. A "still loud" title is reported but does not fail —
a new import is expected to show up there until someone writes its dish name.
"""
from __future__ import annotations

import re
import sys

from . import store

# The tells: an emoji, ALL CAPS shouting, a trailing source/site tag, "Recipe" as a
# suffix, or a superlative that belongs to a thumbnail and not to a dish.
LOUD = re.compile(
    r"[\U0001F300-\U0001FAFF☀-➿]"
    r"|\b(?:BEST|MUST|ABSOLUTE|EASY|FAST|MY)\b"
    r"|\bRecipe!?\s*$"
    r"|\s[-|_]\s*(?:YouTube|Hello Fresh|Keeping It Relle)\s*$"
)


def main() -> int:
    recipes = store.all_recipes()
    by_slug = {r["slug"]: r for r in recipes}

    stranded = sorted(k for k in store._DISH if k not in by_slug)
    loud = sorted(r["slug"] for r in recipes
                  if r["dish"] == r["title"] and LOUD.search(r["title"]))

    if not store._DISH:
        print("dish-titles.json did not load — every card is showing its raw title")
        return 1

    print(f"{len(store._DISH)} dish names over {len(recipes)} recipes")
    for slug in stranded:
        print(f"  STRANDED  {slug}  -> no such note; rename or drop the key")
    for slug in loud:
        print(f"  loud      {slug}  -> {by_slug[slug]['title']!r} has no dish name yet")
    if not stranded and not loud:
        print("  clean")
    return 1 if stranded else 0


if __name__ == "__main__":
    sys.exit(main())

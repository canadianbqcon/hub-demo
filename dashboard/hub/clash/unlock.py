"""The game's unlock order for lab troops, siege machines, spells, heroes and pets.

Each army building's levels name what they unlock; the rank is the building's place in
the game's list, then that building's level. Buildings and traps have no rank."""

from functools import lru_cache

from . import gamedata

_UNLOCKERS = ("barracks", "dark-barracks", "workshop", "spell-factory", "dark-spell-factory", "hero-hall", "pet-house")


@lru_cache(maxsize=None)
def _ranks() -> dict:
    by_id = {d["id"]: d for d in gamedata._index().values()}
    out = {}
    for i, b in enumerate(_UNLOCKERS):
        for lv in by_id.get(b, {}).get("levels", []):
            for k, v in lv.items():
                if k.startswith("unlocked"):
                    for name in v if isinstance(v, list) else [v]:
                        if name:
                            out.setdefault(name, i * 100 + lv["level"])
    return out


def order(name: str):
    return _ranks().get(name)

"""Planning maths: builder queue, wall costs, resource sums. Pure functions over a fixed village.

Level convention: entity(id)["levels"][L - 1] holds the cost and time to reach level L.
Queue items carry the level being built (the target level).
"""
from collections import defaultdict
from datetime import timedelta

# Builder work is every home category except lab, pet house, forge, crafting and wall work.
# Real gamedata categories: defense, army, resource, other, town-hall, research, trap, hero.
NOT_BUILDER_CATEGORIES = {
    "troop", "spell", "pet", "siege-machine", "hero-equipment", "guardian",
    "crafted-defense", "wall",
}
WALL_CATEGORIES = {"wall", "walls"}


def _gd(gd):
    if gd is None:
        from clash import gamedata as gd
    return gd


def _cat(gd, data_id):
    return str(gd.entity(data_id).get("category", "")).lower()


def _step(gd, data_id, level):
    return gd.entity(data_id)["levels"][level - 1]


def _town_hall(gd, village):
    for v in village:
        if gd.entity(v["data_id"]).get("name") == "Town Hall":
            return v["level"]
    raise ValueError("village has no Town Hall")


def builder_queue(village, upgrades, builders, now, gd=None):
    gd = _gd(gd)
    th = _town_hall(gd, village)
    # one chain per physical instance: [data_id, next level to build, ready time]
    free = defaultdict(int)  # (data_id, level) -> instances not yet claimed by a running upgrade
    for v in village:
        if _cat(gd, v["data_id"]) not in NOT_BUILDER_CATEGORIES:
            free[(v["data_id"], v["level"])] += v["cnt"]
    lanes_free = []
    chains = []
    for u in upgrades:
        if u["facility"] != "builder":
            continue
        lanes_free.append(u["finishes_at"])
        key = (u["data_id"], u["from_level"])
        if free[key] > 0:
            free[key] -= 1
        chains.append([u["data_id"], u["from_level"] + 2, u["finishes_at"]])
    for (data_id, level), n in free.items():
        chains += [[data_id, level + 1, now] for _ in range(n)]
    lanes_free += [now] * max(0, builders - len(lanes_free))
    lanes = [[] for _ in lanes_free]

    def remaining(c):
        mx = gd.max_level(c[0], th)
        return sum(_step(gd, c[0], lv)["buildTime"] for lv in range(c[1], mx + 1))

    chains = [c for c in chains if c[1] <= gd.max_level(c[0], th)]
    while chains:
        i = min(range(len(lanes_free)), key=lambda k: lanes_free[k])
        # ponytail: longest remaining chain first; exact optimum is NP-hard
        c = max(chains, key=remaining)
        start = max(lanes_free[i], c[2])
        end = start + timedelta(seconds=_step(gd, c[0], c[1])["buildTime"])
        lanes[i].append({"data_id": c[0], "level": c[1], "start": start, "end": end})
        lanes_free[i] = c[2] = end
        c[1] += 1
        if c[1] > gd.max_level(c[0], th):
            chains.remove(c)
    return {"lanes": lanes, "done_at": max(lanes_free, default=now)}


def walls(village, th, gd=None):
    gd = _gd(gd)
    by_level = defaultdict(int)
    wall_id = None
    for v in village:
        if _cat(gd, v["data_id"]) in WALL_CATEGORIES:
            wall_id = v["data_id"]
            by_level[v["level"]] += v["cnt"]
    out = []
    for level in sorted(by_level):
        count, mx = by_level[level], gd.max_level(wall_id, th)
        to_next, to_max = defaultdict(int), defaultdict(int)
        for lv in range(level + 1, mx + 1):
            s = _step(gd, wall_id, lv)
            to_max[s["buildCostResource"]] += s["buildCost"] * count
            if lv == level + 1:
                to_next[s["buildCostResource"]] += s["buildCost"] * count
        out.append({"level": level, "count": count, "to_next": dict(to_next), "to_max": dict(to_max)})
    return out


def resources(queue, have, gd=None):
    gd = _gd(gd)
    need = defaultdict(int)
    for lane in queue["lanes"]:
        for it in lane:
            s = _step(gd, it["data_id"], it["level"])
            need[s["buildCostResource"]] += s["buildCost"]
    return {
        r: {"need": need[r], "have": have.get(r, 0), "short": max(0, need[r] - have.get(r, 0))}
        for r in sorted(set(need) | set(have))
    }

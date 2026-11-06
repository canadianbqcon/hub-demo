"""Pollen for the home weather block. pollen.com refuses browser cross-site calls
(it wants a User-Agent and its own Referer), so the server relays it. One call per
day: the index only changes daily, and the site is not an API anyone promised."""
from __future__ import annotations

import json
import urllib.request
from datetime import date

ZIP = "11201"
URL = f"https://www.pollen.com/api/forecast/current/pollen/{ZIP}"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": f"https://www.pollen.com/forecast/current/pollen/{ZIP}",
}
# pollen.com's own 0-12 bands
LEVELS = [(2.4, "low"), (4.8, "low-medium"), (7.2, "medium"), (9.6, "medium-high"), (12.1, "high")]

_cache: tuple[str, dict] | None = None


def level(index: float) -> str:
    return next(name for cap, name in LEVELS if index <= cap)


def pollen() -> dict:
    global _cache
    today = date.today().isoformat()
    if _cache and _cache[0] == today:
        return _cache[1]
    try:
        req = urllib.request.Request(URL, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        periods = {p["Type"]: p for p in d["Location"]["periods"]}
        p = periods["Today"]
        out = {
            "index": p["Index"],
            "level": level(p["Index"]),
            "triggers": [t["Name"] for t in p.get("Triggers", [])],
            "tomorrow": periods.get("Tomorrow", {}).get("Index"),
            "date": today,
        }
    except Exception:
        return _cache[1] if _cache else {"index": None, "level": None, "triggers": [], "date": today}
    _cache = (today, out)
    return out


if __name__ == "__main__":
    assert level(0) == "low" and level(6.3) == "medium" and level(12) == "high"
    print(pollen())

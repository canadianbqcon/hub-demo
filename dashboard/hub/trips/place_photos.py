"""place_photos.py — resolve a stored Google place id into live photo links.

Migration 017 stores a stay's photos as hotlinked URLs, which works because a
listing's CDN links stay good for as long as the listing does. Google's do not:
its own docs say a photo name "can expire" and must not be cached, its policy
exempts only the place id from that rule, and links in the wild go dead fast
(a real production cache sampled 27% dead overall, 12% at one week old). So a
hotel row stores `places/<id>` on one line and this turns it into real links
each time the trip is served. The carousel never learns the difference — what
reaches it is the same `url` or `url<TAB>caption` shape as always.

Ceiling: one details call plus one call per photo, each billed per request, so a
short TTL cache sits in front and a page reopened inside the hour costs nothing.
If a stay ever wants more than MAX photos, raise it; Google returns at most 10.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.expanduser("~/.config/vault-api"))
try:
    # pyright resolves `services` against dashboard/services.py (an unrelated,
    # same-named module reachable via pyrightconfig's dashboard extraPath) rather
    # than the ~/.config/vault-api/services.py this sys.path.insert actually
    # targets at runtime -- a per-machine symlink pyright cannot see statically.
    from services import PLACES_API_KEY  # pyright: ignore[reportAttributeAccessIssue]
except Exception:                                    # credentials absent on this box
    PLACES_API_KEY = ""

MAX = 10
TTL = 3600
WIDTH = 1600
_cache: dict[str, tuple[float, list[str], str]] = {}


def is_place(photos: str | None) -> str:
    """The place id if this column holds a pointer rather than URLs, else ''."""
    s = (photos or "").strip()
    return s[len("places/"):] if s.startswith("places/") and "\n" not in s else ""


def _get(url, fields=None):
    h = {"X-Goog-Api-Key": PLACES_API_KEY}
    if fields:
        h["X-Goog-FieldMask"] = fields
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20))


def resolve(pid: str) -> tuple[list[str], str]:
    """(photo links, the place's Google Maps page). Empty on any failure — a stay
    with no photos falls back to its spec strip, which is a worse page but a page."""
    hit = _cache.get(pid)
    if hit and time.time() - hit[0] < TTL:
        return hit[1], hit[2]
    if not PLACES_API_KEY:
        return [], ""
    try:
        d = _get(f"https://places.googleapis.com/v1/places/{pid}", "photos,googleMapsUri")
        urls = []
        for p in (d.get("photos") or [])[:MAX]:
            m = _get(f"https://places.googleapis.com/v1/{p['name']}/media"
                     f"?maxWidthPx={WIDTH}&skipHttpRedirect=true")
            if m.get("photoUri"):
                urls.append(m["photoUri"])
        maps_uri = d.get("googleMapsUri", "")
    except (urllib.error.URLError, OSError, KeyError, ValueError):
        return [], ""
    _cache[pid] = (time.time(), urls, maps_uri)
    return urls, maps_uri


def expand(row: dict) -> dict:
    """Swap a pointer row's photos for live links and mark where they came from.

    Google requires visible credit on a displayed photo, so the row carries the
    name and the link the panel needs; a row whose photos are its own listing's
    carries neither and renders exactly as before."""
    pid = is_place(row.get("photos", ""))
    if not pid:
        return row
    urls, maps_uri = resolve(pid)
    return {**row, "photos": "\n".join(urls),
            "photo_credit": "Google" if urls else "",
            "photo_credit_url": maps_uri}


def demo():
    assert is_place("places/ChIJabc") == "ChIJabc"
    assert is_place("https://a0.muscache.com/im/pictures/x.jpg") == ""
    # A real photo column with many URL lines must never read as a pointer.
    assert is_place("https://a/1.jpg\nhttps://a/2.jpg") == ""
    assert is_place("") == "" and is_place(None) == ""
    # A row that isn't a pointer passes through untouched, credit included.
    r = {"photos": "https://a/1.jpg"}
    assert expand(r) is r
    # A pointer that cannot resolve empties the column rather than raising.
    _cache["DEAD"] = (time.time(), [], "")
    out = expand({"photos": "places/DEAD"})
    assert out["photos"] == "" and out["photo_credit"] == ""
    print("demo ok")


if __name__ == "__main__":
    demo()

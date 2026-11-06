#!/usr/bin/env python3
"""One-time archive seed for the briefing_day snapshot table.

The dashboard only ever freezes a day's forecast going forward (when the page is
open on that day). Days that already passed before the snapshot system existed
have no row, so they'd show "no forecast" forever. This pulls the last ~92 days of
NYC weather from Open-Meteo (the same endpoint the client uses, with past_days)
and inserts forecast-only rows for any PAST day not already stored. It never
overwrites an existing row, so it's safe to re-run.

Usage:  python db/seed_briefing_backfill.py [past_days]   (default 92, Open-Meteo max)
"""

import sys
import pathlib
import urllib.request
import json

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "dashboard"))       # vault_path lives here
sys.path.insert(0, str(_REPO_ROOT / "dashboard" / "hub"))  # briefing_snapshot, tasks

import briefing_snapshot  # noqa: E402  # pyright: ignore[reportMissingImports]  — needs the sys.path setup above (dashboard/hub/ is not a declared pyright extraPath for db/)

PAST_DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 92
URL = (
    "https://api.open-meteo.com/v1/forecast?latitude=40.7128&longitude=-74.006"
    "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    "&temperature_unit=fahrenheit&timezone=America%2FNew_York"
    f"&past_days={PAST_DAYS}&forecast_days=1"
)


def _r(v):
    return round(v) if v is not None else None


def main():
    with urllib.request.urlopen(URL, timeout=30) as resp:
        data = json.load(resp)
    dl = data.get("daily") or {}
    times = dl.get("time") or []
    by_date = {}
    for i, d in enumerate(times):
        hi = _r((dl.get("temperature_2m_max") or [None])[i] if i < len(dl.get("temperature_2m_max") or []) else None)
        lo = _r((dl.get("temperature_2m_min") or [None])[i] if i < len(dl.get("temperature_2m_min") or []) else None)
        code = (dl.get("weather_code") or [None])[i] if i < len(dl.get("weather_code") or []) else None
        precip = (dl.get("precipitation_probability_max") or [None])[i] if i < len(dl.get("precipitation_probability_max") or []) else None
        # headline temp for a non-today day is the day's high, matching the client.
        by_date[d] = {"temp": hi, "code": code, "hi": hi, "lo": lo, "precip": precip}
    n = briefing_snapshot.backfill(by_date)
    print(f"briefing backfill: inserted {n} forecast-only past-day row(s) "
          f"from {len(times)} archive day(s).")


if __name__ == "__main__":
    main()

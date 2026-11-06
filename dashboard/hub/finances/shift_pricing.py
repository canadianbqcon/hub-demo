# vault-code/dashboard/hub/finances/shift_pricing.py
"""Price a scheduled shift from the tip pool's points-per-hour split.

The day-of-week average (migrations 003/004) prices every Friday the same. It
cannot see that a 9pm-3am Friday shares 2.5 of its hours with a second barback
while a 4:30pm-3am Friday shares none, so it misses the thing that actually
moves the number.

The model here is the one Sam described:

  * Every role carries points -- barback 6, server 8, bartender 10, bar captain
    12, host 2. All confirmed by Sam (server 2026-08-15, the rest 2026-09-03).
  * Points are assessed PER HOUR. Each hour's tip pool is split by the points
    of whoever is on the clock in that hour.
  * So two barbacks in the same hour each take half the barback share for that
    hour, and working an hour alone takes the whole thing.

Worked example, a normal Friday at 21:00-23:30 (both barbacks on):
    other roles on clock = bartender 10 + captain 12 + 2 servers 16 + 2 hosts 4 = 42
    two barbacks -> 6 / (42 + 12) = 11.11%
    solo         -> 6 / (42 +  6) = 12.50%   <- the ~12% solo lift
The lift is stable at 10-14% across any sane bartender/host point values,
because 6 points is a small slice of a ~50-60 point denominator.

CALIBRATION. The hourly pool density ($/hour of tips flowing to the whole pool)
is never guessed: `calibrate()` back-solves it from Sam's own paid shifts.
Given his actual clock times and the crew template for that day, his share is
known, so density = actual_tips / sum(hours_i * share_i). Late Fridays start at
the 21:00 boundary and so solve the peak density directly; early Fridays then
solve the pre-21:00 density with the peak contribution subtracted.

The known ceiling is the crew roster. Posted schedules exist for the weeks of
Aug 10 and Aug 17 only, so every other night uses a day-type template built from
those two. A real roster stored in earnings_shift_crew always wins over the
template.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from . import db

# ── Time helpers ──────────────────────────────────────────────────────────────
# Times are 'HH:MM' local. A span whose end is at or before its start crosses
# midnight, so it is carried into the next day rather than read as negative.

def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def span(start_at: str, end_at: str) -> tuple[int, int]:
    """('21:00','03:00') -> (1260, 1620). Minutes from the shift date's midnight."""
    s, e = _minutes(start_at), _minutes(end_at)
    return s, e + 1440 if e <= s else e


def hours(start_at: str, end_at: str) -> float:
    s, e = span(start_at, end_at)
    return (e - s) / 60.0


# ── Crew templates ────────────────────────────────────────────────────────────
# Fallback rosters by day type, read off the posted SpotOn schedules for the
# weeks of 2026-08-10 and 2026-08-17. These list the NON-barback crew only; the
# second barback, where there is one, is resolved by resolve_crew() below.

CREW_TEMPLATES: dict[str, list[tuple[str, str, str]]] = {
    # (role, start_at, end_at)
    "friday": [
        ("bartender",   "16:30", "00:30"),
        ("bar_captain", "19:00", "03:00"),
        ("server",      "17:30", "00:30"),
        ("server",      "20:00", "03:00"),
        ("host",        "18:00", "02:30"),
        ("host",        "18:00", "02:30"),
    ],
    "saturday": [
        ("bartender",   "16:30", "00:30"),
        ("bartender",   "19:00", "03:00"),
        ("server",      "17:30", "00:30"),
        ("server",      "20:00", "03:00"),
        ("host",        "17:30", "22:30"),
        ("host",        "22:30", "03:00"),
    ],
    # Sunday, Wednesday and Thursday run a skeleton crew and -- per the posted
    # schedules -- no second barback, so Sam is solo and his share is much
    # larger against a much smaller pool.
    "sunday":    [("bartender", "15:30", "00:00"), ("server", "17:30", "00:00")],
    "wednesday": [("bartender", "16:30", "00:00"), ("server", "17:30", "00:00")],
    "thursday":  [("bartender", "16:30", "01:00"), ("server", "17:30", "00:00")],
    # Sam 2026-07-29: "only me and bartender during buyout".
    "buyout":    [("bartender", "11:30", "23:30")],
}

_DOW_TEMPLATE = {
    0: "sunday", 1: "wednesday", 2: "wednesday", 3: "wednesday",
    4: "thursday", 5: "friday", 6: "saturday",
}

# Which density parameter each day type draws on. Friday/Saturday split at 21:00.
_PEAK_FROM = _minutes("21:00")


def template_for(shift_date: str, shift_kind: str = "regular") -> str:
    if shift_kind == "buyout":
        return "buyout"
    return _DOW_TEMPLATE[int(date.fromisoformat(shift_date).strftime("%w"))]


# Fri/Sat run two barback slots -- an opener (16:30-23:30) and a closer
# (21:00-03:00), overlapping 21:00-23:30. Sam fills one, so the OTHER is
# whichever he is not in. Hardcoding the opener into the template would have
# priced his own early-Friday shifts as shared for their whole length instead
# of only the overlap, which is the exact effect this model exists to measure.
_BARBACK_OPEN = ("barback", "16:30", "23:30")
_BARBACK_CLOSE = ("barback", "21:00", "03:00")


def resolve_crew(day_type: str, start_at: str) -> list[tuple[str, str, str]]:
    """Template crew for a shift, with the counterpart barback filled in."""
    base = list(CREW_TEMPLATES[day_type])
    if day_type not in ("friday", "saturday"):
        return base                       # skeleton nights roster one barback
    opening = _minutes(start_at) < _PEAK_FROM
    return base + [_BARBACK_CLOSE if opening else _BARBACK_OPEN]


def density_at(minute: int, day_type: str, params: dict[str, float]) -> float:
    """Tip dollars per hour flowing to the whole pool at `minute`."""
    if day_type == "buyout":
        return params["pool_sunday"] * params["buyout_multiple"]
    if day_type in ("friday", "saturday"):
        # The peak boundary repeats each day, so compare within the day.
        return params["pool_weekend_peak" if (minute % 1440) >= _PEAK_FROM
                      or minute >= 1440 else "pool_weekend_early"]
    if day_type == "thursday":
        return params["pool_thursday"]
    if day_type == "sunday":
        return params["pool_sunday"]
    return params["pool_weeknight"]


# ── The model ─────────────────────────────────────────────────────────────────

def price(start_at: str, end_at: str, *, role: str, day_type: str,
          crew: list[tuple[str, str, str]], points: dict[str, float],
          params: dict[str, float]) -> dict:
    """His tips and wages for one shift, hour by hour.

    Walks the shift as intervals cut at every crew arrival/departure and at the
    21:00 peak boundary, because his share only changes when someone clocks in
    or out. Within an interval the roster is constant, so his cut is
    (his points / points on clock) of that interval's pool.
    """
    my_start, my_end = span(start_at, end_at)
    my_points = points.get(role, 0.0)

    spans = [(r, *span(s, e)) for r, s, e in crew]
    # Cut points: every boundary that can change the share or the density.
    cuts = {my_start, my_end}
    for _, s, e in spans:
        cuts.update(x for x in (s, e) if my_start < x < my_end)
    for boundary in (_PEAK_FROM, _PEAK_FROM + 1440):
        if my_start < boundary < my_end:
            cuts.add(boundary)
    edges = sorted(cuts)

    tips = 0.0
    share_minutes = 0.0          # share weighted by minutes, for a mean to display
    served_minutes = 0           # minutes with a pool actually flowing
    for lo, hi in zip(edges, edges[1:], strict=False):  # adjacent-pair window, lengths differ by 1 on purpose
        mid = (lo + hi) / 2
        on = [r for r, s, e in spans if s <= mid < e]
        # No bartender on the clock means the bar is not serving: setup and
        # close-down hours accrue no tips. This is what keeps a 10:30am buyout
        # call time from being priced as six hours of revenue.
        # ponytail: bartender presence as the proxy for "open"; swap for an
        # explicit service window if a shift ever serves without one.
        serving = any(r in ("bartender", "bar_captain") for r in on)
        denom = my_points + sum(points.get(r, 0.0) for r in on)
        share = (my_points / denom) if denom else 0.0
        minutes = hi - lo
        share_minutes += share * minutes
        if serving:
            tips += (minutes / 60.0) * density_at(int(mid), day_type, params) * share
            served_minutes += minutes

    worked = (my_end - my_start) / 60.0
    wages = worked * params["tipped_wage_rate"]
    return {
        "hours": round(worked, 2),
        "wages": round(wages, 2),
        "tips": round(tips, 2),
        "total": round(wages + tips, 2),
        "mean_share": round(share_minutes / (my_end - my_start), 4) if my_end > my_start else 0.0,
        "served_hours": round(served_minutes / 60.0, 2),
    }


# ── Calibration ───────────────────────────────────────────────────────────────

def _weighted_hours(start_at: str, end_at: str, *, role: str, day_type: str,
                    crew: list[tuple[str, str, str]], points: dict[str, float],
                    only_peak: bool | None = None) -> float:
    """Sum of hours * his share, optionally restricted to one side of 21:00.

    Tips are linear in density, so actual_tips / weighted_hours IS the density.
    """
    unit: dict[str, float] = {
        "pool_weekend_early": 1.0, "pool_weekend_peak": 1.0, "pool_sunday": 1.0,
        "pool_weeknight": 1.0, "pool_thursday": 1.0,
        "buyout_multiple": 1.0, "tipped_wage_rate": 0.0,
    }
    if only_peak is None:
        return price(start_at, end_at, role=role, day_type=day_type, crew=crew,
                     points=points, params=unit)["tips"]
    # Restrict by zeroing the density on the side we are not measuring.
    side = dict(unit)
    side["pool_weekend_early"] = 1.0 if not only_peak else 0.0
    side["pool_weekend_peak"] = 1.0 if only_peak else 0.0
    return price(start_at, end_at, role=role, day_type=day_type, crew=crew,
                 points=points, params=side)["tips"]


def calibrate(actuals: list[dict], points: dict[str, float]) -> dict[str, float]:
    """Back-solve pool densities from real paid shifts.

    `actuals`: {shift_date, start_at, end_at, tips}. Late Fridays sit entirely
    past 21:00 and pin the peak density; early Fridays then give the pre-21:00
    density once the peak part is subtracted. Sundays pin their own.
    """
    out: dict[str, float] = {}
    by_type: dict[str, list[dict]] = {}
    for a in actuals:
        by_type.setdefault(template_for(a["shift_date"]), []).append(a)

    weekend = by_type.get("friday", []) + by_type.get("saturday", [])
    late = [a for a in weekend if _minutes(a["start_at"]) >= _PEAK_FROM]
    early = [a for a in weekend if _minutes(a["start_at"]) < _PEAK_FROM]

    def crew(a):
        return resolve_crew(template_for(a["shift_date"]), a["start_at"])

    if late:
        num = sum(a["tips"] for a in late)
        den = sum(_weighted_hours(a["start_at"], a["end_at"], role="barback",
                                  day_type=template_for(a["shift_date"]),
                                  crew=crew(a), points=points, only_peak=True)
                  for a in late)
        out["pool_weekend_peak"] = round(num / den, 2) if den else 0.0

    if early and "pool_weekend_peak" in out:
        peak = out["pool_weekend_peak"]
        num = 0.0
        den = 0.0
        for a in early:
            dt = template_for(a["shift_date"])
            spill = _weighted_hours(a["start_at"], a["end_at"], role="barback",
                                    day_type=dt, crew=crew(a), points=points,
                                    only_peak=True) * peak
            num += a["tips"] - spill
            den += _weighted_hours(a["start_at"], a["end_at"], role="barback",
                                   day_type=dt, crew=crew(a), points=points,
                                   only_peak=False)
        out["pool_weekend_early"] = round(max(num, 0.0) / den, 2) if den else 0.0

    for day_type, key in (("sunday", "pool_sunday"),
                          ("wednesday", "pool_weeknight"),
                          ("thursday", "pool_thursday")):
        rows = by_type.get(day_type, [])
        if not rows:
            continue
        num = sum(a["tips"] for a in rows)
        den = sum(_weighted_hours(a["start_at"], a["end_at"], role="barback",
                                  day_type=day_type,
                                  crew=resolve_crew(day_type, a["start_at"]),
                                  points=points)
                  for a in rows)
        if den:
            out[key] = round(num / den, 2)
    return out


# ── DB glue ───────────────────────────────────────────────────────────────────

def load_points(source: str = "juniper-and-co") -> dict[str, float]:
    with db._conn() as conn:
        return {r["role"]: r["points"] for r in conn.execute(
            "SELECT role, points FROM earnings_tip_points WHERE source=?", (source,))}


def load_params(source: str = "juniper-and-co") -> dict[str, float]:
    with db._conn() as conn:
        return {r["key"]: r["value"] for r in conn.execute(
            "SELECT key, value FROM earnings_pricing_params WHERE source=?", (source,))}


def load_meta(source: str = "juniper-and-co") -> dict:
    """Points and params with their verified flags, for the UI's honesty labels."""
    with db._conn() as conn:
        return {
            "points": [dict(r) for r in conn.execute(
                "SELECT role, points, verified, note FROM earnings_tip_points "
                "WHERE source=? ORDER BY points DESC, role", (source,))],
            "params": [dict(r) for r in conn.execute(
                "SELECT key, value, verified, note FROM earnings_pricing_params "
                "WHERE source=? ORDER BY key", (source,))],
        }


def actual_shifts(source: str = "juniper-and-co") -> list[dict]:
    """Paid tipped shifts, as calibration input. Clock times come off the stub."""
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT s.shift_date, s.clock_in, s.clock_out, "
            "       SUM(COALESCE(s.cash_tips,0) + COALESCE(s.cc_tips_net,0)) AS tips, "
            "       SUM(s.hours) AS hours "
            "FROM earnings_shifts s JOIN earnings e ON e.id = s.earnings_id "
            "WHERE e.source = ? AND s.tipped = 1 AND s.clock_in IS NOT NULL "
            "GROUP BY s.shift_date HAVING SUM(s.hours) > 0 "
            "ORDER BY s.shift_date", (source,)).fetchall()
    out = []
    for r in rows:
        out.append({
            "shift_date": r["shift_date"],
            "start_at": r["clock_in"][11:16],
            "end_at": r["clock_out"][11:16],
            "tips": round(r["tips"], 2),
            "hours": round(r["hours"], 2),
        })
    return out


def crew_for(shift_id: int, shift_date: str, shift_kind: str,
             start_at: str) -> list[tuple[str, str, str]]:
    """Stored roster if one exists, else the day-type template."""
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT role, start_at, end_at FROM earnings_shift_crew WHERE shift_id=?",
            (shift_id,)).fetchall()
    if rows:
        return [(r["role"], r["start_at"], r["end_at"]) for r in rows]
    return resolve_crew(template_for(shift_date, shift_kind), start_at)


def price_all(source: str = "juniper-and-co") -> int:
    """Price every scheduled shift that carries a window, writing the result back.

    A row with no start_at is left unpriced on purpose: the view then falls
    through to the day-of-week average exactly as it did before this module.
    """
    points, params = load_points(source), load_params(source)
    with db._conn() as conn:
        shifts = conn.execute(
            "SELECT id, shift_date, start_at, end_at, role, shift_kind "
            "FROM earnings_scheduled_shifts "
            "WHERE source=? AND start_at IS NOT NULL AND end_at IS NOT NULL",
            (source,)).fetchall()
        n = 0
        for s in shifts:
            kind = s["shift_kind"] or "regular"
            day_type = template_for(s["shift_date"], kind)
            crew = crew_for(s["id"], s["shift_date"], kind, s["start_at"])
            r = price(s["start_at"], s["end_at"], role=s["role"] or "barback",
                      day_type=day_type, crew=crew, points=points, params=params)
            note = (f"{day_type} template, {len(crew)} tipped coworker(s), "
                    f"{r['served_hours']}h serving")
            conn.execute(
                "UPDATE earnings_scheduled_shifts SET model_hours=?, model_wages=?, "
                "model_tips=?, model_total=?, model_share=?, priced_at=datetime('now'), "
                "pricing_note=? WHERE id=?",
                (r["hours"], r["wages"], r["tips"], r["total"], r["mean_share"],
                 note, s["id"]))
            n += 1
        conn.commit()
    return n


def priced_shifts(source: str = "juniper-and-co", limit: int = 60) -> list[dict]:
    with db._conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM earnings_expected_shift WHERE source=? "
            "ORDER BY shift_date LIMIT ?", (source, limit))]


# ── Self-check ────────────────────────────────────────────────────────────────

def demo() -> None:
    """Runnable check of the parts that would silently produce wrong money."""
    pts: dict[str, float] = {"barback": 6.0, "server": 8.0, "bartender": 10.0,
                             "bar_captain": 12.0, "host": 2.0}
    flat = {"pool_weekend_early": 100.0, "pool_weekend_peak": 100.0,
            "pool_sunday": 100.0, "pool_weeknight": 100.0, "pool_thursday": 100.0,
            "buyout_multiple": 1.0, "tipped_wage_rate": 10.00}

    # Spans that cross midnight must not go negative.
    assert span("21:00", "03:00") == (1260, 1620)
    assert hours("16:30", "00:00") == 7.5
    assert hours("10:30", "00:00") == 13.5

    # The counterpart barback is the slot he is NOT in. Getting this backwards
    # priced an early Friday as shared end to end instead of only 21:00-23:30.
    assert _BARBACK_CLOSE in resolve_crew("friday", "16:30")
    assert _BARBACK_OPEN in resolve_crew("friday", "21:00")
    assert all(c[0] != "barback" for c in resolve_crew("sunday", "15:30"))

    # THE CORE CLAIM: solo pays ~12% more per hour than sharing, same crew.
    fri = resolve_crew("friday", "21:00")
    shared = price("21:00", "23:30", role="barback", day_type="friday",
                   crew=fri, points=pts, params=flat)
    solo = price("21:00", "23:30", role="barback", day_type="friday",
                 crew=[c for c in fri if c[0] != "barback"], points=pts, params=flat)
    assert abs(shared["mean_share"] - 6 / 54) < 1e-3, shared["mean_share"]
    assert abs(solo["mean_share"] - 6 / 48) < 1e-3, solo["mean_share"]
    lift = solo["tips"] / shared["tips"]
    assert 1.10 <= lift <= 1.14, f"solo lift {lift:.3f} outside the 10-14% band"

    # The lift must stay in band across any sane bartender/host guess -- that
    # insensitivity is the reason assumed point values are tolerable at all.
    for bt, ho in ((8, 3), (12, 3), (10, 0), (14, 5)):
        p = {**pts, "bartender": bt, "bar_captain": bt, "host": ho}
        a = price("21:00", "23:30", role="barback", day_type="friday", crew=fri,
                  points=p, params=flat)["tips"]
        b = price("21:00", "23:30", role="barback", day_type="friday",
                  crew=[c for c in fri if c[0] != "barback"], points=p,
                  params=flat)["tips"]
        assert 1.09 <= b / a <= 1.16, f"bartender={bt} host={ho} -> {b / a:.3f}"

    # A solo full-span Friday must land BETWEEN one barback's take and the pair's
    # combined take. Summing the two (the mistake this model exists to fix) is an
    # overcount, because the pair commands 12 points during the overlap.
    full = price("16:30", "03:00", role="barback", day_type="friday",
                 crew=[c for c in fri if c[0] != "barback"], points=pts, params=flat)
    early = price("16:30", "23:30", role="barback", day_type="friday",
                  crew=resolve_crew("friday", "16:30"), points=pts, params=flat)
    late = price("21:00", "03:00", role="barback", day_type="friday",
                 crew=resolve_crew("friday", "21:00"), points=pts, params=flat)
    assert late["tips"] < full["tips"] < early["tips"] + late["tips"], (
        f"solo {full['tips']} not between {late['tips']} and "
        f"{early['tips'] + late['tips']}")

    # Thin weeknight crew concentrates his share -- 6/(6+10+8) once the server
    # is on, more in the first hour before they arrive.
    wed = price("16:30", "00:00", role="barback", day_type="wednesday",
                crew=CREW_TEMPLATES["wednesday"], points=pts, params=flat)
    assert 6 / 26 < wed["mean_share"] < 6 / 18, wed["mean_share"]

    # Buyout: him + one bartender -> 6/16 while serving, and the pre-service
    # call time earns nothing rather than a phantom hour of revenue.
    buy = price("10:30", "00:00", role="barback", day_type="buyout",
                crew=CREW_TEMPLATES["buyout"], points=pts, params=flat)
    assert buy["served_hours"] == 12.0, buy["served_hours"]
    assert buy["hours"] == 13.5
    assert abs(buy["tips"] - 12.0 * 100.0 * (6 / 16)) < 0.05, buy["tips"]

    # Wages are hours * rate regardless of the pool.
    assert abs(buy["wages"] - 13.5 * 10.00) < 0.01

    # Calibration must reproduce the tips it was solved from.
    acts = [
        {"shift_date": "2026-09-11", "start_at": "21:00", "end_at": "03:30", "tips": 126.50},
        {"shift_date": "2026-09-18", "start_at": "21:00", "end_at": "03:45", "tips": 171.25},
    ]
    cal = calibrate(acts, pts)
    assert "pool_weekend_peak" in cal and cal["pool_weekend_peak"] > 0
    params = {**flat, **cal}
    got = sum(price(a["start_at"], a["end_at"], role="barback", day_type="friday",
                    crew=fri, points=pts, params=params)["tips"] for a in acts)
    want = sum(a["tips"] for a in acts)
    assert abs(got - want) < 1.0, f"calibration round-trip {got:.2f} vs {want:.2f}"

    print("shift_pricing self-check OK")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="run the self-check and exit")
    ap.add_argument("--calibrate", action="store_true",
                    help="back-solve densities from paid shifts and write them")
    ap.add_argument("--price", action="store_true", help="price all scheduled shifts")
    args = ap.parse_args()

    if args.check:
        demo()
        return

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from vault_path import vault_root
    db.init(vault_root() / "data" / "earnings.db")

    if args.calibrate:
        pts = load_points()
        solved = calibrate(actual_shifts(), pts)
        with db._conn() as conn:
            for k, v in solved.items():
                conn.execute(
                    "UPDATE earnings_pricing_params SET value=?, "
                    "note = note || ' Re-solved ' || date('now') || '.' "
                    "WHERE source='juniper-and-co' AND key=?", (v, k))
            conn.commit()
        for k, v in sorted(solved.items()):
            print(f"  {k:24} {v:>8.2f}")
    if args.price:
        print(f"priced {price_all()} scheduled shifts")


if __name__ == "__main__":
    main()

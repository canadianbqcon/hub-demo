# vault-code/dashboard/hub/finances/budget.py
"""How much per month actually goes to the cards, derived rather than typed in.

Sam's framing, and the only one this module implements: *earnings minus what
I generally spend is what lands on the cards, so express that as a share and
apply it to what I'm projected to earn.* Earn $1,200, spend $200, budget $1,000
-- an 83% share. When the shift schedule changes, the projection moves and the
budget moves with it; nobody retypes a number.

Two sources, each doing the thing it is actually good at:

* **Earnings** come from `earnings.db`. `db.ui_forecast()` walks the roster week
  by week, prices each shift off the day-of-week history, and computes the
  unemployment benefit that week's hours actually earn. Historical earnings come
  from the same place, so the share and the projection use one ruler.
* **Spending** comes from YNAB, which is where spending actually lives.

Reimbursables and card interest are excluded from spend. Payback rows come back,
so counting them as consumption overstates his cost of living; interest is
already modelled by the projection in debt.py and would otherwise be charged
twice.

The share is deliberately NOT taken from what he has historically *paid* the
cards. Those payments ran at 90% of income and above 100% in three of seven
months -- that is a checking account being drained, not a repeatable rate.
Earnings minus spend is what can actually recur.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

if str(Path(__file__).resolve().parent.parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dashboard/

from finances import book

from . import db

# Categories that are not consumption. Payback is money fronted for other people
# and collected back; Interest is the cost of the debt itself, which debt.py
# already simulates -- subtracting it here as well would charge it twice.
NOT_SPEND = {"Payback", "Interest", "Reimbursements"}

# Gross-to-net is measured from real pay periods rather than assumed, but a fresh
# job with no net recorded yet has to fall back on something.
FALLBACK_KEEP = 0.85

# Spend history starts the day after the Austin trip ended (trips.db trip 1,
# 2026-05-14..05-18). Sam's call, and the reason is in the numbers: the
# months with a trip in them ran $1,850 and $1,950, the months without ran $900
# and $720. A vacation month is not a month he lives in, and averaging one in
# sets a budget he could never hit. Move this date when a later trip should
# start a fresh window; it is deliberately not "since the last trip" because
# that would leave three days of data the week after he gets back.
SPEND_SINCE = "2026-05-19"

# What a week the calendar says nothing about is worth. His actual cadence.
ASSUMED_SHIFTS_PER_WEEK = 3

# Mean Gregorian month. The spend window is a run of days, so it converts to a
# monthly figure by rate, not by counting calendar months.
DAYS_PER_MONTH = 30.44

# A month needs this fraction of its days elapsed before its spend total means
# anything. Only the history table uses it -- typical spend is a daily rate now,
# so a part-elapsed month no longer needs to be thrown away, just labelled.
MIN_MONTH_COMPLETE = 0.9


def _month_span(month: str) -> int:
    y, m = int(month[:4]), int(month[5:])
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return (nxt - date(y, m, 1)).days


def _add_months(day: str, n: int) -> str:
    y, m = int(day[:4]), int(day[5:7])
    m += n
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}-{min(int(day[8:10]), _month_span(f'{y:04d}-{m:02d}')):02d}"


def spend_rate(txns: list[dict], since: str, today: str) -> dict:
    """Typical monthly spend, as a daily rate scaled up.

    The window is a run of days, not a set of calendar months. Its first and last
    months are both partial, so averaging whole months would either throw those
    days away or let a half-elapsed month drag the figure down by however early
    in the month it happens to be. A daily rate uses every day exactly once.
    """
    spend = sum(t["amount"] for t in txns
                if t["date"] >= since and t["category"] not in NOT_SPEND)
    excluded = sum(t["amount"] for t in txns
                   if t["date"] >= since and t["category"] in NOT_SPEND)
    days = max((date.fromisoformat(today) - date.fromisoformat(since)).days, 1)
    return {
        "since": since,
        "days": days,
        "total": round(spend, 2),
        "excluded": round(excluded, 2),
        "daily": round(spend / days, 2),
        "monthly": round(spend / days * DAYS_PER_MONTH, 2),
    }


def spend_by_month(txns: list[dict], today: str) -> dict[str, dict]:
    """Per-month spend, for the history table only. Not what sets the budget."""
    out: dict[str, dict] = {}
    for t in txns:
        m = out.setdefault(t["date"][:7], {"spend": 0.0, "excluded": 0.0})
        key = "excluded" if t["category"] in NOT_SPEND else "spend"
        m[key] = round(m[key] + t["amount"], 2)
    for m, row in out.items():
        elapsed = int(today[8:10]) if m == today[:7] else _month_span(m)
        row["days_elapsed"] = elapsed
        row["days_in_month"] = _month_span(m)
        row["complete"] = elapsed / _month_span(m) >= MIN_MONTH_COMPLETE
    return out


def earnings_by_month(since: str) -> dict[str, float]:
    """Net earnings per month, attributed to the month the pay period ended.

    Period end, not deposit date: a period that ends on the 31st is work he did
    in that month, and pinning it to a deposit that clears on the 3rd would slide
    a month's earnings into the next one every time payroll lands late.
    """
    out: dict[str, float] = {}
    for e in db.list_earnings():
        if e["period_end"] < since:
            continue
        m = e["period_end"][:7]
        out[m] = round(out.get(m, 0.0) + (e["net"] or 0.0), 2)
    return out


def keep_rate(since: str = "2026-06-19") -> float:
    """Net as a fraction of gross, measured over recent pay periods.

    Defaults to the tipped era: J&Co moved to $10.00/hr plus tips on 2026-06-19,
    and periods before that have a different withholding profile entirely.
    """
    gross = net = 0.0
    for e in db.list_earnings():
        if e["period_end"] < since or not e["gross"] or not e["net"]:
            continue
        gross += e["gross"]
        net += e["net"]
    return round(net / gross, 4) if gross else FALLBACK_KEEP


def derive(today: str | None = None, months_ahead: int = 6,
           spend_override: float | None = None,
           assume_shifts: int = ASSUMED_SHIFTS_PER_WEEK) -> dict:
    """The whole chain: spend rate -> projected earnings -> monthly budget.

    Weeks the calendar has nothing to say about are filled at `assume_shifts`;
    a week already holding even one rostered shift is left alone, because one
    shift is information and the roster is the better source than an average.
    """
    today = today or date.today().isoformat()
    # One API call. Iterating the live YNAB API is what blew the 200 req/hr limit.
    txns = book.fetch_spend(since_date=SPEND_SINCE)

    rate = spend_rate(txns, SPEND_SINCE, today)
    typical_spend = spend_override if spend_override is not None else rate["monthly"]

    spend = spend_by_month(txns, today)
    earned = earnings_by_month(SPEND_SINCE)
    history = []
    for month in sorted(set(spend) | set(earned)):
        s = spend.get(month, {"spend": 0.0, "excluded": 0.0, "complete": False})
        e = earned.get(month, 0.0)
        history.append({
            "month": month,
            "earnings": round(e, 2),
            "spend": round(s["spend"], 2),
            "excluded": round(s.get("excluded", 0.0), 2),
            "available": round(e - s["spend"], 2),
            "share": round((e - s["spend"]) / e, 4) if e else None,
            "complete": s.get("complete", False),
        })

    keep = keep_rate()
    ui = db.ui_forecast(today=today, assume_shifts=assume_shifts,
                        through=_add_months(today, months_ahead))
    projection = []
    for month, m in sorted(ui["by_month"].items()):
        shift_net = round(m["shift_total"] * keep, 2)
        net = round(shift_net + m["net"], 2)
        # A month can only fund the cards with what is left after living on it.
        budget = round(max(0.0, net - typical_spend), 2)
        projection.append({
            "month": month,
            "weeks": m["weeks"],
            "shifts": m["shifts"],
            "assumed_weeks": m["assumed_weeks"],
            "shift_net": shift_net,
            "ui_net": m["net"],
            "ui_days": m["effective_days"],
            "earnings": net,
            "spend": typical_spend,
            "budget": budget,
            "share": round(budget / net, 4) if net else None,
        })

    headline = projection[0] if projection else None
    return {
        "history": history,
        "spend_rate": rate,
        "typical_spend": typical_spend,
        "typical_spend_source": (
            "override" if spend_override is not None
            else f"{rate['days']}d since {rate['since']} at ${rate['daily']}/day"),
        "keep_rate": keep,
        "projection": projection,
        "budget": headline["budget"] if headline else None,
        "budget_month": headline["month"] if headline else None,
        "share": headline["share"] if headline else None,
        "assumed_shifts_per_week": assume_shifts,
        "ui_claim": ui.get("claim"),
        "roster_horizon": (ui.get("claim") or {}).get("horizon"),
    }


def _self_check() -> None:
    """Assert the arithmetic Sam stated. Run: python3 -m hub.finances.budget"""
    # His own example: earn 1200, spend 200, put 1000 on the cards -> an 83% share.
    net, spend = 1200.0, 200.0
    assert round(net - spend, 2) == 1000.0
    assert round((net - spend) / net, 4) == 0.8333

    # Spend is a daily rate scaled to a month, so a 69-day window and a 30-day
    # one describing the same habit produce the same monthly figure.
    txns = [{"date": "2026-06-01", "category": "Dining", "amount": 690.0},
            {"date": "2026-06-02", "category": "Payback", "amount": 500.0}]
    r = spend_rate(txns, "2026-05-19", "2026-07-27")
    assert r["days"] == 69 and r["total"] == 690.0
    assert r["excluded"] == 500.0          # Payback never counts as consumption
    assert r["monthly"] == round(690.0 / 69 * DAYS_PER_MONTH, 2) == 304.4

    # Anything before the window opens is out, however it arrives.
    assert spend_rate([{"date": "2026-05-15", "category": "Travel", "amount": 900.0}],
                      "2026-05-19", "2026-07-27")["total"] == 0.0

    assert _add_months("2026-07-27", 6) == "2027-01-27"
    assert _add_months("2026-12-31", 2) == "2027-02-28"     # clamps to a real day
    assert _month_span("2026-08") == 31

    # Spend can never push the budget below zero -- a bad month means nothing to
    # the cards, not a negative payment that would silently ADD to the balance.
    assert max(0.0, 300.0 - 900.0) == 0.0

    print("budget.py self-check passed")


if __name__ == "__main__":
    _self_check()

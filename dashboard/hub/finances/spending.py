# vault-code/dashboard/hub/finances/spending.py
"""The spending tab's data: not what he bought, but how he spends.

Sister to the earnings tab, and deliberately built the other way round. Earnings
has its own store (`earnings.db`) because a pay stub is a document that has to be
parsed once and kept. Spending does not get a table: YNAB already is the ledger,
already has the categories, and already has Sam's own corrections in it, so a
local copy would only be a second version of the truth that goes stale. The debt
tab reads YNAB live for the same reason.

The shape of the question comes from his actual data, measured over 10 months:

* His spending is **episodic, not habitual.** $11,400 went to 216 payees seen in
  fewer than four months; $4,900 went to the 18 that recur. The top 25
  transactions are 54% of everything.
* **Row count is inversely related to dollars.** 441 charges under $15 are 62% of
  the rows and 9% of the money; MTA alone is 213 rows and 2%. A date-sorted list
  shows him almost entirely noise, which is why the transaction table is the last
  thing on the page and collapsed.
* **Categories hide the real units.** The snowboard decision cost ~$1,164 across
  Capita, Evo and Ski Barn, split between "Shopping" and "Hobbies", and never
  appears anywhere as one thing.

So spending is split into three bands, in descending order of how little say he
has over each, and the page answers: what does a month cost me before I decide
anything, what keeps happening, what did I actually decide to buy, and what
changed.

1. **Subscriptions** -- his own YNAB `Subscriptions` group. A fixed price he does
   not re-decide monthly. This is read from his taxonomy, not classified: the
   first cut tried cadence plus a tight amount spread and flagged Uniqlo and
   Dunkin' as subscriptions while missing Claude Max entirely. He had already
   done the work by hand in YNAB, and reading it beats re-deriving it badly.
2. **Recurring** -- a payee seen in 3+ distinct months that is *still charging*.
   Uber, MTA, Lyft, the deli: no single charge is a decision, but $360/month is.
   The still-charging half of the test is what keeps a finished payment plan out;
   Lost Lands ran monthly for six months and stopped, so it is an episode he
   paid off, not a habit he has.
3. **Episodes** -- everything left above the threshold: the one-off decisions.

Every row in every band carries its own transactions, so any figure on the page
can be opened down to the charges that produced it. Nothing is a number he has to
take on faith.

Everything is sliced in memory from ONE `book.fetch_spend()` call plus one
category fetch. Iterating the live API per scope is what blew the 200 req/hr
limit before.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

if str(Path(__file__).resolve().parent.parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dashboard/

from finances import book
from vault_path import vault_root

from . import budget, db

SCOPES = ("week", "month", "ytd")

# His own YNAB category group. Everything in it is a standing charge he does not
# re-decide each month; everything outside it he chose.
FLOOR_GROUP = "Subscriptions"

# A payee has to clear this across the window to be called a decision rather than
# background noise. Below it the row would say nothing -- 216 payees share the
# remainder, and the point of the section is the handful that actually moved money.
EPISODE_MIN = 250.0

# How many distinct months a payee must appear in before it counts as a habit
# rather than a coincidence. Two could be one purchase that straddled a month end.
RECUR_MIN_MONTHS = 3

# Months of history the trend reads. Six is enough to see a direction without the
# matrix growing wider than the panel.
TREND_MONTHS = 6

_EPISODE_FILE = vault_root() / "data" / "spending-episodes.json"

# Cadence and cancellation cannot be derived from the ledger. YNAB's history here
# starts 2025-10, so every yearly plan has exactly ONE charge on record, which is
# byte-for-byte what a cancelled monthly plan looks like. And a cancellation is
# the absence of a future charge, which no past transaction records. So both are
# stored facts, keyed by YNAB category, same as the episode merges above.
_SUBS_FILE = vault_root() / "data" / "subscriptions.json"


# ── shared slicing ────────────────────────────────────────────────────────────

def _txns(ts: list[dict]) -> list[dict]:
    """The charges behind a row, newest first, for its expander.

    Every aggregate on this page ships the transactions that produced it. A
    figure he cannot open is a figure he has to trust, and the whole point of the
    tab is that he stops having to.
    """
    return sorted(
        ({"date": t["date"], "payee": t["payee"],
          "category": t["category"], "amount": t["amount"]} for t in ts),
        key=lambda t: t["date"], reverse=True,
    )


def _slice(txns: list[dict], lo: str, hi: str) -> tuple[float, float]:
    """(consumption, excluded) dollars for the inclusive date window."""
    spent = excluded = 0.0
    for t in txns:
        if not (lo <= t["date"] <= hi):
            continue
        if t["category"] in budget.NOT_SPEND:
            excluded += t["amount"]
        else:
            spent += t["amount"]
    return round(spent, 2), round(excluded, 2)


def scope_totals(txns: list[dict], today: str) -> dict[str, dict]:
    """Spent / earned / net for each headline window.

    Earned is the same net figure the earnings tab prints for that window, off
    the same `db.totals()` call, so the two tabs cannot show different numbers
    for the same week. Net is the whole point of the pairing: a spend total on
    its own says nothing about whether the month worked.
    """
    out = {}
    for scope in SCOPES:
        lo, hi = db._scope_bounds(scope, today)
        spent, excluded = _slice(txns, lo, hi)
        earned = db.totals(scope, today)["net"]
        out[scope] = {
            "start": lo, "end": hi,
            "spent": spent, "excluded": excluded,
            "earned": earned, "net": round(earned - spent, 2),
        }
    return out


# ── 1. floor vs. choice ───────────────────────────────────────────────────────

def split_floor(txns: list[dict], groups: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Partition consumption into the standing charges and the decisions.

    A category YNAB does not know about (a new one, or a transaction he has not
    categorized yet) falls to choice. That is the safe direction: calling a real
    purchase "floor" would quietly shrink the number he can actually act on.
    """
    floor, choice = [], []
    for t in txns:
        if t["category"] in budget.NOT_SPEND:
            continue
        (floor if groups.get(t["category"]) == FLOOR_GROUP else choice).append(t)
    return floor, choice


def load_subs() -> dict:
    """Per-category overrides: {"Uber One": {"cadence": "yearly"}}.

    Keys: `cadence` ("monthly" | "yearly", default monthly) and `cancelled`
    (bool). A missing or corrupt file just means everything derives as before.
    """
    try:
        return json.loads(_SUBS_FILE.read_text()).get("subscriptions", {})
    except Exception:
        return {}


def save_subs(subs: dict) -> None:
    _SUBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SUBS_FILE.write_text(json.dumps({"subscriptions": subs}, indent=2) + "\n")


def subscriptions(floor_txns: list[dict], today: str,
                  overrides: dict | None = None) -> dict:
    """What the subscriptions cost per month, at today's prices.

    The rate is the most recent charge of each still-live subscription, NOT the
    window average. A plan he started in April would otherwise read as a third of
    its real price for the rest of the year, and a plan he cancelled in February
    would keep charging him on this page forever.

    A yearly plan is divided by 12 to reach that same monthly figure, and is only
    called stale after 14 months rather than two. Both halves are load-bearing:
    Uber One's one $96 charge was being added to the monthly floor whole, and its
    every-12-months rhythm reads as death to any two-month cutoff.

    Anything marked `cancelled` is dropped outright rather than dimmed. A stopped
    plan the ledger inferred is a guess worth showing; one he has confirmed dead
    is just a row he has to scroll past.
    """
    overrides = load_subs() if overrides is None else overrides

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for t in floor_txns:
        if not overrides.get(t["category"], {}).get("cancelled"):
            by_cat[t["category"]].append(t)

    lines = []
    for cat, ts in by_cat.items():
        yearly = overrides.get(cat, {}).get("cadence") == "yearly"
        newest = max(ts, key=lambda t: t["date"])
        # Gone, not late: two months for a monthly plan, fourteen for a yearly
        # one -- a full cycle plus the grace a monthly plan gets.
        cutoff = budget._add_months(today, -14 if yearly else -2)
        lines.append({
            "name": cat,
            "cadence": "yearly" if yearly else "monthly",
            # The price he pays now, always per month so the floor sums.
            "monthly": round(newest["amount"] / 12, 2) if yearly else newest["amount"],
            "charge": newest["amount"],           # what actually hits the card
            "total": round(sum(t["amount"] for t in ts), 2),
            "count": len(ts),
            "last": newest["date"],
            "live": newest["date"] >= cutoff,
            "txns": _txns(ts),
        })
    lines.sort(key=lambda r: (not r["live"], -r["monthly"]))
    return {
        "monthly": round(sum(r["monthly"] for r in lines if r["live"]), 2),
        "total": round(sum(r["total"] for r in lines), 2),
        "lines": lines,
        "dropped": [r["name"] for r in lines if not r["live"]],
    }


def bands(choice_txns: list[dict], today: str, merges: dict | None = None,
          minimum: float = EPISODE_MIN) -> dict:
    """Split everything he chose into what keeps happening and what he decided.

    **Recurring** is a payee seen in `RECUR_MIN_MONTHS`+ distinct months that is
    still charging -- the last charge falls in the latest closed month or later.
    Both halves are load-bearing. Month count alone would call a six-month
    payment plan a habit: Lost Lands billed monthly from February to June and
    stopped, and listing it as $150/month of ongoing spend would overstate his
    real commitments by that much forever. Recency alone would call any purchase
    made last week recurring.

    **Episodes** are what is left above the threshold. They are anchored on the
    payee, because that is the one grouping the data actually supports: eleven
    Lost Lands charges over six months are one festival, and no category or date
    window would put them together. Cross-payee decisions (Capita + Evo + Ski
    Barn are all one snowboard buy) cannot be inferred without knowing what those
    shops sell, so they are a stored merge rather than a guess -- clustering by
    time here would silently file unrelated same-week purchases together, which
    is worse than not grouping them at all.
    """
    merges = merges or {}
    owner = {p: name for name, payees in merges.items() for p in payees}

    buckets: dict[str, list[dict]] = defaultdict(list)
    for t in choice_txns:
        buckets[owner.get(t["payee"], t["payee"]) or "(no payee)"].append(t)

    # The latest month that has actually finished. Judging "still charging"
    # against the current month would drop every real habit for the first days of
    # a month, before its charges have landed.
    live_from = budget._add_months(today, -1)[:7] + "-01"

    recurring, episodes, rest_total, rest_n = [], [], 0.0, 0
    for name, ts in buckets.items():
        total = sum(t["amount"] for t in ts)
        dates = sorted(t["date"] for t in ts)
        months_seen = len({d[:7] for d in dates})
        by_cat: dict[str, float] = defaultdict(float)
        for t in ts:
            by_cat[t["category"] or "(uncategorized)"] += t["amount"]
        row = {
            # the category carrying most of the money: the page groups rows under it
            "category": max(by_cat, key=lambda k: by_cat[k]),
            "name": name,
            "total": round(total, 2),
            "count": len(ts),
            "first": dates[0], "last": dates[-1],
            "months": months_seen,
            "monthly": round(total / months_seen, 2),
            "merged": name in merges,
            "payees": sorted({t["payee"] for t in ts}),
            "categories": sorted({t["category"] for t in ts if t["category"]}),
            "txns": _txns(ts),
        }
        if months_seen >= RECUR_MIN_MONTHS and dates[-1] >= live_from:
            recurring.append(row)
        elif total >= minimum:
            episodes.append(row)
        else:
            rest_total += total
            rest_n += 1

    recurring.sort(key=lambda r: -r["monthly"])
    episodes.sort(key=lambda r: -r["total"])
    grand = sum(t["amount"] for t in choice_txns)
    return {
        "recurring": {
            "rows": recurring,
            "monthly": round(sum(r["monthly"] for r in recurring), 2),
            "total": round(sum(r["total"] for r in recurring), 2),
        },
        "episodes": {
            "rows": episodes,
            "total": round(sum(r["total"] for r in episodes), 2),
            "share": (round(sum(r["total"] for r in episodes) / grand, 4)
                      if grand else None),
        },
        "rest": {"total": round(rest_total, 2), "payees": rest_n},
        "minimum": minimum,
        "live_from": live_from,
    }


# ── 2. movement ───────────────────────────────────────────────────────────────

def _month_list(today: str, n: int) -> list[str]:
    return [budget._add_months(today, -i)[:7] for i in range(n - 1, -1, -1)]


def trend(txns: list[dict], groups: dict[str, str], today: str,
          months: int = TREND_MONTHS) -> dict:
    """Group-by-month, plus what moved against his own baseline.

    Grouped rather than per-category because eight groups fit on a screen and
    eighteen categories do not, and because a group is the level at which a
    change is legible: "Transportation is up" is a fact he can act on, "Other
    Transportation is up" is a YNAB artifact.

    A mover compares the latest CLOSED month against the average of the ones
    before it. The current month is excluded from both sides -- three days into
    August every category looks like a collapse, and a page that says so every
    month is a page he stops reading.
    """
    ms = _month_list(today, months)
    grid: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in txns:
        m = t["date"][:7]
        if m in ms and t["category"] not in budget.NOT_SPEND:
            grid[groups.get(t["category"]) or "Uncategorized"][m] += t["amount"]

    rows = [{"group": g, "by_month": {m: round(v.get(m, 0.0), 2) for m in ms},
             "total": round(sum(v.values()), 2)}
            for g, v in grid.items()]
    rows.sort(key=lambda r: -r["total"])

    closed = [m for m in ms if m < today[:7]]
    movers: list[dict] = []
    latest = prior = None
    if len(closed) >= 2:
        latest, prior = closed[-1], closed[:-1]
        for r in rows:
            now = r["by_month"][latest]
            base = sum(r["by_month"][m] for m in prior) / len(prior)
            delta = round(now - base, 2)
            if abs(delta) >= 50:      # below this it is noise, not a move
                movers.append({"group": r["group"], "now": now,
                               "baseline": round(base, 2), "delta": delta})
        movers.sort(key=lambda m: -abs(m["delta"]))

    totals = {m: round(sum(r["by_month"][m] for r in rows), 2) for m in ms}
    peak = max(totals.values()) if totals else 0.0
    return {
        "months": ms, "rows": rows, "totals": totals,
        "movers": movers[:4], "latest_closed": latest,
        "peak": peak, "peak_month": max(totals, key=lambda m: totals[m]) if totals else None,
        "vs_peak": (round((totals[latest] - peak) / peak, 4)
                    if latest and peak else None),
    }


# ── 3. episodes ───────────────────────────────────────────────────────────────

def load_names() -> dict:
    """Hand-merged episodes: {"Snowboarding": ["Capita Snowboardi", "Evo"]}.

    A missing or corrupt file is not an error worth failing the page over -- the
    auto-grouped episodes are still true without any merges on top.
    """
    try:
        return json.loads(_EPISODE_FILE.read_text()).get("merges", {})
    except Exception:
        return {}


def save_names(merges: dict) -> None:
    _EPISODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _EPISODE_FILE.write_text(json.dumps({"merges": merges}, indent=2) + "\n")


# ── by category (group-aware, expandable) ─────────────────────────────────────

def by_category(txns: list[dict], lo: str, hi: str,
                groups: dict[str, str] | None = None) -> list[dict]:
    """Every category that saw money in the window, biggest first.

    Uncategorized transactions are real spending and get their own bucket rather
    than vanishing into a blank label -- an empty category name is the signal
    that a row still needs `/ynab`, not a reason to drop it from the total.
    """
    groups = groups or {}
    agg: dict[str, dict] = {}
    for t in txns:
        if not (lo <= t["date"] <= hi):
            continue
        name = t["category"] or "(uncategorized)"
        row = agg.setdefault(name, {
            "category": name, "group": groups.get(t["category"], ""),
            "amount": 0.0, "count": 0, "rows": [],
            "excluded": t["category"] in budget.NOT_SPEND,
        })
        row["amount"] += t["amount"]
        row["count"] += 1
        row["rows"].append(t)
    total = sum(r["amount"] for r in agg.values() if not r["excluded"])
    for r in agg.values():
        r["amount"] = round(r["amount"], 2)
        # Share is of consumption only, so the percentages on the spending rows
        # still add to 100 with a Payback row sitting among them.
        r["share"] = round(r["amount"] / total, 4) if total and not r["excluded"] else None
        r["txns"] = _txns(r.pop("rows"))
    return sorted(agg.values(), key=lambda r: (r["excluded"], -r["amount"]))


def months(txns: list[dict], today: str, since: str) -> list[dict]:
    """Month by month: earned, spent, and what was left of it.

    Both halves come from the modules that already own them -- spend from
    `budget.spend_by_month`, earnings from `budget.earnings_by_month` -- so the
    monthly table here and the history the debt tab budgets off are one
    computation, not two that drift.
    """
    spend = budget.spend_by_month(txns, today)
    earned = budget.earnings_by_month(since)
    out = []
    for month in sorted(set(spend) | set(earned), reverse=True):
        s = spend.get(month, {"spend": 0.0, "excluded": 0.0, "complete": False})
        e = earned.get(month, 0.0)
        out.append({
            "month": month,
            "earnings": round(e, 2),
            "spend": round(s["spend"], 2),
            "excluded": round(s.get("excluded", 0.0), 2),
            "net": round(e - s["spend"], 2),
            "complete": s.get("complete", False),
        })
    return out


# ── assembly ──────────────────────────────────────────────────────────────────

def snapshot(today: str | None = None, since: str | None = None) -> dict:
    """The whole tab in one response."""
    today = today or date.today().isoformat()
    since = since or f"{today[:4]}-01-01"
    if not book.is_configured():
        return {"configured": False, "since": since, "today": today}

    # One fetch, two windows. A yearly plan charges once and can sit well behind
    # a calendar-YTD `since` -- the YNAB subscription last billed in November is
    # live and was rendering nowhere -- so the floor reads 14 months back. Every
    # other band is sliced to `since`, because widening those would fold last
    # year's charges into this year's episodes and trend.
    wide = book.fetch_spend(since_date=min(since, budget._add_months(today, -14)))
    wide.sort(key=lambda t: t["date"], reverse=True)
    txns = [t for t in wide if t["date"] >= since]
    groups = {c["name"]: c["group_name"] for c in book.fetch_categories()}

    floor_txns, _ = split_floor(wide, groups)
    _, choice_txns = split_floor(txns, groups)
    scopes = scope_totals(txns, today)
    for v in scopes.values():
        v["card_payments"] = book.card_payments(v["start"], v["end"])
    subs = subscriptions(floor_txns, today)
    bd = bands(choice_txns, today, load_names())

    # The committed figure is what a month costs before he decides anything:
    # the subscriptions he does not re-decide plus the habits that keep charging.
    committed = round(subs["monthly"] + bd["recurring"]["monthly"], 2)

    return {
        "configured": True,
        "since": since,
        "today": today,
        "not_spend": sorted(budget.NOT_SPEND),
        "floor_group": FLOOR_GROUP,
        "scopes": scopes,
        "subscriptions": subs,
        "recurring": bd["recurring"],
        "episodes": bd["episodes"],
        "rest": bd["rest"],
        "committed_monthly": committed,
        "trend": trend(txns, groups, today),
        "by_category": {s: by_category(txns, v["start"], v["end"], groups)
                        for s, v in scopes.items()},
        "months": months(txns, today, since),
        "transactions": _txns(txns),
    }


def _self_check() -> None:
    """Run: python3 -m hub.finances.spending (from dashboard/)."""
    T = [
        {"id": "1", "date": "2026-08-03", "category": "Dining", "amount": 40.0, "payee": "A"},
        {"id": "2", "date": "2026-08-01", "category": "Payback", "amount": 500.0, "payee": "B"},
        {"id": "3", "date": "2026-07-15", "category": "Dining", "amount": 60.0, "payee": "C"},
        {"id": "4", "date": "2026-07-16", "category": "", "amount": 10.0, "payee": "D"},
    ]
    G = {"Dining": "Food", "Spotify Family Plan": FLOOR_GROUP}

    assert _slice(T, "2026-08-01", "2026-08-03") == (40.0, 500.0)
    assert _slice(T, "2026-07-01", "2026-07-31") == (70.0, 0.0)
    assert _slice(T, "2026-01-01", "2026-06-30") == (0.0, 0.0)

    cats = by_category(T, "2026-07-01", "2026-07-31", G)
    assert [c["category"] for c in cats] == ["Dining", "(uncategorized)"]
    assert cats[0]["group"] == "Food" and cats[0]["count"] == 1
    assert round(sum(c["share"] for c in cats), 4) == 1.0
    aug = by_category(T, "2026-08-01", "2026-08-31", G)
    assert aug[-1]["category"] == "Payback" and aug[-1]["excluded"] is True
    assert aug[-1]["share"] is None and aug[0]["share"] == 1.0
    assert by_category([T[1]], "2026-08-01", "2026-08-31", G)[0]["share"] is None

    # ── floor vs choice ──
    sub = {"id": "s", "date": "2026-07-02", "category": "Spotify Family Plan",
           "amount": 21.99, "payee": "Spotify"}
    floor, choice = split_floor(T + [sub], G)
    assert [t["id"] for t in floor] == ["s"]
    assert "2" not in [t["id"] for t in choice]          # Payback is neither
    # An unknown category falls to choice, never to floor.
    assert split_floor([{"date": "2026-07-01", "category": "Brand New",
                         "amount": 5.0, "payee": "X"}], G)[0] == []

    # Rate is the LATEST charge, not the window average: a price rise counts at
    # the new price, and a cancelled plan stops counting after two silent months.
    hist = [
        {"date": "2026-05-02", "category": "Claude Max 5x", "amount": 20.0, "payee": "a"},
        {"date": "2026-07-02", "category": "Claude Max 5x", "amount": 109.0, "payee": "a"},
        {"date": "2026-02-02", "category": "Dead Sub", "amount": 9.0, "payee": "b"},
    ]
    fr = subscriptions(hist, "2026-08-03", overrides={})   # {} = derive everything
    assert fr["monthly"] == 109.0                        # not (20+109)/2, not 138
    assert fr["dropped"] == ["Dead Sub"]
    assert fr["total"] == 138.0                          # total still counts it all
    # Every row opens to its own charges, newest first.
    assert [t["date"] for t in fr["lines"][0]["txns"]] == ["2026-07-02", "2026-05-02"]

    # A yearly plan: one charge, 13 months of silence, and still alive. Derived
    # alone it is indistinguishable from a cancellation, which is the whole
    # reason cadence is stored rather than inferred.
    yr = [{"date": "2026-07-16", "category": "Uber One", "amount": 96.0, "payee": "u"}]
    d_yr = subscriptions(yr, "2026-08-03", overrides={})["lines"][0]
    o_yr = subscriptions(yr, "2026-08-03",
                         overrides={"Uber One": {"cadence": "yearly"}})["lines"][0]
    assert d_yr["monthly"] == 96.0 and o_yr["monthly"] == 8.0     # $96/yr is not $96/mo
    assert o_yr["charge"] == 96.0                                # the card still sees $96
    # Two months' silence kills it derived; fourteen is the yearly grace.
    assert subscriptions(yr, "2026-11-01", overrides={})["dropped"] == ["Uber One"]
    assert subscriptions(yr, "2027-06-01",
                         overrides={"Uber One": {"cadence": "yearly"}})["dropped"] == []
    assert subscriptions(yr, "2027-10-01",
                         overrides={"Uber One": {"cadence": "yearly"}})["dropped"] == ["Uber One"]

    # A confirmed cancellation leaves entirely -- not dimmed, not in `dropped`,
    # and not in `total`. That is the difference from an inferred stop.
    gone = subscriptions(hist, "2026-08-03",
                         overrides={"Dead Sub": {"cancelled": True}})
    assert [r["name"] for r in gone["lines"]] == ["Claude Max 5x"]
    assert gone["dropped"] == [] and gone["total"] == 129.0

    # ── trend ──
    tr_txns = [
        {"date": "2026-05-10", "category": "Dining", "amount": 100.0, "payee": "p"},
        {"date": "2026-06-10", "category": "Dining", "amount": 100.0, "payee": "p"},
        {"date": "2026-07-10", "category": "Dining", "amount": 300.0, "payee": "p"},
        {"date": "2026-08-01", "category": "Dining", "amount": 5.0, "payee": "p"},
    ]
    tr = trend(tr_txns, G, "2026-08-03", months=4)
    assert tr["months"] == ["2026-05", "2026-06", "2026-07", "2026-08"]
    assert tr["latest_closed"] == "2026-07"              # August is not compared
    assert tr["movers"][0]["group"] == "Food"
    assert tr["movers"][0]["delta"] == 200.0             # 300 vs the 100 baseline
    # A sub-$50 wobble is not a move.
    assert trend([{"date": "2026-06-10", "category": "Dining", "amount": 100.0, "payee": "p"},
                  {"date": "2026-07-10", "category": "Dining", "amount": 120.0, "payee": "p"}],
                 G, "2026-08-03", months=3)["movers"] == []

    # ── bands: recurring vs episodes ──
    NOW = "2026-08-03"          # latest closed month is July, so live_from = 2026-07-01
    ep_txns = [
        # a finished payment plan: 3 months, but nothing since June
        {"date": "2026-02-01", "category": "Parties", "amount": 500.0, "payee": "Lost Lands"},
        {"date": "2026-04-01", "category": "Parties", "amount": 300.0, "payee": "Lost Lands"},
        {"date": "2026-06-05", "category": "Parties", "amount": 214.0, "payee": "Lost Lands"},
        # a live habit: 3 months and still charging
        {"date": "2026-05-02", "category": "Ride Share", "amount": 60.0, "payee": "Uber"},
        {"date": "2026-06-02", "category": "Ride Share", "amount": 90.0, "payee": "Uber"},
        {"date": "2026-07-27", "category": "Ride Share", "amount": 150.0, "payee": "Uber"},
        # one-off decisions, one under the threshold
        {"date": "2026-01-05", "category": "Shopping", "amount": 620.0, "payee": "Capita"},
        {"date": "2026-01-09", "category": "Hobbies", "amount": 315.0, "payee": "Evo"},
        {"date": "2026-03-01", "category": "Casual Food", "amount": 6.0, "payee": "Deli"},
    ]
    b = bands(ep_txns, NOW)
    assert b["live_from"] == "2026-07-01"
    # Month count alone would call the finished plan a habit; recency is what
    # keeps $300/mo of commitment he no longer has off the page.
    assert [r["name"] for r in b["recurring"]["rows"]] == ["Uber"]
    assert b["recurring"]["monthly"] == 100.0            # 300 over 3 months
    assert [r["name"] for r in b["episodes"]["rows"]] == ["Lost Lands", "Capita", "Evo"]
    assert b["episodes"]["rows"][0]["total"] == 1014.0
    assert b["rest"]["total"] == 6.0 and b["rest"]["payees"] == 1   # the deli is noise

    # A merge folds separate payees into one decision and spans their categories.
    m = bands(ep_txns, NOW, {"Snowboarding": ["Capita", "Evo"]})
    top = [x for x in m["episodes"]["rows"] if x["name"] == "Snowboarding"][0]
    assert top["total"] == 935.0 and top["merged"] is True
    assert top["payees"] == ["Capita", "Evo"]
    assert top["categories"] == ["Hobbies", "Shopping"]
    assert "Capita" not in [x["name"] for x in m["episodes"]["rows"]]
    # Merging never silently drops charges.
    assert len(top["txns"]) == 2

    # Every band row opens to its charges, newest first.
    assert [t["date"] for t in b["recurring"]["rows"][0]["txns"]] == [
        "2026-07-27", "2026-06-02", "2026-05-02"]

    print("spending.py self-check passed")


if __name__ == "__main__":
    _self_check()

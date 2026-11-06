# vault-code/dashboard/hub/finances/trip_debts.py
"""Trip lines Sam fronted, read out of trips.db as debts other people owe him.

Why this exists rather than a hand-typed row: a trip debt's amount is COMPUTED —
a share of a stay, a van, a ticket — and the owed tab used to hold a copy of that
number. Sam, 2026-08-28: "the cost, if it changes in trips, should
automatically update the owed tab correctly." A copy cannot. So the amount is
derived here on every read of the tab and written through to the row, keyed by
`owed.src`.

This is a narrow port of the ledger in trips/frontend/static/trips-cost.js, kept
narrow on purpose. That file answers "who owes whom across the whole crew," which
needs netting and a greedy settle-up. This one answers only "what does someone
owe SAM," which is one pass with no netting: he is the payer or the line is
not ours. The two agree on the parts that overlap — committed rows only, the
row's own cents-per-point rate, an explicit split_with as the share list — and
those definitions are duplicated here rather than imported because one is
browser JavaScript and the other is server Python.

ponytail: no netting against what HE owes on the same trip. The Denver house is
  Megan's card and the van is Jasmine's, so he is the debtor there and those
  lines simply never enter this function. If a trip ever has him fronting one
  line and owing another to the same person, this will show her share of his
  line while the trips ledger nets it — settle from the trips board in that case.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlite_helpers import connect as sqlite_connect, rows as _rows

# Same three words the trips board treats as real money. An estimate is not a
# debt: nobody owes a share of a rideshare that has not been booked.
COMMITTED = ("booked", "confirmed", "paid")

# The Chase cash-out floor, and the fallback for a row with no redemption rate of
# its own. Mirrors UR_CENTS in trips-cost.js — if that constant moves, this one
# moves with it.
UR_CENTS = 0.0125

ME_SLUG = "sam-rivera"

# table -> the column holding its cash cost. Same fallback chain as rowCost().
_COST_COL = {
    "housing": "total_cost",
    "flights": "cost",
    "transportation": "cost",
    "expenses": "amount",
}
# What to call the line on the owed tab, per table.
_LABEL_COL = {
    "housing": "name",
    "flights": "airline",
    "transportation": "description",
    "expenses": "description",
}


def _c(x: float) -> float:
    """Round money half-up. Python's round() is banker's, which turns the Dino
    Express half-share ($300.25 / 2 = $150.125) into $150.12 while every other
    figure on the tab was rounded up to $150.13. One rule, and it matches the
    rows already there."""
    return int(abs(x) * 100 + 0.5) / 100 * (1 if x >= 0 else -1)


def _rate(row: dict) -> float:
    """Cents per point for this row, as a dollar multiplier."""
    cents = row.get("cents_per_point") or 0
    return (float(cents) / 100) if float(cents) > 0 else UR_CENTS


def _ur(row: dict) -> float:
    """Points that actually left his balance. Never both figures — points_total
    on a row that also carries points_transfer would double the same money."""
    return float(row.get("points_transfer") or 0) or float(row.get("points_total") or 0)


def _cash(row: dict, table: str) -> float:
    return float(row.get(_COST_COL[table]) or 0)


def _split_ids(row: dict) -> list[str]:
    raw = str(row.get("split_with") or "").strip()
    return [s.strip() for s in raw.split(",") if s.strip()]


def _owner_id(members: list[dict]) -> str | None:
    """Whose board this is. There is no owner flag on `members`, so the contact
    slug is the marker, falling back to the first name on the roster — the same
    rule trips-cost.js uses."""
    named = [m for m in members if str(m.get("name") or "").strip()]
    if not named:
        return None
    me = next((m for m in named if (m.get("contact_slug") or "") == ME_SLUG), named[0])
    return str(me["id"])


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _iso(v) -> str:
    """A trip date only if it is actually a date. These columns are free text and
    hold whatever was pasted in: housing 7 carries "2026-09-17 15:00" and housing
    10 carries "Dec 16, 3:00 PM". Slicing the second one to ten characters put
    "Dec 16, 3:" into `incurred`, which the tab rendered as "undefined NaN c 16,
    3:". Anything that is not ISO gets no date, which the tab already handles."""
    m = _ISO.match(str(v or "").strip())
    return m.group(0) if m else ""


def _key(trip_id, table: str, row: dict) -> str:
    """What identifies the LINE a debt came from.

    A flight is keyed by its confirmation, not its row id, because a round trip
    is two rows and one ticket. Aria's El Salvador booking is CGJTF7 out and
    CGJTF7 back — the cash sits on the outbound leg and the points sit on both,
    and billing her twice for one ticket is not what either row means. Every
    other table is one row per thing bought, so the row id is the line.
    """
    if table == "flights":
        conf = str(row.get("confirmation") or "").strip()
        if conf:
            return f"trip:{trip_id}/flights/{conf}"
    return f"trip:{trip_id}/{table}/{row['id']}"


def _row_debt_ids(r: dict, owner: str, crew_ids: set[str]) -> list[str] | None:
    """The crew ids actually on the hook for this row, or None if the row is not
    a Sam-fronted, committed, split line."""
    if (r.get("status") or "") not in COMMITTED:
        return None
    payer = str(r.get("paid_by") or "").strip()
    # A payer is a members.id, always. `expenses.paid_by` predates the crew
    # list and holds typed names on old rows; a name matches nobody and reads
    # as unclaimed, which is the honest answer.
    if payer not in crew_ids or payer != owner:
        return None
    ids = [i for i in _split_ids(r) if i in crew_ids]
    return ids or None      # unticked: nobody is on the hook, by design


def _fold_row_onto_line(lines: dict[str, dict], trip: dict, table: str, r: dict,
                        ids: list[str]) -> None:
    key = _key(trip["id"], table, r)
    line = lines.setdefault(key, {
        "key": key, "table": table, "trip": trip["name"],
        "label": "", "value": 0.0, "cash": 0.0, "ids": ids,
        "date": "", "conf": str(r.get("confirmation") or "").strip(),
    })
    cash = _cash(r, table)
    line["value"] += cash + _ur(r) * _rate(r)
    line["cash"] += cash
    # The leg carrying the money is the one worth naming.
    lab = str(r.get(_LABEL_COL[table]) or "").strip()
    if lab and (not line["label"] or cash):
        line["label"] = lab
    line["date"] = line["date"] or _iso(r.get("check_in") or r.get("scheduled_date"))


def _fold_lines(trip: dict, tables: dict, owner: str, crew_ids: set[str]) -> dict[str, dict]:
    """Fold each table's rows onto their line key first, so a two-leg ticket is
    one debt. Anything not a flight folds onto itself."""
    lines: dict[str, dict] = {}
    for table, rows in tables.items():
        for r in rows:
            if r["trip_id"] != trip["id"]:
                continue
            ids = _row_debt_ids(r, owner, crew_ids)
            if not ids:
                continue
            _fold_row_onto_line(lines, trip, table, r, ids)
    return lines


def _lines_to_debts(lines: dict[str, dict], owner: str, name_of: dict[str, str]) -> list[dict]:
    out: list[dict] = []
    for line in lines.values():
        share = _c(line["value"] / len(line["ids"]))
        if share <= 0:
            continue
        for mid in line["ids"]:
            if mid == owner:
                continue        # his own share is not a debt to himself
            out.append({
                "src": f"{line['key']}/member:{mid}",
                "person": name_of[mid],
                "amount": share,
                "what": _describe(line),
                "incurred": line["date"] or None,
                "paid_out": _c(line["value"]) if len(line["ids"]) > 1 else None,
                "grp": line["trip"],
                "note": _note(line, share),
            })
    return out


def derive(trips_db: Path) -> list[dict]:
    """Every share of a Sam-fronted trip line that somebody else owes him.

    One entry per (line, debtor), carrying the `src` pointer the owed table
    stores, the derived amount, and enough text to read the row without opening
    the trips board.
    """
    with sqlite_connect(trips_db, "trips.db") as conn:
        trips = _rows(conn.execute("SELECT id, name FROM trips"))
        members = _rows(conn.execute("SELECT id, trip_id, name, contact_slug FROM members"))
        tables = {t: _rows(conn.execute(f"SELECT * FROM {t}")) for t in _COST_COL}

    by_trip_member: dict = {}
    for m in members:
        by_trip_member.setdefault(m["trip_id"], []).append(m)

    out: list[dict] = []
    for trip in trips:
        crew = by_trip_member.get(trip["id"], [])
        owner = _owner_id(crew)
        if not owner:
            continue
        crew_ids = {str(m["id"]) for m in crew}
        name_of = {str(m["id"]): m["name"] for m in crew}
        lines = _fold_lines(trip, tables, owner, crew_ids)
        out.extend(_lines_to_debts(lines, owner, name_of))
    return out


def _describe(line: dict) -> str:
    n = len(line["ids"])
    label = line["label"] or line["table"]
    if line["table"] == "flights":
        return f"{line['trip']} — {label} ticket" + (f" ({line['conf']})" if line["conf"] else "")
    return f"{line['trip']} — {label}" + (f" — 1 of {n}" if n > 1 else "")


def _note(line: dict, share: float) -> str:
    bits = ["Derived from the trips board; the amount follows the trip line and "
            "updates when its cost does."]
    total = _c(line["value"])
    if len(line["ids"]) > 1:
        bits.append(f"${total:,.2f} split {len(line['ids'])} ways = ${share:,.2f} each.")
    points = total - _c(line["cash"])
    if points > 0.005:
        bits.append(f"Booked partly on points: ${line['cash']:,.2f} cash plus points valued at "
                    f"${points:,.2f} at the row's own redemption rate. A debt is always in "
                    f"dollars — nobody settles up by transferring points.")
    return " ".join(bits)

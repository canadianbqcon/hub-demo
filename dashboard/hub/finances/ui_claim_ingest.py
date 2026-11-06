#!/usr/bin/env python3
"""Load NYS unemployment payment history into earnings.db.

Paste the Payment History table straight off the NYSDOL claim page into a file
and pipe it in -- the parser reads the tab/space separated rows and ignores
everything around them, so no hand-cleaning:

    python3 dashboard/hub/finances/ui_claim_ingest.py < claim.txt

One `earnings` row per benefit week (Mon-Sun, keyed on the week-ending date),
so re-running with a longer history updates in place instead of duplicating.
No shift rows: UI is not shift work, and a week is the atom the state pays on.
"""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402

SOURCE = "nys-unemployment"
SOURCE_TYPE = "benefits"
WEEKLY_RATE = 180.00          # 4 effective days; one day is a quarter of this

# "07/12/2026  $140.00  $122.50  3  07/16/2026  Direct Deposit"
ROW_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+\$?([\d,]+\.\d{2})\s+\$?([\d,]+\.\d{2})\s+(\d)\s+"
    r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s*$")


def _iso(mdy: str) -> str:
    m, d, y = mdy.split("/")
    return f"{y}-{m}-{d}"


def _money(s: str) -> float:
    return float(s.replace(",", ""))


def parse(text: str) -> list[dict]:
    """Payment-history rows, oldest first. Non-matching lines are skipped."""
    out = []
    for line in text.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        week_end, total, net, eff_days, released, kind = m.groups()
        out.append({
            "week_end": _iso(week_end),
            "gross": _money(total),
            "net": _money(net),
            "effective_days": int(eff_days),
            "released": _iso(released),
            "type": kind.strip(),
        })
    return sorted(out, key=lambda r: r["week_end"])


def to_earning(row: dict) -> dict:
    end = date.fromisoformat(row["week_end"])
    start = end - timedelta(days=6)              # benefit week runs Mon-Sun
    # A waiting week is recorded, not skipped: it consumed a week of the claim
    # and its absence would read as a gap in the history.
    waiting = row["gross"] == 0.0
    note = (f"{row['effective_days']} effective day"
            f"{'' if row['effective_days'] == 1 else 's'}"
            f" · released {row['released']} · {row['type']}")
    if waiting:
        note = "Unpaid waiting week (no benefit payable). " + note
    elif row["effective_days"] < 4:
        note += (f" · partial week, {4 - row['effective_days']} day"
                 f"{'' if row['effective_days'] == 3 else 's'} reduced for hours worked")
    return {
        "source": SOURCE,
        "source_type": SOURCE_TYPE,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "granularity": "week",
        "gross": row["gross"],
        "net": row["net"],
        "hours": None,                            # benefits are not hours-paid
        "wages": None,
        "tax_withheld": round(row["gross"] - row["net"], 2),
        "source_doc": "NYSDOL claim summary (Payment History)",
        "notes": note,
    }


def main() -> None:
    rows = parse(sys.stdin.read())
    if not rows:
        sys.exit("no payment-history rows found on stdin")

    db.init(vault_root() / "data" / "earnings.db")
    for row in rows:
        db.upsert_earning(to_earning(row), [])

    gross = sum(r["gross"] for r in rows)
    net = sum(r["net"] for r in rows)
    days = sum(r["effective_days"] for r in rows if r["gross"] > 0)
    print(f"{len(rows)} benefit weeks: {rows[0]['week_end']} to {rows[-1]['week_end']}")
    print(f"  gross ${gross:,.2f}  net ${net:,.2f}  withheld ${gross - net:,.2f}"
          f"  ({(gross - net) / gross * 100:.2f}%)")
    print(f"  {days} effective days paid, {104 - days} of 104 remaining"
          f" (~${(104 - days) * WEEKLY_RATE / 4:,.2f} gross)")


if __name__ == "__main__":
    main()

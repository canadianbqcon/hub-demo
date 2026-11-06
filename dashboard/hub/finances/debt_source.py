# vault-code/dashboard/hub/finances/debt_source.py
"""Assembles the debt tab's inputs: live YNAB balances + terms from cards.db.

Kept apart from debt.py so the engine stays pure and testable without a network
or a database, and apart from api.py so the same assembly can be reused by a
skill or a script later. This module is the only place that knows the two
sources have to be merged by card name.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from datetime import date
from functools import lru_cache
from pathlib import Path

if str(Path(__file__).resolve().parent.parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dashboard/

from finances import book
from sqlite_helpers import apply_pragmas
from vault_path import vault_root

from . import debt

_DB = vault_root() / "data" / "cards.db"


def _terms() -> list[dict]:
    """Every row in cards.db, or [] when the DB has not been migrated yet."""
    if not _DB.exists():
        return []
    conn = sqlite3.connect(_DB)
    conn.row_factory = sqlite3.Row
    apply_pragmas(conn)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM card").fetchall()]
    except sqlite3.OperationalError:
        return []  # pre-002 schema; the debt tab reports "not configured"
    finally:
        conn.close()


# ponytail: a one-minute time-bucket cache, not a cache layer. YNAB allows 200
# calls an hour and one payment change costs eight (the main view plus six
# what-if scenarios), so a few minutes of trying values hit 429 and the tab
# quietly collapsed to the loan. Balances change once a day; a minute is nothing.
def _bucket() -> int:
    return int(time.time() // 60)


@lru_cache(maxsize=1)
def _balances(bucket: int) -> dict[str, float]:
    b = book.fetch_card_balances()
    if not b:   # a failure is not cached, and never shown as "no cards"
        raise RuntimeError("YNAB did not return card balances (rate limit or token); try again in a minute")
    return b


@lru_cache(maxsize=1)
def _payments(bucket: int) -> list[dict]:
    return book.fetch_card_payments()


def accounts(asof: date | None = None) -> list[debt.Account]:
    """Build the account list the engine consumes.

    Balances come from YNAB (the live truth); rates, limits and promo windows come
    from cards.db (which YNAB does not expose). Matched by name, case-insensitively,
    the same way hub/cards.py merges due dates.

    A card in YNAB with no cards.db row still appears — at 0% APR, flagged — rather
    than being dropped, because a missing balance understates total debt, which is
    the one number that must never be wrong. A cards.db row with no YNAB account is
    dropped unless it is a loan (loans have no account of their own; they live
    inside a parent card's balance).
    """
    asof = asof or date.today()
    balances = _balances(_bucket())
    rows = {r["name"].lower(): r for r in _terms()}
    out: list[debt.Account] = []

    for name, bal in balances.items():
        r = rows.get(name.lower(), {})
        acct = debt.Account(
            name=name,
            balance=round(bal, 2),
            apr=r.get("apr") or 0.0,
            promo_apr=r.get("promo_apr"),
            promo_end=r.get("promo_end"),
            credit_limit=r.get("credit_limit"),
            min_payment=r.get("min_payment"),
            due_day=r.get("due_day"),
        )
        if not r:
            acct.notes.append("no terms in cards.db — add it to db/seed_cards.py")
        out.append(acct)

    for r in rows.values():
        if r.get("kind") != "loan":
            continue
        principal, start = r.get("balance"), r.get("start_date")
        if principal and start:
            remaining, made = debt.loan_balance(
                principal, r.get("apr") or 0.0, r.get("fixed_payment") or 0.0, start, asof
            )
            note = f"{made} of {r.get('term_months')} payments made"
        else:
            remaining, note = principal or 0.0, "balance not amortized (no start_date)"
        acct = debt.Account(
            name=r["name"],
            balance=remaining,
            apr=r.get("apr") or 0.0,
            kind="loan",
            fixed_payment=r.get("fixed_payment"),
            due_day=r.get("due_day"),
            parent=r.get("parent"),
        )
        acct.notes.append(note)
        out.append(acct)

    return debt.reconcile_parent(out)


def snapshot(monthly_budget: float | None = None, asof: date | None = None) -> dict:
    """Full debt picture: projection plus recent payment history."""
    accts = accounts(asof)
    result = debt.project(accts, monthly_budget, start=asof)
    result["payments"] = _payments(_bucket())
    result["configured"] = book.is_configured()
    return result


def scenarios(budgets: list[float], asof: date | None = None) -> list[dict]:
    """Same debt, several monthly payment levels — the trajectory comparison."""
    return debt.compare(lambda: accounts(asof), budgets, start=asof)

# vault-code/dashboard/hub/finances/debt.py
"""Debt projection engine for the Hub finances debt tab.

Pure functions over plain dicts — no DB, no network, no Flask. The API layer
hands it live YNAB balances merged with the terms in cards.db and gets back a
month-by-month simulation: when each card dies, what interest it costs on the
way, and how a different monthly payment changes both.

Three modelling choices worth stating up front, because they decide every number
downstream:

1. **Interest accrues before the payment lands.** Real issuers charge on an
   average daily balance, which lands somewhere between "before" and "after".
   Accruing first is the pessimistic end of that range, which is the right
   direction to be wrong in for a payoff planner.
2. **Promotional 0% is a plain rate window, not deferred interest.** Discover It
   and Citi Diamond Preferred both revert going-forward at the cliff; neither
   retroactively bills the promo period. Store cards that DO defer would need a
   separate flag — none of Sam's do.
3. **The decomposition always sums to the live YNAB total.** An installment loan
   drawn against a card line (My Chase Loan on the Sapphire) is already inside
   that card's YNAB balance, so it is carved out rather than added. When the
   contractual loan schedule exceeds what YNAB says the account holds, the loan
   is clamped down to the account balance and the gap is reported rather than
   silently absorbed — see reconcile_parent().
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

# Typical revolving-card minimum: interest plus 1% of principal, with a dollar
# floor. Issuers vary (1–2%, $25–$41 floors); these are the common Chase/Discover
# terms and are only used when cards.db has no explicit min_payment.
# ponytail: flat constants, not per-issuer rules — override via min_payment when a
# card's real terms matter enough to look up.
MIN_PCT = 0.01
MIN_FLOOR = 25.0

# Simulation guard. 50 years is far past any real payoff; hitting it means the
# payment does not cover interest, which is reported as never_pays_off.
MAX_MONTHS = 600


@dataclass
class Account:
    """One debt line. `balance` is what is owed today, positive."""

    name: str
    balance: float
    apr: float = 0.0                 # ongoing rate, percent
    promo_apr: float | None = None   # rate while promo_end is in the future
    promo_end: str | None = None     # ISO date the promo rate expires
    kind: str = "card"               # 'card' | 'loan'
    fixed_payment: float | None = None   # loans: contractual installment
    min_payment: float | None = None     # cards: explicit minimum, overrides the formula
    credit_limit: float | None = None
    due_day: int | None = None
    parent: str | None = None        # loans: card whose balance contains this one
    # Filled by reconcile_parent(); not an input.
    notes: list[str] = field(default_factory=list)


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_month(d: date) -> date:
    return date(d.year + (d.month == 12), 1 if d.month == 12 else d.month + 1, 1)


def monthly_rate(acct: Account, on: date) -> float:
    """Rate charged for the cycle starting `on`, as a decimal fraction.

    The promo rate applies through promo_end; the cycle containing the cliff is
    billed at the promo rate and the next one reverts. Being one cycle generous
    at the boundary beats being one cycle alarmist about a date the issuer sets.
    """
    apr = acct.apr
    if acct.promo_end and acct.promo_apr is not None:
        if on <= date.fromisoformat(acct.promo_end):
            apr = acct.promo_apr
    return apr / 100.0 / 12.0


def minimum_due(acct: Account, balance: float, interest: float) -> float:
    """Smallest payment that keeps the account current this cycle."""
    if balance <= 0:
        return 0.0
    if acct.kind == "loan":
        # A loan installment is contractual and does not shrink with the balance,
        # except on the final cycle where only the remainder is owed.
        return min(balance, acct.fixed_payment or 0.0)
    floor = acct.min_payment if acct.min_payment is not None else max(
        MIN_FLOOR, interest + balance * MIN_PCT
    )
    return min(balance, floor)


def loan_balance(principal: float, apr: float, payment: float,
                 start: str, asof: date) -> tuple[float, int]:
    """Amortize a fixed installment loan from origination to `asof`.

    Returns (remaining principal, payments made). Lets the seed record only facts
    that never move — original principal, rate, term, installment — instead of a
    current balance that goes stale the moment a payment posts.
    """
    r = apr / 100.0 / 12.0
    start_d = date.fromisoformat(start)
    # One payment per elapsed whole month since origination.
    made = (asof.year - start_d.year) * 12 + (asof.month - start_d.month)
    if asof.day < start_d.day:
        made -= 1
    made = max(0, made)
    bal = principal
    for _ in range(made):
        if bal <= 0:
            break
        bal = max(0.0, bal + bal * r - payment)
    return round(bal, 2), made


def reconcile_parent(accounts: list[Account]) -> list[Account]:
    """Carve loan principal out of the parent card it was drawn against.

    The parent's YNAB balance already contains the loan, so counting both would
    inflate total debt. Subtracting is the normal path. The exception is real and
    worth surfacing: a balance transfer off the parent line can drop the account
    below the loan's contractual schedule, at which point the two numbers
    genuinely disagree and guessing which is right would be inventing data. In
    that case the loan is clamped to what the account actually holds and both
    figures are recorded in notes, so the total still ties to YNAB and the
    discrepancy stays visible instead of being smoothed away.
    """
    by_name = {a.name: a for a in accounts}
    for acct in accounts:
        if acct.kind != "loan" or not acct.parent:
            continue
        parent = by_name.get(acct.parent)
        if parent is None:
            acct.notes.append(f"parent card '{acct.parent}' not found; counted standalone")
            continue
        revolving = round(parent.balance - acct.balance, 2)
        if revolving < 0:
            acct.notes.append(
                f"contractual schedule says ${acct.balance:,.2f} but {parent.name} "
                f"only holds ${parent.balance:,.2f} — clamped to the account balance"
            )
            parent.notes.append(
                f"fully accounted for by {acct.name}; no revolving balance detected"
            )
            acct.balance = parent.balance
            parent.balance = 0.0
        else:
            parent.notes.append(f"excludes ${acct.balance:,.2f} carried as {acct.name}")
            parent.balance = revolving
    return accounts


def _priority(accounts: list[Account], balances: dict[str, float],
              strategy: str | list[str], on: date) -> list[str]:
    """Order the accounts that still owe money, best target for extra cash first.

    `strategy` is "avalanche" or an explicit list of account names — the latter
    is how a hand-picked payoff order gets compared against the textbook one.
    Names the list omits fall to the back in avalanche order, so a partial
    ordering is still a valid one. Snowball was removed 2026-09-03: on Sam's
    cards it only ever cost more, and the toggle was one more thing to read.
    """
    live = [a for a in accounts if balances[a.name] > 0.005]
    if isinstance(strategy, list):
        rank = {n: i for i, n in enumerate(strategy)}
        live.sort(key=lambda a: (rank.get(a.name, len(rank)),
                                 -monthly_rate(a, on), a.name))
    else:  # avalanche — highest rate charged right now
        # Rate alone cannot separate two cards both sitting at 0%, and the
        # balance tie-break that used to decide it is arbitrary: it sent Sam's
        # December cash to the Citi (0% until 2028, but the larger balance) while
        # the Discover's 0% window shut on 12/25. Among equal current rates the
        # urgent card is the one whose cheap window closes first; only then does
        # size matter.
        live.sort(key=lambda a: (-monthly_rate(a, on), a.promo_end or "9999-12-31",
                                 -balances[a.name], a.name))
    return [a.name for a in live]


def _accrue_interest(accounts: list[Account], balances: dict, interest_paid: dict,
                     first_interest: dict, on: date, month: int) -> dict:
    accrued = {}
    for a in accounts:
        bal = balances[a.name]
        if bal <= 0.005:
            accrued[a.name] = 0.0
            continue
        i = round(bal * monthly_rate(a, on), 2)
        accrued[a.name] = i
        balances[a.name] = bal + i
        interest_paid[a.name] += i
        if month == 0:
            first_interest[a.name] = i
    return accrued


def _pay_minimums(accounts: list[Account], balances: dict, accrued: dict, due: dict,
                  principal_paid: dict, payoff_frac: dict, need: dict, extra: float) -> None:
    """Minimums are non-negotiable; they come out before any strategy runs."""
    for a in accounts:
        paid = due[a.name]
        balances[a.name] = round(balances[a.name] - paid, 2)
        principal_paid[a.name] += paid - accrued[a.name]
        if paid and balances[a.name] <= 0.005 and a.name not in payoff_frac:
            payoff_frac[a.name] = need[a.name] / (need[a.name] + extra)


def _promo_cycles(acct: Account, on: date) -> int:
    """Payments that can still land at the promo rate, counting the cycle starting `on`.

    The cliff month counts only if the due day falls before the cliff day; a
    payment due the 28th against a window that shuts the 25th lands too late.
    """
    end = date.fromisoformat(acct.promo_end or "0001-01-01")
    n = (end.year - on.year) * 12 + (end.month - on.month) + 1
    if acct.due_day and acct.due_day > end.day:
        n -= 1
    return max(0, n)


def _pace_cliff(accounts: list[Account], balances: dict, principal_paid: dict,
                payoff_frac: dict, need: dict, on: date, extra: float,
                spend: float) -> tuple[float, float]:
    """Pay the soonest-closing 0% card on pace to clear before its rate flips.

    Sam's rule (2026-11-03): beating the Discover's December cliff comes
    before every rate, and only what the cliff does not need cascades onward.
    The pace is remaining balance over payments left, so the card is cleared
    exactly at the last cycle and nothing more than necessary is tied up early.
    """
    live = [a for a in accounts if a.promo_end and a.promo_apr is not None
            and balances[a.name] > 0.005 and _promo_cycles(a, on) > 0]
    if not live or extra <= 0:
        return extra, spend
    c = min(live, key=lambda a: a.promo_end or "")
    bal = balances[c.name]
    pay = min(extra, bal, math.ceil(bal / _promo_cycles(c, on) * 100) / 100)
    balances[c.name] = round(bal - pay, 2)
    principal_paid[c.name] += pay
    extra -= pay
    if balances[c.name] <= 0.005:
        payoff_frac[c.name] = need[c.name] / (need[c.name] + extra)
    return extra, spend + pay


def _cascade_extra(accounts: list[Account], balances: dict, principal_paid: dict,
                   payoff_frac: dict, need: dict, strategy: str | list[str], on: date,
                   extra: float, spend: float) -> tuple[float, float]:
    """Whatever is left over cascades down the priority order."""
    if extra <= 0:
        return extra, spend
    for name in _priority(accounts, balances, strategy, on):
        if extra <= 0.005:
            break
        pay = min(extra, balances[name])
        balances[name] = round(balances[name] - pay, 2)
        principal_paid[name] += pay
        spend += pay
        extra -= pay
        if balances[name] <= 0.005:
            payoff_frac[name] = need[name] / (need[name] + extra)
    return extra, spend


def _record_payoffs(accounts: list[Account], balances: dict, payoff: dict, on: date) -> None:
    for a in accounts:
        if payoff[a.name] is None and balances[a.name] <= 0.005:
            payoff[a.name] = on.isoformat()


def _build_card_rows(accounts: list[Account], start: date, payoff: dict, payoff_frac: dict,
                     interest_paid: dict, first_interest: dict) -> list[dict]:
    cards = []
    for a in accounts:
        bal = float(a.balance)
        cards.append({
            "name": a.name,
            "kind": a.kind,
            "balance": round(bal, 2),
            "apr": a.apr,
            "current_apr": round(monthly_rate(a, start) * 12 * 100, 2),
            "promo_apr": a.promo_apr,
            "promo_end": a.promo_end,
            "credit_limit": a.credit_limit,
            "utilization": round(bal / a.credit_limit * 100, 1) if a.credit_limit else None,
            "due_day": a.due_day,
            "parent": a.parent,
            "min_payment": round(minimum_due(a, bal, bal * monthly_rate(a, start)), 2),
            "monthly_interest": first_interest.get(a.name, 0.0),
            "total_interest": round(interest_paid[a.name], 2),
            "payoff_date": payoff[a.name],
            "months_to_payoff": _months_between(start, payoff[a.name]),
            "payoff_frac": round(payoff_frac[a.name], 4) if a.name in payoff_frac else None,
            "never_pays_off": payoff[a.name] is None and bal > 0.005,
            "promo_monthly_needed": _promo_needed(a, start),
            "notes": a.notes,
        })
    return cards


def _payoff_summary(cards: list[dict]) -> tuple[str, list[dict]]:
    """Last card(s) to clear, and the date they cleared on."""
    all_done = max((c["payoff_date"] or "" for c in cards), default="")
    last = [c for c in cards if all_done and c["payoff_date"] == all_done]
    return all_done, last


def _totals_summary(start: date, cards: list[dict], total_debt: float, month_one: float,
                    total_interest: float, weighted: float, all_done: str,
                    last: list[dict]) -> dict:
    return {
        "debt": total_debt,
        "monthly_interest": month_one,
        "annual_interest_at_current_rates": round(month_one * 12, 2),
        "blended_apr": round(weighted / total_debt, 2) if total_debt else 0.0,
        "total_interest": total_interest,
        "debt_free": all_done or None,
        "months": _months_between(start, all_done) if all_done else None,
        "debt_free_frac": max(c["payoff_frac"] or 1.0 for c in last) if last else None,
    }


def project(accounts: list[Account], monthly_budget: float | None = None,
            strategy: str | list[str] = "avalanche", start: date | None = None,
            horizon: int = MAX_MONTHS) -> dict:
    """Simulate every account forward until paid off or the horizon runs out.

    `monthly_budget` is total dollars available per month across all debt. None,
    or anything below the summed minimums, means minimums-only — the budget is
    never allowed to underfund a minimum, since skipping one is a fee and a rate
    hike, not a saving. Anything above goes to `strategy`'s first target and
    cascades as accounts die.
    """
    start = _month_start(start or date.today())
    balances = {a.name: float(a.balance) for a in accounts}
    interest_paid = {a.name: 0.0 for a in accounts}
    principal_paid = {a.name: 0.0 for a in accounts}
    payoff: dict[str, str | None] = {a.name: None for a in accounts}
    # How far into its payoff month a card reached: what it still needed over
    # what the month had for it. Whole months are too coarse for the chart —
    # a $50 change rarely crosses a month boundary, so bars sat still and then
    # jumped a full column. With this the bar end moves with every dollar.
    payoff_frac: dict[str, float] = {}
    first_interest: dict[str, float] = {}
    timeline = []

    on = start
    for month in range(horizon):
        if all(b <= 0.005 for b in balances.values()):
            break

        accrued = _accrue_interest(accounts, balances, interest_paid, first_interest, on, month)
        need = dict(balances)   # owed this month, interest included

        due = {a.name: minimum_due(a, balances[a.name], accrued[a.name]) for a in accounts}
        spend = sum(due.values())
        extra = max(0.0, (monthly_budget or 0.0) - spend)
        _pay_minimums(accounts, balances, accrued, due, principal_paid, payoff_frac, need, extra)
        extra, spend = _pace_cliff(accounts, balances, principal_paid, payoff_frac, need,
                                   on, extra, spend)
        extra, spend = _cascade_extra(accounts, balances, principal_paid, payoff_frac, need,
                                      strategy, on, extra, spend)
        _record_payoffs(accounts, balances, payoff, on)

        timeline.append({
            "month": on.isoformat(),
            "total": round(sum(max(0.0, b) for b in balances.values()), 2),
            "interest": round(sum(accrued.values()), 2),
            "paid": round(spend, 2),
            "by_card": {n: round(max(0.0, b), 2) for n, b in balances.items()},
        })
        on = _add_month(on)

    total_debt = round(sum(float(a.balance) for a in accounts), 2)
    total_interest = round(sum(interest_paid.values()), 2)
    month_one = round(sum(first_interest.values()), 2)
    # Blended APR is balance-weighted on the CURRENT rate, so a card sitting in a
    # 0% window correctly drags the average down while the promo lasts.
    weighted = sum(float(a.balance) * monthly_rate(a, start) * 12 * 100 for a in accounts)

    cards = _build_card_rows(accounts, start, payoff, payoff_frac, interest_paid, first_interest)
    all_done, last = _payoff_summary(cards)

    return {
        "strategy": strategy,
        "monthly_budget": round(monthly_budget, 2) if monthly_budget else None,
        "minimums_total": round(
            sum(minimum_due(a, float(a.balance), float(a.balance) * monthly_rate(a, start))
                for a in accounts), 2),
        "totals": _totals_summary(start, cards, total_debt, month_one, total_interest,
                                  weighted, all_done, last),
        "cards": cards,
        "timeline": timeline,
    }


def _months_between(start: date, iso: str | None) -> int | None:
    if not iso:
        return None
    d = date.fromisoformat(iso)
    return (d.year - start.year) * 12 + (d.month - start.month) + 1


def _promo_needed(acct: Account, start: date) -> float | None:
    """Monthly payment that clears the balance before a 0% window shuts.

    This is the number that matters for a promo card and the one an avalanche
    ordering will never surface: at 0% the card ranks last for extra cash right
    up until the cliff flips it to the highest rate on the books.
    """
    if not acct.promo_end or acct.promo_apr is None or acct.balance <= 0:
        return None
    months = _promo_cycles(acct, start)
    if months <= 0:
        return None
    return round(acct.balance / months, 2)


def compare(accounts_factory, budgets: list[float],
            strategy: str | list[str] = "avalanche",
            start: date | None = None) -> list[dict]:
    """Run the projection at several monthly budgets to show the trajectory shift.

    Takes a factory rather than a list because project() consumes the accounts it
    is given; each scenario needs its own copies.
    """
    out = []
    for b in budgets:
        r = project(accounts_factory(), b, strategy, start)
        out.append({
            "monthly_budget": b,
            "debt_free": r["totals"]["debt_free"],
            "months": r["totals"]["months"],
            "total_interest": r["totals"]["total_interest"],
        })
    return out


def _self_check() -> None:
    """Assert the engine's load-bearing behaviours. Run: python3 debt.py"""
    today = date(2026, 7, 1)

    # A 0% card accrues nothing while the promo holds, and reverts after.
    promo = Account("promo", 1200.0, apr=27.0, promo_apr=0.0, promo_end="2026-12-25")
    assert monthly_rate(promo, date(2026, 8, 1)) == 0.0
    assert round(monthly_rate(promo, date(2027, 1, 1)) * 12 * 100, 2) == 27.0

    # Paying exactly the promo-needed amount clears it before the cliff.
    need = _promo_needed(promo, today)
    assert need == round(1200 / 6, 2), need   # Jul..Dec: the Dec cycle bills at 0%
    r = project([Account("promo", 1200.0, apr=27.0, promo_apr=0.0, promo_end="2026-12-25")],
                monthly_budget=need, start=today)
    assert r["cards"][0]["payoff_date"] <= "2026-12-01", r["cards"][0]
    assert r["totals"]["total_interest"] == 0.0, r["totals"]

    # A loan amortizes down and lands on zero at the end of its term.
    bal, made = loan_balance(4261.0, 10.99, 198.48, "2026-06-15", date(2026, 7, 27))
    assert made == 1, made
    assert 4090 < bal < 4110, bal
    done, _ = loan_balance(4261.0, 10.99, 198.48, "2026-06-15", date(2028, 7, 15))
    assert done == 0.0, done

    # Loan principal is carved out of its parent, never added on top.
    accts = reconcile_parent([
        Account("Card", 3000.0, apr=27.49),
        Account("Loan", 1000.0, apr=10.99, kind="loan", parent="Card", fixed_payment=100.0),
    ])
    assert {a.name: a.balance for a in accts} == {"Card": 2000.0, "Loan": 1000.0}

    # When the schedule exceeds the account, the total still ties to the account.
    accts = reconcile_parent([
        Account("Card", 800.0, apr=27.49),
        Account("Loan", 1000.0, apr=10.99, kind="loan", parent="Card", fixed_payment=100.0),
    ])
    assert sum(a.balance for a in accts) == 800.0
    assert any(a.notes for a in accts)

    # More money per month = sooner and cheaper. This is the whole trajectory claim.
    def factory():
        return [Account("A", 3000.0, apr=26.24), Account("B", 2000.0, apr=10.99)]

    low, high = compare(factory, [300.0, 900.0], start=today)
    assert high["months"] < low["months"], (low, high)
    assert high["total_interest"] < low["total_interest"], (low, high)

    # Avalanche kills the expensive card first.
    def mixed():
        return [Account("big-cheap", 5000.0, apr=5.0), Account("small-dear", 900.0, apr=29.0)]

    av = project(mixed(), 600.0, "avalanche", today)
    by = {c["name"]: c["payoff_date"] for c in av["cards"]}
    assert by["small-dear"] < by["big-cheap"], by

    # The fractional payoff moves with every dollar: month + fraction never rises
    # as the budget rises, and it steps by less than a whole month at a time.
    def when(r, name):
        c = next(c for c in r["cards"] if c["name"] == name)
        return c["months_to_payoff"] - 1 + c["payoff_frac"]
    ends = [when(project(mixed(), b, start=today), "big-cheap") for b in range(600, 1500, 25)]
    assert all(0 < e for e in ends) and ends == sorted(ends, reverse=True), ends
    assert max(a - b for a, b in zip(ends, ends[1:], strict=False)) < 1.0, ends
    assert 0 < av["totals"]["debt_free_frac"] <= 1.0, av["totals"]

    # Two cards at 0%: the money goes to the one whose window shuts first, not
    # the bigger one. This is the December-cliff case, and it is the whole reason
    # promo_end is in the sort key.
    soon = Account("soon", 1000.0, apr=27.0, promo_apr=0.0, promo_end="2026-12-25")
    late = Account("late", 3000.0, apr=29.0, promo_apr=0.0, promo_end="2028-03-18")
    order = _priority([soon, late], {"soon": 1000.0, "late": 3000.0}, "avalanche", today)
    assert order == ["soon", "late"], order

    # The cliff card is paced to clear before it flips even with a 26% card on the
    # books; avalanche alone sends Nov's cash to the 26% card and misses the cliff.
    nov = date(2026, 11, 1)
    def cliff_case(due):
        return [Account("soon", 1000.0, apr=27.0, promo_apr=0.0, promo_end="2026-12-25", due_day=due),
                Account("dear", 300.0, apr=26.0)]
    paced = {c["name"]: c for c in project(cliff_case(22), 600.0, start=nov)["cards"]}
    assert paced["soon"]["payoff_date"] == "2026-12-01", paced["soon"]
    assert paced["soon"]["total_interest"] == 0.0, paced["soon"]
    # Due the 28th, the December payment lands after the flip: one cycle left.
    assert _promo_cycles(cliff_case(28)[0], nov) == 1
    assert _promo_cycles(cliff_case(22)[0], nov) == 2

    # An explicit order is honoured, and costs at least what avalanche costs.
    hand = project(mixed(), 600.0, ["big-cheap", "small-dear"], today)
    by = {c["name"]: c["payoff_date"] for c in hand["cards"]}
    assert by["big-cheap"] < by["small-dear"], by
    assert hand["totals"]["total_interest"] >= av["totals"]["total_interest"]

    # Minimums are funded even when the budget is short — never skip one.
    tight = project([Account("A", 3000.0, apr=26.24)], monthly_budget=1.0, start=today)
    assert tight["timeline"][0]["paid"] >= MIN_FLOOR

    # A payment that cannot cover interest is reported, not looped forever.
    stuck = project([Account("A", 100000.0, apr=29.0, min_payment=1.0)],
                    monthly_budget=1.0, start=today, horizon=24)
    assert stuck["cards"][0]["never_pays_off"] is True

    # Balance-weighted blended APR: a 0% half drags the average to half the rate.
    blend = project([Account("z", 1000.0, apr=0.0), Account("y", 1000.0, apr=20.0)],
                    start=today)
    assert blend["totals"]["blended_apr"] == 10.0, blend["totals"]

    print("debt.py self-check passed")


if __name__ == "__main__":
    _self_check()

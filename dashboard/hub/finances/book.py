# vault-code/dashboard/hub/finances/book.py
"""The local transaction book (data/book.db), behind dashboard/ynab.py's public surface.

Same function names, arguments, return shapes and units as ynab.py, so callers
change only their import line. Money is INTEGER cents in the DB; each function
converts to the unit its ynab.py namesake returned (dollar floats for spend,
balances and payments; signed milliunits for fetch_unreviewed amounts and
split input). Ids passed in and out are txn `uid` strings. `budget_id` is
accepted and ignored.
"""

from __future__ import annotations

import calendar
import logging
import re
import sqlite3
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from itertools import combinations
from pathlib import Path

from sqlite_helpers import connect as sqlite_connect

logger = logging.getLogger(__name__)

# The importer files the opening-balance row under this YNAB category; it is a
# balance being declared, not a purchase.
READY_TO_ASSIGN = "Inflow: Ready to Assign"

# Bank wording for a payment to a credit card: "PAYMENT TO CHASE CARD ENDING IN 0000",
# "CITI CARD ONLINE PAYMENT", "DISCOVER E-PAYMENT". Venmo / Zelle payments do not match.
_CARD_PAYMENT = re.compile(r"payment to \w+ card|card (?:online )?payment|\be-?payment\b|autopay", re.I)

# Payees that look recurring but aren't subscriptions
_NOISE = re.compile(
    r"\b(mta|mbta|metro|subway|lirr|amtrak|lyft|uber|taxi|"
    r"affirm|klarna|afterpay|sezzle|"
    r"united|delta|american airlines|southwest|jetblue|spirit)\b"
    r"|transfer\s*:",
    re.IGNORECASE,
)

# How far above a hold a posted charge may settle and still be read as the same
# bill plus gratuity. 35% covers a 20-25% tip with tax rounding; past that the
# charge is more likely a different visit than a generous one.
TIP_MAX_RATIO = 1.35

_db_path: Path | None = None


def init(db_path: Path | str | None = None) -> None:
    """Point the module at a book. Default: <vault>/data/book.db."""
    global _db_path
    if db_path is None:
        from vault_path import vault_root
        db_path = vault_root() / "data" / "book.db"
    _db_path = Path(db_path)


def _path() -> Path:
    if _db_path is None:
        init()
    assert _db_path is not None  # init() just set it
    return _db_path


def _conn():
    return sqlite_connect(_path(), "book.db")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def is_configured() -> bool:
    """book.db exists and has at least one account."""
    try:
        if not _path().exists():
            return False
        with _conn() as c:
            return c.execute("SELECT 1 FROM account LIMIT 1").fetchone() is not None
    except Exception:
        logger.exception("is_configured failed")
        return False


# --- loading ----------------------------------------------------------------

_TXN_SQL = """
SELECT t.id AS rid, t.uid, t.account_id, a.name AS account_name, t.date,
       t.amount_cents, t.payee_id,
       COALESCE(p.name, NULLIF(t.raw_description, ''), '') AS payee_name,
       t.category_id, c.name AS category_name, t.memo, t.approved, t.cleared,
       t.pending, ta.name AS transfer_account_name,
       t.suggested_category_id, sc.name AS suggested_category_name,
       t.suggested_confidence
FROM txn t
JOIN account a ON a.id = t.account_id
LEFT JOIN payee p ON p.id = t.payee_id
LEFT JOIN category c ON c.id = t.category_id
LEFT JOIN category sc ON sc.id = t.suggested_category_id
LEFT JOIN account ta ON ta.id = t.transfer_account_id
WHERE t.deleted = 0 AND t.date >= ?
ORDER BY t.date, t.id
"""

_SPLIT_SQL = """
SELECT s.txn_id, s.ord, s.amount_cents, s.category_id, c.name AS category_name,
       s.memo, s.payee_id, p.name AS payee_name
FROM split s
JOIN txn t ON t.id = s.txn_id
LEFT JOIN category c ON c.id = s.category_id
LEFT JOIN payee p ON p.id = s.payee_id
WHERE t.deleted = 0 AND t.date >= ?
ORDER BY s.txn_id, s.ord
"""


def _load(since: str) -> list[dict]:
    """Live rows on or after `since`, in ynab.py's transaction-dict shape.

    `id` is the uid, `amount` is signed milliunits (cents * 10) so the hold
    matcher and tally logic moved over from ynab.py run unchanged, `cleared` is
    "cleared"/"uncleared", `transfer_account_id` is the other account's name
    (None when not a transfer), `subtransactions` is [] for an unsplit row.
    """
    with _conn() as c:
        rows = c.execute(_TXN_SQL, (since,)).fetchall()
        legs = defaultdict(list)
        for s in c.execute(_SPLIT_SQL, (since,)):
            legs[s["txn_id"]].append(s)
    out = []
    for r in rows:
        subs = [
            {
                "id": f"{r['uid']}#{s['ord']}",
                "amount": s["amount_cents"] * 10,
                "category_id": str(s["category_id"]) if s["category_id"] else None,
                "category_name": s["category_name"],
                "memo": s["memo"],
                "payee_name": s["payee_name"],
            }
            for s in legs.get(r["rid"], [])
        ]
        out.append(
            {
                "id": r["uid"],
                "account_id": r["account_id"],
                "account_name": r["account_name"],
                "date": r["date"],
                "amount": r["amount_cents"] * 10,
                "payee_id": r["payee_id"],
                "payee_name": r["payee_name"],
                "category_id": r["category_id"],
                # YNAB names an uncategorized non-transfer row "Uncategorized"; keep that label
                "category_name": r["category_name"] or (
                    None if subs or r["transfer_account_name"] else "Uncategorized"),
                "memo": r["memo"],
                "approved": bool(r["approved"]),
                "cleared": "cleared" if r["cleared"] else "uncleared",
                "pending": bool(r["pending"]),
                "transfer_account_id": r["transfer_account_name"],
                "subtransactions": subs,
                "suggested_category_id": r["suggested_category_id"],
                "suggested_category_name": r["suggested_category_name"],
                "suggested_confidence": r["suggested_confidence"],
                "deleted": False,
            }
        )
    return out


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


# --- subscriptions ----------------------------------------------------------

_MON = ["jan", "feb", "mar", "apr", "may", "jun",
        "jul", "aug", "sep", "oct", "nov", "dec"]


def _next_month(d: date) -> date:
    """Advance d by one calendar month, clamping to the last day if needed."""
    m = d.month % 12 + 1
    y = d.year + (1 if d.month == 12 else 0)
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def _is_monthly(dates: list[str]) -> bool:
    """True if dates are approximately 25-45 days apart on average."""
    parsed = sorted(datetime.strptime(d, "%Y-%m-%d") for d in dates)
    gaps = [(parsed[i + 1] - parsed[i]).days for i in range(len(parsed) - 1)]
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        return False
    return 25 <= (sum(gaps) / len(gaps)) <= 45


def fetch_subscriptions(
    budget_id: str = "last-used", lookback_days: int = 90
) -> list[dict]:
    """Detect recurring monthly subscriptions from the book's recent outflows.

    Groups by payee + whole-dollar amount, keeps groups with 2+ occurrences and a
    ~monthly cadence, drops transit, rideshare, BNPL, airline and interest noise.
    Returns [{name, cycle, amt, next_billing}].
    """
    try:
        txns = _load(_days_ago(lookback_days))
        groups: dict[tuple, list[tuple[str, float]]] = defaultdict(list)
        for t in txns:
            if t["amount"] >= 0:
                continue
            payee = (t.get("payee_name") or "").strip()
            if not payee or _NOISE.search(payee):
                continue
            if (t.get("category_name") or "").strip().lower() == "interest":
                continue
            exact = round(abs(t["amount"]) / 1000.0, 2)
            bucket = round(exact)
            if bucket < 1:
                continue
            groups[(payee, bucket)].append((t["date"], exact))

        subs = []
        for (payee, _), entries in groups.items():
            dates = [d for d, _ in entries]
            if len(dates) >= 2 and _is_monthly(dates):
                last_date, last_amt = max(entries, key=lambda e: e[0])
                nxt = _next_month(datetime.strptime(last_date, "%Y-%m-%d").date())
                subs.append(
                    {
                        "name": payee,
                        "cycle": "monthly",
                        "amt": f"${last_amt:.2f}",
                        "next_billing": f"{_MON[nxt.month - 1]} {nxt.day}",
                    }
                )
        subs.sort(key=lambda s: -float(s["amt"].lstrip("$")))
        return subs
    except Exception:
        logger.exception("fetch_subscriptions failed")
        return []


# --- reads ------------------------------------------------------------------


def fetch_transactions(
    budget_id: str = "last-used",
    since_date: str | None = None,
) -> list[dict]:
    """Recent outflow transactions for the memo link UI.

    Each dict: {id, date, payee, amount_str, memo, cleared}.
    """
    if since_date is None:
        since_date = _days_ago(30)
    try:
        results = [
            {
                "id": t["id"],
                "date": t["date"],
                "payee": (t.get("payee_name") or "").strip(),
                "amount_str": f"${abs(t['amount']) / 1000.0:.2f}",
                "memo": t.get("memo") or "",
                "cleared": t.get("cleared") == "cleared",
            }
            for t in _load(since_date)
            if t["amount"] < 0
        ]
        results.sort(key=lambda x: x["date"], reverse=True)
        return results
    except Exception:
        logger.exception("fetch_transactions failed since_date=%s", since_date)
        return []


def fetch_spend(
    since_date: str | None = None,
    budget_id: str = "last-used",
) -> list[dict]:
    """Every non-transfer outflow across all accounts, oldest first.

    Splits are expanded into their legs (a split parent carries no usable
    category). Transfers, inflows and the Ready to Assign opening balance are
    dropped.

    Each dict: {id, date, category, amount, payee}. `amount` is positive dollars.
    """
    if since_date is None:
        since_date = _days_ago(180)
    try:
        out = []
        for t in _load(since_date):
            payee = (t.get("payee_name") or "").strip()
            for leg in (t["subtransactions"] or [t]):
                if leg is t and t.get("transfer_account_id"):
                    continue
                if leg["amount"] >= 0:
                    continue
                if (leg.get("category_name") or "").strip() == READY_TO_ASSIGN:
                    continue
                # A card payment is not spend. The sync links it as a transfer once the
                # checking side posts; until then (a scheduled payment sits pending for
                # days) it read as uncategorized spend (mark 2026-11-03 "credit card
                # payments dont count").
                if leg is t and not t.get("category_id") and _CARD_PAYMENT.search(payee):
                    continue
                out.append(
                    {
                        "id": leg["id"],
                        "date": t["date"],
                        "category": (leg.get("category_name") or "").strip(),
                        "amount": round(abs(leg["amount"]) / 1000.0, 2),
                        "payee": (leg.get("payee_name") or "").strip() or payee,
                    }
                )
        out.sort(key=lambda x: x["date"])
        return out
    except Exception:
        logger.exception("fetch_spend failed since_date=%s", since_date)
        return []


def card_payments(lo: str, hi: str) -> float:
    """Dollars paid onto credit cards between lo and hi (inclusive), the money
    fetch_spend leaves out. Shown beside the spend totals so a YTD figure is not
    read as including them (mark 2026-11-03 "most of it was credit card payments")."""
    with _conn() as c:
        r = c.execute(
            "SELECT COALESCE(SUM(t.amount_cents), 0) FROM txn t JOIN account a ON a.id = t.account_id "
            "WHERE t.deleted = 0 AND a.type = 'credit' AND t.transfer_account_id IS NOT NULL "
            "AND t.amount_cents > 0 AND t.date >= ? AND t.date <= ?", (lo, hi)).fetchone()
    return round(r[0] / 100.0, 2)


def fetch_categories(budget_id: str = "last-used") -> list[dict]:
    """Assignable categories flattened across groups.

    Skips hidden categories, hidden groups and "Internal Master Category".
    Each dict: {id, name, group_name, full_name}.
    """
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT c.id, c.name, g.name AS gname FROM category c "
                "JOIN category_group g ON g.id = c.group_id "
                "WHERE c.hidden = 0 AND g.hidden = 0 "
                "AND g.name != 'Internal Master Category' ORDER BY g.id, c.id"
            ).fetchall()
        cats = []
        for r in rows:
            name, gname = r["name"].strip(), r["gname"].strip()
            cats.append(
                {
                    "id": str(r["id"]),
                    "name": name,
                    "group_name": gname,
                    "full_name": f"{gname}: {name}" if gname else name,
                }
            )
        return cats
    except Exception:
        logger.exception("fetch_categories failed")
        return []


def fetch_category_groups(budget_id: str = "last-used") -> list[dict]:
    """Category groups: [{id, name, hidden}]. Includes the internal group."""
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT id, name, hidden FROM category_group ORDER BY id"
            ).fetchall()
        return [
            {"id": str(r["id"]), "name": r["name"].strip(), "hidden": bool(r["hidden"])}
            for r in rows
        ]
    except Exception:
        logger.exception("fetch_category_groups failed")
        return []


# An account's balance in cents: the recorded one, else the sum of its live rows.
BALANCE_SQL = ("COALESCE(a.balance_cents, (SELECT COALESCE(SUM(amount_cents), 0) "
               "FROM txn WHERE account_id = a.id AND deleted = 0))")


def _open_cards() -> list[sqlite3.Row]:
    """Open credit accounts with their balance in cents (YNAB sign: owing is negative).

    Falls back to the sum of live rows when no balance has been recorded yet.
    """
    with _conn() as c:
        return c.execute(
            f"SELECT a.id, a.name, {BALANCE_SQL} AS bal "  # noqa: S608 - BALANCE_SQL is a module constant
            "FROM account a WHERE a.type = 'credit' AND a.closed = 0 ORDER BY a.id"
        ).fetchall()


def fetch_credit_cards(budget_id: str = "last-used") -> list[dict]:
    """Open credit card accounts as [{name, last4, due, amt, status}]."""
    try:
        cards = []
        for r in _open_cards():
            balance = r["bal"] / 100.0
            cards.append(
                {
                    "name": r["name"],
                    "last4": "",  # cards.enrich() fills it from data/cards.db
                    "due": "",
                    "amt": f"${abs(balance):.2f}",
                    "status": "due" if balance < 0 else "ok",  # YNAB sign: owing is negative
                }
            )
        return cards
    except Exception:
        logger.exception("fetch_credit_cards failed")
        return []


def last_sync_at() -> int | None:
    """Epoch ms of the last SimpleFIN sync that reached the bank, or None."""
    with _conn() as c:
        r = c.execute("SELECT at FROM sync_run WHERE status IN ('ok','partial') "
                      "ORDER BY id DESC LIMIT 1").fetchone()
    return int(datetime.fromisoformat(r["at"]).timestamp() * 1000) if r else None


def fetch_card_balances(budget_id: str = "last-used") -> dict[str, float]:
    """{card account name: amount owed} as positive floats; an overpaid card is negative."""
    try:
        return {r["name"]: -r["bal"] / 100.0 for r in _open_cards()}
    except Exception:
        logger.exception("fetch_card_balances failed")
        return {}


def fetch_card_payments(
    since_date: str | None = None,
    budget_id: str = "last-used",
) -> list[dict]:
    """Inflows to open credit cards, newest first, classified by `kind`.

    payment (funded from a cash account), balance_transfer (funded from another
    card, total debt unchanged) or credit (refund or reversal, no funding account).

    Each dict: {id, date, card, amount, payee, memo, kind, source}.
    """
    if since_date is None:
        since_date = _days_ago(180)
    try:
        cards = {r["name"] for r in _open_cards()}
        out = []
        for t in _load(since_date):
            if t["account_name"] not in cards or t["amount"] <= 0:
                continue
            src = t.get("transfer_account_id")
            out.append(
                {
                    "id": t["id"],
                    "date": t["date"],
                    "card": t["account_name"],
                    "amount": round(t["amount"] / 1000.0, 2),
                    "payee": (t.get("payee_name") or "").strip(),
                    "memo": t.get("memo") or "",
                    "kind": "credit" if not src
                    else "balance_transfer" if src in cards
                    else "payment",
                    "source": src or "",
                }
            )
        out.sort(key=lambda x: x["date"], reverse=True)
        return out
    except Exception:
        logger.exception("fetch_card_payments failed since_date=%s", since_date)
        return []


def is_pending_hold(txn: dict) -> bool:
    """True if this row is a pending card authorization, not a posted charge."""
    return bool(txn.get("pending"))


def fetch_unreviewed(
    budget_id: str = "last-used",
    since_date: str | None = None,
) -> list[dict]:
    """Rows that need attention: unapproved OR uncategorized OR memo-blank.

    Transfers are excluded. Pending rows are included, flagged `pending`, but
    never ask for approval. A split row counts as categorized. Both inflow and
    outflow surface; `direction` distinguishes them.

    Each dict: {id, date, payee, payee_id, amount, amount_str, direction,
    memo, category_id, category_name, suggested_category_id,
    suggested_category_name, suggested_confidence, approved, pending, needs}.
    `amount` is signed milliunits.
    """
    if since_date is None:
        since_date = _days_ago(90)
    try:
        results = []
        for t in _load(since_date):
            if t.get("transfer_account_id"):
                continue
            pending = is_pending_hold(t)
            split = bool(t["subtransactions"])
            needs = []
            if not t["approved"] and not pending:
                needs.append("approval")
            if not t["category_id"] and not split:
                needs.append("category")
            if not (t["memo"] or "").strip():
                needs.append("memo")
            if not needs:
                continue
            amount = t["amount"]
            results.append(
                {
                    "id": t["id"],
                    "date": t["date"],
                    "payee": (t.get("payee_name") or "").strip(),
                    "payee_id": str(t["payee_id"]) if t["payee_id"] else None,
                    "amount": amount,
                    "amount_str": f"${abs(amount) / 1000.0:.2f}",
                    "direction": "inflow" if amount >= 0 else "outflow",
                    "memo": t["memo"] or "",
                    "category_id": str(t["category_id"]) if t["category_id"] else None,
                    "category_name": t["category_name"],
                    "suggested_category_id": (
                        str(t["suggested_category_id"]) if t["suggested_category_id"] else None),
                    "suggested_category_name": t["suggested_category_name"],
                    "suggested_confidence": t["suggested_confidence"],
                    "approved": t["approved"],
                    "pending": pending,
                    "needs": needs,
                }
            )
        results.sort(key=lambda x: x["date"], reverse=True)
        return results
    except Exception:
        logger.exception("fetch_unreviewed failed since_date=%s", since_date)
        return []


# --- hold matching and payee history ----------------------------------------


def find_superseded_holds(
    budget_id: str = "last-used",
    since_date: str | None = None,
) -> list[dict]:
    """Pending holds whose posted charge has already landed, i.e. duplicates.

    Two passes, in order. **Exact** first: some subset of same-account holds sums
    exactly to a posted charge within the following two weeks. Then **tip**, over
    whatever the exact pass did not consume: a single hold that a charge exceeds
    by no more than TIP_MAX_RATIO (the gratuity case). The exact pass runs to
    completion first so a fuzzy tip match can never steal a hold an exact match
    needed. Each hold is consumed by at most one charge, charges oldest-first.
    A charge must be a bank-fed or YNAB-imported row, not a transfer.

    Each dict: {id, date, payee, amount_str, memo, covered_by, confidence}.
    ``confidence`` is ``"exact"`` or ``"tip"``; a tip match is inferred from a
    ratio, so callers must surface it as the weaker claim it is.
    """
    if since_date is None:
        since_date = _days_ago(120)
    try:
        with _conn() as c:
            pairs = _match_holds(c, since_date)
        out = [
            {
                "id": h["uid"],
                "date": h["date"],
                "payee": (h["payee_name"] or "").strip(),
                "amount_str": f"${abs(h['amount_cents']) / 100.0:.2f}",
                "memo": h["memo"] or "",
                "covered_by": f"{chg['date']} ${abs(chg['amount_cents']) / 100.0:.2f}",
                "confidence": conf,
            }
            for h, chg, conf in pairs
        ]
        out.sort(key=lambda x: x["date"])
        return out
    except Exception:
        logger.exception("find_superseded_holds failed")
        return []


# Holds, plus the rows that may settle one: bank-fed (simplefin_id, which an
# adopted YNAB row also carries) or YNAB-imported. Transfers and the local
# xfer: counterparts convert_to_transfer inserts are never a charge.
_MATCH_SQL = """
SELECT t.id AS rid, t.uid, t.account_id, t.date, t.amount_cents, t.payee_id, t.pending,
       t.category_id, t.memo, t.approved,
       COALESCE(p.name, NULLIF(t.raw_description, ''), '') AS payee_name
FROM txn t LEFT JOIN payee p ON p.id = t.payee_id
WHERE t.deleted = 0 AND t.date >= ? AND t.transfer_account_id IS NULL
  AND (t.pending = 1 OR t.simplefin_id IS NOT NULL OR t.source = 'ynab')
"""


def _match_holds(c: sqlite3.Connection, since: str,
                 charge_uids: set[str] | None = None) -> list[tuple[dict, dict, str]]:
    """(hold, charge, "exact"|"tip") for every superseded hold on or after `since`.

    `charge_uids` limits which posted rows may settle a hold (the sync passes
    the rows it just inserted). Rows are plain dicts of _MATCH_SQL columns.
    """
    rows = [dict(r) for r in c.execute(_MATCH_SQL, (since,))]
    holds = [r for r in rows if is_pending_hold(r)]
    charges = sorted((r for r in rows if not is_pending_hold(r)
                      and (charge_uids is None or r["uid"] in charge_uids)),
                     key=lambda r: r["date"])
    consumed: set[str] = set()
    pairs: list[tuple[dict, dict, str]] = []
    for chg in charges:
        pool = sorted(_candidate_holds(chg, holds, consumed), key=lambda h: h["date"])
        for h in _find_exact_combo(pool, chg) or ():
            consumed.add(h["uid"])
            pairs.append((h, chg, "exact"))
    # ponytail: ratio band, not a real tip model. If a wrong pairing ever
    # slips the confirm gate, narrow the band before adding tip heuristics.
    for chg in charges:
        best = _best_tip_match(chg, holds, consumed)
        if best:
            consumed.add(best["uid"])
            pairs.append((best, chg, "tip"))
    return pairs


def _candidate_holds(chg: dict, holds: list[dict], consumed: set[str]) -> list[dict]:
    """Unconsumed holds this charge could plausibly settle.

    Same account and same sign are required. Payee is compared only when both
    rows have a resolved payee_id: a bank description changes between pending
    and posted ("PENDING ..." prefixes), so descriptions are never compared.
    """
    return [
        h for h in holds
        if h["uid"] not in consumed
        and h["account_id"] == chg["account_id"]
        and h["amount_cents"] * chg["amount_cents"] > 0
        and (not h["payee_id"] or not chg["payee_id"] or h["payee_id"] == chg["payee_id"])
        # A hold carries the tap/auth date; the posted charge carries the
        # bank's post date, one to two days later (Chase CSV, 2026-09-03).
        # So a charge never predates its own hold. The old -1 tolerance
        # let yesterday's $3.00 MTA ride claim today's $3.00 hold.
        and 0 <= (date.fromisoformat(chg["date"]) - date.fromisoformat(h["date"])).days <= 14
    ]


_WORD = re.compile(r"[a-z]{3,}")
_BANK_WORDS = {"pending", "pos", "purchase", "debit", "card", "the", "payment", "recurring"}


def same_payee(a: dict, b: dict) -> bool:
    """Do two _MATCH_SQL rows name the same merchant? Equal payee_id when both
    have one, else a shared word of 3+ letters in their names (bank boilerplate
    like "PENDING" or "POS" ignored)."""
    if a["payee_id"] and b["payee_id"]:
        return a["payee_id"] == b["payee_id"]
    words = lambda r: set(_WORD.findall((r["payee_name"] or "").lower())) - _BANK_WORDS  # noqa: E731
    return bool(words(a) & words(b))


def _find_exact_combo(pool: list[dict], chg: dict) -> tuple | None:
    """The smallest subset (1-3 holds) of `pool` summing exactly to the charge.

    One hold may match on amount alone. Two or three must each name the
    charge's merchant: otherwise two $3.00 rides add up to any $6.00 coffee.
    """
    named = [h for h in pool if same_payee(h, chg)]
    for size in (1, 2, 3):
        for combo in combinations(pool if size == 1 else named, size):
            if sum(h["amount_cents"] for h in combo) == chg["amount_cents"]:
                return combo
    return None


def _best_tip_match(chg: dict, holds: list[dict], consumed: set[str]) -> dict | None:
    """The single hold the charge exceeds by the smallest ratio within TIP_MAX_RATIO."""
    best = None
    for h in _candidate_holds(chg, holds, consumed):
        ratio = abs(chg["amount_cents"]) / abs(h["amount_cents"])
        if 1.0 < ratio <= TIP_MAX_RATIO and (best is None or ratio < best[0]):
            best = (ratio, h)
    return best[1] if best else None


def payee_category_history(
    budget_id: str = "last-used",
    lookback_days: int = 365,
) -> dict[str, dict]:
    """Payee -> dominant-category map from approved, categorized history.

    Keyed by payee id as a string. Each value:
        {category_id, category_name, count, total, ratio}
    where `count` is how often the dominant category was used for that payee,
    `total` is that payee's categorized-row count, `ratio = count / total`.
    """
    try:
        tally: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(dict))
        totals: dict[str, int] = defaultdict(int)
        for t in _load(_days_ago(lookback_days)):
            if not t["approved"] or not t["payee_id"] or not t["category_id"]:
                continue
            if t.get("transfer_account_id"):
                continue
            pid, cid = str(t["payee_id"]), str(t["category_id"])
            slot = tally[pid].setdefault(cid, {"count": 0, "name": t["category_name"]})
            slot["count"] += 1
            totals[pid] += 1

        history: dict[str, dict] = {}
        for pid, cats in tally.items():
            cat_id, info = max(cats.items(), key=lambda kv: kv[1]["count"])
            total = totals[pid]
            history[pid] = {
                "category_id": cat_id,
                "category_name": info["name"],
                "count": info["count"],
                "total": total,
                "ratio": info["count"] / total if total else 0.0,
            }
        return history
    except Exception:
        logger.exception("payee_category_history failed")
        return {}


def payee_short_names() -> dict[str, str]:
    """Bank payee name -> human title, only where one is set. The page flips between them."""
    try:
        with _conn() as c:
            return dict(c.execute(
                "SELECT name, short_name FROM payee WHERE short_name IS NOT NULL AND short_name != name"))
    except Exception:
        logger.exception("payee_short_names failed")
        return {}


def set_payee_short_names(names: dict[str, str]) -> int:
    """Write {bank name: short title}; an empty title clears it. Returns rows changed."""
    with _conn() as c:
        return sum(c.execute("UPDATE payee SET short_name = ? WHERE name = ?",
                             (short.strip() or None, name)).rowcount
                   for name, short in names.items())


# --- writes -----------------------------------------------------------------


def _check_category(c: sqlite3.Connection, category_id) -> None:
    """ValueError (a 400 at the API) for an id with no category row, before the FK turns it into a 500."""
    if not c.execute("SELECT 1 FROM category WHERE id = ?", (int(category_id),)).fetchone():
        raise ValueError(f"no category with id {category_id}")


def _set_txn(c: sqlite3.Connection, uid: str, category_id, memo, approved) -> bool:
    """False when no live row has this uid. Raises ValueError for a category on a split row.
    A category_id of "" clears the category."""
    sets: list[str] = ["updated_at = ?"]
    args: list = [_now()]
    if category_id == "":
        sets.append("category_id = NULL")
    elif category_id is not None:
        if c.execute("SELECT 1 FROM split s JOIN txn t ON t.id = s.txn_id WHERE t.uid = ? LIMIT 1",
                     (uid,)).fetchone():
            raise ValueError("a split row carries its categories on the legs; edit the split")
        _check_category(c, category_id)
        sets.append("category_id = ?")
        args.append(int(category_id))
    if memo is not None:
        sets.append("memo = ?")
        args.append(memo)
    if approved is not None:
        sets.append("approved = ?")
        args.append(int(bool(approved)))
    if category_id is not None or approved is not None:
        sets.append("suggested_confidence = NULL")  # a human decided: autocat's guess no longer stands alone
    cur = c.execute(
        f"UPDATE txn SET {', '.join(sets)} WHERE uid = ? AND deleted = 0",  # noqa: S608
        (*args, uid),
    )
    return cur.rowcount > 0


def update_transaction(
    transaction_id: str,
    category_id: str | None = None,
    memo: str | None = None,
    approved: bool | None = None,
    budget_id: str = "last-used",
) -> bool:
    """Write any combination of category, memo and approved to a row by uid.

    Only fields passed (non-None) are written; category_id "" clears it. Returns
    True on success, False for an unknown uid. Raises ValueError for a category
    on a split row or an unknown category.
    """
    if category_id is None and memo is None and approved is None:
        return False
    try:
        with _conn() as c:
            return _set_txn(c, transaction_id, category_id, memo, approved)
    except ValueError:
        raise
    except Exception:
        logger.exception("update_transaction failed for %s", transaction_id)
        return False


def update_transactions_bulk(
    updates: list[dict],
    budget_id: str = "last-used",
) -> int:
    """Update many rows in one transaction. Each entry carries `id` (the uid)
    plus any of `category_id`, `memo`, `approved`. Returns the rows updated."""
    done = 0
    try:
        with _conn() as c:
            for u in updates:
                tid = u.get("id")
                fields = (u.get("category_id"), u.get("memo"), u.get("approved"))
                if not tid or all(f is None for f in fields):
                    continue
                try:
                    done += _set_txn(c, tid, *fields)
                except ValueError as e:  # refused before any write: skip the row, keep the batch
                    logger.warning("update_transactions_bulk skipped %s: %s", tid, e)
    except Exception:
        logger.exception("update_transactions_bulk failed")
        return 0  # the whole batch rolled back
    return done


def update_transaction_memo(
    transaction_id: str,
    memo_text: str,
    budget_id: str = "last-used",
) -> bool:
    """Write memo_text to a row's memo. Thin wrapper over update_transaction."""
    return update_transaction(transaction_id, memo=memo_text, budget_id=budget_id)


def update_transaction_split(  # noqa: C901 - validate-then-write over split legs; each branch is one input check
    transaction_id: str,
    subtransactions: list[dict],
    memo: str | None = None,
    approved: bool | None = None,
    budget_id: str = "last-used",
) -> bool:
    """Convert a row into a split across categories.

    `subtransactions` is [{amount (milliunits, signed), category_id, memo?}].
    Raises ValueError when an amount is not a whole number of cents, the legs
    do not sum to the row's total, or the row is a transfer. The parent's
    category is cleared.
    """
    if not subtransactions:
        return False
    legs = []
    for s in subtransactions:
        milli = int(s["amount"])
        if milli % 10:
            raise ValueError(f"split amount {milli} milliunits is not a whole number of cents")
        if not s.get("category_id"):
            raise ValueError("every split leg needs a category")  # an uncategorized leg drops out of review
        legs.append((milli // 10, s.get("category_id"), s.get("memo") or ""))
    try:
        with _conn() as c:
            for _, cat, _ in legs:
                _check_category(c, cat)
            row = c.execute(
                "SELECT id, amount_cents, transfer_account_id FROM txn WHERE uid = ? AND deleted = 0",
                (transaction_id,),
            ).fetchone()
            if row is None:
                return False
            if row["transfer_account_id"] is not None:
                raise ValueError("a transfer cannot be split")
            if sum(a for a, _, _ in legs) != row["amount_cents"]:
                raise ValueError("split legs do not sum to the transaction amount")
            c.execute("DELETE FROM split WHERE txn_id = ?", (row["id"],))
            for i, (cents, cat, m) in enumerate(legs):
                c.execute(
                    "INSERT INTO split(txn_id, ord, amount_cents, category_id, memo) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (row["id"], i, cents, int(cat) if cat else None, m),
                )
            c.execute("UPDATE txn SET category_id = NULL, updated_at = ? WHERE id = ?",
                      (_now(), row["id"]))
            _set_txn(c, transaction_id, None, memo, approved)
        return True
    except ValueError:
        raise
    except Exception:
        logger.exception("update_transaction_split failed for %s", transaction_id)
        return False


def create_category_group(name: str, budget_id: str = "last-used") -> str | None:
    """Create a category group. Returns the new group id, or None on error."""
    try:
        with _conn() as c:
            return str(c.execute("INSERT INTO category_group(name) VALUES (?)", (name,)).lastrowid)
    except Exception:
        logger.exception("create_category_group failed for name=%s", name)
        return None


def create_category(
    name: str, group_id: str, budget_id: str = "last-used"
) -> str | None:
    """Create a category inside group_id. Returns the new category id, or None."""
    try:
        with _conn() as c:
            return str(c.execute(
                "INSERT INTO category(group_id, name) VALUES (?, ?)", (int(group_id), name)
            ).lastrowid)
    except Exception:
        logger.exception("create_category failed for name=%s group_id=%s", name, group_id)
        return None


def update_category(
    category_id: str,
    name: str | None = None,
    group_id: str | None = None,
    budget_id: str = "last-used",
) -> bool:
    """Rename a category and/or move it to another group. Returns True on success."""
    sets, args = [], []
    if name is not None:
        sets.append("name = ?")
        args.append(name)
    if group_id is not None:
        sets.append("group_id = ?")
        args.append(int(group_id))
    if not sets:
        return False
    try:
        with _conn() as c:
            cur = c.execute(
                f"UPDATE category SET {', '.join(sets)} WHERE id = ?",  # noqa: S608
                (*args, int(category_id)),
            )
            return cur.rowcount > 0
    except Exception:
        logger.exception("update_category failed for category_id=%s", category_id)
        return False


def delete_transaction(uid: str) -> bool:
    """Soft-delete a row (deleted = 1); every fetch skips it."""
    try:
        with _conn() as c:
            cur = c.execute(
                "UPDATE txn SET deleted = 1, updated_at = ? WHERE uid = ? AND deleted = 0",
                (_now(), uid),
            )
            return cur.rowcount > 0
    except Exception:
        logger.exception("delete_transaction failed for %s", uid)
        return False


def _transfer_payee(c: sqlite3.Connection, other_name: str, other_id: int) -> int:
    """The "Transfer : <account>" payee, created on first use."""
    pname = f"Transfer : {other_name}"
    r = c.execute("SELECT id FROM payee WHERE name = ?", (pname,)).fetchone()
    if r:
        return r["id"]
    return c.execute(
        "INSERT INTO payee(name, transfer_account_id) VALUES (?, ?)", (pname, other_id)
    ).lastrowid  # pyright: ignore[reportReturnType]  # set after a successful INSERT


def _link_transfer(c: sqlite3.Connection, uid: str, acct_id: int, acct_name: str,
                   other_uid: str, other_id: int, other_name: str) -> None:
    """Point two rows at each other as a transfer pair, each with its "Transfer : <other>" payee."""
    now = _now()
    link = ("UPDATE txn SET transfer_account_id = ?, transfer_txn_uid = ?, "
            "payee_id = ?, updated_at = ? WHERE uid = ?")
    c.execute(link, (other_id, other_uid, _transfer_payee(c, other_name, other_id), now, uid))
    c.execute(link, (acct_id, uid, _transfer_payee(c, acct_name, acct_id), now, other_uid))


def _add_counterpart(c: sqlite3.Connection, t, tgt_id: int, tgt_name: str) -> str:
    """Insert the other side of row `t` (needs uid, account_id, aname, date, amount_cents,
    cleared, source) in account `tgt_id` and link the pair. Returns the new row's uid."""
    cp_uid = f"xfer:{uuid.uuid4().hex}"
    c.execute(
        "INSERT INTO txn(uid, account_id, date, amount_cents, raw_description, "
        "approved, cleared, source, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
        (cp_uid, tgt_id, t["date"], -t["amount_cents"],
         f"Transfer : {t['aname']}", t["cleared"], t["source"], _now()),
    )
    _link_transfer(c, t["uid"], t["account_id"], t["aname"], cp_uid, tgt_id, tgt_name)
    return cp_uid


def convert_to_transfer(uid: str, account_name: str) -> bool:
    """Turn a row into a transfer with `account_name`.

    Links the counterpart already in that account (opposite amount, within 5
    days, not yet a transfer, nearest date first); when none exists, inserts it,
    so money never leaves the book. Returns False for an unknown uid or account,
    when the row is already in `account_name`, or when it is already a transfer
    or a split (relinking would strand the old counterpart; a split's legs would
    still count as spend).
    """
    try:
        with _conn() as c:
            t = c.execute(
                "SELECT t.*, a.name AS aname FROM txn t JOIN account a ON a.id = t.account_id "
                "WHERE t.uid = ? AND t.deleted = 0", (uid,)
            ).fetchone()
            tgt = c.execute("SELECT id FROM account WHERE name = ?", (account_name,)).fetchone()
            if t is None or tgt is None or tgt["id"] == t["account_id"]:
                return False
            if t["transfer_txn_uid"] or t["transfer_account_id"] is not None or c.execute(
                    "SELECT 1 FROM split WHERE txn_id = ?", (t["id"],)).fetchone():
                logger.warning("convert_to_transfer refused %s: already a transfer or a split", uid)
                return False
            cp = c.execute(
                "SELECT uid FROM txn WHERE account_id = ? AND deleted = 0 AND amount_cents = ? "
                "AND transfer_txn_uid IS NULL AND ABS(julianday(date) - julianday(?)) <= 5 "
                "ORDER BY ABS(julianday(date) - julianday(?)), id LIMIT 1",
                (tgt["id"], -t["amount_cents"], t["date"], t["date"]),
            ).fetchone()
            if cp:
                _link_transfer(c, uid, t["account_id"], t["aname"], cp["uid"], tgt["id"], account_name)
            else:
                _add_counterpart(c, t, tgt["id"], account_name)
        return True
    except Exception:
        logger.exception("convert_to_transfer failed for %s", uid)
        return False

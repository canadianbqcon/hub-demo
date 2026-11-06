"""One-shot YNAB import into data/book.db, plus a verify pass against live YNAB.

    cd dashboard/hub && python -m finances.ynab_import [--verify] [--db PATH]

Reads YNAB only (GET through _get). Nothing here ever writes to YNAB.
Idempotent: upserts on ynab_id / natural keys, and each transaction's splits are
deleted and rewritten, all inside one DB transaction.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

_DASHBOARD = str(Path(__file__).resolve().parents[2])
if _DASHBOARD not in sys.path:
    sys.path.insert(0, _DASHBOARD)

from finances.book import READY_TO_ASSIGN  # noqa: E402
from sqlite_helpers import connect  # noqa: E402

YNAB_BASE = "https://api.ynab.com/v1"
BUDGET = "last-used"
BUDGET_START = "2000-01-01"
# Only creditCard is a card, as in ynab.py; every other type (lineOfCredit included) is checking.
_TYPES = {"creditCard": "credit", "savings": "savings"}


def _cents(milli: int) -> int:
    if milli % 10:
        raise ValueError(f"milliunits {milli} not divisible by 10")
    return milli // 10


def _split_cents(subs: list[dict], parent_cents: int) -> list[int]:
    """Split lines in cents. YNAB allows sub-cent split lines (one 2026-09-11 charge was split
    into two -26.725 halves), so each line is floored to a cent and the leftover goes on the
    last line, keeping the lines summing to the parent."""
    out = [s["amount"] // 10 for s in subs]
    if out:
        out[-1] += parent_cents - sum(out)
    return out


def _get(path: str) -> dict:
    """Read-only GET against the YNAB API. This importer never writes to YNAB."""
    req = urllib.request.Request(f"{YNAB_BASE}{path}",
                                 headers={"Authorization": f"Bearer {os.environ['YNAB_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _ynab_spend(since: str) -> dict[str, int]:
    """{category name: cents} of non-transfer outflows on YNAB since `since`, splits expanded."""
    out: dict[str, int] = {}
    for t in _get(f"/budgets/{BUDGET}/transactions?since_date={since}")["data"]["transactions"]:
        if t.get("deleted"):
            continue
        for leg in (t.get("subtransactions") or [t]):
            if leg.get("deleted") or leg.get("transfer_account_id") or leg.get("amount", 0) >= 0:
                continue
            name = (leg.get("category_name") or "").strip()
            if name == READY_TO_ASSIGN:
                continue
            out[name] = out.get(name, 0) + round(abs(leg["amount"]) / 10)
    return out


def _ensure_token() -> None:
    # A bare shell has no YNAB_TOKEN; services loads dashboard/.env (ENV_FILE) into os.environ.
    if not os.environ.get("YNAB_TOKEN"):
        import services  # noqa: F401


def _fetch() -> dict:
    g = lambda p: _get(f"/budgets/{BUDGET}{p}")["data"]  # noqa: E731
    return {
        "accounts": g("/accounts")["accounts"],
        "groups": g("/categories")["category_groups"],
        "payees": g("/payees")["payees"],
        "txns": [t for t in g(f"/transactions?since_date={BUDGET_START}")["transactions"]
                 if not t.get("deleted")],
    }


def import_all(db_path: Path | str, data: dict | None = None) -> dict:  # noqa: C901 - one-time seed: a linear run of table imports
    """One-time seed of the book from YNAB. Refused once SimpleFIN has synced: a rerun
    would overwrite categories, memos, approvals and balances the book now owns, and
    bring back holds the sync expired."""
    with connect(db_path, "ynab_import") as c:
        if c.execute("SELECT 1 FROM sync_run LIMIT 1").fetchone():
            raise RuntimeError("the book has SimpleFIN syncs; a YNAB re-import would overwrite them")
    data = data or _fetch()
    now = datetime.now().isoformat(timespec="seconds")
    with connect(db_path, "ynab_import") as c:
        acct = {}
        for a in data["accounts"]:
            typ = _TYPES.get(a["type"], "checking")
            # balance_cents is YNAB's own signed balance (a card you owe is negative), which is
            # sign * bank balance with credit's default sign -1; owed = -balance_cents / 100 then
            # equals the YNAB account balance.
            c.execute(
                "INSERT INTO account(name, type, ynab_id, balance_sign, balance_cents, balance_at, closed) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(ynab_id) DO UPDATE SET name=excluded.name, "
                "type=excluded.type, balance_cents=excluded.balance_cents, "
                "balance_at=excluded.balance_at, closed=excluded.closed",
                (a["name"], typ, a["id"], -1 if typ == "credit" else 1,
                 _cents(a["balance"]), now, int(bool(a.get("closed")))))
            acct[a["id"]] = c.execute("SELECT id FROM account WHERE ynab_id=?", (a["id"],)).fetchone()[0]

        cat = {}
        for g in data["groups"]:
            if g.get("deleted"):
                continue
            c.execute("INSERT INTO category_group(name, ynab_id, hidden) VALUES (?,?,?) "
                      "ON CONFLICT(name) DO UPDATE SET ynab_id=excluded.ynab_id, hidden=excluded.hidden",
                      (g["name"], g["id"], int(bool(g.get("hidden")))))
            gid = c.execute("SELECT id FROM category_group WHERE name=?", (g["name"],)).fetchone()[0]
            for k in g.get("categories", []):
                if k.get("deleted"):
                    continue
                c.execute("INSERT INTO category(group_id, name, ynab_id, hidden) VALUES (?,?,?,?) "
                          "ON CONFLICT(group_id, name) DO UPDATE SET ynab_id=excluded.ynab_id, "
                          "hidden=excluded.hidden",
                          (gid, k["name"], k["id"], int(bool(k.get("hidden")))))
                cat[k["id"]] = c.execute("SELECT id FROM category WHERE group_id=? AND name=?",
                                         (gid, k["name"])).fetchone()[0]

        payee = {}

        def _payee(pid, name, transfer=None):
            c.execute("INSERT INTO payee(name, ynab_id, transfer_account_id) VALUES (?,?,?) "
                      "ON CONFLICT(name) DO UPDATE SET ynab_id=excluded.ynab_id, "
                      "transfer_account_id=excluded.transfer_account_id", (name, pid, transfer))
            return c.execute("SELECT id FROM payee WHERE name=?", (name,)).fetchone()[0]

        for p in data["payees"]:
            if not p.get("deleted"):
                payee[p["id"]] = _payee(p["id"], p["name"], acct.get(p.get("transfer_account_id")))

        n_split = 0
        for t in data["txns"]:
            pid = payee.get(t.get("payee_id"))
            if pid is None and t.get("payee_name"):
                pid = _payee(t.get("payee_id"), t["payee_name"])
            subs = [s for s in (t.get("subtransactions") or []) if not s.get("deleted")]
            tl = t.get("transfer_transaction_id")
            c.execute(
                "INSERT INTO txn(uid, ynab_id, account_id, date, amount_cents, payee_id, raw_description, "
                "category_id, memo, approved, cleared, pending, transfer_account_id, transfer_txn_uid, "
                "deleted, source, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,'ynab',?) "
                "ON CONFLICT(ynab_id) DO UPDATE SET account_id=excluded.account_id, date=excluded.date, "
                "amount_cents=excluded.amount_cents, payee_id=excluded.payee_id, "
                "raw_description=excluded.raw_description, category_id=excluded.category_id, "
                "memo=excluded.memo, approved=excluded.approved, cleared=excluded.cleared, "
                "pending=excluded.pending, transfer_account_id=excluded.transfer_account_id, "
                "transfer_txn_uid=excluded.transfer_txn_uid, deleted=0, updated_at=excluded.updated_at",
                ("ynab:" + t["id"], t["id"], acct[t["account_id"]], t["date"], _cents(t["amount"]), pid,
                 (t.get("payee_name") or "").strip(),
                 None if subs else cat.get(t.get("category_id")),  # a split parent carries no category
                 t.get("memo") or "", int(bool(t.get("approved"))),
                 int(t.get("cleared") in ("cleared", "reconciled")),
                 # ynab.py's is_pending_hold: a P: import id on a row still uncleared
                 int((t.get("import_id") or "").startswith("YNAB:P:")
                     and t.get("cleared") == "uncleared"),
                 acct.get(t.get("transfer_account_id")), ("ynab:" + tl) if tl else None, now))
            tid = c.execute("SELECT id FROM txn WHERE ynab_id=?", (t["id"],)).fetchone()[0]
            c.execute("DELETE FROM split WHERE txn_id=?", (tid,))
            for i, (s, amt) in enumerate(zip(subs, _split_cents(subs, _cents(t["amount"])), strict=False)):
                c.execute("INSERT INTO split(txn_id, ord, amount_cents, category_id, memo, payee_id) "
                          "VALUES (?,?,?,?,?,?)",
                          (tid, i, amt, cat.get(s.get("category_id")),
                           s.get("memo") or "", payee.get(s.get("payee_id"))))
                n_split += 1
    return {"accounts": len(acct), "categories": len(cat), "txns": len(data["txns"]), "splits": n_split}


def _book_spend(db_path, since: str, use_book: bool) -> dict[str, int]:
    """{category name: cents} from the book, same rules as _ynab_spend."""
    if use_book:
        from finances import book
        book.init(db_path)
        out: dict[str, int] = {}
        for r in book.fetch_spend(since_date=since):
            out[r["category"]] = out.get(r["category"], 0) + round(r["amount"] * 100)
        return out
    out = {}
    with connect(db_path, "ynab_import") as c:
        rows = c.execute(
            "SELECT t.id, t.amount_cents, t.transfer_account_id, k.name AS cat FROM txn t "
            "LEFT JOIN category k ON k.id = t.category_id WHERE t.deleted=0 AND t.date >= ?", (since,)).fetchall()
        for r in rows:
            legs = c.execute("SELECT s.amount_cents, k.name AS cat FROM split s LEFT JOIN category k "
                             "ON k.id = s.category_id WHERE s.txn_id=?", (r["id"],)).fetchall()
            for amt, name in ([(x["amount_cents"], x["cat"]) for x in legs] or [(r["amount_cents"], r["cat"])]):
                if r["transfer_account_id"] or amt >= 0 or (name or "") == READY_TO_ASSIGN:
                    continue
                out[name or ""] = out.get(name or "", 0) + -amt
    return out


def verify(db_path: Path | str, data: dict | None = None, use_book: bool = True) -> int:
    """Print a book-vs-YNAB table; return 0 only when every row matches."""
    from finances.budget import SPEND_SINCE

    data = data or _fetch()
    txns = data["txns"]
    cats = [k for g in data["groups"] if not g.get("deleted")
            for k in g.get("categories", []) if not k.get("deleted")]
    rows: list[tuple[str, Any, Any]] = []
    with connect(db_path, "ynab_import") as c:
        q = lambda sql, *a: c.execute(sql, a).fetchone()[0]  # noqa: E731
        live = "ynab_id IS NOT NULL AND deleted=0"
        rows += [
            ("transactions", q(f"SELECT COUNT(*) FROM txn WHERE {live}"), len(txns)),  # noqa: S608 - `live` is a module-local constant; no user value in the SQL
            ("memos", q(f"SELECT COUNT(*) FROM txn WHERE {live} AND memo != ''"),  # noqa: S608 - `live` is a module-local constant; no user value in the SQL
             sum(1 for t in txns if t.get("memo"))),
            ("splits", q(f"SELECT COUNT(*) FROM split WHERE txn_id IN (SELECT id FROM txn WHERE {live})"),  # noqa: S608 - `live` is a module-local constant; no user value in the SQL
             sum(len([s for s in (t.get("subtransactions") or []) if not s.get("deleted")]) for t in txns)),
            ("transfers", q(f"SELECT COUNT(*) FROM txn WHERE {live} AND transfer_account_id IS NOT NULL"),  # noqa: S608 - `live` is a module-local constant; no user value in the SQL
             sum(1 for t in txns if t.get("transfer_account_id"))),
            ("categories", q("SELECT COUNT(*) FROM category WHERE ynab_id IS NOT NULL"), len(cats)),
        ]
        book_memo = dict(c.execute(f"SELECT ynab_id, memo FROM txn WHERE {live}").fetchall())  # noqa: S608 - `live` is a module-local constant; no user value in the SQL
        rows.append(("memo text mismatches",
                     sum(1 for t in txns if book_memo.get(t["id"]) != (t.get("memo") or "")), 0))
        book_bal = dict(c.execute("SELECT ynab_id, balance_cents FROM account WHERE ynab_id IS NOT NULL").fetchall())
        for a in data["accounts"]:
            rows.append((f"balance {a['name']}", book_bal.get(a["id"]), _cents(a["balance"])))

    want = _ynab_spend(SPEND_SINCE)
    have = _book_spend(db_path, SPEND_SINCE, use_book)
    rows.append(("spend total (cents)", sum(have.values()), sum(want.values())))
    rows += [(f"spend {k or '(none)'}", have.get(k, 0), want.get(k, 0))
             for k in sorted(set(have) | set(want)) if have.get(k, 0) != want.get(k, 0)]

    # YNAB's float spend rounds each sub-cent split line on its own, so it can sit up to one
    # cent per such line away from the book's exact cents (see _split_cents).
    slack = sum(1 for t in txns for s in (t.get("subtransactions") or []) if s["amount"] % 10)
    bad = 0
    print(f"{'check':<44}{'book':>12}{'ynab':>12}  ok")
    for name, b, y in rows:
        ok = b == y or (name.startswith("spend") and abs(b - y) <= slack)
        bad += not ok
        print(f"{name[:43]:<44}{str(b):>12}{str(y):>12}  {'ok' if ok else 'MISMATCH'}")
    print("verify: " + ("clean" if not bad else f"{bad} mismatch(es)"))
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--verify", action="store_true", help="compare book against live YNAB, import nothing")
    ap.add_argument("--db", help="book.db path (default <vault>/data/book.db)")
    args = ap.parse_args(argv)
    if args.db:
        db = Path(args.db)
    else:
        from vault_path import vault_root
        db = vault_root() / "data" / "book.db"
    _ensure_token()
    if args.verify:
        return verify(db)
    print(import_all(db))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Finances Hub blueprint -- routes under /finances. Earnings is the first tab;
spending and investments slot in later without restructuring."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, jsonify, render_template, request

from . import autocat, book, budget, db, debt_source, owed, shift_pricing, simplefin, spending

bp = Blueprint(
    "finances",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/finances",
)

@bp.route("/")
def page():
    return render_template("finances.html", exposed=current_app.config.get("EXPOSED", False),
                           payee_short=book.payee_short_names())


@bp.route("/api/earnings")
def api_earnings():
    return jsonify({"earnings": db.list_earnings()})


@bp.route("/api/earnings/<int:eid>")
def api_earning(eid: int):
    row = db.get_earning(eid)
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)


@bp.route("/api/totals")
def api_totals():
    today = date.today().isoformat()
    return jsonify({
        "week": db.totals("week", today),
        "month": db.totals("month", today),
        "ytd": db.totals("ytd", today),
        "by_source": db.by_source(),
    })


@bp.route("/api/spending")
def api_spending():
    """The spending tab: one YNAB fetch sliced into totals, categories, months.

    Failing here must not take the tab down silently — the earnings side of the
    same page is still true — so a fetch that blows up degrades to the same
    not-configured shape the frontend already knows how to render.
    """
    try:
        return jsonify(spending.snapshot())
    except Exception:
        current_app.logger.exception("spending.snapshot failed")
        return jsonify({"configured": False, "error": "fetch failed"}), 503


@bp.route("/api/expected")
def api_expected():
    return jsonify(db.expected(months=4, today=date.today().isoformat()))


@bp.route("/api/pricing")
def api_pricing():
    """The model's inputs, each flagged verified or assumed.

    The page shows money built on numbers Sam confirmed (barback 6, server 5)
    sitting next to numbers nobody has confirmed (bartender points, the buyout
    multiple). Shipping the verified flag is what lets the UI say which is which
    instead of presenting a guess with the same authority as a measurement.
    """
    return jsonify(shift_pricing.load_meta())


@bp.route("/api/budget")
def api_budget():
    """The monthly payment the debt tab seeds itself with, and its whole chain.

    Every earlier version of this number was invented -- a rounded-up multiple of
    the minimums, then a figure from a method Sam did not ask for. It is
    derived here or it is not shown, so the response carries the spend window and
    the assumed-week count that produced it.
    """
    try:
        return jsonify(budget.derive(today=date.today().isoformat()))
    except Exception:
        current_app.logger.exception("budget.derive failed")
        # The debt tab is still true without a seed; it falls back to minimums.
        return jsonify({"error": "derive failed", "budget": None}), 503


def _budget_arg() -> float | None:
    """Parse ?budget=, tolerating blank and junk as 'minimums only'.

    A bad number must not 500 the whole tab — the debt figures are still true
    without a what-if budget, so an unparseable value degrades to None.
    """
    raw = request.args.get("budget", "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


@bp.route("/api/debt")
def api_debt():
    """Full debt picture at one monthly budget: cards, projection, payments."""
    try:
        return jsonify(debt_source.snapshot(_budget_arg()))
    except RuntimeError as e:   # YNAB unavailable: say so, never show a partial picture
        return jsonify({"error": str(e)}), 503


@bp.route("/api/debt/scenarios")
def api_debt_scenarios():
    """Same debt at several monthly payment levels — the trajectory comparison."""
    raw = request.args.get("budgets", "")
    budgets = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            budgets.append(max(0.0, float(part)))
        except ValueError:
            continue
    if not budgets:
        return jsonify({"error": "no valid budgets"}), 400
    # Cap the fan-out: each scenario is a full simulation, and nothing useful
    # needs more than a handful of comparison points.
    try:
        return jsonify({"scenarios": debt_source.scenarios(budgets[:8])})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503


@bp.route("/api/manual", methods=["POST"])
def api_manual():
    body = request.get_json(force=True) or {}
    required = ("source", "source_type", "period_start", "period_end")
    missing = [k for k in required if not body.get(k)]
    if missing:
        return jsonify({"error": f"missing: {', '.join(missing)}"}), 400
    eid = db.upsert_earning(body, shifts=[])
    return jsonify({"id": eid})


# ── owed — what other people owe him (data/owed.db) ──────────────────────────

@bp.route("/api/owed")
def api_owed():
    return jsonify(owed.snapshot())


@bp.route("/api/owed", methods=["POST"])
def api_owed_add():
    body = request.get_json(force=True) or {}
    if not (body.get("person") or "").strip():
        return jsonify({"error": "person is required"}), 400
    if not (body.get("what") or "").strip():
        return jsonify({"error": "what is required"}), 400
    try:
        amount = float(body.get("amount"))  # pyright: ignore[reportArgumentType]  # a None here is deliberately caught below, not a type bug
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400
    # Signed like a YNAB line: a negative amount is money he owes them.
    if amount < 0:
        body["dir"] = -1
    body["amount"] = abs(amount)
    return jsonify({"id": owed.add(body)})


@bp.route("/api/owed/<int:rid>", methods=["PATCH"])
def api_owed_update(rid: int):
    if owed.get(rid) is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(owed.update(rid, request.get_json(force=True) or {}))


@bp.route("/api/owed/<int:rid>", methods=["DELETE"])
def api_owed_delete(rid: int):
    owed.delete(rid)
    return jsonify({"ok": True})


# ── owed: asking for it, and the money that comes back ───────────────────────

@bp.route("/api/owed/request", methods=["POST"])
def api_owed_request():
    """Build the Venmo charge link for one person's lines and mark them asked.

    Returns the link rather than opening anything: no API can send a Venmo or
    Zelle request on his behalf, so the last step is always his tap.
    """
    body = request.get_json(force=True) or {}
    ids = body.get("ids") or ([body["id"]] if body.get("id") else [])
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return jsonify({"error": "ids must be numbers"}), 400
    if not ids:
        return jsonify({"error": "nothing to request"}), 400
    out = owed.request(ids, mark=bool(body.get("mark", True)))
    return (jsonify(out), 400) if out.get("error") else jsonify(out)


@bp.route("/api/owed/handle", methods=["POST"])
def api_owed_handle():
    body = request.get_json(force=True) or {}
    if not (body.get("person") or "").strip():
        return jsonify({"error": "person is required"}), 400
    owed.set_handle(body["person"], body.get("venmo"))
    return jsonify({"handles": owed.handles()})


@bp.route("/api/owed/payments/scan", methods=["POST"])
def api_owed_scan():
    """Read the mailbox now, instead of waiting for the morning job."""
    from . import payments_scan
    try:
        days = int((request.get_json(silent=True) or {}).get("days", 60))
    except (TypeError, ValueError):
        days = 60
    try:
        return jsonify(payments_scan.scan(days=max(1, min(days, 365))))
    except Exception as exc:
        current_app.logger.exception("payments_scan.scan failed")
        return jsonify({"error": str(exc)}), 503


@bp.route("/api/owed/payments/<int:pid>/apply", methods=["POST"])
def api_owed_payment_apply(pid: int):
    body = request.get_json(force=True) or {}
    try:
        owed_ids = [int(i) for i in (body.get("owed_ids") or [])]
    except (TypeError, ValueError):
        return jsonify({"error": "owed_ids must be numbers"}), 400
    if not owed_ids:
        return jsonify({"error": "pick at least one line"}), 400
    out = owed.apply_payment(pid, owed_ids)
    return jsonify(out) if out else (jsonify({"error": "not found"}), 404)


@bp.route("/api/owed/payments/<int:pid>/apply", methods=["DELETE"])
def api_owed_payment_unapply(pid: int):
    out = owed.unapply_payment(pid)
    return jsonify(out) if out else (jsonify({"error": "not found"}), 404)


@bp.route("/api/owed/payments/<int:pid>", methods=["PATCH"])
def api_owed_payment_status(pid: int):
    body = request.get_json(force=True) or {}
    out = owed.set_payment_status(pid, body.get("status", ""))
    return jsonify(out) if out else (jsonify({"error": "bad status"}), 400)


@bp.route("/api/owed/payments/<int:pid>", methods=["DELETE"])
def api_owed_payment_delete(pid: int):
    owed.delete_payment(pid)
    return jsonify({"ok": True})


# ── book: the local transaction ledger (data/book.db) ────────────────────────

SYNC_MIN_GAP = timedelta(hours=1)   # SimpleFIN allows ~24 requests a day


@bp.route("/api/book/accounts")
def api_book_accounts():
    """Open accounts with balance. Credit shows the amount owed (positive)."""
    with book._conn() as c:
        rows = c.execute(
            "SELECT a.id, a.name, a.type, a.simplefin_id, a.balance_at, "  # noqa: S608 - BALANCE_SQL is a module constant
            f"{book.BALANCE_SQL} AS bal "
            "FROM account a WHERE a.closed = 0 ORDER BY a.id").fetchall()
        last = c.execute("SELECT at FROM sync_run WHERE status IN ('ok','partial') "
                         "ORDER BY id DESC LIMIT 1").fetchone()
    out = []
    for r in rows:
        credit = r["type"] == "credit"
        out.append({"id": r["id"], "name": r["name"], "type": r["type"],
                    "linked": bool(r["simplefin_id"]), "balance_at": r["balance_at"],
                    "balance": (-r["bal"] if credit else r["bal"]) / 100.0,
                    "owed": credit})
    return jsonify({"accounts": out, "last_sync": last["at"] if last else None})


@bp.route("/api/book/categories")
def api_book_categories():
    return jsonify({"categories": book.fetch_categories()})


# Same rule as book.fetch_unreviewed; test_book_api asserts the two agree.
_REVIEW_SQL = (
    "(t.transfer_account_id IS NULL AND ("
    "(t.approved = 0 AND t.pending = 0) "
    "OR (t.category_id IS NULL AND NOT EXISTS (SELECT 1 FROM split s WHERE s.txn_id = t.id)) "
    # TRIM's default strips spaces only; Python's strip() also takes tabs, newlines and nbsp
    "OR TRIM(t.memo, char(32, 9, 10, 11, 12, 13, 160)) = ''))")


@bp.route("/api/book/transactions")
def api_book_transactions():  # noqa: C901 - flat list of optional filters, one branch each
    """Filters: q (payee, memo, bank text or amount), account, category,
    review=1 (same rule as book.fetch_unreviewed), since, until, limit."""
    a = request.args
    where, args = ["t.deleted = 0"], []
    q = a.get("q", "").strip()
    if q:
        like = f"%{q}%"
        cond = ["p.name LIKE ?", "p.short_name LIKE ?", "t.memo LIKE ?", "t.raw_description LIKE ?"]
        args += [like, like, like, like]
        try:
            cents = round(abs(float(q.replace("$", "").replace(",", ""))) * 100)
            cond.append("ABS(t.amount_cents) = ?")
            args.append(cents)
        except (ValueError, OverflowError):
            pass
        where.append("(" + " OR ".join(cond) + ")")
    if a.get("account", "").isdigit():
        where.append("t.account_id = ?")
        args.append(int(a["account"]))
    if a.get("category", "") == "none":
        where.append("t.category_id IS NULL")
    elif a.get("category", "").isdigit():
        where.append("t.category_id = ?")
        args.append(int(a["category"]))
    if a.get("review") in ("1", "true"):
        where.append(_REVIEW_SQL)
    for key, op in (("since", ">="), ("until", "<=")):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.get(key, "")):
            where.append(f"t.date {op} ?")
            args.append(a[key])
    try:
        limit = max(1, min(int(a.get("limit", 200)), 1000))
    except ValueError:
        limit = 200
    sql = (
        "SELECT t.id AS rid, t.uid, t.date, t.amount_cents, t.account_id, ac.name AS account, "  # noqa: S608 - where holds only fixed clauses; every value is bound
        "COALESCE(p.name, NULLIF(t.raw_description, ''), '') AS payee, t.category_id, "
        "c.name AS category, t.memo, t.approved, t.pending, "
        "(t.transfer_account_id IS NOT NULL) AS transfer, "
        f"{_REVIEW_SQL} AS review "
        "FROM txn t JOIN account ac ON ac.id = t.account_id "
        "LEFT JOIN payee p ON p.id = t.payee_id LEFT JOIN category c ON c.id = t.category_id "
        f"WHERE {' AND '.join(where)} ORDER BY t.date DESC, t.id DESC LIMIT ?")
    with book._conn() as c:
        rows = c.execute(sql, (*args, limit)).fetchall()
        legs = {}
        if rows:
            marks = ",".join("?" * len(rows))
            for s in c.execute(
                    "SELECT s.txn_id, s.amount_cents, s.category_id, s.memo FROM split s "  # noqa: S608 - marks is only "?" placeholders
                    f"WHERE s.txn_id IN ({marks}) ORDER BY s.txn_id, s.ord",
                    [r["rid"] for r in rows]):
                legs.setdefault(s["txn_id"], []).append(
                    {"amount_cents": s["amount_cents"], "category_id": s["category_id"], "memo": s["memo"]})
    out = [{"uid": r["uid"], "date": r["date"], "amount": r["amount_cents"] / 100.0,
            "amount_cents": r["amount_cents"], "account_id": r["account_id"], "account": r["account"],
            "payee": r["payee"], "category_id": r["category_id"], "category": r["category"],
            "memo": r["memo"], "approved": bool(r["approved"]), "pending": bool(r["pending"]),
            "transfer": bool(r["transfer"]), "review": bool(r["review"]),
            "splits": legs.get(r["rid"], [])} for r in rows]
    return jsonify({"transactions": out, "count": len(out), "limit": limit})


def _book_write_result(ok: bool, uid: str):
    """book writes return False for an unknown uid or a logged write failure; tell them apart."""
    if ok:
        return jsonify({"ok": True}), 200
    with book._conn() as c:
        found = c.execute("SELECT 1 FROM txn WHERE uid = ? AND deleted = 0", (uid,)).fetchone()
    return (jsonify({"error": "write failed"}), 500) if found else (jsonify({"error": "not found"}), 404)


@bp.route("/api/book/transactions/<uid>", methods=["PATCH"])
def api_book_txn_update(uid: str):
    """Any of category_id, memo, approved (a JSON bool). A memo of "" clears it;
    a category_id of null or "" clears the category."""
    body = request.get_json(silent=True) or {}
    cat, memo, approved = body.get("category_id"), body.get("memo"), body.get("approved")
    if "category_id" in body and cat in (None, ""):
        cat = ""  # book reads "" as clear; None means leave it
    if cat not in (None, "") and (isinstance(cat, bool) or not str(cat).isdigit()):
        return jsonify({"error": "category_id must be a category id"}), 400
    if memo is not None and not isinstance(memo, str):
        return jsonify({"error": "memo must be text"}), 400
    if approved is not None and not isinstance(approved, bool):
        return jsonify({"error": "approved must be true or false"}), 400
    if cat is None and memo is None and approved is None:
        return jsonify({"error": "nothing to update"}), 400
    try:
        ok = book.update_transaction(uid, category_id=cat, memo=memo, approved=approved)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return _book_write_result(ok, uid)


@bp.route("/api/book/transactions/<uid>/split", methods=["POST"])
def api_book_txn_split(uid: str):
    """Body {legs: [{amount_cents (signed), category_id, memo?}]}; legs must sum to the row."""
    legs = (request.get_json(silent=True) or {}).get("legs")
    if not isinstance(legs, list) or len(legs) < 2:
        return jsonify({"error": "a split needs at least two legs"}), 400
    try:
        if any(type(leg["amount_cents"]) is not int for leg in legs):  # int() would truncate 12.5
            raise TypeError
        subs = [{"amount": leg["amount_cents"] * 10, "category_id": leg.get("category_id") or None,
                 "memo": leg.get("memo") or ""} for leg in legs]
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "each leg needs a whole-cent amount_cents"}), 400
    try:
        ok = book.update_transaction_split(uid, subs)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return _book_write_result(ok, uid)


def _sync_row(c):
    return c.execute("SELECT * FROM sync_run ORDER BY id DESC LIMIT 1").fetchone()


def _next_sync_at(c) -> datetime | None:
    """When Sync opens again: an hour after the last run that reached the bank.
    An error run does not count, so a failed pull can be retried at once."""
    r = c.execute("SELECT at FROM sync_run WHERE status IN ('ok','partial') ORDER BY id DESC LIMIT 1").fetchone()
    return datetime.fromisoformat(r["at"]) + SYNC_MIN_GAP if r else None


_UNLINKED = re.compile(r"SimpleFIN account '(.*?)' is not linked")
_SF_ID = re.compile(r"\(id ([^)\s]+)\)")


def _sync_payload(c) -> dict:
    """Last run with its errors and the unlinked accounts named in them."""
    row, nxt = _sync_row(c), _next_sync_at(c)
    if row is None:
        return {"last": None}
    errors = json.loads(row["errors"] or "[]")
    unlinked = [{"name": m.group(1), "simplefin_id": (sf.group(1) if (sf := _SF_ID.search(e)) else None)}
                for e in errors if (m := _UNLINKED.search(e))]
    nxt = nxt or datetime.now().replace(microsecond=0)
    return {"last": {"at": row["at"], "status": row["status"], "added": row["added"],
                     "updated": row["updated"], "superseded": row["superseded"],
                     "errors": errors, "unlinked": unlinked},
            "can_sync": datetime.now() >= nxt,
            "next_sync_at": nxt.isoformat(timespec="seconds")}


@bp.route("/api/book/sync")
def api_book_sync_status():
    with book._conn() as c:
        return jsonify(_sync_payload(c))


@bp.route("/api/book/sync", methods=["POST"])
def api_book_sync_now():
    """Run one SimpleFIN pull now. Refused inside an hour of the last run that
    reached the bank (429) and while another sync, scheduled or not, is running (409)."""
    with book._conn() as c:
        nxt = _next_sync_at(c)
    if nxt is not None:
        wait = (nxt - datetime.now()).total_seconds()
        if wait > 0:
            resp = jsonify({"error": "synced less than an hour ago", "retry_after": int(wait) + 1})
            resp.status_code = 429
            resp.headers["Retry-After"] = str(int(wait) + 1)
            return resp
    try:
        result = simplefin.sync()
    except simplefin.Busy:
        return jsonify({"error": "a sync is already running; try again in a minute"}), 409
    try:
        ac = autocat.run(limit=25)
    except Exception as e:
        current_app.logger.exception("autocat.run failed")
        ac = {"status": "error", "reason": str(e)}
    with book._conn() as c:
        payload = _sync_payload(c)
    payload["autocat"] = ac
    payload["result"] = {k: result.get(k) for k in ("added", "updated", "superseded")}
    return jsonify(payload)


@bp.route("/api/book/link-account", methods=["POST"])
def api_book_link_account():
    """Attach a SimpleFIN account id to a book account; the next sync fills it in."""
    body = request.get_json(silent=True) or {}
    sfid = str(body.get("simplefin_id") or "").strip()
    aid = body.get("account_id")
    if not sfid or not str(aid).isdigit():
        return jsonify({"error": "account_id and simplefin_id are required"}), 400
    with book._conn() as c:
        acct = c.execute("SELECT simplefin_id FROM account WHERE id = ? AND closed = 0", (int(str(aid)),)).fetchone()
        if acct is None:
            return jsonify({"error": "no such account"}), 404
        if acct["simplefin_id"]:
            return jsonify({"error": "account is already linked"}), 409
        if c.execute("SELECT 1 FROM account WHERE simplefin_id = ?", (sfid,)).fetchone():
            return jsonify({"error": "that SimpleFIN account is already linked"}), 409
        c.execute("UPDATE account SET simplefin_id = ? WHERE id = ?", (sfid, int(str(aid))))
    return jsonify({"ok": True})

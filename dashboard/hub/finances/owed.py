# vault-code/dashboard/hub/finances/owed.py
"""What other people owe Sam — the data layer behind the /finances `owed` tab.

Its own database (data/owed.db) rather than a table in earnings.db, per the
warehouse contract: a new money surface is a new tab composed at the view layer,
never a table bolted onto another module's file.

One flat `owed` table. A person's balance, a group front, and the settled log are
all the same rows read three ways, so there is no parent/child schema to keep in
step. Money is REAL and every sum rounds to cents, matching finances/db.py.

`dir` is the sign: +1 they owe him, -1 he owes them (Venmo requests sent to him).
`amount` stays a magnitude; a person's total is the net of both. Everything that
chases money in (ask links, payment matching, groups, "paid back") is dir = 1 only.
"""

from __future__ import annotations

import sys
import re
from pathlib import Path
from typing import overload
from urllib.parse import quote

import frontmatter

from sqlite_helpers import connect as sqlite_connect, row as _row, rows as _rows

from . import trip_debts

_db_path: Path | None = None
_trips_path: Path | None = None
_contacts_dir: Path | None = None

OPEN_STATUSES = ("open", "requested")
_FIELDS = ("person", "what", "amount", "incurred", "paid_out",
           "status", "settled", "method", "grp", "note", "dir")


def init(db_path: Path, trips_path: Path | None = None,
         contacts_dir: Path | None = None) -> None:
    """`trips_path` wires up the trip-backed rows. Omitted, the tab still works
    and simply holds whatever is already in the table — the sync is additive.
    `contacts_dir` defaults to the vault's wiki/contacts beside data/."""
    global _db_path, _trips_path, _contacts_dir
    _db_path = db_path
    _trips_path = trips_path
    _contacts_dir = contacts_dir or Path(db_path).parent.parent / "wiki" / "contacts"


def _conn():
    return sqlite_connect(_db_path, "owed.db")


def _cents(v) -> float:
    return round(float(v or 0), 2)


def _in(r) -> bool:
    """Money coming to him. Rows read before migration 004 have no dir: +1."""
    return (r.get("dir") or 1) == 1


def _dir(v) -> int:
    return -1 if str(v).strip() == "-1" else 1


# Every read carries `paid_in` (money already applied to the line from arrived
# payments) and `due` (what is still owed). `amount` stays the original debt.
_SELECT = ("SELECT o.*, COALESCE((SELECT SUM(pl.amount) FROM payment_line pl"
           " WHERE pl.owed_id = o.id), 0) AS paid_in FROM owed o")


@overload
def _with_due(r: dict) -> dict: ...
@overload
def _with_due(r: None) -> None: ...
def _with_due(r):
    if r is not None:
        r["paid_in"] = _cents(r.get("paid_in"))
        r["due"] = _cents(r["amount"] - r["paid_in"])
    return r


# ── reads ─────────────────────────────────────────────────────────────────────

def list_rows(status: str | None = None) -> list[dict]:
    sql = _SELECT
    args: list = []
    if status == "open":
        sql += " WHERE status IN (?, ?)"
        args += list(OPEN_STATUSES)
    elif status:
        sql += " WHERE status = ?"
        args.append(status)
    # Oldest debt first: age is the thing that decides which one to chase.
    sql += " ORDER BY incurred IS NULL, incurred, person, id"
    with _conn() as conn:
        return [_with_due(r) for r in _rows(conn.execute(sql, args))]


def snapshot() -> dict:
    """The whole tab in one response: people, groups, settled, unassigned, totals."""
    sync_trips()
    rows = list_rows()

    people: dict[str, dict] = {}
    for r in rows:
        if r["status"] not in OPEN_STATUSES:
            continue
        p = people.setdefault(r["person"], {"person": r["person"], "total": 0.0, "lines": []})
        p["total"] = _cents(p["total"] + (r["due"] if _in(r) else -r["due"]))
        p["lines"].append(r)

    # Biggest balance first — the page is a chase list, not an address book.
    ordered = sorted(people.values(), key=lambda p: -p["total"])

    groups: dict[str, dict] = {}
    for r in rows:
        if r["status"] not in OPEN_STATUSES or not r["grp"] or not _in(r):
            continue
        g = groups.setdefault(r["grp"], {"grp": r["grp"], "total": 0.0, "people": 0})
        g["total"] = _cents(g["total"] + r["due"])
        g["people"] += 1

    settled = [r for r in rows if r["status"] == "paid"]
    settled.sort(key=lambda r: (r["settled"] or ""), reverse=True)

    live = [r for r in rows if r["status"] in OPEN_STATUSES]
    outstanding = _cents(sum(r["due"] for r in live if _in(r)))
    requested = _cents(sum(r["due"] for r in rows if r["status"] == "requested" and _in(r)))
    you_owe = _cents(sum(r["due"] for r in live if not _in(r)))

    return {
        "people": ordered,
        "groups": sorted(groups.values(), key=lambda g: -g["total"]),
        "settled": settled,
        "incoming": incoming(),
        "payments": list_payments(),
        "handles": handles(),
        "unassigned": [r for r in rows if r["status"] == "unassigned"],
        "totals": {
            "outstanding": outstanding,
            "requested": requested,
            "unrequested": _cents(outstanding - requested),
            "people": len({r["person"] for r in live if _in(r)}),
            "lines": sum(1 for r in live if _in(r)),
            "recovered": _cents(sum(r["amount"] if r["status"] == "paid" else r["paid_in"]
                                    for r in rows if _in(r))),
            "you_owe": you_owe,
            "you_owe_people": len({r["person"] for r in live if not _in(r)}),
            "you_owe_lines": sum(1 for r in live if not _in(r)),
            "net": _cents(outstanding - you_owe),
        },
    }


def get(rid: int) -> dict | None:
    with _conn() as conn:
        return _with_due(_row(conn.execute(_SELECT + " WHERE o.id = ?", (rid,)).fetchone()))


# ── writes ────────────────────────────────────────────────────────────────────

def add(body: dict) -> int:
    vals = {k: body.get(k) for k in _FIELDS}
    vals["person"] = (vals["person"] or "").strip()
    vals["what"] = (vals["what"] or "").strip()
    vals["amount"] = _cents(vals["amount"])
    vals["status"] = vals["status"] or "open"
    vals["note"] = vals["note"] or ""
    vals["dir"] = _dir(vals["dir"])
    for k in ("incurred", "paid_out", "settled", "method", "grp"):
        if vals[k] in ("", None):
            vals[k] = None
    if vals["paid_out"] is not None:
        vals["paid_out"] = _cents(vals["paid_out"])
    cols = ", ".join(_FIELDS)
    marks = ", ".join("?" for _ in _FIELDS)
    with _conn() as conn:
        cur = conn.execute(f"INSERT INTO owed ({cols}) VALUES ({marks})",
                           [vals[k] for k in _FIELDS])
        return int(cur.lastrowid)


def update(rid: int, body: dict) -> dict | None:
    """Patch named fields. Settling is just status='paid' + a settled date.

    The date is defaulted here rather than in the UI so the schema's
    "paid implies a date" check can never be the thing that rejects a click.
    """
    patch = {k: v for k, v in body.items() if k in _FIELDS}
    if not patch:
        return get(rid)
    if patch.get("status") == "paid" and not patch.get("settled"):
        existing = get(rid)
        if not (existing and existing["settled"]):
            from datetime import date
            patch["settled"] = date.today().isoformat()
    if patch.get("status") in OPEN_STATUSES:
        patch["settled"] = None      # un-settling must clear the date, not keep a lie
    if "amount" in patch:
        patch["amount"] = _cents(patch["amount"])
    if "dir" in patch:
        patch["dir"] = _dir(patch["dir"])
    sets = ", ".join(f"{k} = ?" for k in patch) + ", updated = datetime('now')"
    with _conn() as conn:
        conn.execute(f"UPDATE owed SET {sets} WHERE id = ?", [*patch.values(), rid])
    return get(rid)


def delete(rid: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM owed WHERE id = ?", (rid,))


# ── trip-backed rows ──────────────────────────────────────────────────────────

def sync_trips() -> dict:
    """Pull every Sam-fronted trip share into the table, and keep the amounts
    following the trips board.

    Runs on every read of the tab, which is what makes "change the cost in trips
    and the owed tab is right" true without anybody remembering to press
    anything. It is idempotent: rows are keyed by `src`, so a second run finds
    what the first one wrote.

    An amount is only overwritten while it still matches `src_amount` — the value
    last derived for that pointer. The moment Sam types his own figure over
    it the two diverge, and from then on the sync refreshes `src_amount` alone
    and leaves his number standing. That is the whole override mechanism: no
    flag, no lock column, just editing the amount.

    A settled row is history and is never repriced.

    ponytail: a derived row whose trip line later disappears (deleted, or moved
      off `booked`) is left alone rather than deleted — money someone owes should
      not evaporate because a board changed. To retire one, untick that person in
      the trip's "split between", which stops it being derived, then delete the
      row. Deleting it while the trip line still splits to them just brings it
      back on the next read.
    """
    if _trips_path is None:
        return {"added": 0, "repriced": 0, "held": 0}
    try:
        derived = trip_debts.derive(_trips_path)
    except Exception as e:
        print(f"owed: trip debt derive failed: {e}", file=sys.stderr)
        return {"added": 0, "repriced": 0, "held": 0, "error": True}

    added = repriced = held = 0
    with _conn() as conn:
        existing = {r["src"]: r for r in
                    _rows(conn.execute("SELECT * FROM owed WHERE src IS NOT NULL"))}
        for d in derived:
            cur = existing.get(d["src"])
            amt = _cents(d["amount"])
            if cur is None:
                cols = [*_FIELDS, "src", "src_amount"]
                vals = {**{k: d.get(k) for k in _FIELDS}, "src": d["src"], "src_amount": amt}
                vals["status"] = "open"
                vals["amount"] = amt
                vals["note"] = d.get("note") or ""
                vals["method"] = None
                vals["settled"] = None
                vals["dir"] = 1
                conn.execute(
                    f"INSERT INTO owed ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                    [vals[k] for k in cols])
                added += 1
                continue
            if cur["status"] == "paid":
                continue
            overridden = (cur["src_amount"] is not None
                          and abs(_cents(cur["amount"]) - _cents(cur["src_amount"])) > 0.005)
            if overridden:
                conn.execute("UPDATE owed SET src_amount = ?, updated = datetime('now')"
                             " WHERE id = ?", (amt, cur["id"]))
                held += 1
            elif abs(_cents(cur["amount"]) - amt) > 0.005 or cur["src_amount"] is None:
                conn.execute("UPDATE owed SET amount = ?, src_amount = ?, what = ?,"
                             " paid_out = ?, updated = datetime('now') WHERE id = ?",
                             (amt, amt, d["what"], d.get("paid_out"), cur["id"]))
                repriced += 1
    return {"added": added, "repriced": repriced, "held": held}


# ── requests — the ask half ───────────────────────────────────────────────────
#
# Nothing here sends anything. Venmo retired its developer API in 2016 and Zelle
# has never had a consumer one, so a request is a prefilled link he taps (Venmo)
# or a memo he pastes into Chase (Zelle). What the code owns is the note, and the
# note is what makes the return trip automatic: the tag it carries comes back
# verbatim in the payment notification, so the money that lands is matched to the
# debt by an id rather than by guessing from a name and an amount.

TAG_RE = re.compile(r"#o([\d.]+)")
_NOTE_CAP = 200          # Venmo truncates long notes; leave room for the tag


def _tag(ids) -> str:
    # Dots, not commas or plus signs: a comma is punctuation a payer might type
    # into a reply, and a plus decodes to a space in a query string.
    return "#o" + ".".join(str(i) for i in ids)


def parse_tag(note: str) -> list[int]:
    """Pull owed row ids back out of a payment note. Empty list when there is none."""
    m = TAG_RE.search(note or "")
    if not m:
        return []
    return [int(p) for p in m.group(1).split(".") if p.isdigit()]


def request(ids: list[int], mark: bool = True) -> dict:
    """Build the ask for one or more of a person's debts.

    Returns the Venmo charge link, the Zelle memo (same note, no link — Chase is
    the only place a Zelle request can be made), and whether a handle is missing.
    Marking them `requested` is the point of pressing the button, so it defaults
    on; the link is still returned when it is off.
    """
    # A line he owes is never asked for, even when "ask for all" sends its id.
    rows = [r for r in (get(i) for i in ids) if r and _in(r)]
    if not rows:
        return {"error": "nothing they owe you in that"}
    people = {r["person"] for r in rows}
    if len(people) > 1:
        return {"error": "one person at a time"}
    person = rows[0]["person"]
    amount = _cents(sum(r["due"] for r in rows))

    what = ", ".join(r["what"] for r in rows)
    if len(what) > _NOTE_CAP:
        what = f"{len(rows)} things"
    note = f"{what} {_tag(r['id'] for r in rows)}".strip()

    handle = (handle_for(person) or "").lstrip("@")
    q = f"txn=charge&amount={amount:.2f}&note={quote(note)}"
    # No handle: the link still opens Venmo with the amount and note filled, and
    # he picks the person there. Better than refusing to build it.
    url = f"https://venmo.com/{handle}?{q}" if handle else f"https://venmo.com/?{q}"

    if mark:
        with _conn() as conn:
            conn.execute(
                f"UPDATE owed SET status = 'requested', updated = datetime('now')"
                f" WHERE id IN ({', '.join('?' for _ in rows)}) AND status = 'open'",
                [r["id"] for r in rows])

    return {"person": person, "amount": amount, "note": note,
            "venmo_url": url, "handle": handle or None, "ids": [r["id"] for r in rows]}


# ── handles ───────────────────────────────────────────────────────────────────

_FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def _contacts() -> list[tuple[Path, list[str], str | None]]:
    """(page, [name, *aliases], venmo) for every contact page. People are tracked
    once, on their wiki contact; the person table only covers debtors with no page.
    A fresh read each call: ~70 small files, and a cache is how an edit made in
    Obsidian stops showing up here."""
    out = []
    if not _contacts_dir or not _contacts_dir.is_dir():
        return out
    for f in sorted(_contacts_dir.glob("*.md")):
        try:
            meta = frontmatter.load(str(f)).metadata
        except Exception as e:  # a contact page with unreadable frontmatter is skipped, not fatal
            print(f"owed: unreadable contact page: {e}", file=sys.stderr)
            continue
        aliases = meta.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        names = [str(n).strip() for n in [meta.get("name"), *aliases] if n]  # pyright: ignore[reportGeneralTypeIssues]  # YAML aliases is a list (str case wrapped above)
        venmo = str(meta.get("venmo") or "").strip().lstrip("@") or None
        if names:
            out.append((f, names, venmo))
    return out


def _contact_for(person: str):
    key = (person or "").strip().casefold()
    return next((c for c in _contacts() if key in {n.casefold() for n in c[1]}), None)


def handles() -> dict:
    """Every known handle keyed by name; a contact page beats the person table."""
    with _conn() as conn:
        out = {r["person"]: r["venmo"]
               for r in _rows(conn.execute("SELECT person, venmo FROM person"))}
    for _, names, venmo in _contacts():
        if venmo:
            out.update({n: venmo for n in names})
    return out


def handle_for(person: str) -> str | None:
    key = (person or "").strip().casefold()
    return next((v for k, v in handles().items() if k.casefold() == key and v), None)


def _write_contact_venmo(page: Path, venmo: str | None) -> None:
    # A line edit, not frontmatter.dumps: dumping re-serialises `[[wikilink]]`
    # relationship values into nested YAML lists and breaks every edge on the page.
    text = page.read_text(encoding="utf-8")
    m = _FM.match(text)
    if not m:
        return
    lines = [ln for ln in m.group(1).split("\n") if not ln.startswith("venmo:")]
    if venmo:
        lines.append(f'venmo: "{venmo}"')
    page.write_text(f"---\n{chr(10).join(lines)}\n---\n" + text[m.end():], encoding="utf-8")


def set_handle(person: str, venmo: str | None) -> None:
    person = (person or "").strip()
    venmo = (venmo or "").strip().lstrip("@") or None
    if not person:
        return
    contact = _contact_for(person)
    if contact:
        _write_contact_venmo(contact[0], venmo)
    with _conn() as conn:
        conn.execute(
            "INSERT INTO person (person, venmo) VALUES (?, ?)"
            " ON CONFLICT(person) DO UPDATE SET venmo = excluded.venmo,"
            " updated = datetime('now')", (person, venmo))


# ── payments — the arrival half ───────────────────────────────────────────────

def list_payments(status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM payment"
    args: list = []
    if status:
        sql += " WHERE status = ?"
        args.append(status)
    sql += " ORDER BY received DESC, id DESC"
    with _conn() as conn:
        out = _rows(conn.execute(sql, args))
        for p in out:
            p["lines"] = _rows(conn.execute(
                "SELECT pl.owed_id, pl.amount, o.what FROM payment_line pl"
                " JOIN owed o ON o.id = pl.owed_id WHERE pl.payment_id = ?", (p["id"],)))
        return out


def record_payment(p: dict) -> int | None:
    """Insert one arrived transfer. Returns None when its ext_id is already known.

    That None is the idempotency guarantee the scanner leans on: re-reading the
    same mailbox week after week inserts each transaction exactly once, with no
    high-water mark to keep in step and no risk of double-settling a debt.
    """
    with _conn() as conn:
        if p.get("ext_id"):
            hit = conn.execute("SELECT id FROM payment WHERE ext_id = ?",
                               (p["ext_id"],)).fetchone()
            if hit:
                return None
        cur = conn.execute(
            "INSERT INTO payment (person, amount, method, received, note, ext_id, msg_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            ((p.get("person") or "").strip(), _cents(p["amount"]), p["method"],
             p["received"], p.get("note") or "", p.get("ext_id"), p.get("msg_id")))
        return int(cur.lastrowid)


def apply_payment(pid: int, owed_ids: list[int]) -> dict | None:
    """Deduct this payment from the named debts, in the order given.

    Each line takes what it still owes or what is left of the payment, whichever
    is smaller. A line is settled only when it reaches zero; a short payment
    leaves it open with a smaller `due` (Teddy's $30 against a $36.40 share,
    2026-09-28). Money left over after the last line stays unallocated.
    """
    with _conn() as conn:
        pay = _row(conn.execute("SELECT * FROM payment WHERE id = ?", (pid,)).fetchone())
        if pay is None:
            return None
        left = _cents(pay["amount"] - conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payment_line WHERE payment_id = ?",
            (pid,)).fetchone()[0])
        for oid in owed_ids:
            row = _with_due(_row(conn.execute(_SELECT + " WHERE o.id = ?", (oid,)).fetchone()))
            if row is None or row["status"] == "paid" or not _in(row) or left <= 0:
                continue
            take = min(row["due"], left)
            if take <= 0:
                continue
            conn.execute(
                "INSERT INTO payment_line (payment_id, owed_id, amount) VALUES (?, ?, ?)"
                " ON CONFLICT(payment_id, owed_id) DO UPDATE SET amount = amount + excluded.amount",
                (pid, oid, take))
            left = _cents(left - take)
            if take >= row["due"] - 0.005:
                conn.execute(
                    "UPDATE owed SET status = 'paid', settled = ?, method = ?,"
                    " updated = datetime('now') WHERE id = ?",
                    (pay["received"], pay["method"], oid))
        conn.execute("UPDATE payment SET status = 'applied' WHERE id = ?", (pid,))
    return get_payment(pid)


def unapply_payment(pid: int) -> dict | None:
    """Undo an application: the debts reopen and the payment waits again.

    Reopened lines come back as `open`, not `requested`. Whether he had asked is
    not recorded on the row, and claiming he did would inflate the "asked for"
    total, which is a chase list — understating it is the safe direction.
    """
    with _conn() as conn:
        oids = [r["owed_id"] for r in _rows(conn.execute(
            "SELECT owed_id FROM payment_line WHERE payment_id = ?", (pid,)))]
        for oid in oids:
            # Only lines this payment closed reopen; a part-paid line never left open.
            conn.execute("UPDATE owed SET status = 'open', settled = NULL, method = NULL,"
                         " updated = datetime('now') WHERE id = ? AND status = 'paid'", (oid,))
        conn.execute("DELETE FROM payment_line WHERE payment_id = ?", (pid,))
        conn.execute("UPDATE payment SET status = 'unapplied' WHERE id = ?", (pid,))
    return get_payment(pid)


def set_payment_status(pid: int, status: str) -> dict | None:
    if status not in ("unapplied", "applied", "ignored"):
        return None
    with _conn() as conn:
        conn.execute("UPDATE payment SET status = ? WHERE id = ?", (status, pid))
    return get_payment(pid)


def get_payment(pid: int) -> dict | None:
    with _conn() as conn:
        p = _row(conn.execute("SELECT * FROM payment WHERE id = ?", (pid,)).fetchone())
        if p:
            p["lines"] = _rows(conn.execute(
                "SELECT pl.owed_id, pl.amount, o.what FROM payment_line pl"
                " JOIN owed o ON o.id = pl.owed_id WHERE pl.payment_id = ?", (pid,)))
        return p


def delete_payment(pid: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM payment WHERE id = ?", (pid,))


# ── matching an arrival to a debt ─────────────────────────────────────────────

def _norm(name: str) -> str:
    return " ".join((name or "").lower().split())


def _first(name: str) -> str:
    parts = _norm(name).split()
    return parts[0] if parts else ""


def _same_given_name(a: str, b: str) -> bool:
    """Given names agree, allowing one to be a shortening of the other."""
    if not a or not b:
        return False
    if a == b:
        return True
    return len(a) >= 3 and len(b) >= 3 and (a.startswith(b) or b.startswith(a))


def match_person(name: str, candidates: list[str]) -> str | None:
    """Best open-debtor for a payer name, or nothing.

    The rule is that the GIVEN names must agree — exactly, or one shortening the
    other ("Leo" for "Leonardo"). A shared surname is not a match and never will
    be: three Riveras owe him money, and the first version of this happily read a
    $120 Zelle from Jack Rivera as a repayment from Ben Rivera because they share
    "rivera". That is the same shape as answering a question about Dana with a
    record about Naveed, and it is not recoverable by looking at the tab — the
    wrong debt just says paid.

    Ambiguity resolves to None rather than to a coin flip. An unmatched payment
    costs one click; a wrongly matched one costs a debt nobody chases again.
    """
    n = _norm(name)
    if not n:
        return None
    for c in candidates:
        if _norm(c) == n:
            return c
    first = _first(n)
    hits = [c for c in candidates if _same_given_name(first, _first(c))]
    return hits[0] if len(hits) == 1 else None


def auto_apply(pid: int) -> bool:
    """Settle a payment on its own only when the tag says exactly which debts.

    Two conditions, both required: the note carries the tag this code wrote into
    the request, and the amount matches those lines to the cent. Anything else —
    a tagged request paid short, an untagged transfer, a name that merely looks
    familiar — is left unapplied for a click. Guessing here writes a wrong
    settlement into the log that nobody would ever notice.
    """
    pay = get_payment(pid)
    if not pay or pay["status"] != "unapplied":
        return False
    ids = parse_tag(pay["note"])
    if not ids:
        return False
    rows = [r for r in (get(i) for i in ids) if r and r["status"] in OPEN_STATUSES and _in(r)]
    if len(rows) != len(ids):
        return False
    if abs(_cents(sum(r["due"] for r in rows)) - _cents(pay["amount"])) > 0.005:
        return False
    apply_payment(pid, ids)
    return True


def incoming() -> list[dict]:
    """Unapplied arrivals, each with the open debts it plausibly settles."""
    rows = [r for r in list_rows() if _in(r)]
    open_people = sorted({r["person"] for r in rows if r["status"] in OPEN_STATUSES})
    out = []
    for p in list_payments("unapplied"):
        who = match_person(p["person"], open_people)
        lines = [r for r in rows
                 if r["status"] in OPEN_STATUSES and who and r["person"] == who]
        tagged = set(parse_tag(p["note"]))
        for line in lines:
            line["suggested"] = line["id"] in tagged
        # No tag to go on: preselect the single line that matches the amount, if
        # exactly one does. Two lines at $40 preselect neither.
        if not tagged:
            exact = [line for line in lines
                     if abs(line["due"] - _cents(p["amount"])) <= 0.005]
            if len(exact) == 1:
                exact[0]["suggested"] = True
        out.append({**p, "matched_person": who, "candidates": lines})
    return out

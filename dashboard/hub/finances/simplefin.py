"""SimpleFIN Bridge sync into data/book.db.

    cd dashboard/hub
    python -m finances.simplefin claim <setup-token>
    python -m finances.simplefin sync [--fixture PATH] [--db PATH]

The access URL carries basic-auth credentials: it lives only in dashboard/.env
(written 0600 where the filesystem honors it; /mnt/c does not) and is never
printed, logged or put in an error message.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

_DASHBOARD = str(Path(__file__).resolve().parents[2])
if _DASHBOARD not in sys.path:
    sys.path.insert(0, _DASHBOARD)

from finances import book  # noqa: E402

ENV_KEY = "SIMPLEFIN_ACCESS_URL"
ENV_FILE = Path(_DASHBOARD) / ".env"
MAX_BACK_DAYS = 44  # SimpleFIN warns past 45 days, and a dormant card pins the window there
CAL_MIN_CENTS = 5000  # below $50 the balance sign is not calibrated yet


class Busy(RuntimeError):
    """Another sync of the same book is running."""


# --- credentials ------------------------------------------------------------

_CRED = re.compile(r"https?://[^/\s@]*@")


def _redact(text: str, access: str = "") -> str:
    if access:
        text = text.replace(access, "[access-url]")
    return _CRED.sub("https://[redacted]@", text)


def access_url_or_none() -> str | None:
    """The access URL, read from ENV_FILE fresh on every call so a re-claim lands
    without a Hub restart. The file wins over os.environ, which the Hub seeded
    from the same file at startup; the environment is only the fallback."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() == ENV_KEY and value.strip():
                return value.strip()
    return os.environ.get(ENV_KEY) or None


def _access_url() -> str:
    url = access_url_or_none()
    if not url:
        raise RuntimeError(f"{ENV_KEY} is not set in dashboard/.env")
    return url


def _http(url: str, method: str = "GET") -> str:
    """One request. Basic-auth creds embedded in the URL move into a header."""
    parts = urlsplit(url)
    req_url = urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))
    req = urllib.request.Request(req_url, method=method, data=b"" if method == "POST" else None)
    # The Bridge answers 403 to urllib's default "Python-urllib" agent (seen 2026-10-07).
    req.add_header("User-Agent", "vault-hub/1.0")
    if parts.username is not None:
        cred = f"{unquote(parts.username)}:{unquote(parts.password or '')}".encode()
        # unredirected: a redirect must never carry the credentials to another host
        req.add_unredirected_header("Authorization", "Basic " + base64.b64encode(cred).decode())
    # 180s: the Bridge refreshes banks inside this request and read-timed-out at 60s
    # on 71 of 101 scheduled pulls 2026-10-08..20, while a manual pull took 2s.
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read().decode()


def claim(token: str, env_file: Path | None = None, post=None) -> None:
    """Trade a single-use setup token for an access URL and store it in .env."""
    if env_file is None:
        env_file = ENV_FILE
    token = token.strip()
    claim_url = base64.b64decode(token + "=" * (-len(token) % 4)).decode().strip()
    if not claim_url.startswith("https://"):
        raise ValueError("setup token does not decode to an https claim URL")
    try:
        access = (post or (lambda u: _http(u, "POST")))(claim_url).strip()
    except Exception as e:
        raise RuntimeError(_redact(f"claim failed: {type(e).__name__}: {e}", claim_url)) from None
    if not access.startswith("https://"):
        raise RuntimeError("claim response was not an access URL")

    env_file = Path(env_file)
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    new = f"{ENV_KEY}={access}"
    if any(ln.startswith(f"{ENV_KEY}=") for ln in lines):
        lines = [new if ln.startswith(f"{ENV_KEY}=") else ln for ln in lines]
    else:
        lines.append(new)
    tmp = env_file.with_name(env_file.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, env_file)
    print(f"{ENV_KEY} saved to {env_file}")


def _network_fetch(start: int) -> dict:
    access = _access_url()
    try:
        return json.loads(_http(f"{access.rstrip('/')}/accounts?start-date={start}&pending=1"))
    except Exception as e:
        # The Bridge's 403s come and go on a good token; the body is the only clue to who refused.
        body = e.read(300).decode(errors="replace") if isinstance(e, urllib.error.HTTPError) else ""
        msg = " ".join(f"fetch failed: {type(e).__name__}: {e} {body}".split())
        raise RuntimeError(_redact(msg, access)) from None


# --- parsing helpers --------------------------------------------------------

def _cents(s) -> int:
    return int(Decimal(str(s)).scaleb(2).to_integral_value())


def _day(epoch) -> str:
    return datetime.fromtimestamp(int(epoch)).date().isoformat()  # local day, like every other date here


def _errors(payload: dict) -> list[str]:
    out = [str(e) for e in payload.get("errors") or []]
    for e in payload.get("errlist") or []:
        if isinstance(e, dict):
            msg = e.get("msg") or e.get("message") or ""
            out.append(f"{e['code']}: {msg}" if e.get("code") else str(msg))
        else:
            out.append(str(e))
    return list(dict.fromkeys(m for m in out if m))


# --- account linking --------------------------------------------------------

_GENERIC = {"bank", "card", "it", "chrome", "credit", "account", "the", "of", "usa", "na"}
_ALIAS = {"citibank": "citi"}


def _norm(name: str) -> list[str]:
    name = re.sub(r"\(\s*\d+\s*\)", " ", name.lower())
    toks = [_ALIAS.get(t, t) for t in re.sub(r"[^a-z0-9 ]+", " ", name).split()]
    return [t for t in toks if t not in _GENERIC and not t.isdigit()]


def _last4(name: str) -> str | None:
    m = re.findall(r"(?<!\d)(\d{4})(?!\d)", name)
    return m[-1] if m else None


def _same_account(a: list[str], b: list[str]) -> bool:
    if not a or not b:
        return False
    sa, sb = set(a), set(b)
    return sa <= sb or sb <= sa or (a[0] == b[0] and len(sa & sb) > 1)


def _link(c, acct: dict, taken: set[int]) -> int | None:
    """Book account id for a SimpleFIN account, persisting simplefin_id once linked."""
    row = c.execute("SELECT id FROM account WHERE simplefin_id = ?", (acct["id"],)).fetchone()
    if row:
        return row["id"]
    free = [r for r in c.execute(
        "SELECT id, name FROM account WHERE closed = 0 AND simplefin_id IS NULL") if r["id"] not in taken]
    sf_name = acct.get("name", "")
    org = (acct.get("org") or {}).get("name", "")
    found: list[int] = []
    l4 = _last4(sf_name)
    if l4:
        found = [r["id"] for r in free if l4 in re.findall(r"\d{4}", r["name"])]
    if len(found) != 1:
        cands = [_norm(sf_name), _norm(f"{org} {sf_name}")]
        found = [r["id"] for r in free
                 if any(_same_account(cn, _norm(r["name"])) for cn in cands)]
    if len(found) != 1:
        return None
    c.execute("UPDATE account SET simplefin_id = ? WHERE id = ?", (acct["id"], found[0]))
    return found[0]


# --- start date -------------------------------------------------------------

def _start_epoch(c) -> int:
    """5 days before the last good run, pulled back to the stalest linked account.

    A run that skipped an account (bank error, not yet linked) still counts as
    good, so each linked account's newest bank row also bounds the start: the
    skipped one back-fills on the next pull.
    """
    floor = datetime.now(timezone.utc) - timedelta(days=MAX_BACK_DAYS)
    last = c.execute("SELECT at FROM sync_run WHERE status IN ('ok','partial') "
                     "ORDER BY id DESC LIMIT 1").fetchone()
    if last:
        start = datetime.fromisoformat(last["at"]).astimezone(timezone.utc) - timedelta(days=5)
        # ponytail: a dormant card pins the window at its last row (capped by MAX_BACK_DAYS);
        # a per-account last-seen column if the wider fetch ever matters
        for r in c.execute(
                "SELECT (SELECT MAX(date) FROM txn WHERE account_id = a.id AND simplefin_id IS NOT NULL) AS sf, "
                "(SELECT MAX(date) FROM txn WHERE account_id = a.id) AS any_d "
                "FROM account a WHERE a.simplefin_id IS NOT NULL AND a.closed = 0"):
            d = r["sf"] or r["any_d"]
            acct_start = (datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
                          - timedelta(days=5 if r["sf"] else 14)) if d else floor
            start = min(start, acct_start)
    else:
        r = c.execute("SELECT MAX(date) AS d FROM txn WHERE source = 'ynab'").fetchone()
        start = (datetime.fromisoformat(r["d"]).replace(tzinfo=timezone.utc) - timedelta(days=14)
                 if r["d"] else floor)
    return int(max(start, floor).timestamp())


# --- ingest -----------------------------------------------------------------

def _set_balance(c, acct_id: int, bal_cents: int, at: str) -> None:
    """Record the bank balance, calibrating balance_sign once (in this same transaction)."""
    a = c.execute("SELECT type, balance_sign, balance_cents, sign_calibrated FROM account WHERE id = ?",
                  (acct_id,)).fetchone()
    sign = a["balance_sign"]
    if not a["sign_calibrated"]:
        if abs(bal_cents) < CAL_MIN_CENTS and a["balance_cents"] is not None:
            return  # near-zero: an overpaid card could invert the sign, so wait
        sign = -1 if a["type"] == "credit" else 1
        if a["balance_cents"] is not None and abs(-sign * bal_cents - a["balance_cents"]) < abs(
                sign * bal_cents - a["balance_cents"]):
            sign = -sign
    c.execute("UPDATE account SET balance_sign = ?, balance_cents = ?, balance_at = ?, "
              "sign_calibrated = 1 WHERE id = ?", (sign, sign * bal_cents, at, acct_id))


def _payee_key(text: str) -> tuple[str, ...]:
    """Bank text reduced to its merchant words: "MTA*NYCT PAYGO" -> (mta, nyct, paygo),
    "Amazon.com*3C6XP87V3" -> (amazon, com). Any token with a digit (order ids, store
    numbers, masked account numbers) is dropped."""
    text = re.sub(r"['\u2019]", "", text.lower())
    return tuple(t for t in re.sub(r"[^a-z0-9]+", " ", text).split() if not re.search(r"\d", t))


def payee_index(c) -> tuple[dict, dict]:
    """(history: raw-text key -> {payee ids}, names: payee-name key -> {payee ids}) for
    ordinary payees (no transfer payees). Built once per sync."""
    hist: dict[tuple, set] = {}
    names: dict[tuple, set] = {}
    for r in c.execute("SELECT id, name FROM payee WHERE transfer_account_id IS NULL "
                       "AND name NOT LIKE 'Transfer : %'"):
        k = _payee_key(r["name"])
        if len("".join(k)) >= 4:  # "SP", "FS": too short to say anything
            names.setdefault(k, set()).add(r["id"])
    for r in c.execute("SELECT DISTINCT t.raw_description AS raw, t.payee_id FROM txn t JOIN payee p "
                       "ON p.id = t.payee_id WHERE p.transfer_account_id IS NULL AND t.raw_description != ''"):
        k = _payee_key(r["raw"])
        if len("".join(k)) >= 4:
            hist.setdefault(k, set()).add(r["payee_id"])
    return hist, names


def match_payee(index: tuple[dict, dict], desc: str) -> int | None:
    """An existing payee for this bank text, or None when nothing or more than one fits.
    First the same text seen before on a row that has a payee, else the longest payee
    name whose words open the text ("UBER *EATS" -> Uber Eats, not Uber)."""
    hist, names = index
    k = _payee_key(desc)
    if not k:
        return None
    seen = hist.get(k, set())
    if len(seen) == 1:
        return next(iter(seen))
    for n in range(len(k), 0, -1):
        ids = names.get(k[:n], set())
        if ids:
            return next(iter(ids)) if len(ids) == 1 else None
    return None


def _ingest_account(c, acct_id: int, acct: dict, now: str, today: str, res: dict, errors: list,  # noqa: C901 - one account's pull: dedupe, insert, reconcile
                    new_charges: list, touched: list, payees: tuple = ({}, {})) -> None:
    sync_from = c.execute("SELECT sync_from FROM account WHERE id = ?", (acct_id,)).fetchone()[0]
    fresh: dict[str, tuple] = {}  # simplefin id -> (cents, day, desc, pending), not yet in the book
    for t in acct.get("transactions") or []:
        try:
            sid, cents = str(t["id"]), _cents(t["amount"])
            posted = int(t.get("posted") or 0)
            pending = 1 if (t.get("pending") or not posted) else 0
            day = _day(posted) if posted else _day(t["transacted_at"]) if t.get("transacted_at") else today
        except (KeyError, InvalidOperation, ValueError, TypeError):
            errors.append(f"skipped a malformed transaction in {acct.get('name', '?')}")
            continue
        desc = t.get("description") or t.get("payee") or ""
        if sync_from and day < sync_from:
            continue
        cur = c.execute("SELECT * FROM txn WHERE simplefin_id = ?", (sid,)).fetchone()
        if cur:
            # deleted = 2 is a hold _expire_pending aged out; the bank posting it brings it back
            if cur["deleted"] and not (cur["deleted"] == 2 and not pending):
                continue
            # category, memo and approved are never touched on a repeat
            new_pending = cur["pending"] and pending
            if cents != cur["amount_cents"] and (
                    cur["transfer_txn_uid"] or cur["transfer_account_id"] is not None
                    or c.execute("SELECT 1 FROM split WHERE txn_id = ?", (cur["id"],)).fetchone()):
                errors.append(f"bank changed the amount of a split or transfer row ({cur['uid']}: "
                              f"{cur['amount_cents']} -> {cents} cents); kept the book amount, fix it by hand")
                cents = cur["amount_cents"]
            if cur["source"] == "ynab":
                day = cur["date"]  # a YNAB row keeps its purchase date, not the bank's post date
            if cur["deleted"] or (cur["amount_cents"], cur["date"], cur["raw_description"], cur["pending"]) != (
                    cents, day, desc, new_pending):
                c.execute("UPDATE txn SET amount_cents=?, date=?, raw_description=?, pending=?, "
                          "cleared=?, deleted=0, updated_at=? WHERE id=?",
                          (cents, day, desc, new_pending, 0 if new_pending else 1, now, cur["id"]))
                res["updated"] += 1
                touched.append(cur["uid"])
            elif cur["pending"]:
                c.execute("UPDATE txn SET updated_at = ? WHERE id = ?", (now, cur["id"]))  # last seen
            continue
        fresh.setdefault(sid, (cents, day, desc, pending))
    adopted = _adopt(c, acct_id, {sid: f for sid, f in fresh.items() if not f[3]})
    for sid, (cents, day, desc, pending) in fresh.items():
        if sid in adopted:
            c.execute("UPDATE txn SET simplefin_id=?, pending=0, cleared=1, updated_at=?, "
                      "first_seen_at=COALESCE(first_seen_at, ?) WHERE id=?",
                      (sid, now, now, adopted[sid]["id"]))
            res["updated"] += 1
            touched.append(adopted[sid]["uid"])
            continue
        alias = c.execute("SELECT payee_id FROM payee_alias WHERE raw = ?", (desc,)).fetchone()
        payee_id = alias["payee_id"] if alias else match_payee(payees, desc)
        c.execute(
            "INSERT INTO txn(uid, simplefin_id, account_id, date, amount_cents, payee_id, "
            "raw_description, approved, cleared, pending, source, updated_at, first_seen_at) "
            "VALUES (?,?,?,?,?,?,?,0,?,?,'simplefin',?,?)",
            (f"sf:{sid}", sid, acct_id, day, cents, payee_id, desc,
             0 if pending else 1, pending, now, now))
        res["added"] += 1
        touched.append(f"sf:{sid}")
        if not pending:
            new_charges.append(f"sf:{sid}")


def _adopt(c, acct_id: int, posted: dict[str, tuple]) -> dict:
    """Overlap adopt: pair new posted bank rows with book rows of the same amount that
    have no simplefin_id (YNAB imports, convert_to_transfer's xfer: rows) within 3 days.

    Pairs are taken closest date first across the whole batch (0, then 1, 2, 3 days),
    so each book row goes to its nearest bank row. Returns {simplefin id: row}.
    """
    if not posted:
        return {}
    days = [f[1] for f in posted.values()]
    cands = c.execute(
        "SELECT id, uid, date, amount_cents FROM txn WHERE account_id=? AND simplefin_id IS NULL "
        "AND deleted=0 AND pending=0 AND date BETWEEN date(?, '-3 day') AND date(?, '+3 day')",
        (acct_id, min(days), max(days))).fetchall()
    pairs = sorted(
        (abs((date.fromisoformat(r["date"]) - date.fromisoformat(day)).days), r["id"], sid)
        for sid, (cents, day, _, _) in posted.items() for r in cands if r["amount_cents"] == cents)
    rows = {r["id"]: r for r in cands}
    out: dict[str, object] = {}
    used: set[int] = set()
    for dist, rid, sid in pairs:
        if dist <= 3 and sid not in out and rid not in used:
            out[sid] = rows[rid]
            used.add(rid)
    return out


def _supersede(c, charge_uids: list[str], now: str) -> int:
    """Pending holds settled by the posted rows just inserted (new id, changed description).

    Exact matches only; a tip match waits for the /finance skill's confirm step
    (find_superseded_holds still reports it). The charge keeps its own fields and
    takes what it lacks from its holds: their memos joined, a category, approval
    (only when every hold names the charge's merchant), and for a single hold its
    split legs.
    """
    if not charge_uids:
        return 0
    # Runs on the ingest connection: a failure rolls back the whole pull.
    q = ",".join("?" * len(charge_uids))
    lo = c.execute(f"SELECT MIN(date) FROM txn WHERE uid IN ({q})", charge_uids).fetchone()[0]  # noqa: S608 - q is only "?" placeholders
    since = (date.fromisoformat(lo) - timedelta(days=14)).isoformat()
    groups: dict[str, tuple[dict, list[dict]]] = {}
    for h, chg, conf in book._match_holds(c, since, set(charge_uids)):
        if conf == "exact":
            groups.setdefault(chg["uid"], (chg, []))[1].append(h)
    n = 0
    for chg, holds in groups.values():
        memo = "; ".join(dict.fromkeys(
            m.strip() for m in [chg["memo"]] + [h["memo"] for h in holds] if m and m.strip()))
        cat = chg["category_id"] or next((h["category_id"] for h in holds if h["category_id"]), None)
        if (len(holds) == 1 and not chg["category_id"]
                and c.execute("SELECT 1 FROM split WHERE txn_id = ?", (holds[0]["rid"],)).fetchone()
                and not c.execute("SELECT 1 FROM split WHERE txn_id = ?", (chg["rid"],)).fetchone()):
            c.execute("UPDATE split SET txn_id = ? WHERE txn_id = ?", (chg["rid"], holds[0]["rid"]))
            cat = None  # a split parent carries no category
        approved = chg["approved"] or (all(book.same_payee(h, chg) for h in holds)
                                       and max(h["approved"] for h in holds))
        c.execute("UPDATE txn SET category_id=?, memo=?, approved=?, updated_at=? WHERE id=?",
                  (cat, memo, approved, now, chg["rid"]))
        for h in holds:
            c.execute("UPDATE txn SET deleted=1, updated_at=? WHERE id=?", (now, h["rid"]))
        n += len(holds)
    return n


def _names(desc: str, acct_name: str, last4: str | None, issuer_ok: bool = False) -> bool:
    """Does a bank description name this account (by last 4 or by its product words)?
    `issuer_ok`: the account is its issuer's only open one, so the issuer word alone counts
    ("CITI CARD ONLINE PAYMENT" never says "Diamond Preferred")."""
    if last4 and re.search(rf"(?<!\d){last4}(?!\d)", desc):
        return True
    toks = _norm(acct_name)
    generic = {"checking", "savings", "total", "convenience"}
    keys = [t for t in toks[1:] if t not in generic] or toks[:1]
    if issuer_ok:
        keys = keys + toks[:1]
    return bool(set(keys) & set(_norm(desc)))


def _issuer_unique(c) -> dict[int, bool]:
    """Open account id -> is it the only open account under its issuer word?"""
    accts = c.execute("SELECT id, name FROM account WHERE closed = 0").fetchall()
    first = {a["id"]: (_norm(a["name"]) or [""])[0] for a in accts}
    return {i: list(first.values()).count(w) == 1 for i, w in first.items()}


_CARD_PAY = re.compile(r"payment|pmt|autopay", re.I)


def _card_paid(c, t, last4s: dict[int, str | None], unique: dict[int, bool]):
    """The one open credit account a checking outflow pays, by its description, else None."""
    if t["amount_cents"] >= 0 or not _CARD_PAY.search(t["raw_description"] or ""):
        return None
    src = c.execute("SELECT type FROM account WHERE id = ?", (t["account_id"],)).fetchone()
    if not src or src["type"] == "credit":
        return None
    hits = [a for a in c.execute("SELECT id, name FROM account WHERE closed = 0 AND type = 'credit'")
            if _names(t["raw_description"] or "", a["name"], last4s.get(a["id"]), unique.get(a["id"], False))]
    return hits[0] if len(hits) == 1 else None


def _link_transfers(c, touched: list[str], last4s: dict[int, str | None]) -> None:
    """An outflow plus the opposite inflow in another account within 5 days become a
    transfer pair when the outflow's description names the inflow's account. Either
    side may be the one just touched: the inflow often posts a sync later."""
    if not touched:
        return
    # Runs on the ingest connection.
    unique = _issuer_unique(c)
    for uid in dict.fromkeys(touched):
        t = c.execute("SELECT t.*, a.name AS aname FROM txn t JOIN account a ON a.id=t.account_id "
                      "WHERE uid=? AND deleted=0 AND pending=0 AND transfer_txn_uid IS NULL "
                      "AND amount_cents != 0", (uid,)).fetchone()
        if not t:
            continue
        for o in c.execute(
                "SELECT t.uid, t.account_id, t.raw_description, a.name AS aname "
                "FROM txn t JOIN account a ON a.id=t.account_id "
                "WHERE t.account_id != ? AND t.deleted=0 AND t.pending=0 AND t.transfer_txn_uid IS NULL "
                "AND t.amount_cents = ? AND ABS(julianday(t.date)-julianday(?)) <= 5 "
                "ORDER BY ABS(julianday(t.date)-julianday(?)), t.id",
                (t["account_id"], -t["amount_cents"], t["date"], t["date"])).fetchall():
            out, inn = (t, o) if t["amount_cents"] < 0 else (o, t)
            if _names(out["raw_description"] or "", inn["aname"], last4s.get(inn["account_id"]),
                      unique.get(inn["account_id"], False)):
                book._link_transfer(c, uid, t["account_id"], t["aname"],
                                    o["uid"], o["account_id"], o["aname"])
                break
        else:
            # a card payment whose card side has not synced (or never will: a broken bank login)
            # becomes a transfer now; _adopt pairs the card's own posting with the placeholder later
            card = _card_paid(c, t, last4s, unique)
            if card:
                book._add_counterpart(c, t, card["id"], card["name"])


def _expire_pending(c, seen_accounts: set[int], now: str) -> None:
    """Drop pending rows gone from the bank feed.

    Absence is tracked with txn.updated_at, which every sync stamps on each pending
    row it sees (no schema change). A row not stamped since the second-latest prior
    run was missing from the current run and two before it, so with the 14-day age
    test it is deleted. YNAB-imported holds count too: they have no simplefin_id,
    so the feed never reports them and they only ever age out. Expired rows get
    deleted = 2, not 1, so _ingest_account can revive one the bank later posts.
    """
    prior = c.execute("SELECT at FROM sync_run WHERE status IN ('ok','partial') "
                      "ORDER BY id DESC LIMIT 2").fetchall()
    if len(prior) < 2 or not seen_accounts:
        return
    q = ",".join("?" * len(seen_accounts))
    c.execute(f"UPDATE txn SET deleted=2, updated_at=? WHERE source IN ('simplefin','ynab') "  # noqa: S608 - q is only "?" placeholders
              f"AND pending=1 AND deleted=0 AND updated_at < ? AND date < ? AND account_id IN ({q})",
              (now, prior[1]["at"], (date.today() - timedelta(days=14)).isoformat(), *seen_accounts))


# --- entry point ------------------------------------------------------------

def _lock_path() -> Path:
    # ponytail: one lock per book file in the temp dir, so the vault's data/ gets no stray file
    key = hashlib.sha1(str(book._path().resolve()).encode(), usedforsecurity=False).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"book-sync-{key}.lock"


def sync(fetch=None) -> dict:
    """One pull. Returns {added, updated, superseded, status, errors}; always writes a sync_run row.

    Raises Busy, writing nothing, when another sync of this book holds the lock.
    """
    fd = os.open(_lock_path(), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy("a book sync is already running") from None
        return _sync(fetch)
    finally:
        os.close(fd)


def _sync(fetch) -> dict:
    res = {"added": 0, "updated": 0, "superseded": 0}
    errors: list[str] = []
    status = "ok"
    now = book._now()
    try:
        with book._conn() as c:
            start = _start_epoch(c)
        payload = (fetch or _network_fetch)(start)
        errors = _errors(payload)
        new_charges: list[str] = []
        touched: list[str] = []
        seen: set[int] = set()
        last4s: dict[int, str | None] = {}
        with book._conn() as c:
            payees = payee_index(c)
            taken: set[int] = set()
            for acct in payload.get("accounts") or []:
                acct_id = _link(c, acct, taken)
                if acct_id is None:
                    n = len(acct.get("transactions") or [])
                    errors.append(f"SimpleFIN account '{acct.get('name', '?')}' is not linked to a book "
                                  f"account; {n} transactions not written (id {acct.get('id', '?')})")
                    continue
                taken.add(acct_id)
                seen.add(acct_id)
                last4s[acct_id] = _last4(acct.get("name", ""))
                _ingest_account(c, acct_id, acct, now, date.today().isoformat(), res, errors,
                                new_charges, touched, payees)
                if acct.get("balance") is not None:
                    try:
                        at = (datetime.fromtimestamp(int(acct["balance-date"])).isoformat(timespec="seconds")
                              if acct.get("balance-date") else now)
                        _set_balance(c, acct_id, _cents(acct["balance"]), at)
                    except (InvalidOperation, ValueError, TypeError):
                        errors.append(f"bad balance for '{acct.get('name', '?')}'")
                try:  # every sighting is kept: when the Bridge last refreshed this bank, and when we asked
                    c.execute("INSERT INTO account_refresh(account_id, refreshed_at, seen_at) VALUES (?,?,?)",
                              (acct_id, datetime.fromtimestamp(int(acct["balance-date"])).isoformat(
                                  timespec="seconds"), now))
                except (KeyError, ValueError, TypeError):
                    pass  # no usable balance-date: nothing real to log, never a guessed time
            res["superseded"] = _supersede(c, new_charges, now)
            _expire_pending(c, seen, now)  # after supersede, so a hold that just settled keeps its memo
            _link_transfers(c, touched, last4s)
        if errors:
            status = "partial"
    except Exception as e:
        status = "error"
        errors.append(_redact(f"{type(e).__name__}: {e}"))
    with book._conn() as c:
        c.execute("INSERT INTO sync_run(at, status, added, updated, superseded, errors) "
                  "VALUES (?,?,?,?,?,?)",
                  (now, status, res["added"], res["updated"], res["superseded"], json.dumps(errors)))
    return {**res, "status": status, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="finances.simplefin")
    ap.add_argument("--db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("claim").add_argument("token")
    sub.add_parser("sync").add_argument("--fixture")
    args = ap.parse_args(argv)
    if args.cmd == "claim":
        claim(args.token)
        return 0
    book.init(args.db)
    fetch = None
    if args.fixture:
        data = json.loads(Path(args.fixture).read_text())
        fetch = lambda _start: data  # noqa: E731
    try:
        out = sync(fetch)
    except Busy as e:
        print(e, file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# vault-code/dashboard/hub/finances/payments_scan.py
"""Read Venmo and Zelle payment notifications out of Gmail into the owed tab.

This is the automatic half of the owed loop. Neither Venmo nor Zelle can be
asked for money by an API, but both announce an arrival by email, and those two
emails are machine-parseable down to the payer, the amount, the note and the
provider's own transaction id.

What it does NOT do is settle a debt on a resemblance. A payment is applied on
its own only when the note carries the tag the request button wrote and the
amount matches those lines to the cent (`owed.auto_apply`). Everything else is
recorded as arrived and left for a click. The failure this avoids is silent and
permanent: money credited against the wrong debt looks exactly like a debt that
was paid, and nobody ever audits a line that says settled.

Every insert is keyed on the provider's transaction id, which is UNIQUE in the
table, so the scan is idempotent — it can run every morning over the same 60-day
window forever and each transfer lands once. There is no high-water mark to keep
in step, which is the usual way a mail scanner starts skipping messages.

Run it: `python -m finances.payments_scan --days 90` from dashboard/, or on the
Hub schedule as the `owed-payments` job.
"""

from __future__ import annotations

import base64
import html
import re
from datetime import datetime, timezone

from . import owed

# Both senders in one query; the parsers decide what they actually recognise.
QUERY = "(from:venmo.com OR from:chase.com) newer_than:{days}d"

_MONEY = r"([\d,]+\.\d{2})"
_VENMO_SUBJECT = re.compile(r"^(?P<who>.+?) paid (?:you |your )?\$" + _MONEY)
_VENMO_TXN = re.compile(r"Transaction ID\s*([0-9]{6,})")
_ZELLE_AMOUNT = re.compile(r"Amount\s*\$" + _MONEY)
_ZELLE_TXN = re.compile(r"Transaction number\s*([A-Za-z0-9]{4,})")
_ZELLE_WHO = re.compile(r"([A-Za-z][\w'’.\- ]{1,60}?)\s+sent you money")
_ZELLE_LEAD = re.compile(r"^(?:.*\bpayment\b\s+)", re.I)

# Chase drops boilerplate straight after the Memo label when the memo is blank.
_MEMO_NOISE = re.compile(r"registered with a Zelle|Go to Zelle|Questions\?|"
                         r"Securely access|About this message", re.I)


def _money(s: str) -> float:
    return round(float(s.replace(",", "")), 2)


def _lines(payload: dict) -> list[str]:
    """Readable lines from a Gmail payload, HTML included.

    Written here rather than reused from `gmail._extract_text` because that one
    strips tags without putting anything in their place, which runs a table's
    cells together. Both of these emails put the fields in adjacent cells, so the
    cell boundary is the only thing separating a label from its value.
    """
    chunks: list[str] = []

    def walk(part):
        data = part.get("body", {}).get("data")
        if data:
            chunks.append(base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace"))
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    raw = "\n".join(chunks)
    raw = re.sub(r"(?is)<(style|script|head)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    raw = re.sub(r"<[^>]+>", "\n", raw)
    out = []
    for line in html.unescape(raw).splitlines():
        line = re.sub(r"[ \t ]+", " ", line).strip()
        if line:
            out.append(line)
    return out


def _flat(lines: list[str]) -> str:
    """One-line form for label-then-value regexes, which straddle a cell break."""
    return " ".join(lines)


def _received(msg: dict) -> str:
    ms = int(msg.get("internalDate") or 0)
    if not ms:
        return datetime.now().date().isoformat()
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().date().isoformat()


def parse_venmo(subject: str, lines: list[str], msg_id: str, received: str) -> dict | None:
    """A Venmo payment-received notification, or None if this is another Venmo mail.

    The payer comes from the SUBJECT and only the subject. The HTML preheader
    names the account holder — a real message reading "Nina Ford paid your
    $700.00 request" carries "Sam Rivera paid you $700.00" as its first body
    line, so a body-first parser records the wrong person every time.
    """
    m = _VENMO_SUBJECT.match(subject.strip())
    if not m:
        return None
    who = m.group("who").strip()
    # "You paid Brian $50" is an outflow, and Venmo phrases it the same way.
    if who.lower() in ("you", "your"):
        return None

    flat = _flat(lines)
    txn = _VENMO_TXN.search(flat)

    # The note sits between the amount and the "See transaction" link. Venmo
    # renders the amount split across cells ($ / 744 / . / 00), so the candidate
    # is skipped when it is one of those fragments rather than a note.
    note = ""
    if "See transaction" in lines:
        idx = lines.index("See transaction")
        for cand in reversed(lines[max(0, idx - 3):idx]):
            if re.fullmatch(r"[$.]|\d{1,3}|[\d,]+", cand):
                continue
            note = cand
            break

    # Two of Venmo's layouts carry no Transaction ID at all. The Gmail message id
    # is the fallback key: unique, stable, and never reused, so the row still
    # inserts exactly once. It only fails to dedupe the same transfer announced
    # twice in two different emails, which Venmo does not do.
    ext = f"venmo:{txn.group(1)}" if txn else f"venmo:msg:{msg_id}"

    return {"person": who, "amount": _money(m.group(2)), "method": "venmo",
            "received": received, "note": note, "ext_id": ext, "msg_id": msg_id}


def parse_zelle(subject: str, lines: list[str], msg_id: str, received: str) -> dict | None:
    """A Chase "you received money with Zelle" notification, or None.

    Chase's subject carries no payer and no amount — both live in the body — so
    unlike Venmo this one has to trust the body, and the guard is that it must
    find all three of payer, amount and transaction number or return nothing.
    """
    flat = _flat(lines)
    if "sent you money" not in flat:
        return None                      # "You sent money with Zelle" is an outflow
    # The payer is read off its own line first: flattened, the sentence trails
    # the "Zelle ® payment" heading and a name-shaped regex swallows the word
    # "payment" into the name.
    who = None
    for line in lines:
        hit = _ZELLE_WHO.fullmatch(line)
        if hit:
            who = hit
            break
    if who is None:
        who = _ZELLE_WHO.search(flat)
    amt = _ZELLE_AMOUNT.search(flat)
    txn = _ZELLE_TXN.search(flat)
    if not (who and amt and txn):
        return None

    note = ""
    if "Memo" in lines:
        idx = lines.index("Memo")
        if idx + 1 < len(lines) and not _MEMO_NOISE.search(lines[idx + 1]):
            note = lines[idx + 1][:200]

    payer = _ZELLE_LEAD.sub("", who.group(1)).strip()
    return {"person": payer, "amount": _money(amt.group(1)),
            "method": "zelle", "received": received, "note": note,
            "ext_id": f"zelle:{txn.group(1)}", "msg_id": msg_id}


def parse_message(msg: dict) -> dict | None:
    """Route one full Gmail message to whichever parser recognises it."""
    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    sender = headers.get("From", "")
    subject = headers.get("Subject", "")
    lines = _lines(msg.get("payload", {}))
    received = _received(msg)
    if "venmo.com" in sender:
        return parse_venmo(subject, lines, msg["id"], received)
    if "chase.com" in sender:
        return parse_zelle(subject, lines, msg["id"], received)
    return None


def scan(days: int = 60, limit: int = 200) -> dict:
    """Read the window, record what is new, auto-apply only the exact matches."""
    import gmail

    service = gmail._get_service()
    listing = service.users().messages().list(
        userId="me", q=QUERY.format(days=days), maxResults=limit).execute()
    ids = [m["id"] for m in listing.get("messages", [])]

    found = recorded = applied = 0
    for mid in ids:
        msg = service.users().messages().get(userId="me", id=mid, format="full").execute()
        parsed = parse_message(msg)
        if not parsed:
            continue
        found += 1
        pid = owed.record_payment(parsed)
        if pid is None:
            continue                      # already known — the ext_id did its job
        recorded += 1
        if owed.auto_apply(pid):
            applied += 1

    return {"scanned": len(ids), "payments": found, "new": recorded, "auto_applied": applied}


if __name__ == "__main__":
    import argparse
    import json
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from vault_path import vault_root

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true", help="parse only, write nothing")
    args = ap.parse_args()

    owed.init(vault_root() / "data" / "owed.db", vault_root() / "data" / "trips.db")
    if args.dry_run:
        import gmail
        service = gmail._get_service()
        listing = service.users().messages().list(
            userId="me", q=QUERY.format(days=args.days), maxResults=200).execute()
        for m in listing.get("messages", []):
            full = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
            p = parse_message(full)
            if p:
                print(json.dumps(p))
    else:
        print(json.dumps(scan(days=args.days), indent=2))

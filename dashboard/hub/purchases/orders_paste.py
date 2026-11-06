"""Turn a pasted Amazon "Your Orders" page into rows in the `orders` table.

Why this exists at all: `orders_mail` is the only thing that advances an order
past "ordered", and it reads Gmail. Sam's Amazon account does not send to
the mailbox this vault can read — a search for an order number, the product
name, or `from:amazon.com` across all mail including spam and trash returns
nothing — so every Amazon parcel sat at "ordered" forever and the two he
actually wanted (a power bank and a cable, both delivered 2026-09-02) were
still showing as in flight a week later. The orders page is where those facts
live, and copying it is the input he already has.

Same two rules as the mail scan, for the same reason: a paste only ever fills
a BLANK field, and status only moves forward. Re-pasting the same page is a
no-op, and nothing he typed by hand is ever overwritten.

Self-check:  python3 orders_paste.py
"""

from __future__ import annotations

import re
from datetime import date, datetime

from orders_mail import _STATUS_RANK  # forward-only status, shared with the mail scan

VENDOR = "Amazon"

# Every line the orders page draws that is a button, a heading, or chrome. The
# product title is whatever survives this filter, so a miss here shows up as a
# row named "Buy it again" — loud, not silent.
_CHROME = (
    "order placed", "total", "ship to", "order #", "view order details",
    "view invoice", "ask alexa about this order", "buy it again",
    "get product support", "track package", "return or replace items",
    "more options", "write a product review", "archive order",
    "problem with order", "leave seller feedback", "share gift receipt",
    "return items", "replace items", "view return status", "cancel items",
    "your package was delivered", "your package was left", "was handed directly",
    "delivered to", "view your item", "get help", "tell us what you think",
)
_STATUS_LINE = [
    ("delivered", re.compile(r"^delivered\b", re.I)),
    ("out for delivery", re.compile(r"^out for delivery\b", re.I)),
    ("shipped", re.compile(r"^(shipped|arriving|now arriving|expected)\b", re.I)),
    ("cancelled", re.compile(r"^(cancell?ed|order cancell?ed)\b", re.I)),
    ("returned", re.compile(r"^(returned|refund(ed)? issued|return complete)", re.I)),
]
_ORDER_NUM = re.compile(r"^order\s*#\s*([0-9A-Za-z\-]{6,})", re.I)
_MONEY = re.compile(r"^\$\s*([\d,]+\.\d{2})$")
_RETURN_BY = re.compile(r"eligible through\s+([A-Za-z]+ \d{1,2},? \d{4})", re.I)
# "Delivered September 2" — Amazon drops the year on the status line.
_DELIVERED_ON = re.compile(r"^delivered\s+([A-Za-z]+ \d{1,2})(?:,?\s*(\d{4}))?\s*$", re.I)
_FULL_DATE = re.compile(r"^([A-Za-z]+ \d{1,2},? \d{4})$")


def _iso(text: str, year: int | None = None) -> str:
    """"August 31, 2026" or "September 2" (+ a year to borrow) → ISO. '' if unparseable."""
    text = text.strip().rstrip(",")
    for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    if year is None:
        return ""
    # Give the parser the year rather than patching it on afterwards: replacing
    # the year on a parsed Feb 29 raises, and 3.15 drops the yearless default.
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(f"{text} {year}", fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def _is_chrome(line: str) -> bool:
    low = line.strip().lower()
    return (not low) or any(low.startswith(c) for c in _CHROME) or bool(_MONEY.match(low))


def parse(text: str) -> list[dict]:
    """One pasted orders page → the orders it asserts, newest block first.

    Blocks are split on the "Order placed" heading that starts each card."""
    lines = [ln.strip() for ln in text.splitlines()]
    starts = [i for i, ln in enumerate(lines) if ln.lower() == "order placed"]
    if not starts:
        return []
    out = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        order = _parse_block(lines[start:end])
        if order:
            out.append(order)
    return out


def _status_line_delivered_on(ln: str, ordered_on: str) -> str:
    """"Delivered September 2" -> ISO, rolling the year forward when a December
    order shows a delivery date that parses earlier than it was ordered."""
    md = _DELIVERED_ON.match(ln)
    if not md:
        return ""
    year = int(md.group(2)) if md.group(2) else (
        int(ordered_on[:4]) if ordered_on else date.today().year)
    delivered_on = _iso(md.group(1), year)
    if ordered_on and delivered_on and delivered_on < ordered_on:
        delivered_on = _iso(md.group(1), year + 1)
    return delivered_on


def _scan_block_fields(lines: list[str]) -> dict:
    ordered_on = total = order_number = return_by = delivered_on = ""
    status = "ordered"
    status_at = None
    for i, ln in enumerate(lines):
        if not ordered_on and _FULL_DATE.match(ln):
            ordered_on = _iso(ln)
            continue
        if ln.lower() == "total":
            m = _MONEY.match(lines[i + 1]) if i + 1 < len(lines) else None
            if m:
                total = m.group(1).replace(",", "")
            continue
        m = _ORDER_NUM.match(ln)
        if m:
            order_number = m.group(1)
            continue
        m = _RETURN_BY.search(ln)
        if m:
            return_by = _iso(m.group(1))
            continue
        if status_at is None:
            for name, pat in _STATUS_LINE:
                if pat.match(ln):
                    status, status_at = name, i
                    delivered_on = _status_line_delivered_on(ln, ordered_on)
                    break
    return {
        "ordered_on": ordered_on, "total": total, "order_number": order_number,
        "return_by": return_by, "status": status, "status_at": status_at,
        "delivered_on": delivered_on,
    }


def _collect_titles(lines: list[str], status_at: int | None) -> list[str]:
    """Product titles: everything after the status line that is not chrome. Amazon
    prints each title twice (image alt, then link), so consecutive repeats fold."""
    titles: list[str] = []
    for ln in lines[(status_at + 1) if status_at is not None else 0:]:
        if _is_chrome(ln):
            continue
        if not titles or titles[-1] != ln:
            titles.append(ln)
    return titles


def _parse_block(lines: list[str]) -> dict | None:
    fields = _scan_block_fields(lines)
    if not fields["order_number"]:
        return None  # without the order number there is nothing safe to key on
    titles = _collect_titles(lines, fields["status_at"])
    if not titles:
        return None
    return {
        "vendor": VENDOR,
        "order_number": fields["order_number"],
        "ordered_on": fields["ordered_on"],
        "total": float(fields["total"]) if fields["total"] else None,
        "ship_status": fields["status"],
        "delivered_on": fields["delivered_on"],
        "return_by": fields["return_by"],
        # ponytail: one row per order, first title wins and the rest go in notes.
        # Split into per-item rows only if a multi-item order ever needs its own
        # return window, which the page does not give per item anyway.
        "item": titles[0],
        "extra_items": titles[1:],
    }


_STOPWORDS = {
    "with", "for", "and", "the", "usb", "usbc", "type", "cable", "charger",
    "portable", "power", "bank", "fast", "charging", "universal", "black",
    "white", "pack", "mini", "gift", "men", "women", "smartphone", "smartphones",
}


def _tokens(name: str) -> set[str]:
    """Words distinctive enough to identify a product. Digits, units and generic
    category words are dropped — "10000mAh" and "cable" match everything."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9]*", name.lower())
    return {w for w in words if len(w) >= 4 and not w.isdigit() and w not in _STOPWORDS}


def match_row(parsed: dict, rows: list[dict]) -> dict | None:
    """The existing order this paste is about, or None.

    The order number is exact and wins. Failing that — which is the normal case
    for a row created from a purchase decision, where the vendor reads "INIU"
    and not "Amazon" — the product name is matched on distinctive words. A tie
    matches nothing: two plausible rows means ask, never pick."""
    num = (parsed.get("order_number") or "").strip()
    if num:
        for r in rows:
            if (r.get("order_number") or "").strip() == num:
                return r
    want = _tokens(parsed["item"])
    if not want:
        return None
    scored = [(len(want & _tokens(r.get("item") or "")), r) for r in rows
              if _STATUS_RANK.get(r.get("ship_status") or "", 0) < _STATUS_RANK["delivered"]]
    scored = [(n, r) for n, r in scored if n]
    if not scored:
        return None
    best = max(n for n, _ in scored)
    top = [r for n, r in scored if n == best]
    return top[0] if len(top) == 1 else None


_FILL_BLANK = ("vendor", "order_number", "ordered_on", "return_by")


def merge_fields(existing: dict, parsed: dict) -> dict:
    """Only the blanks, and status only forward. Same contract as the mail scan."""
    patch = {}
    for f in _FILL_BLANK:
        if parsed.get(f) and not (existing.get(f) or "").strip():
            patch[f] = parsed[f]
    if parsed.get("total") is not None and existing.get("total") is None:
        patch["total"] = parsed["total"]
    old = _STATUS_RANK.get(existing.get("ship_status") or "", 0)
    new = _STATUS_RANK.get(parsed.get("ship_status") or "", 0)
    if new > old:
        patch["ship_status"] = parsed["ship_status"]
        if parsed.get("delivered_on") and not (existing.get("delivered_on") or "").strip():
            patch["delivered_on"] = parsed["delivered_on"]
    return patch


def apply(db, text: str) -> dict:
    """Fold a pasted orders page into `orders`. Returns what changed, verbatim
    enough to show him: updated rows with the fields filled, created rows, and
    anything the paste could not be pinned to an order."""
    parsed_all = parse(text)
    rows = db.list_orders()
    updated, created, unchanged = [], [], []
    for parsed in parsed_all:
        target = match_row(parsed, rows)
        if target:
            patch = merge_fields(target, parsed)
            if patch:
                db.update_order(target["id"], patch)
                updated.append({"id": target["id"], "item": target["item"],
                                "filled": sorted(patch)})
            else:
                unchanged.append({"id": target["id"], "item": target["item"]})
            continue
        notes = "; ".join(parsed["extra_items"]) if parsed["extra_items"] else ""
        row = db.create_order({
            "item": parsed["item"], "vendor": parsed["vendor"],
            "order_number": parsed["order_number"], "ordered_on": parsed["ordered_on"],
            "total": parsed["total"], "ship_status": parsed["ship_status"],
            "delivered_on": parsed["delivered_on"], "return_by": parsed["return_by"],
            "source": "paste", "notes": notes,
        })
        created.append({"id": row["id"], "item": row["item"]})
    return {"parsed": len(parsed_all), "updated": updated, "created": created,
            "unchanged": unchanged}


# The real paste that produced this module, trimmed to one order.
_SAMPLE = """Order placed
August 31, 2026
Total
$29.95
Ship to
Sam Rivera 
Order # 112-6068133-4430610
View order details  View invoice

Ask Alexa about this order
Delivered September 2
Your package was delivered. It was handed directly to a resident.
INIU Portable Charger, Ultra Mini 10000mAh 45W Fast Charging Power Bank
INIU Portable Charger, Ultra Mini 10000mAh 45W Fast Charging Power Bank
Return or replace items: Eligible through October 2, 2026
Buy it again
Get product support
Track package
Return or replace items
More options
"""


def demo() -> None:
    o = parse(_SAMPLE)
    assert len(o) == 1, o
    o = o[0]
    assert o["order_number"] == "112-6068133-4430610", o
    assert o["ordered_on"] == "2026-08-31" and o["total"] == 29.95, o
    assert o["ship_status"] == "delivered" and o["delivered_on"] == "2026-09-02", o
    assert o["return_by"] == "2026-10-02", o
    assert o["item"].startswith("INIU Portable Charger"), o["item"]
    assert o["extra_items"] == [], o["extra_items"]

    # Two cards in one paste, and a still-in-flight one.
    two = parse(_SAMPLE + _SAMPLE.replace("112-6068133-4430610", "112-0000000-0000000")
                .replace("Delivered September 2", "Arriving tomorrow")
                .replace("Your package was delivered. It was handed directly to a resident.",
                         "Now expected"))
    assert len(two) == 2 and two[1]["ship_status"] == "shipped", two[1]
    assert two[1]["delivered_on"] == "", two[1]

    # A December order delivered in January belongs to the next year.
    ny = parse(_SAMPLE.replace("August 31, 2026", "December 30, 2026")
                      .replace("Delivered September 2", "Delivered January 2"))[0]
    assert ny["delivered_on"] == "2027-01-02", ny["delivered_on"]

    # A decision-created row reads "INIU", not "Amazon" — the product name is
    # the only thing the two have in common, which is the case that matters.
    rows = [
        {"id": 3, "item": "INIU Carry P50-E1", "vendor": "INIU", "order_number": "",
         "ship_status": "ordered", "ordered_on": "", "total": None, "delivered_on": "",
         "return_by": ""},
        {"id": 4, "item": "Rolling Square inCharge XL", "vendor": "Rolling Square",
         "order_number": "", "ship_status": "ordered", "ordered_on": "", "total": None,
         "delivered_on": "", "return_by": ""},
    ]
    hit = match_row(o, rows)
    assert hit and hit["id"] == 3, hit
    patch = merge_fields(hit, o)
    assert patch["ship_status"] == "delivered" and patch["delivered_on"] == "2026-09-02", patch
    assert patch["return_by"] == "2026-10-02" and patch["total"] == 29.95, patch
    # "INIU" is the maker, already on the row, so the retailer never overwrites it.
    assert "vendor" not in patch and patch["ordered_on"] == "2026-08-31", patch

    cable = dict(o, item="inCharge Rolling Square XL 30 cm - USB-C Cable, Universal "
                         "Smartphone Cable, Gift for Men, 6-in-1 Universal Charger",
                 order_number="112-2307868-1538630")
    cable_hit = match_row(cable, rows)
    assert cable_hit and cable_hit["id"] == 4, cable_hit

    # Re-pasting the same page changes nothing.
    done = {"id": 3, "item": "INIU Carry P50-E1", "vendor": "Amazon",
            "order_number": "112-6068133-4430610", "ship_status": "delivered",
            "ordered_on": "2026-08-31", "total": 29.95, "delivered_on": "2026-09-02",
            "return_by": "2026-10-02"}
    assert merge_fields(done, o) == {}, merge_fields(done, o)

    # A hand-typed field outranks the paste, and status never walks backwards.
    typed = dict(done, total=99.0, ship_status="returned")
    assert merge_fields(typed, o) == {}, merge_fields(typed, o)

    # Nothing distinctive in common → no guess.
    assert match_row(dict(o, item="Generic USB Cable", order_number=""),
                     [{"id": 9, "item": "Anon M5", "ship_status": "ordered"}]) is None

    # Two equally plausible rows → no guess either.
    twins = [{"id": 1, "item": "INIU Carry P50-E1", "ship_status": "ordered"},
             {"id": 2, "item": "INIU Carry P51L", "ship_status": "ordered"}]
    assert match_row(dict(o, order_number=""), twins) is None

    assert parse("nothing here") == []
    print("orders_paste: 14 checks pass")


if __name__ == "__main__":
    demo()

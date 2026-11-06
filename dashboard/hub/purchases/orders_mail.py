"""Pull order + shipment facts out of Gmail into the `orders` table.

What this is not: a general email understander. It reads the handful of things
retailers write in a machine-shaped way — a tracking number, an order number, a
total, a delivery verb — and leaves everything else to Sam. A parcel it can
only half-read still lands as a row with the blanks showing, which is the point:
an order in the tab with a missing tracking number is one he can type into,
while an order that never got created is invisible.

Two rules keep a re-scan safe:
  * every consumed message is recorded in `order_emails`, so a second scan does
    not re-add the same parcel;
  * a scan only ever fills a BLANK field. Anything already on the row — a name
    he corrected, a tracking code he typed in himself — outranks the email.

Self-check:  python3 orders_mail.py
"""

from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime

# ── Carrier fingerprints ──────────────────────────────────────────────────────
# Ordered most-specific first: a UPS 1Z code and a USPS 9400 code cannot collide,
# but a bare 12-digit FedEx number and a 10-digit DHL number are just digits, so
# they only count when the carrier is named nearby or in the message at all.
_TRACK_PATTERNS = [
    ("ups",   re.compile(r"\b1Z[0-9A-Z]{16}\b")),
    ("usps",  re.compile(r"\b(?:9[2345]\d{20}|\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2})\b")),
    ("usps",  re.compile(r"\b[A-Z]{2}\d{9}US\b")),
    ("fedex", re.compile(r"\b(?:\d{12}|\d{15}|\d{20})\b")),
    ("dhl",   re.compile(r"\b\d{10}\b")),
    ("ontrac", re.compile(r"\b[CD]\d{14}\b")),
]

# "Tracking number: 1Z999..." — an explicit label beats any pattern guess, so it
# is tried first and its capture is taken verbatim.
_TRACK_LABELLED = re.compile(
    r"tracking\s*(?:number|no\.?|#|code|id)?\s*[:#]\s*([A-Z0-9][A-Z0-9\- ]{6,32}?)(?=\s|$|<)",
    re.IGNORECASE,
)
_ORDER_NUM = re.compile(
    r"order\s*(?:number|no\.?|#|id)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{3,29})", re.IGNORECASE
)
# \b matters and is the whole point: without it "Subtotal: $150.00" matched on
# the "total" inside it and became the order total, hiding the $24.00 of
# shipping and tax that were actually charged. The specific labels are tried
# before the bare word so a receipt listing both resolves to the real one.
_TOTAL = re.compile(
    r"\b(?:order\s+total|grand\s+total|total\s+price|total\s+(?:charged|paid)|total)"
    r"\s*[:\-]?\s*(?:US)?\$\s*([\d,]+\.\d{2})",
    re.IGNORECASE,
)
_RETURN_DAYS = re.compile(
    r"(?:return|returned|returns)\s+(?:it\s+)?(?:within|up to)\s+(\d{1,3})\s*days"
    r"|(\d{1,3})[- ]day\s+(?:free\s+)?return",
    re.IGNORECASE,
)
_CARRIER_WORDS = {
    "ups": "ups", "united parcel": "ups",
    "fedex": "fedex", "usps": "usps", "united states postal": "usps",
    "dhl": "dhl", "ontrac": "ontrac", "canada post": "canada post",
    "amazon logistics": "amazon",
}

# The status the message asserts, strongest verb first — a "delivered" email
# also says "shipped" further down, so order matters.
_STATUS_PHRASES = [
    ("delivered", ("was delivered", "has been delivered", "your package was delivered",
                   "delivered:", "it's here", "was left")),
    ("out for delivery", ("out for delivery", "arriving today", "on the truck")),
    # "tracking number" is deliberately NOT in this bucket. Order confirmations
    # promise one in the future -- Bob's Sports Chalet, 2026-09-08: "we will send
    # you an email confirmation with a tracking number" -- and that promise alone
    # marked an unshipped parcel shipped. A tracking number that actually parses
    # still counts; that is applied in parse_message, where it is known.
    ("shipped", ("has shipped", "have shipped", "on its way", "on the way",
                 "shipment confirmation", "your order shipped")),
]
# The gate that keeps this tab about parcels. Sam's Gmail taxonomy already
# draws this line — "Products" is physical items only — so a McDonald's mobile
# order, a Google Play receipt and a Taco Bell confirmation are all order-shaped
# email that must never become a row here. Nothing without a shipping leg does.
# Only phrases that imply a physical address or a courier. "on its way" and
# "arriving" are deliberately absent: a Ticketmaster transfer is "on its way"
# and is not a parcel. They still decide purchase-vs-shipment below, where a
# false positive costs a status word rather than a whole junk row.
_SHIPS_HINTS = (
    "ship to", "shipping address", "ships to", "will ship", "has shipped",
    "have shipped", "shipping confirmation", "shipment", "tracking",
    "out for delivery", "was delivered", "estimated delivery",
    "delivery address", "free shipping", "shipping method",
)
# What makes it a shipment rather than the original purchase: the SUBJECT says
# so, or a tracking number turned up. A confirmation email that merely mentions
# shipping in its footer is still the purchase.
_SHIPMENT_SUBJECTS = ("shipped", "on its way", "out for delivery", "delivered",
                      "tracking", "shipment", "on the way")

# Senders that are never a purchase, however order-shaped the subject reads.
_SENDER_DENY = ("no-reply@accounts.google", "linkedin.com", "indeed.com", "glassdoor")

# Carrier mail (UPS My Choice, USPS Informed Delivery, FedEx Delivery Manager)
# covers every parcel addressed to him, including ones whose store never sent a
# tracking number. The sender is the carrier, so the vendor comes from the
# shipper line ("From SKI BARN" in UPS mail, 2025-11) and there is no order number.
_CARRIER_SENDERS = ("ups.com", "usps.com", "fedex.com")
_SHIPPER = re.compile(
    r"^[ \t]*(?:from|shipper|shipped by|sender)[ \t]*:?[ \t]+([^\n<:]{2,60}?)[ \t]*$"
    r"|\bpackage from\s+([^\n<]{2,60}?)\s+(?:is|has|was|will)\b",
    re.IGNORECASE | re.MULTILINE,
)

SCAN_QUERY = (
    'newer_than:{days}d ('
    'subject:("your order" OR "order confirmation" OR "order #" OR "has shipped" '
    'OR "is on its way" OR "out for delivery" OR "was delivered" OR "shipping confirmation") '
    'OR "tracking number" OR from:(ups.com OR usps.com OR fedex.com))'
)


def _sender(from_header: str) -> tuple[str, str]:
    """(display name, domain) — the vendor guess and the thing to deny on."""
    name = from_header.split("<")[0].strip().strip('"')
    m = re.search(r"<([^>]+)>", from_header) or re.search(r"([\w.+-]+@[\w.-]+)", from_header)
    addr = (m.group(1) if m else "").lower()
    domain = addr.split("@")[-1] if "@" in addr else ""
    # "Amazon.com", "Best Buy Orders", "Monos Team" → the brand
    name = re.sub(r"\s*(?:orders?|team|shipping|store|support|customer care)\s*$", "", name, flags=re.I)
    name = re.sub(r"\.(com|net|co|io|shop)$", "", name, flags=re.I).strip()
    if not name and domain:
        name = domain.split(".")[0]
    return name, domain


def _tracking(text: str) -> tuple[str, str]:
    """(carrier, tracking number). Empty strings when nothing is confident."""
    lower = text.lower()
    named = [c for word, c in _CARRIER_WORDS.items() if word in lower]
    m = _TRACK_LABELLED.search(text)
    if m:
        num = re.sub(r"\s+", "", m.group(1)).strip("-")
        for carrier, pat in _TRACK_PATTERNS:
            if pat.fullmatch(num):
                return carrier, num
        return (named[0] if named else ""), num
    for carrier, pat in _TRACK_PATTERNS:
        hit = pat.search(text)
        if not hit:
            continue
        # digit-only shapes are ambiguous; require the carrier to be named
        if carrier in ("fedex", "dhl") and carrier not in named:
            continue
        return carrier, re.sub(r"\s+", "", hit.group(0))
    return (named[0] if named else ""), ""


def _status(text: str) -> str:
    lower = text.lower()
    for status, phrases in _STATUS_PHRASES:
        if any(p in lower for p in phrases):
            return status
    return "ordered"


def _received(date_header: str) -> str:
    try:
        return parsedate_to_datetime(date_header).date().isoformat()
    except (TypeError, ValueError):
        return datetime.now().date().isoformat()


# "You placed an order: Brand New Monos Hybrid Carry-On" — when a retailer names
# the product it is almost always after this. Tried first, because stripping
# boilerplate out of that subject word by word mangles the product name with it.
_ITEM_AFTER = re.compile(r"\border\s*(?:of|for|:)\s*(.{4,})$", re.IGNORECASE)
# Whole clauses, only at the head or tail of the subject — never mid-string, which
# is what turned "You placed an order: ..." into "You placed an : ...".
_BOILERPLATE = re.compile(
    r"^(?:re|fwd)\s*:\s*"
    r"|^(?:thanks?|thank you)\s+(?:for|you\s+for)\s+(?:placing\s+)?(?:your|a|an)?\s*"
    # The optional clause below is what lets a vendor name sit between "your" and
    # "order": "Thank You for Your Bob's Sports Chalet Order" is boilerplate end to end.
    r"(?:mobile\s+)?(?:[\w'&.\- ]{0,40}?\s+)?order[!.]?\s*"
    r"|^(?:your|our)?\s*(?:order|shipment|package|parcel)\s*"
    r"(?:confirmation|update|receipt)?\s*[:\-]?\s*"
    r"|\s*(?:order\s+)?(?:has|have|is|was)\s+(?:been\s+)?"
    r"(?:shipped|delivered|on its way|out for delivery)[!.]?$"
    r"|\s*(?:shipping|order)\s+confirmation[!.]?$",
    re.IGNORECASE,
)


def _item_name(subject: str, vendor: str) -> str:
    """The product, if the subject names one; otherwise the subject with its
    boilerplate trimmed off each end. A retailer often names nothing, so this is
    frequently a placeholder he renames — still better than a row called "order",
    because it says which email it came from."""
    s = subject.strip()
    m = _ITEM_AFTER.search(s)
    if m:
        s = m.group(1)
    else:
        prev = None
        while prev != s:  # head and tail clauses can both apply
            prev = s
            s = _BOILERPLATE.sub("", s).strip()
    s = re.sub(r"#\s*[A-Z0-9\-]{5,}\b", "", s)
    s = re.sub(r"[(\[]\s*[)\]]", "", s)  # the brackets the order number lived in
    s = re.sub(r"[\s\-\u2013\u2014:,.!]+$", "", re.sub(r"^[\s\-\u2013\u2014:,.!]+", "", s)).strip()
    return s if len(s) > 2 else (f"{vendor} order".strip() if vendor else "order")


def parse_message(msg: dict) -> dict | None:
    """One Gmail message → the order facts it asserts, or None if it is not an
    order email at all."""
    from_header = msg.get("from", "")
    if any(bad in from_header.lower() for bad in _SENDER_DENY):
        return None
    subject = msg.get("subject", "")
    body = msg.get("body", "")
    blob = f"{subject}\n{body}"
    vendor, domain = _sender(from_header)
    carrier, tracking = _tracking(blob)
    carrier_mail = any(domain == d or domain.endswith("." + d) for d in _CARRIER_SENDERS)
    if carrier_mail:
        if not tracking:
            return None  # a passcode, a promo, an account notice: no parcel in it
        ms = _SHIPPER.search(body)
        shipper = next((g for g in ms.groups() if g), "").strip() if ms else ""
        vendor = shipper.title() if shipper.isupper() else shipper
    status = _status(blob)
    if tracking and status == "ordered":
        status = "shipped"  # a real tracking code is a shipment even if no verb says so
    order_no = ""
    m = _ORDER_NUM.search(blob)
    if m and len(m.group(1).strip("-")) >= 5:
        order_no = m.group(1).strip("-")
    total = None
    mt = _TOTAL.search(blob)
    if mt:
        try:
            total = float(mt.group(1).replace(",", ""))
        except ValueError:
            total = None
    return_days = None
    mr = _RETURN_DAYS.search(blob)
    if mr:
        return_days = int(mr.group(1) or mr.group(2))
    blob_lower = blob.lower()
    if not (tracking or carrier or any(h in blob_lower for h in _SHIPS_HINTS)):
        return None  # a meal, a download, a service — order-shaped, but nothing ships
    subj_lower = subject.lower()
    kind = "shipment" if (tracking or any(h in subj_lower for h in _SHIPMENT_SUBJECTS)) else "purchase"
    return {
        "message_id": msg.get("id", ""),
        "kind": kind,
        "sender": from_header,
        "subject": subject,
        "received": _received(msg.get("date", "")),
        "vendor": vendor,
        "domain": domain,
        "order_number": order_no,
        "carrier": carrier,
        "tracking_number": tracking,
        "ship_status": status,
        "total": total,
        "return_days": return_days,
        # a carrier subject never names the product ("Your Package Is Coming Today")
        "item": f"{vendor or 'Unknown shipper'} package" if carrier_mail else _item_name(subject, vendor),
        "carrier_mail": carrier_mail,
    }


# Forward-only: a scan must never walk an order back from delivered to ordered
# because a stale confirmation email got read after the delivery notice.
# "returned" and "cancelled" outrank delivered because they are exits, not
# steps: a delivery notice arriving after he returned the thing must not undo
# the return. Shared with orders_paste, which merges on the same ladder.
_STATUS_RANK = {"": 0, "ordered": 1, "shipped": 2, "out for delivery": 3,
                "delivered": 4, "returned": 5, "cancelled": 5}


def merge_fields(existing: dict, parsed: dict) -> dict:
    """Only the blanks. Everything already on the row wins — a scan is a source
    of missing facts, never a correction of typed ones."""
    patch = {}
    for field in ("vendor", "order_number", "carrier", "tracking_number"):
        if parsed.get(field) and not (existing.get(field) or "").strip():
            patch[field] = parsed[field]
    for field in ("total", "return_days"):
        if parsed.get(field) is not None and existing.get(field) is None:
            patch[field] = parsed[field]
    if not (existing.get("ordered_on") or "").strip() and parsed["kind"] == "purchase":
        patch["ordered_on"] = parsed["received"]
    old = _STATUS_RANK.get(existing.get("ship_status") or "", 0)
    new = _STATUS_RANK.get(parsed.get("ship_status") or "", 0)
    if new > old:
        patch["ship_status"] = parsed["ship_status"]
        if parsed["ship_status"] == "delivered" and not (existing.get("delivered_on") or "").strip():
            patch["delivered_on"] = parsed["received"]
    return patch


def scan(db, days: int = 45, max_results: int = 60) -> dict:
    """Read recent order mail and fold it into `orders`. Returns a report the UI
    shows verbatim — created rows, updated rows, and what was ignored."""
    import gmail

    if not gmail.is_authenticated():
        return {"error": "Gmail is not connected on this machine."}
    messages = gmail.search_messages(SCAN_QUERY.format(days=days), max_results=max_results)
    seen = db.seen_email_ids()
    created, updated, ignored = [], [], 0
    for msg in messages:
        if msg["id"] in seen:
            continue
        parsed = parse_message(msg)
        if not parsed:
            ignored += 1
            continue
        target = db.match_order(parsed["vendor"], parsed["order_number"],
                                parsed["tracking_number"])
        if target:
            patch = merge_fields(target, parsed)
            if patch:
                db.update_order(target["id"], patch)
                updated.append({"id": target["id"], "item": target["item"],
                                "filled": sorted(patch)})
            db.link_email(parsed["message_id"], target["id"], parsed["kind"],
                          parsed["sender"], parsed["subject"], parsed["received"])
            continue
        row = db.create_order({
            "item": parsed["item"], "vendor": parsed["vendor"],
            "order_number": parsed["order_number"],
            "ordered_on": parsed["received"] if parsed["kind"] == "purchase" else "",
            "total": parsed["total"], "carrier": parsed["carrier"],
            "tracking_number": parsed["tracking_number"],
            "ship_status": parsed["ship_status"],
            "return_days": parsed["return_days"],
            "source": "email",
            "notes": ("Check: carrier email matched no order, confirm the item and store\n"
                      if parsed["carrier_mail"] else "")
                     + f"from email: {parsed['subject'][:120]}",
        })
        db.link_email(parsed["message_id"], row["id"], parsed["kind"],
                      parsed["sender"], parsed["subject"], parsed["received"])
        created.append({"id": row["id"], "item": row["item"],
                        "needs_tracking": not row["tracking_number"]})
    return {"scanned": len(messages), "created": created, "updated": updated,
            "ignored": ignored, "skipped_seen": len(messages) - len(created) - len(updated) - ignored}


def demo() -> None:
    """Self-check on the shapes that actually decide a row."""
    def _parsed(msg: dict) -> dict:
        d = parse_message(msg)
        assert d is not None, msg
        return d

    ups = _parsed({
        "id": "m1", "from": "Monos Team <orders@monos.com>",
        "subject": "Your order has shipped!", "date": "Wed, 3 Sep 2026 10:00:00 -0400",
        "body": "Order number: MN-88213\nTracking Number: 1Z999AA10123456784\nvia UPS",
    })
    assert ups["carrier"] == "ups" and ups["tracking_number"] == "1Z999AA10123456784", ups
    assert ups["order_number"] == "MN-88213" and ups["ship_status"] == "shipped", ups
    assert ups["vendor"] == "Monos" and ups["kind"] == "shipment", ups

    # A bare 12-digit number is only FedEx when FedEx is named.
    bare = parse_message({
        "id": "m2", "from": "Shop <hi@shop.example>", "subject": "Your order confirmation",
        "date": "", "body": "Order #: A1234567 Reference 123456789012 Order total: $198.40",
    })
    assert bare is None, bare  # no shipping leg anywhere in it
    bare = _parsed({
        "id": "m2", "from": "Shop <hi@shop.example>", "subject": "Your order confirmation",
        "date": "", "body": "Ship to: 1 Main St. Reference 123456789012 Order total: $198.40",
    })
    assert bare["tracking_number"] == "" and bare["total"] == 198.40, bare
    assert bare["kind"] == "purchase" and bare["item"] == "Shop order", bare

    # A subtotal is not the total. (Tactics receipt, 2026-09-04: $150.00 sub,
    # $174.00 charged — the bare-word regex took the wrong one.)
    subtotal = _parsed({
        "id": "m7", "from": "Tactics <notifications@tactics.com>",
        "subject": "Order Confirmation", "date": "",
        "body": "Shipping Address: 100 Example St\nSubtotal: $150.00\n"
                "Super Saver Shipping: $10.00\nSales Tax: $14.00\nTotal Price: $174.00",
    })
    assert subtotal["total"] == 174.00, subtotal["total"]

    # A ticket transfer travels, but not in a box.
    assert parse_message({
        "id": "j0", "from": "Ticketmaster <customer_support@email.ticketmaster.com>",
        "subject": "Your ticket transfer for Zedd In The Park is on its way to Kermit",
        "date": "", "body": "Your tickets are on their way."}) is None

    # A meal and a download are order-shaped email that must never land here.
    for junk in (
        {"id": "j1", "from": "Taco Bell <noreply@info.tacobell.com>",
         "subject": "Success, we got your order.", "date": "",
         "body": "Order #920146 Total: $20.79 pick up in store"},
        {"id": "j2", "from": "Google Play <googleplay-noreply@google.com>",
         "subject": "Your Google Play Order Receipt from Aug 16, 2026", "date": "",
         "body": "Order number: GPA.1234-5678 Total: $5.43"},
    ):
        assert parse_message(junk) is None, junk["subject"]

    # The product name survives when the retailer actually gives one.
    named_item = _parsed({
        "id": "m6", "from": "Facebook Marketplace <noreply@marketplace.facebook.com>",
        "subject": "You placed an order: Brand New Monos Hybrid Carry-On, Jungle Green",
        "date": "", "body": "Ship to: Sam. Order number: 10240325020360682 Total: $175.00",
    })
    assert named_item["item"] == "Brand New Monos Hybrid Carry-On, Jungle Green", named_item["item"]
    named = _parsed({**{"id": "m3", "from": "Shop <hi@shop.example>",
                              "subject": "Shipped", "date": ""},
                           "body": "Your shipment is on its way via FedEx 123456789012"})
    assert named["carrier"] == "fedex" and named["tracking_number"] == "123456789012", named

    delivered = _parsed({
        "id": "m4", "from": "Amazon.com <ship@amazon.com>",
        "subject": "Delivered: your package was delivered", "date": "",
        "body": "Your package was delivered. Return it within 30 days. Order # 112-9988776-1234567",
    })
    assert delivered["ship_status"] == "delivered", delivered
    assert delivered["return_days"] == 30 and delivered["vendor"] == "Amazon", delivered

    # An order confirmation that only PROMISES a tracking number has not shipped,
    # and its whole subject is boilerplate. (Bob's Sports Chalet reorder of the
    # Anon hood, 2026-09-08 -- the old code filed it as shipped and named it
    # "Thank You for Your Bob's Sports Chalet Order ()".)
    promise = _parsed({
        "id": "m8", "from": '"Bob\'s Sports Chalet" <Support@bobssportschalet.com>',
        "subject": "Thank You for Your Bob's Sports Chalet Order (#371376)", "date": "",
        "body": "Shipping Address: 100 Example Street\\nOnce it's processed and is ready to "
                "ship, we will send you an email confirmation with a tracking number.\\n"
                "Order #: 371376\\nOrder Total: $76.45",
    })
    assert promise["ship_status"] == "ordered", promise["ship_status"]
    assert promise["item"] == "Bob's Sports Chalet order", promise["item"]
    assert promise["order_number"] == "371376" and promise["total"] == 76.45, promise

    # Job-board noise is not a purchase.
    assert parse_message({"id": "m5", "from": "LinkedIn <jobs@linkedin.com>",
                          "subject": "Your order confirmation", "date": "", "body": "x"}) is None

    # Merge fills blanks, never overwrites, and never walks status backwards.
    existing = {"vendor": "Monos", "order_number": "", "carrier": "",
                "tracking_number": "TYPED-BY-HAND", "total": None,
                "return_days": None, "ordered_on": "2026-08-31",
                "ship_status": "delivered", "delivered_on": "2026-09-02"}
    patch = merge_fields(existing, ups)
    assert patch == {"order_number": "MN-88213", "carrier": "ups"}, patch

    # An exit is terminal: a late delivery notice must not undo a return.
    returned = dict(existing, ship_status="returned", delivered_on="")
    assert "ship_status" not in merge_fields(returned, delivered), merge_fields(returned, delivered)

    fresh = {"vendor": "", "order_number": "MN-88213", "carrier": "", "tracking_number": "",
             "total": None, "return_days": None, "ordered_on": "", "ship_status": "ordered",
             "delivered_on": ""}
    patch2 = merge_fields(fresh, delivered)
    assert patch2["ship_status"] == "delivered" and patch2["delivered_on"] == delivered["received"], patch2

    # Carrier mail: the vendor is the shipper line, not "UPS". (Real UPS My
    # Choice body, Ski Barn parcel, 2025-11-02.)
    carrier = _parsed({
        "id": "c1", "from": "UPS <pkginfo@ups.com>", "date": "",
        "subject": "UPS Update: Package Scheduled for Delivery Tomorrow",
        "body": " Your package is arriving tomorrow.\n From SKI BARN \n Estimated Delivery\n"
                " Monday 11/03/2025\n by 9:00 PM\n UPS Ground\n 1Z57E4R00323590421\n",
    })
    assert carrier["vendor"] == "Ski Barn" and carrier["carrier_mail"], carrier
    assert carrier["tracking_number"] == "1Z57E4R00323590421", carrier
    assert carrier["item"] == "Ski Barn package" and carrier["order_number"] == "", carrier
    fedex = _parsed({"id": "c2", "from": "FedEx <TrackingUpdates@fedex.com>", "date": "",
                     "subject": "Your package from Monos is scheduled for delivery",
                     "body": "Your package from Monos is on its way. Tracking ID 123456789012 FedEx"})
    assert fedex["vendor"] == "Monos" and fedex["tracking_number"] == "123456789012", fedex
    # A carrier email with no parcel in it is not a row.
    assert parse_message({"id": "c3", "from": "noreply@id.ups.com", "date": "", "body": "",
                          "subject": "UPS: [372783] is Your One-Time Passcode"}) is None

    print("orders_mail: 22 checks pass")


if __name__ == "__main__":
    demo()

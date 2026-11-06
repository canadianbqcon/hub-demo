"""Guest access to the public mirror: signup, approval, per-person cosmetics,
and the wrong-code gate.

Split out of trips/db.py (Task 2). `NAME_KEY`, `GUEST_FIELDS` and the gate's
tuning constants stay on the facade (Rule 1) and are reached here as
`db.<name>` at call time. `member_key`/`_key_where` moved to db_members.py
(identity resolution, not access) to keep this file under the 500-line bar;
reached here as `db.member_key`/`db._key_where`.
"""

from __future__ import annotations

from . import db


def card_look(key: str) -> dict:
    """The three cosmetic picks for one person, by member_key.

    Read off `members` rather than a table of its own — a person's rows already
    exist, one per trip, and the look belongs to the person. Any of their rows
    answers; they are written together.
    """
    if not key:
        return {k: "" for k in db._CARD_SLOTS}
    where, val = db._key_where(key)
    with db._conn() as conn:
        row = conn.execute(
            f"SELECT {', '.join(db._CARD_SLOTS)} FROM members WHERE {where} LIMIT 1", (val,)
        ).fetchone()
    return {k: (row[k] if row else "") or "" for k in db._CARD_SLOTS}


def set_card_look(key: str, look: dict) -> dict:
    """Write whichever of the three slots were named, across every trip.

    Every row for the key, not one: the same person on three trips is three
    rows, and a look that only took on the trip they happened to pick it from
    is the kind of split state nobody ever goes and reconciles.
    """
    if not key:
        return card_look(key)
    sets = {k: str(look[k] or "").strip()[:32] for k in db._CARD_SLOTS if k in look}
    if sets:
        where, val = db._key_where(key)
        with db._conn() as conn:
            conn.execute(
                f"UPDATE members SET {', '.join(f'{k}=?' for k in sets)} WHERE {where}",
                (*sets.values(), val),
            )
    return card_look(key)


def trips_for_slug(key: str) -> set[int]:
    """The trips a person is on — the whole of what their code may reach.

    Derived from `members` rather than stored, so access follows the crew list
    with nothing to keep in step: add someone to a trip and their code opens it
    on the next request; take them off and it closes. An empty key returns an
    empty set rather than everything, because the one way this function must
    never fail is open.
    """
    if not key:
        return set()
    where, value = db._key_where(key)
    with db._conn() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT trip_id FROM members WHERE {where}", (value,)
        ).fetchall()
    return {r["trip_id"] for r in rows}


def trips_by_key(keys) -> dict[str, set[int]]:
    """`trips_for_slug` for a whole roster, in one connection instead of one each.

    The guest panel asks this about every crew member at once, and calling
    `trips_for_slug` in a loop opened a connection per person — on /mnt/c that
    cost more than every query on the page put together. Per-key semantics are
    unchanged: a slug key matches `contact_slug`, a `name:` key matches the
    lowercased trimmed name, and a row matching both keys counts for both.
    """
    keys = [k for k in keys if k]
    if not keys:
        return {}
    out: dict[str, set[int]] = {k: set() for k in keys}
    by_slug: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    for k in out:
        if k.startswith(db.NAME_KEY):
            by_name.setdefault(k[len(db.NAME_KEY):], []).append(k)
        else:
            by_slug.setdefault(k, []).append(k)
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT contact_slug, LOWER(TRIM(name)) AS lname, trip_id FROM members"
        ).fetchall()
    for r in rows:
        for k in by_slug.get(r["contact_slug"], ()):
            out[k].add(r["trip_id"])
        for k in by_name.get(r["lname"], ()):
            out[k].add(r["trip_id"])
    return out


def guest_code_by_code(code: str) -> dict | None:
    """An APPROVED code, or None. Pending and denied rows never unlock anything."""
    with db._conn() as conn:
        row = conn.execute(
            "SELECT * FROM guest_codes WHERE code=? AND status='approved'", (code,)
        ).fetchone()
    return db._row(row) if row else None


def guest_code_by_id(code_id: int) -> dict | None:
    """Re-read on every request, so revoking access actually revokes it — the
    session cookie carries this id and nothing else, and a denied row stops
    working immediately rather than when the cookie expires."""
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM guest_codes WHERE id=?", (code_id,)).fetchone()
    return db._row(row) if row else None


def list_guest_codes() -> list[dict]:
    """Pending first — the panel exists to action those; the rest is history.
    Members by most recent sign-in, never-signed-in last ('' sorts below any
    datetime); pending and denied rows have no last_seen, so they fall through
    to newest-first."""
    with db._conn() as conn:
        rows = conn.execute("""
            SELECT * FROM guest_codes
            ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
                     last_seen DESC, created_at DESC
        """).fetchall()
    return db._rows(rows)


def pending_guest_code_count() -> int:
    with db._conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM guest_codes WHERE status='pending'"
        ).fetchone()[0]


def set_guest_home(contact_slug: str, lat: float, lng: float) -> None:
    """Cache the geocode of an approved guest's own address. Address text is
    never touched here — this only ever writes the point it resolves to."""
    with db._conn() as conn:
        conn.execute(
            "UPDATE guest_codes SET home_lat=?, home_lng=? "
            "WHERE status='approved' AND contact_slug=?",
            (lat, lng, str(contact_slug or "").strip()),
        )


def guest_display_name(first: str, last: str) -> str:
    return " ".join(p for p in (str(first or "").strip(), str(last or "").strip()) if p)


def request_guest_code(first_name: str, last_name: str, code: str,
                       phone: str = "", email: str = "") -> None:
    """File a signup request. Returns nothing on purpose.

    Every caller gets the same answer whether or not the code is already taken.
    Reporting a collision here is what would let someone walk 0000-9999 and read
    off the live codes without ever making a wrong guess at the keypad.
    """
    first, last = str(first_name or "").strip(), str(last_name or "").strip()
    with db._conn() as conn:
        conn.execute(
            "INSERT INTO guest_codes (name, first_name, last_name, phone, email, code)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (guest_display_name(first, last), first, last,
             str(phone or "").strip(), str(email or "").strip(), code),
        )


def geocode_home(address: str) -> tuple[float | None, float | None]:
    """Coordinates for a home address, or a pair of Nones.

    Never raises and never blocks a save. A home that cannot be placed loses its
    pin, not its address — the string still prints, and the trip's geocode pass
    can try again later.
    """
    addr = (address or "").strip()
    if not addr:
        return (None, None)
    try:
        import geocode  # local: dashboard/ is on the path in both apps
        # No `name=`. That fallback is for landmarks known by name rather than by
        # street, and a person's home is a street address or it is nothing.
        hit = geocode.geocode(addr)
        if hit:
            return tuple(hit)  # type: ignore[return-value]
        # The plain lookup fails on exactly the addresses the account page's own
        # autocomplete produced, because that field writes the picker's formatted
        # string and the picker is a different engine: "1 Irving Carriage City
        # Plaza" and "45-26 41 Street" are what it emits and neither re-resolves.
        # So ask the engine that wrote the string, and accept its answer ONLY on an
        # exact match of the whole line — that is the same address, not a near one.
        want = " ".join(addr.lower().split())
        for h in geocode.search_addresses(addr, limit=6):
            if " ".join(str(h.get("address") or "").lower().split()) == want:
                return (h["lat"], h["lng"])
        return (None, None)
    except Exception:  # noqa: BLE001 - an unplaceable home is not a failed save
        db.logger.warning("could not geocode home address %r", addr)
        return (None, None)


def set_guest_fields(code_id: int, data: dict) -> dict:
    """Edit who a code belongs to — the name parts, phone, email, address. Anything not in
    `data` is left alone, so the panel can save one field at a time.

    A CHANGED address is geocoded here, in the one place any address is written —
    the guest's own account form and Sam's access panel both land in this
    function. Doing it at the write is what puts a new address on the day-of map
    immediately; leaving it to the trip's geocode pass meant an address typed
    months ago still had no point on it, so the person had no ride on their
    liftoff and could not be chained into anyone else's (Aaron, Jasmine and
    Akshay all sat like that until 2026-08-31).

    The old point is dropped either way. Coordinates for the address someone just
    replaced are worse than none: they put a pin on a door nobody lives at.
    """
    sets, vals = [], []
    for k in db.GUEST_FIELDS:
        if k in data:
            sets.append(f"{k}=?")
            vals.append(str(data[k] or "").strip())
    if not sets:
        raise ValueError("nothing to change")
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM guest_codes WHERE id=?", (code_id,)).fetchone()
        if not row:
            raise ValueError("no such code")
        if "address" in data:
            addr = str(data["address"] or "").strip()
            if addr != str(row["address"] or "").strip():
                lat, lng = geocode_home(addr)
                sets += ["home_lat=?", "home_lng=?"]
                vals += [lat, lng]
        first = str(data.get("first_name", row["first_name"]) or "").strip()
        last = str(data.get("last_name", row["last_name"]) or "").strip()
        name = guest_display_name(first, last)
        if not name:
            raise ValueError("a name is first, last, or both — not neither")
        sets.append("name=?")
        vals.append(name)
        conn.execute(f"UPDATE guest_codes SET {', '.join(sets)} WHERE id=?", (*vals, code_id))
    result = guest_code_by_id(code_id)
    assert result is not None, "row just written by this same call vanished"
    return result


def approve_guest_code(code_id: int, contact_slug: str) -> dict:
    """Link a request to a person and switch it on.

    Raises ValueError on a collision or an unknown slug so the caller can tell
    Sam which it was — this is the private side, where saying "that code is
    taken" costs nothing and saves a confused guest.
    """
    with db._conn() as conn:
        where, value = db._key_where(contact_slug)
        known = conn.execute(
            f"SELECT 1 FROM members WHERE {where} LIMIT 1", (value,)
        ).fetchone()
        if not known:
            raise ValueError(f"no trip member matches '{contact_slug}'")
        row = conn.execute("SELECT code FROM guest_codes WHERE id=?", (code_id,)).fetchone()
        if not row:
            raise ValueError("no such request")
        clash = conn.execute(
            "SELECT name FROM guest_codes WHERE code=? AND status='approved' AND id<>?",
            (row["code"], code_id),
        ).fetchone()
        if clash:
            raise ValueError(f"code {row['code']} is already {clash['name']}'s — ask for another")
        # One person, one code. A second code on the same crew member is a second
        # way into their trips that nobody is tracking — revoking the one you
        # remember would leave the other live. Enforced here rather than only in
        # the picker, because the picker is a convenience and this is the rule.
        held = conn.execute(
            "SELECT name, code FROM guest_codes"
            " WHERE contact_slug=? AND status='approved' AND id<>?",
            (contact_slug, code_id),
        ).fetchone()
        if held:
            raise ValueError(
                f"that person already holds code {held['code']} ({held['name']})"
                " — revoke it first"
            )
        conn.execute(
            "UPDATE guest_codes SET status='approved', contact_slug=?,"
            " decided_at=datetime('now') WHERE id=?",
            (contact_slug, code_id),
        )
    result = guest_code_by_id(code_id)
    assert result is not None, "row just written by this same call vanished"
    return result


def set_guest_code(code_id: int, code: str) -> dict:
    """Change the four digits on an existing row.

    The code is the whole credential, so this is a password change: same
    uniqueness rule as approving, checked against the live rows rather than
    trusted from the caller.
    """
    code = (code or "").strip()
    if len(code) != 4 or not code.isdigit():
        raise ValueError("a code is four digits")
    with db._conn() as conn:
        row = conn.execute("SELECT status FROM guest_codes WHERE id=?", (code_id,)).fetchone()
        if not row:
            raise ValueError("no such code")
        clash = conn.execute(
            "SELECT name FROM guest_codes WHERE code=? AND status='approved' AND id<>?",
            (code, code_id),
        ).fetchone()
        if clash:
            raise ValueError(f"code {code} is already {clash['name']}'s — pick another")
        conn.execute("UPDATE guest_codes SET code=? WHERE id=?", (code, code_id))
    result = guest_code_by_id(code_id)
    assert result is not None, "row just written by this same call vanished"
    return result


def deny_guest_code(code_id: int) -> None:
    """Deny keeps the row. Deleting it frees the code to be resubmitted a second
    later, which is a resubmission loop Sam has to keep clicking through; the
    row costs nothing because the unique index skips denied rows."""
    with db._conn() as conn:
        conn.execute(
            "UPDATE guest_codes SET status='denied', contact_slug='',"
            " decided_at=datetime('now') WHERE id=?",
            (code_id,),
        )


def touch_guest_code(code_id: int, stale_after_minutes: int = 0) -> None:
    """Move a guest's `last_seen` to now.

    `last_seen` is read as "last online" — the access panel prints it as `last in
    3m ago` — so it has to move on every visit, not only on the one request where
    somebody types their code. The session cookie lasts thirty days, so a guest
    who unlocked once and then read the board every morning for a month passed
    through the keypad exactly once: the panel showed the unlock and called it
    their last visit.

    `stale_after_minutes` is what keeps that honest without a write per request.
    The gate hook runs on every authenticated hit, including a board page's API
    calls, and a timestamp accurate to five minutes is already finer than any
    reading of it — `ago()` rounds to minutes and then to hours. The guard is in
    the WHERE clause rather than in the caller so a burst of parallel requests
    settles at the database, where the comparison and the write are one statement.

    Zero means unconditional, which is what the unlock itself passes.
    """
    with db._conn() as conn:
        if stale_after_minutes <= 0:
            conn.execute(
                "UPDATE guest_codes SET last_seen=datetime('now') WHERE id=?", (code_id,)
            )
            return
        conn.execute(
            "UPDATE guest_codes SET last_seen=datetime('now')"
            " WHERE id=? AND (last_seen IS NULL OR last_seen=''"
            "                 OR last_seen < datetime('now', ?))",
            (code_id, f"-{int(stale_after_minutes)} minutes"),
        )


# A four-digit code is 10,000 entries, which is small enough that the only honest
# defence is a budget on guesses rather than a delay between them. So wrong codes
# accumulate into strikes, each strike shuts the keypad for twice as long as the
# last, and the fifth does not reopen on a timer at all — it waits for Sam.
#
# That caps an attacker at roughly 150 tries before a human is in the loop: a 1.5%
# chance against the space, and a loud one, because the access panel shows the
# freeze. Members pay nothing for it. A guest already holding a session never
# posts to the keypad, so a freeze can only delay a NEW unlock, and honest typing
# does not reach ten wrong codes inside one window.
#
# The window/strike tuning (`_WINDOW_FAILS`, `_WINDOW_SECONDS`, `_FREEZE_BASE_SECONDS`,
# `_HARD_STOP_STRIKE`, `_STRIKE_DECAY_SECONDS`, `_HARD_STOP_UNTIL`) lives on the
# facade (Rule 1) and is reached here as `db.<name>`.


def _stats_row(conn) -> dict:
    conn.execute("INSERT OR IGNORE INTO guest_gate_stats (id) VALUES (1)")
    row = conn.execute("SELECT * FROM guest_gate_stats WHERE id=1").fetchone()
    return db._row_strict(row)


def record_gate_failure() -> dict:
    """Count one wrong code and return the gate's state after it.

    Everything happens inside one transaction because two guesses arriving
    together must not each read the same window and both decide it has room.
    """
    with db._conn() as conn:
        r = _stats_row(conn)
        now = conn.execute("SELECT datetime('now')").fetchone()[0]

        def age(stamp):
            if not stamp:
                return None
            return conn.execute(
                "SELECT CAST(strftime('%s', ?) AS INTEGER) - CAST(strftime('%s', ?) AS INTEGER)",
                (now, stamp),
            ).fetchone()[0]

        # A day with no strike drops the escalation back to nothing, so a member
        # who fat-fingers their code months apart never inherits an old attack.
        strikes = r.get("strikes") or 0
        since_strike = age(r.get("last_strike_at"))
        if strikes and since_strike is not None and since_strike > db._STRIKE_DECAY_SECONDS:
            strikes = 0

        window_fails = (r.get("window_fails") or 0) + 1
        window_start = r.get("window_start") or now
        since_window = age(r.get("window_start"))
        if since_window is None or since_window > db._WINDOW_SECONDS:
            window_fails, window_start = 1, now

        frozen_until, last_strike_at = r.get("frozen_until") or "", r.get("last_strike_at") or ""
        if window_fails >= db._WINDOW_FAILS:
            strikes += 1
            last_strike_at = now
            window_fails, window_start = 0, now
            if strikes >= db._HARD_STOP_STRIKE:
                frozen_until = db._HARD_STOP_UNTIL
            else:
                secs = db._FREEZE_BASE_SECONDS * (2 ** (strikes - 1))
                frozen_until = conn.execute(
                    "SELECT datetime(?, ?)", (now, f"+{secs} seconds")
                ).fetchone()[0]

        conn.execute(
            """UPDATE guest_gate_stats
                  SET fails = fails + 1, last_fail_at = ?, strikes = ?, frozen_until = ?,
                      window_fails = ?, window_start = ?, last_strike_at = ?
                WHERE id = 1""",
            (now, strikes, frozen_until, window_fails, window_start, last_strike_at),
        )
        return _stats_row(conn)


def gate_frozen_until() -> str:
    """The timestamp the keypad reopens, or "" when it is open right now.

    Compared in SQLite rather than Python so the reading matches the writing —
    every stamp in this table is `datetime('now')`, which is UTC and naive, and
    comparing that against a local `datetime.now()` is off by the offset.
    """
    with db._conn() as conn:
        r = _stats_row(conn)
        until = r.get("frozen_until") or ""
        if not until:
            return ""
        still = conn.execute("SELECT ? > datetime('now')", (until,)).fetchone()[0]
        return until if still else ""


def clear_gate_freeze() -> dict:
    """Sam's reset, from the access panel. Reopens the keypad and forgives the
    escalation; the lifetime `fails` counter is left alone, because it is the only
    record that any of this happened."""
    with db._conn() as conn:
        _stats_row(conn)
        conn.execute(
            """UPDATE guest_gate_stats
                  SET strikes = 0, frozen_until = '', window_fails = 0,
                      window_start = '', last_strike_at = ''
                WHERE id = 1"""
        )
        return _stats_row(conn)


def gate_stats() -> dict:
    """What the access panel renders: the lifetime failure count, plus whether the
    keypad is shut right now and whether it needs Sam to reopen it."""
    with db._conn() as conn:
        r = _stats_row(conn)
        until = r.get("frozen_until") or ""
        frozen = bool(until) and bool(
            conn.execute("SELECT ? > datetime('now')", (until,)).fetchone()[0]
        )
    return {
        "fails": r.get("fails") or 0,
        "last_fail_at": r.get("last_fail_at") or "",
        "strikes": r.get("strikes") or 0,
        "frozen_until": until if frozen else "",
        "needs_clearing": frozen and until == db._HARD_STOP_UNTIL,
    }

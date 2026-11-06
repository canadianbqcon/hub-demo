# vault-code/dashboard/hub/finances/paystub_ingest.py
"""Deterministic file + DB operations for the /icloud pay-stub handler.

Claude does the image parse and shows numbers for Sam to confirm; this
module does only the mechanical, testable parts: HEIC->PNG, md5-verified
preserve, and the idempotent DB write. Destructive cleanup (deleting the iCloud
original) is done by the skill ONLY after write_paystub returns successfully.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import icloud_root, vault_root  # noqa: E402

from finances import db  # noqa: E402

PAYSTUBS_DIR = vault_root() / "finance" / "paystubs"
# Resolves per machine (WSL vs Mac); ICLOUD_DRIVE still overrides, for tests.
ICLOUD_DRIVE = icloud_root()
# Canonical earnings DB — same path the Hub app inits at app.py (EARNINGS_DB).
EARNINGS_DB = vault_root() / "data" / "earnings.db"


def _ensure_db() -> None:
    """Point `db` at the canonical earnings.db when it isn't already inited.

    The Hub app calls db.init(EARNINGS_DB) at startup, but the /icloud skill
    runs this module as a standalone process where that never fires — leaving
    db._db_path None, so DB ops would silently open a stray "None" file instead
    of data/earnings.db. init() is idempotent (CREATE TABLE IF NOT EXISTS), so
    calling it here is safe whether or not the app already ran.
    """
    if db._db_path is None:
        db.init(EARNINGS_DB)


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes(), usedforsecurity=False).hexdigest()


def heic_to_png(src: Path, dst: Path) -> Path:
    """Convert a HEIC image to PNG so Claude can read it."""
    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    img = Image.open(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "PNG")
    return dst


def preserve_stub(src_heic: Path, period_start: str, period_end: str,
                  transcription_md: str) -> tuple[Path, Path]:
    """Copy the stub into finance/paystubs/ (md5-verified) + write the .md beside it."""
    PAYSTUBS_DIR.mkdir(parents=True, exist_ok=True)
    # Validate the period strings are ISO dates before they become a filename,
    # so a traversal-shaped value can't escape PAYSTUBS_DIR. Raises ValueError.
    date.fromisoformat(period_start)
    date.fromisoformat(period_end)
    base = f"jc-paystub-{period_start}_{period_end}"
    heic_dst = PAYSTUBS_DIR / f"{base}.heic"
    md_dst = PAYSTUBS_DIR / f"{base}.md"
    shutil.copy2(src_heic, heic_dst)
    if _md5(src_heic) != _md5(heic_dst):
        raise IOError(f"md5 mismatch preserving {src_heic} -> {heic_dst}")
    md_dst.write_text(transcription_md)
    return heic_dst, md_dst


def already_ingested(period_start: str, period_end: str,
                     source: str = "juniper-and-co") -> bool:
    _ensure_db()
    for row in db.list_earnings():
        if (row["source"] == source and row["period_start"] == period_start
                and row["period_end"] == period_end):
            return True
    return False


def write_paystub(parsed: dict) -> int:
    """Write one parsed stub (idempotent on the UNIQUE period key)."""
    _ensure_db()
    return db.upsert_earning(
        parsed["record"],
        parsed.get("shifts", []),
        parsed.get("deductions", []),
    )


# ── Pay-stub → calendar time correction ──────────────────────────────────────
# A shift event is created days ahead as a prediction ("15:30–00:00"); the stub
# records what was actually punched ("15:27–21:57"). Nothing used to carry the
# second back onto the first, so the calendar permanently overstated hours.
#
# Direction is one-way and narrow on purpose: the punch clock corrects the
# calendar, never the reverse, and only `start`/`end` are patched -- title,
# colour, location and description are the calendar's own and stay untouched.
# A punched shift with no calendar event is REPORTED, never created (Sam's
# call, 2026-08-29): the calendar is his record of what he planned, and shifts
# appearing retroactively in weeks he has already read past is worse than a gap.

CORRECTION_TZ = "America/New_York"


def _ev_times(ev: dict) -> tuple[str | None, str | None]:
    """(start, end) dateTimes, or (None, None) for an all-day event."""
    s = (ev.get("start") or {}).get("dateTime")
    e = (ev.get("end") or {}).get("dateTime")
    return (s, e) if s and e else (None, None)


def calendar_corrections(earnings_id: int, events: list[dict] | None = None) -> list[dict]:
    """What the calendar should say for one pay stub's shifts, vs what it says.

    Returns one row per punched shift, each tagged:
      'fix'      -- a work-shift event exists and its times disagree
      'ok'       -- event already matches (nothing to do)
      'no_event' -- nothing on the calendar for that day; report, do not create
      'all_day'  -- an all-day event carries no clock time to correct
    Read-only. Nothing here writes; `apply_corrections` does that.
    """
    _ensure_db()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import shift_calendar  # noqa: E402  (local: needs the finances dir on path)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from gcal import snap_iso_to_5min  # noqa: E402

    earning = db.get_earning(earnings_id)
    if not earning:
        raise ValueError(f"no earnings row {earnings_id}")
    shifts = [s for s in earning["shifts"] if s.get("clock_in") and s.get("clock_out")]
    if not shifts:
        return []

    if events is None:
        # +2 days: an overnight shift on the last day of the period ends on a
        # date outside it, and Google filters by the event's own window.
        lo = date.fromisoformat(min(s["shift_date"] for s in shifts))
        hi = date.fromisoformat(max(s["shift_date"] for s in shifts)) + timedelta(days=2)
        events = shift_calendar.list_events(start=lo, end=hi)

    work = [ev for ev in events
            if shift_calendar.source_for(ev.get("summary", ""), ev.get("description"),
                                         ev.get("location"))]

    out = []
    for s in sorted(shifts, key=lambda r: r["shift_date"]):
        new_start = snap_iso_to_5min(s["clock_in"])
        new_end = snap_iso_to_5min(s["clock_out"])
        # Same-day candidates; if he was double-booked, the nearest start wins.
        same_day = [ev for ev in work
                    if ((ev.get("start") or {}).get("dateTime")
                        or (ev.get("start") or {}).get("date") or "")[:10] == s["shift_date"]]
        row = {"shift_date": s["shift_date"], "hours": s.get("hours"),
               "new_start": new_start, "new_end": new_end,
               "event_id": None, "summary": None, "cur_start": None, "cur_end": None}
        if not same_day:
            out.append({**row, "status": "no_event"})
            continue
        ev = min(same_day, key=lambda e: abs(
            _mins((e.get("start") or {}).get("dateTime") or "") - _mins(new_start)))
        cur_start, cur_end = _ev_times(ev)
        row.update({"event_id": ev.get("id"), "summary": ev.get("summary"),
                    "cur_start": cur_start, "cur_end": cur_end})
        if cur_start is None:
            out.append({**row, "status": "all_day"})
        elif cur_start == new_start and cur_end == new_end:
            out.append({**row, "status": "ok"})
        else:
            out.append({**row, "status": "fix"})
    return out


def _mins(iso: str) -> int:
    """Minutes-since-midnight of an ISO dateTime; a missing one sorts last."""
    if "T" not in (iso or ""):
        return 10 ** 6
    t = iso[11:16]
    return int(t[:2]) * 60 + int(t[3:])


def apply_corrections(rows: list[dict]) -> list[dict]:
    """Patch every row tagged 'fix'. Returns the rows it actually wrote.

    Only start/end are sent, so a failed patch cannot damage anything else on
    the event. A row without a 'fix' status is ignored -- callers pass the whole
    reviewed list and this picks the approved subset out of it.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from gcal import patch_event  # noqa: E402

    written = []
    for r in rows:
        if r.get("status") != "fix" or not r.get("event_id"):
            continue
        patch_event(r["event_id"], {
            "start": {"dateTime": r["new_start"], "timeZone": CORRECTION_TZ},
            "end": {"dateTime": r["new_end"], "timeZone": CORRECTION_TZ},
        })
        written.append(r)
    return written

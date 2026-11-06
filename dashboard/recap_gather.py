"""Day-window data pulls for the /recap skill. Read-only.

Provides the three gather functions that did not already have a helper:
the vault-log extractor, the YNAB window filter, and the Gmail window query.
Everything else /recap needs is reused from gcal.py, memo_ingest.py,
geocode.py, tasks.py, hub/finances/book.py, and services.py.
"""
import logging
import os
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def _vault_path() -> str:
    return Path(os.path.expanduser("~/.config/vault-api/vault_path")).read_text().strip()


def log_entries_for_date(date_str: str, log_path: str | None = None) -> list[str]:
    """Bullet lines under the `## <date_str>` H2 section of log/log.md."""
    path = log_path or os.path.join(_vault_path(), "log", "log.md")
    try:
        lines = Path(path).read_text().splitlines()
    except FileNotFoundError:
        return []
    out, in_section = [], False
    for line in lines:
        if line.startswith("## "):
            in_section = line[3:].strip() == date_str
            continue
        if in_section and line.lstrip().startswith("- "):
            out.append(line.lstrip()[2:].strip())
    return out


def ynab_transactions_for_window(start_date: str, end_date: str) -> list[dict]:
    """Book outflows whose date is in [start_date, end_date] (inclusive).

    The book is date-granular; there is no intra-day timestamp. since_date is set
    to start_date so the API returns from the window's start forward.
    """
    import sys
    from pathlib import Path
    _hub = str(Path(__file__).resolve().parent / "hub")
    if _hub not in sys.path:
        sys.path.insert(0, _hub)
    from finances import book
    txns = book.fetch_transactions(since_date=start_date)
    return [t for t in txns if start_date <= t.get("date", "") <= end_date]


# Senders/labels that carry real-world activity signal (corroboration only).
_GMAIL_SIGNAL = (
    'label:invoices OR label:travel OR label:receipts '
    'OR from:uber OR from:lyft OR from:opentable OR from:resy '
    'OR subject:(receipt OR confirmation OR reservation OR "order")'
)


def build_gmail_query(start_date: str, end_date: str, include_sent: bool = True) -> str:
    """Gmail q= string for the window, pre-filtered to activity signal.

    Gmail before: is exclusive, so it is set to the day AFTER end_date.
    """
    after = start_date.replace("-", "/")
    before = (date.fromisoformat(end_date) + timedelta(days=1)).isoformat().replace("-", "/")
    parts = [f"after:{after}", f"before:{before}", f"({_GMAIL_SIGNAL})"]
    q = " ".join(parts)
    if include_sent:
        q = f"({q}) OR (after:{after} before:{before} in:sent)"
    return q


def gmail_messages_for_window(start_date: str, end_date: str, include_sent: bool = True) -> list[dict]:
    """Pre-filtered Gmail messages in the window. Read-only, best-effort."""
    try:
        # services.py lives in ~/.config/vault-api/, not on the dashboard path.
        # Add it so callers do not have to know where the credentials module is.
        import sys
        _cfg = os.path.expanduser("~/.config/vault-api")
        if _cfg not in sys.path:
            sys.path.insert(0, _cfg)
        import services  # pyright: ignore[reportMissingImports]
        svc = services.gmail_readonly()
        q = build_gmail_query(start_date, end_date, include_sent)
        listed = svc.users().messages().list(userId="me", q=q, maxResults=100).execute()
        out = []
        for m in listed.get("messages", []):
            full = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()
            hdrs = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
            out.append({
                "id": m["id"],
                "from": hdrs.get("From", ""),
                "to": hdrs.get("To", ""),
                "subject": hdrs.get("Subject", ""),
                "date_header": hdrs.get("Date", ""),
                "snippet": full.get("snippet", ""),
            })
        return out
    except Exception:
        logger.exception("gmail_messages_for_window failed for %s..%s", start_date, end_date)
        return []

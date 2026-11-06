from __future__ import annotations

import logging
import base64
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import google_auth
from config import CONFIG_DIR
from google_auth import CREDENTIALS_FILE  # noqa: F401  (module surface)

logger = logging.getLogger(__name__)

DASHBOARD_DIR = Path(__file__).parent
TOKEN_FILE = CONFIG_DIR / "gmail_token.json"

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# Gmail shares the PKCE flow but keeps its own is_authenticated and _load_creds:
# it persists token expiry and probes liveness with a forced refresh, which the
# other connectors don't need.
_auth = google_auth.GoogleAuth(TOKEN_FILE, SCOPES)

has_credentials = _auth.has_credentials
needs_reauth = _auth.needs_reauth
get_auth_url = _auth.get_auth_url
handle_callback = _auth.handle_callback

_auth_cache: dict = {}  # {"mtime": float, "ok": bool}


def is_authenticated() -> bool:
    """True only when a token exists AND can produce usable credentials.

    A token whose refresh token has been revoked or expired returns False —
    the file existing is not enough. This is what lets the dashboard show an
    honest "gmail disconnected" state instead of a green dot over an empty
    panel. Result is memoized against the token file's mtime so the repeated
    calls in one page render don't each hit Google; re-auth rewrites the file,
    which changes the mtime and busts the cache."""
    if not TOKEN_FILE.exists():
        return False
    try:
        mtime = TOKEN_FILE.stat().st_mtime
    except OSError:
        return False
    if _auth_cache.get("mtime") == mtime:
        return _auth_cache["ok"]
    try:
        _load_creds(force_refresh=True)
        ok = True
    except Exception:
        ok = False
    # _load_creds rewrites the token file on a successful refresh, changing the
    # mtime; re-read it so the cache key matches the file we'll see next call.
    try:
        mtime = TOKEN_FILE.stat().st_mtime
    except OSError:
        pass
    _auth_cache["mtime"] = mtime
    _auth_cache["ok"] = ok
    return ok


def _load_creds(force_refresh: bool = False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    data = json.loads(TOKEN_FILE.read_text())
    creds = Credentials(
        token=data["token"],
        refresh_token=data.get("refresh_token"),
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data.get("scopes", SCOPES),
    )
    stored_expiry = data.get("expiry")
    if stored_expiry:
        try:
            exp = datetime.fromisoformat(stored_expiry.replace("Z", "+00:00"))
            # google.auth compares expiry against a naive UTC now(), so an
            # aware datetime (the "Z" form google's own to_json writes) raises
            # "can't compare offset-naive and offset-aware". Normalize to naive
            # UTC before handing it to the credentials object.
            if exp.tzinfo is not None:
                exp = exp.astimezone(timezone.utc).replace(tzinfo=None)
            creds.expiry = exp
        except ValueError:
            stored_expiry = None
    # Refresh when forced (the is_authenticated liveness probe), when the access
    # token is expired, or when we have no recorded expiry. A stored expiry can
    # still read "valid" after the token was revoked server-side, so the honest
    # connection test forces a refresh — a revoked or expired refresh token
    # raises RefreshError here, which is what is_authenticated() reports on.
    if creds.refresh_token and (force_refresh or not creds.valid or not stored_expiry):
        creds.refresh(Request())
        data["token"] = creds.token
        if creds.expiry:
            data["expiry"] = creds.expiry.isoformat()
        TOKEN_FILE.write_text(json.dumps(data))
    return creds


def _get_service():
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=_load_creds())


def _fetch_from_label(label_ids: list[str], max_results: int) -> list[dict]:
    """Shared fetch logic for a set of label IDs. Returns [{id, from, subj, age}].

    The per-message metadata is fetched in a single Gmail *batch* HTTP request
    rather than one sequential .get() per message. The old N+1 loop made the home
    page block ~2s per label (list + ~6-12 serial round-trips to Google); batching
    collapses that to one round-trip. Same live data, no caching.
    """
    service = _get_service()
    result = (
        service.users()
        .messages()
        .list(
            userId="me",
            labelIds=label_ids,
            maxResults=max_results,
        )
        .execute()
    )
    msg_ids = result.get("messages", [])
    if not msg_ids:
        return []

    # Collect each message's detail keyed by id via one batch request. Individual
    # message failures are skipped (callback's exception arg) rather than failing
    # the whole batch.
    details: dict[str, dict] = {}

    def _collect(request_id: str, response: dict, exception) -> None:
        if exception is None and response is not None:
            details[request_id] = response

    batch = service.new_batch_http_request(callback=_collect)
    for m in msg_ids:
        batch.add(
            service.users()
            .messages()
            .get(
                userId="me",
                id=m["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ),
            request_id=m["id"],
        )
    batch.execute()

    today = datetime.now(timezone.utc).date()
    out = []
    for m in msg_ids:  # preserve the list's recency order
        detail = details.get(m["id"])
        if detail is None:
            continue
        headers = {
            h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])
        }
        from_raw = headers.get("From", "")
        from_name = (
            from_raw.split("<")[0].strip().strip('"').lower() or from_raw.lower()
        )
        subj = headers.get("Subject", "(no subject)").lower()[:48]
        date_raw = headers.get("Date", "")
        try:
            msg_date = parsedate_to_datetime(date_raw).date()
            delta = (today - msg_date).days
            age = f"{delta}d" if delta > 0 else "today"
        except Exception:
            age = "—"
        out.append({"id": m["id"], "from": from_name, "subj": subj, "age": age})
    return out


def _extract_text(payload: dict) -> str:
    """Recursively extract readable text from a Gmail message payload. Prefers plain text; falls back to stripped HTML."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime_type == "text/plain" and body_data:
        return base64.urlsafe_b64decode(body_data + "==").decode(
            "utf-8", errors="replace"
        )

    # Recurse into parts first (plain-text parts anywhere in the tree win)
    for part in payload.get("parts", []):
        text = _extract_text(part)
        if text:
            return text

    # HTML fallback: strip tags when no plain-text part was found
    if "html" in mime_type and body_data:
        html = base64.urlsafe_b64decode(body_data + "==").decode(
            "utf-8", errors="replace"
        )
        html = re.sub(
            r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE
        )
        html = re.sub(
            r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE
        )
        html = re.sub(r"<(?:br|p|div|tr|h[1-6])[^>]*>", "\n", html, flags=re.IGNORECASE)
        html = re.sub(r"<[^>]+>", "", html)
        html = re.sub(r"\n{3,}", "\n\n", re.sub(r" +", " ", html))
        return html.strip()

    return ""


def fetch_message_body(message_id: str) -> dict:
    """Fetch full headers + plain-text body for a single message."""
    try:
        service = _get_service()
        detail = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="full",
            )
            .execute()
        )
        headers = {
            h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])
        }
        return {
            "id": message_id,
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "body": _extract_text(detail.get("payload", {})),
        }
    except Exception as exc:
        return {"error": str(exc)}


def fetch_messages(max_results: int = 8) -> list[dict]:
    """Fetch recent inbox messages. Returns [{from, subj, age}]."""
    try:
        return _fetch_from_label(["INBOX"], max_results)
    except Exception:
        logger.exception("fetch_messages failed")
        return []


def fetch_applications(max_results: int = 12) -> list[dict]:
    """Fetch emails from the Job Apps/b. Applications Gmail label. Returns [{from, subj, age}]."""
    try:
        # Label_14 = IV. Job Apps/b. Applications
        return _fetch_from_label(["Label_14"], max_results)
    except Exception:
        logger.exception("fetch_applications failed")
        return []


def search_messages(query: str, max_results: int = 60) -> list[dict]:
    """Gmail search by query string, returning full bodies.

    `_fetch_from_label` is metadata-only and label-scoped, which is right for the
    home page's counts and wrong here: matching an order email means reading it.
    Bodies are fetched in one batch request rather than N serial gets, same as
    that helper does for metadata. Returns [{id, from, subject, date, body}].
    """
    service = _get_service()
    listing = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    msg_ids = listing.get("messages", [])
    if not msg_ids:
        return []

    details: dict[str, dict] = {}

    def _collect(request_id: str, response: dict, exception) -> None:
        if exception is None and response is not None:
            details[request_id] = response

    # Gmail rate-limits a batch of full gets: of 60 in one batch only 42 came
    # back (2026-10-22), the rest failing quietly in _collect. Small batches,
    # then each straggler fetched on its own, so a search never drops mail.
    for i in range(0, len(msg_ids), 20):
        batch = service.new_batch_http_request(callback=_collect)
        for m in msg_ids[i:i + 20]:
            batch.add(
                service.users().messages().get(userId="me", id=m["id"], format="full"),
                request_id=m["id"],
            )
        batch.execute()
    for m in msg_ids:
        if m["id"] not in details:
            details[m["id"]] = (
                service.users().messages().get(userId="me", id=m["id"], format="full").execute()
            )

    out = []
    for m in msg_ids:  # preserve recency order
        detail = details.get(m["id"])
        if detail is None:
            continue
        payload = detail.get("payload", {})
        headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
        out.append(
            {
                "id": m["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "body": _extract_text(payload),
            }
        )
    return out

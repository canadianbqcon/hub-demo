"""Global vault API access — the one import every skill uses for Google and YNAB.

    import sys, os
    sys.path.insert(0, os.path.expanduser('~/.config/vault-api'))
    from services import gmail, calendar, drive, docs, sheets, YNAB_TOKEN

    svc = gmail()

Reached through the symlink `~/.config/vault-api/services.py`, which is what the
skills put on `sys.path`. The file itself lives here in the code repo so it is
version-controlled; it used to exist only as an unversioned copy in
`~/.config/vault-api/` on one machine, which meant the single import path every
Google-touching skill depends on had no backup anywhere.

This module is a thin facade over the connector modules beside it (`gcal`,
`gmail`, `gdrive`, `gdocs`, `gsheets`) — it owns no OAuth logic of its own. All
of that is `google_auth.GoogleAuth`, and tokens live in `CONFIG_DIR`
(`~/.config/vault-api/`, overridable with `VAULT_API_CONFIG`), so a token minted
through the Hub's auth routes is immediately visible here with no copying.

The one thing this layer adds is the read-only Gmail boundary. `gmail_readonly()`
returns a service built from a `gmail.readonly` token, and `gmail()` returns it
automatically when `VAULT_HEADLESS_READONLY=1` — the flag the Hub scheduler sets
for unattended runs. That makes draft-only a *credential* guarantee rather than a
prompt instruction: every write call (`messages().modify`, `.trash`, label
create) 403s at Google rather than relying on the model to hold back. See
`hub/scheduler.py::_enforce_boundary`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Locate the code repo, then the connector modules ──────────────────────────

_CONFIG_DIR_DEFAULT = Path.home() / ".config" / "vault-api"
CONFIG_DIR = Path(os.environ.get("VAULT_API_CONFIG", _CONFIG_DIR_DEFAULT))


def _code_root() -> Path:
    """The vault-code repo: VAULT_CODE_PATH, else the machine-local pointer file.

    Falls back to this file's own parent chain so an in-repo import still works
    on a machine that never wrote the pointer files.
    """
    env = os.environ.get("VAULT_CODE_PATH")
    if env:
        return Path(env)
    pointer = CONFIG_DIR / "code_path"
    if pointer.exists():
        text = pointer.read_text().strip()
        if text:
            return Path(text)
    return Path(__file__).resolve().parent.parent


CODE_ROOT = _code_root()
DASHBOARD_DIR = CODE_ROOT / "dashboard"

if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

# ── Credential and token paths ────────────────────────────────────────────────

CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
CALENDAR_TOKEN = CONFIG_DIR / "token.json"
GMAIL_TOKEN = CONFIG_DIR / "gmail_token.json"
GMAIL_READONLY_TOKEN = CONFIG_DIR / "gmail_readonly_token.json"
DRIVE_TOKEN = CONFIG_DIR / "drive_token.json"
DOCS_TOKEN = CONFIG_DIR / "docs_token.json"
SHEETS_TOKEN = CONFIG_DIR / "sheets_token.json"

GMAIL_READONLY_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# ── dashboard/.env ────────────────────────────────────────────────────────────

ENV_FILE = DASHBOARD_DIR / ".env"


def _load_env() -> dict:
    """Parse dashboard/.env into a dict and seed os.environ (setdefault).

    Same reader as `hub/app.py` uses, kept here so a skill that imports this
    module without going through the Hub gets the same values.
    """
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        values[key] = value
        os.environ.setdefault(key, value)
    return values


ENV = _load_env()

YNAB_TOKEN = os.environ.get("YNAB_TOKEN", "")
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "vault-research/1.0")


# ── Guardrail ─────────────────────────────────────────────────────────────────


def _require(token_file: Path, auth_route: str):
    """Fail with the fix, not a stack trace three frames deep in googleapiclient."""
    if not CREDENTIALS_FILE.exists():
        raise RuntimeError(
            f"{CREDENTIALS_FILE} is missing — the shared Google OAuth client secret.\n"
            "It is gitignored and per-machine. Download it from the 'Vesper Dashboard' "
            "project in console.cloud.google.com, or copy it from a machine that has "
            "it. Setup: <vault-code>/dashboard/CLAUDE-first-run.md"
        )
    if not token_file.exists():
        raise RuntimeError(
            f"{token_file} is missing — this connector has never been authorised on "
            f"this machine.\nStart the Hub (port 5002) and visit "
            f"http://localhost:5002{auth_route} once to mint it."
        )


# ── Service factories ─────────────────────────────────────────────────────────


def calendar():
    """Google Calendar v3, read/write."""
    _require(CALENDAR_TOKEN, "/api/calendar/auth")
    import gcal

    return gcal._get_service()


def gmail():
    """Gmail v1.

    Read/write normally. Under VAULT_HEADLESS_READONLY=1 this returns the
    read-only service instead, so an unattended run cannot write even if it tries.
    """
    if os.environ.get("VAULT_HEADLESS_READONLY") == "1":
        return gmail_readonly()
    _require(GMAIL_TOKEN, "/api/gmail/auth")
    import gmail as _gmail_module

    return _gmail_module._get_service()


def gmail_readonly():
    """Gmail v1 built from a gmail.readonly token — every write 403s at Google."""
    _require(GMAIL_READONLY_TOKEN, "/api/gmail/auth?readonly=1")
    import google_auth

    return google_auth.GoogleAuth(GMAIL_READONLY_TOKEN, GMAIL_READONLY_SCOPES).service(
        "gmail", "v1"
    )


def drive():
    """Google Drive v3, full scope."""
    _require(DRIVE_TOKEN, "/api/drive/auth")
    import gdrive

    return gdrive._get_service()


def docs():
    """Google Docs v1, read/write."""
    _require(DOCS_TOKEN, "/api/docs/auth")
    import gdocs

    return gdocs._get_service()


def sheets():
    """Google Sheets v4, read/write."""
    _require(SHEETS_TOKEN, "/api/sheets/auth")
    import gsheets

    return gsheets._get_service()


# ── Reddit (client_credentials, read-only by construction) ────────────────────

_reddit_token: dict = {}


def reddit_get(path: str, **params):
    """GET a Reddit API path and return the parsed JSON.

    App-only OAuth (`client_credentials`), so there is no user context and
    nothing here can post, vote or comment. Credentials come from
    dashboard/.env: REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET.
    """
    import time

    import requests

    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        raise RuntimeError(
            "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are not set in "
            f"{ENV_FILE} — reddit_get cannot authenticate."
        )
    if _reddit_token.get("expires_at", 0) <= time.time():
        resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": REDDIT_USER_AGENT},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        _reddit_token["token"] = payload["access_token"]
        _reddit_token["expires_at"] = time.time() + payload.get("expires_in", 3600) - 60

    resp = requests.get(
        f"https://oauth.reddit.com/{path.lstrip('/')}",
        headers={
            "Authorization": f"bearer {_reddit_token['token']}",
            "User-Agent": REDDIT_USER_AGENT,
        },
        params=params,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


# ── Diagnostics ───────────────────────────────────────────────────────────────


def status() -> dict:
    """What is actually authorised on this machine. Cheap — reads no network."""
    return {
        "config_dir": str(CONFIG_DIR),
        "dashboard_dir": str(DASHBOARD_DIR),
        "credentials.json": CREDENTIALS_FILE.exists(),
        "calendar": CALENDAR_TOKEN.exists(),
        "gmail": GMAIL_TOKEN.exists(),
        "gmail_readonly": GMAIL_READONLY_TOKEN.exists(),
        "drive": DRIVE_TOKEN.exists(),
        "docs": DOCS_TOKEN.exists(),
        "sheets": SHEETS_TOKEN.exists(),
        "ynab_token": bool(YNAB_TOKEN),
        "reddit": bool(REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET),
        "headless_readonly": os.environ.get("VAULT_HEADLESS_READONLY") == "1",
    }


if __name__ == "__main__":
    import json

    print(json.dumps(status(), indent=2))

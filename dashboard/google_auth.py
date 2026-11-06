"""Shared Google OAuth (installed-app PKCE) flow for the dashboard connectors.

One `GoogleAuth` instance per connector, parameterised by its token file and
scopes. The five connectors (gcal, gdocs, gdrive, gsheets, gmail) all share the
same client secrets file and the same PKCE dance; only the token file, the
scope list, and the discovery API name/version differ.

Usage in a connector module:

    _auth = google_auth.GoogleAuth(CONFIG_DIR / "docs_token.json", SCOPES)
    has_credentials = _auth.has_credentials
    is_authenticated = _auth.is_authenticated
    needs_reauth = _auth.needs_reauth
    get_auth_url = _auth.get_auth_url
    handle_callback = _auth.handle_callback
    _load_creds = _auth.load_creds

    def _get_service():
        return _auth.service("docs", "v1")

gmail.py keeps its own `is_authenticated` (a live refresh probe, memoized on the
token file's mtime) and its own `load_creds` (expiry persistence + force_refresh),
and reuses only the flow half of this class.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from pathlib import Path

from config import CONFIG_DIR

logger = logging.getLogger(__name__)

CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"


def pkce_pair() -> tuple[str, str]:
    """A PKCE (verifier, S256 challenge) pair."""
    verifier = secrets.token_urlsafe(96)[:128]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


class GoogleAuth:
    def __init__(self, token_file: Path, scopes: list[str]):
        self.token_file = token_file
        self.scopes = scopes
        # Per-connector, since two connectors can be mid-consent at once.
        self._flow_state: dict = {}

    # ── State ──────────────────────────────────────────────────────────────────

    def has_credentials(self) -> bool:
        return CREDENTIALS_FILE.exists()

    def is_authenticated(self) -> bool:
        return self.token_file.exists()

    def needs_reauth(self) -> bool:
        """True if the stored token lacks a scope this connector now requires."""
        if not self.token_file.exists():
            return False
        try:
            stored = set(json.loads(self.token_file.read_text()).get("scopes", []))
            return not set(self.scopes).issubset(stored)
        except Exception:
            logger.exception("needs_reauth check failed for %s", self.token_file.name)
            return False

    # ── Flow ───────────────────────────────────────────────────────────────────

    def _flow(self, **kwargs):
        from google_auth_oauthlib.flow import Flow

        return Flow.from_client_secrets_file(
            str(CREDENTIALS_FILE), scopes=self.scopes, **kwargs
        )

    def get_auth_url(self, redirect_uri: str) -> str:
        flow = self._flow(redirect_uri=redirect_uri)
        verifier, challenge = pkce_pair()
        url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            code_challenge=challenge,
            code_challenge_method="S256",
        )
        self._flow_state = {
            "state": state,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
        return url

    def handle_callback(self, authorization_response_url: str) -> tuple[bool, str]:
        try:
            flow = self._flow(
                redirect_uri=self._flow_state.get("redirect_uri", ""),
                state=self._flow_state.get("state"),
            )
            os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
            flow.fetch_token(
                authorization_response=authorization_response_url,
                code_verifier=self._flow_state.get("code_verifier", ""),
            )
            self.write_token(flow.credentials)
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def write_token(self, creds) -> None:
        """Persist credentials as the token JSON every connector's load_creds reads.

        `expiry` is written for all connectors even though only gmail reads it —
        one write path beats a per-connector variant, and an unused key is free.
        """
        self.token_file.write_text(
            json.dumps(
                {
                    "token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri": getattr(creds, "token_uri", None),
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": list(creds.scopes or self.scopes),
                    "expiry": creds.expiry.isoformat() if creds.expiry else None,
                }
            )
        )

    # ── Credentials ────────────────────────────────────────────────────────────

    def load_creds(self):
        """Credentials from the stored token, refreshed and rewritten if expired."""
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        data = json.loads(self.token_file.read_text())
        creds = Credentials(
            token=data["token"],
            refresh_token=data.get("refresh_token"),
            token_uri=data["token_uri"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scopes=data.get("scopes", self.scopes),
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            data["token"] = creds.token
            self.token_file.write_text(json.dumps(data))
        return creds

    def service(self, api: str, version: str):
        from googleapiclient.discovery import build

        return build(api, version, credentials=self.load_creds())

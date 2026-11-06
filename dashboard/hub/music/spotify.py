"""Spotify Web API for the music pull (reads) and the sort playlists (create + add only). Stdlib only.

Login once:  python3 -m music.library login
"""

import base64
import http.server
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_CONF = Path.home() / ".config" / "vault-api"
TOKEN_PATH = _CONF / "spotify_token.json"
CREDS_PATH = _CONF / "spotify_creds.json"
REDIRECT = "http://127.0.0.1:8888/callback"
# modify scopes are for create_playlist/add_items only; nothing here edits or deletes an existing list
SCOPES = ("playlist-read-private playlist-read-collaborative user-library-read "
          "playlist-modify-private playlist-modify-public")
API = "https://api.spotify.com/v1"
_AUTH = "https://accounts.spotify.com/authorize"
_TOKEN = "https://accounts.spotify.com/api/token"

_sleep = time.sleep  # tests stub this
MAX_WAIT = 60  # longest Retry-After worth sleeping through
_cached = {}  # {"access_token", "expires_at"}


class AuthError(Exception):
    """No usable login; run `python3 -m music.library login`."""


def _open(req):
    """The only place HTTP happens. -> (status, headers dict, parsed JSON or None)."""
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, hdrs, body = r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        status, hdrs, body = e.code, dict(e.headers), e.read()
    try:
        data = json.loads(body) if body else None
    except ValueError:
        data = None
    return status, hdrs, data


def _creds():
    try:
        c = json.loads(CREDS_PATH.read_text())
        return c["client_id"], c["client_secret"]
    except (OSError, ValueError, KeyError) as e:
        raise AuthError(f"no usable {CREDS_PATH.name}") from e


def _basic(cid, secret):
    return "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()


def _token_post(form):
    cid, secret = _creds()
    req = urllib.request.Request(_TOKEN, data=urllib.parse.urlencode(form).encode(), method="POST",
                                 headers={"Authorization": _basic(cid, secret),
                                          "Content-Type": "application/x-www-form-urlencoded"})
    return _open(req)


def _save(tok):
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_PATH.with_name(TOKEN_PATH.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(tok, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, TOKEN_PATH)


def login():
    cid, _ = _creds()
    state = secrets.token_urlsafe(16)
    url = _AUTH + "?" + urllib.parse.urlencode({
        "client_id": cid, "response_type": "code", "redirect_uri": REDIRECT,
        "scope": SCOPES, "state": state})
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Spotify login received. You can close this tab.")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 8888), H)
    print("Open this URL and approve:\n" + url, flush=True)
    try:
        srv.handle_request()
    finally:
        srv.server_close()
    if got.get("state") != state or "code" not in got:
        raise AuthError("login not approved or state mismatch: " + got.get("error", "no code"))
    status, _, data = _token_post({"grant_type": "authorization_code", "code": got["code"],
                                   "redirect_uri": REDIRECT})
    if status != 200 or not data or "refresh_token" not in data:
        raise AuthError(f"code exchange failed ({status})")
    _save({"refresh_token": data["refresh_token"], "access_token": data["access_token"],
           "expires_at": time.time() + data.get("expires_in", 3600), "scope": data.get("scope", "")})
    _cached.clear()
    print("Saved Spotify token.")


def _access_token(force=False):
    if not force and _cached.get("access_token") and _cached.get("expires_at", 0) > time.time() + 60:
        return _cached["access_token"]
    try:
        tok = json.loads(TOKEN_PATH.read_text())
        rt = tok["refresh_token"]
    except (OSError, ValueError, KeyError) as e:
        raise AuthError("no Spotify login on disk") from e
    status, _, data = _token_post({"grant_type": "refresh_token", "refresh_token": rt})
    if status in (400, 401):
        raise AuthError(f"refresh rejected ({status})")
    if status != 200 or not data:
        raise RuntimeError(f"token refresh failed ({status})")
    _cached.update(access_token=data["access_token"], expires_at=time.time() + data.get("expires_in", 3600))
    if data.get("refresh_token") and data["refresh_token"] != rt:  # rotated
        tok["refresh_token"] = data["refresh_token"]
        _save(tok)
    return _cached["access_token"]


def _get(url, method="GET", body=None):
    """One call with 429 backoff (5 retries) and a single re-auth on 401 -> JSON."""
    reauthed = False
    for attempt in range(6):
        hd = {"Authorization": "Bearer " + _access_token()}
        if body is not None:
            hd["Content-Type"] = "application/json"
        req = urllib.request.Request(url, method=method, headers=hd,
                                     data=None if body is None else json.dumps(body).encode())
        status, hdrs, data = _open(req)
        if status in (200, 201):
            return data
        if status == 401 and not reauthed:
            reauthed = True
            _access_token(force=True)
            continue
        if status == 401:
            raise AuthError("API rejected the token")
        if status == 429:
            if attempt == 5:
                break
            h = {k.lower(): v for k, v in hdrs.items()}
            wait = int(h.get("retry-after", 1))
            if wait > MAX_WAIT:  # a lockout, not a blip: sleeping it out hangs the pull for hours
                lifts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + wait))
                raise RuntimeError(f"Spotify rate limit lockout, lifts around {lifts} ({wait}s)")
            _sleep(wait)
            continue
        raise RuntimeError(f"{method} {url} -> {status}: {(data or {}).get('error', '')}")
    raise RuntimeError(f"{method} {url} still rate limited after 5 retries")


def get_all(url):
    """Follow `next` links; -> every item across pages."""
    out = []
    while url:
        page = _get(url)
        out.extend(page.get("items") or [])  # pyright: ignore[reportOptionalMemberAccess]  _get returns a dict for every endpoint used here (None only on 204)
        url = page.get("next")  # pyright: ignore[reportOptionalMemberAccess]  _get returns a dict for every endpoint used here (None only on 204)
    return out


def _track(obj):
    """Spotify track object -> library track dict, or None for null tracks and episodes."""
    if not obj or obj.get("type", "track") != "track" or not obj.get("uri"):
        return None
    alb = obj.get("album") or {}
    return {"uri": obj["uri"], "isrc": (obj.get("external_ids") or {}).get("isrc"),
            "name": obj.get("name") or "", "album": alb.get("name"),
            "artists": ";".join(a.get("name", "") for a in obj.get("artists") or []),
            "release_date": alb.get("release_date"), "duration_ms": obj.get("duration_ms"),
            "explicit": 1 if obj.get("explicit") else 0,
            "is_local": 1 if obj.get("is_local") or obj["uri"].startswith("spotify:local:") else 0}


def _tracks(items):
    # Feb 2026 API renamed the entry field track -> item; accept both.
    return [t for t in (_track(i.get("item") or i.get("track")) for i in items) if t]


def owned_playlists():
    me = _get(API + "/me")["id"]  # pyright: ignore[reportOptionalSubscript]  _get returns a dict for every endpoint used here (None only on 204)
    return [{"id": p["id"], "name": p["name"], "snapshot_id": p.get("snapshot_id")}
            for p in get_all(API + "/me/playlists?limit=50")
            if p and (p.get("owner") or {}).get("id") == me]


def playlist_items(pid):
    return _tracks(get_all(f"{API}/playlists/{pid}/items?limit=100"))


def liked_head():
    """One request: (total Liked Songs, uris of the newest 50). New likes land on top."""
    page = _get(API + "/me/tracks?limit=50")
    return page.get("total", 0), {t["uri"] for t in _tracks(page.get("items") or [])}  # pyright: ignore[reportOptionalMemberAccess]  _get returns a dict for every endpoint used here (None only on 204)


def liked_tracks():
    return _tracks(get_all(API + "/me/tracks?limit=50"))


def create_playlist(name, description=""):
    """New private playlist on his account (Feb 2026 API: POST /me/playlists) -> id."""
    return _get(API + "/me/playlists", "POST", {"name": name, "description": description, "public": False})["id"]  # pyright: ignore[reportOptionalSubscript]  _get returns a dict for every endpoint used here (None only on 204)


def add_items(pid, uris):
    """Append uris to a playlist, 100 per request (the API's cap)."""
    for i in range(0, len(uris), 100):
        _get(f"{API}/playlists/{pid}/items", "POST", {"uris": uris[i:i + 100]})

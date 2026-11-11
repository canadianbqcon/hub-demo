"""Official Clash of Clans API client with a last-good-answer cache (table api_cache)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from . import db, gamedata

BASE = "https://api.clashofclans.com/v1"
ENV = Path.home() / ".config" / "vault-api" / ".env"
IPIFY = "https://api.ipify.org"


def _key() -> str | None:
    try:
        for line in ENV.read_text(encoding="utf-8").splitlines():
            name, _, val = line.partition("=")
            if name.strip() == "COC_API_KEY" and val.strip():
                return val.strip().strip("\"'")
    except OSError:
        pass
    return None


def _ip() -> str:
    try:
        with urllib.request.urlopen(IPIFY, timeout=10) as r:
            return r.read().decode().strip() or "IP unknown"
    except Exception:
        return "IP unknown"


def _get(path: str, key: str):
    """-> (status, body_text, reason). status 0 = network failure."""
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8"), None
    except urllib.error.HTTPError as e:
        try:
            reason = json.loads(e.read().decode("utf-8")).get("reason")
        except Exception:
            reason = None
        return e.code, None, reason
    except Exception as e:
        return 0, None, f"{type(e).__name__}: {e}"


def _record(conn, path, status, body, err, final=False):
    """final: the error is a real answer (no war, private log), so the last good body goes too;
    a 429, 5xx or network failure keeps it."""
    now = db.now()
    if status == 200:
        conn.execute(
            "INSERT INTO api_cache (path, ok_body, ok_at, last_attempt_at, last_status, last_error) VALUES (?,?,?,?,200,NULL) "
            "ON CONFLICT(path) DO UPDATE SET ok_body=excluded.ok_body, ok_at=excluded.ok_at, "
            "last_attempt_at=excluded.last_attempt_at, last_status=200, last_error=NULL",
            (path, body, now, now))
    else:
        conn.execute(
            "INSERT INTO api_cache (path, last_attempt_at, last_status, last_error) VALUES (?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET last_attempt_at=excluded.last_attempt_at, "
            "last_status=excluded.last_status, last_error=excluded.last_error",
            (path, now, status, err))
        if final:
            conn.execute("UPDATE api_cache SET ok_body=NULL, ok_at=NULL WHERE path=?", (path,))
    conn.commit()


def cached(conn, path):
    r = conn.execute("SELECT ok_body, ok_at, last_error FROM api_cache WHERE path=?", (path,)).fetchone()
    if r is None:
        return None, None, None
    body = json.loads(r[0]) if r[0] else None
    return body, r[1], r[2]


def refresh(conn, tag):
    out = {"ok": [], "errors": {}, "banner": None}
    key = _key()
    if not key:
        out["banner"] = {"kind": "no_key", "ip": None}
        return out

    def fetch(path, war=False):
        """Fetch + record; returns parsed body on 200 else None. Sets the banner on 403."""
        status, body, reason = _get(path, key)
        if status == 200:
            _record(conn, path, 200, body, None)
            out["ok"].append(path)
            return json.loads(body)
        final = war and status in (403, 404)
        if final:  # 404: not in war / CWL over; 403 on a clan path: private war log (key and IP passed on /players)
            reason = "not_in_war"
        elif status == 403:
            if out["banner"] is None:
                out["banner"] = ({"kind": "invalid_ip", "ip": _ip()} if reason == "accessDenied.invalidIp"
                                 else {"kind": "refused", "ip": None})
            reason = reason or "forbidden"
        elif status == 0:
            pass
        else:
            reason = reason or f"http {status}"
        _record(conn, path, status, None, reason, final)
        out["errors"][path] = reason
        return None

    enc = quote(tag, safe="")
    player = fetch(f"/players/{enc}")
    if out["banner"]:  # key or IP rejected: the rest would fail the same way
        return out
    clan = ((player or {}).get("clan") or {}).get("tag")
    if player:
        conn.execute("UPDATE account SET name=?, th_level=?, clan_tag=?, updated_at=? WHERE tag=?",
                     (player.get("name", ""), player.get("townHallLevel", 1), clan or "", db.now(), tag))
        conn.commit()
        gamedata.reload_api()  # hero caps follow the new body
    elif clan is None:
        row = conn.execute("SELECT clan_tag FROM account WHERE tag=?", (tag,)).fetchone()
        clan = row[0] if row and row[0] else None
    if not clan:
        return out
    ce = quote(clan, safe="")
    fetch(f"/clans/{ce}/currentwar", war=True)
    fetch(f"/clans/{ce}/warlog", war=True)
    group = fetch(f"/clans/{ce}/currentwar/leaguegroup", war=True)
    for rnd in (group or {}).get("rounds", []):
        for wt in rnd.get("warTags", []):
            if wt != "#0":
                fetch(f"/clanwarleagues/wars/{quote(wt, safe='')}", war=True)
    return out

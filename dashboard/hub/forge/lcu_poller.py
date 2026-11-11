"""Read the League client's champ select and post it to the Hub's Draft feed.

Runs under Windows Python (`pythonw.exe`), stdlib only, started at logon by a
Task Scheduler entry. The client's local API (the LCU) listens on 127.0.0.1
Windows-side with a self-signed certificate and a per-launch password in the
lockfile; WSL cannot reach it, so this is the half that lives on Windows.

    pythonw.exe lcu_poller.py              # run forever (Task Scheduler)
    python.exe  lcu_poller.py --once --dry # print one envelope, post nothing

Every post is an envelope (`forge/draft_feed.py` reads it): a random
`pollerId` per start, a `seq` that only counts up, `capturedAt`, `status`
idle|draft, and in a draft the session body plus his current rune page (the
session carries no perks, probe-notes "lcu runes"). It posts on any change and
as a heartbeat every HEARTBEAT seconds, so the page can tell idle from dead.
The last-sent hash moves only after a 2xx, so a failed post retries next tick.

Once a game is up, Riot's Live Client Data API (port 2999, same self-signed
certificate, no password) lists every player's keystone and items; that goes to
/forge/api/draft/ingame every POLL_GAME seconds while no draft is live. The first
real payload is saved beside the log, because the test fixture only follows
Riot's documented shape.

Read-only against the client: GETs only, never a write to champ select.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import logging
import logging.handlers
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

LOCKFILE = Path(r"C:\Riot Games\League of Legends\lockfile")
HUB = "http://127.0.0.1:5002/forge/api/draft/session"
HUB_INGAME = "http://127.0.0.1:5002/forge/api/draft/ingame"
HUB_RANK = "http://127.0.0.1:5002/forge/api/me/rank"
LIVE_CLIENT = "https://127.0.0.1:2999/liveclientdata/playerlist"
# 0.5 s in champ select keeps the worst case near 1.3 s of the 2 s budget
# (spec section 1); 3 s otherwise is cheap and still catches a draft starting.
POLL_DRAFT = 0.5
POLL_IDLE = 3.0
HEARTBEAT = 5.0
POLL_GAME = 15.0
TIMEOUT = 3.0
HOME = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "forge-poller"

# Certificate checks off for the client's own loopback host only. The context is
# never used for the Hub post (plain http) or anything off this machine.
_LCU_TLS = ssl.create_default_context()
_LCU_TLS.check_hostname = False
_LCU_TLS.verify_mode = ssl.CERT_NONE

log = logging.getLogger("forge-poller")


class Client:
    """The LCU, re-read from the lockfile whenever a call fails (client restart)."""

    def __init__(self):
        self.base = self.auth = None

    def _load(self) -> bool:
        try:
            _name, _pid, port, pw, _proto = LOCKFILE.read_text().split(":")
        except (OSError, ValueError):
            self.base = None
            return False
        self.base = f"https://127.0.0.1:{port}"
        self.auth = "Basic " + base64.b64encode(f"riot:{pw}".encode()).decode()
        return True

    def get(self, path: str):
        """(status, body) or (None, None) when the client is not reachable."""
        if self.base is None and not self._load():
            return None, None
        req = urllib.request.Request(self.base + path, headers={
            "Authorization": self.auth, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, context=_LCU_TLS, timeout=TIMEOUT) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                self.base = None              # password rotated: re-read next call
            return e.code, None
        except (OSError, ValueError, http.client.HTTPException):
            self.base = None
            return None, None


def snapshot(lcu: Client) -> dict:
    """One reading: status plus, in a draft, the session and rune page."""
    code, session = lcu.get("/lol-champ-select/v1/session")
    if code != 200 or not isinstance(session, dict):
        return {"status": "idle"}
    _c, runes = lcu.get("/lol-perks/v1/currentpage")
    return {"status": "draft", "session": session, "queueId": _game(lcu).get("queue", {}).get("id"),
            "runes": runes if isinstance(runes, dict) else None}


def _game(lcu: Client) -> dict:
    """gameflow's gameData, or {}: the only place that names the queue and game id."""
    _c, flow = lcu.get("/lol-gameflow/v1/session")
    data = flow.get("gameData") if isinstance(flow, dict) else None
    return data if isinstance(data, dict) else {}


def ingame_body(payload: list, seq: int, now: float, game_id=None, poller=None) -> dict:
    """The playerlist to what the Hub keeps. Consumables are dropped; a component
    stays in `items`, since only a finished core item can match a core."""
    players = []
    for p in payload:
        keystone = ((p.get("runes") or {}).get("keystone") or {}).get("id")
        players.append({"riotId": p.get("riotId") or p.get("summonerName"),
                        "team": p.get("team"), "champion": p.get("championName"),
                        "keystone": keystone,
                        "items": [i["itemID"] for i in p.get("items") or []
                                  if i.get("itemID") and not i.get("consumable")]})
    if game_id is None:   # the client closed mid-game: the ten players still name this game
        game_id = "live:" + "|".join(sorted(str(p["riotId"]) for p in players))
    return {"gameId": game_id, "pollerId": poller, "seq": seq, "capturedAt": now, "players": players}


def read_players():
    """The Live Client playerlist, or None when no game is running."""
    try:
        with urllib.request.urlopen(LIVE_CLIENT, context=_LCU_TLS, timeout=TIMEOUT) as r:
            body = json.loads(r.read() or b"null")
    except (OSError, ValueError, http.client.HTTPException):
        return None
    return body if isinstance(body, list) and body else None


def poll_game(lcu: Client, seq: int, now: float, read=read_players, send=None, poller=None) -> bool:
    """One in-game reading; False when no game is up, and then nothing is posted."""
    players = read()
    if players is None:
        return False
    sample = HOME / "playerlist-sample.json"
    if not sample.exists():
        sample.parent.mkdir(parents=True, exist_ok=True)
        sample.write_text(json.dumps(players, indent=1), encoding="utf-8")
    body = ingame_body(players, seq, now, _game(lcu).get("gameId"), poller)
    (send or (lambda b: post(b, HUB_INGAME)))(body)
    return True


_DIVISIONS = {"I": 1, "II": 2, "III": 3, "IV": 4}


def ranked(lcu: Client) -> dict | None:
    """His Solo / Duo standing straight from the client: tier, division, LP and the
    win / loss count. The count is what ties a reading to games: it steps by one per
    ranked game, so the first reading after a game is that game's LP exactly."""
    _c, body = lcu.get("/lol-ranked/v1/current-ranked-stats")
    if not isinstance(body, dict):
        return None
    q = (body.get("queueMap") or {}).get("RANKED_SOLO_5x5") or next(
        (x for x in body.get("queues") or [] if x.get("queueType") == "RANKED_SOLO_5x5"), None)
    if not isinstance(q, dict) or q.get("tier") in (None, "", "NONE", "UNRANKED"):
        log.warning("no Solo / Duo standing in ranked stats (keys %s)", sorted(body)[:8])
        return None
    return {"tier": q["tier"], "division": _DIVISIONS.get(q.get("division")),
            "lp": q.get("leaguePoints"), "wins": q.get("wins"), "losses": q.get("losses")}


def post(body: dict, url: str = HUB) -> bool:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        log.warning("hub refused: %s", e.code)
        return e.code == 409           # stale: nothing a retry fixes
    except (OSError, http.client.HTTPException) as e:
        log.warning("hub unreachable: %s", e)
        return False


def _single_instance():
    """Hold a lock file for the process lifetime; exit if another poller has it."""
    import msvcrt
    HOME.mkdir(parents=True, exist_ok=True)
    fh = open(HOME / "poller.lock", "a+")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        sys.exit("another forge poller is running")
    return fh


def run() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(HOME / "poller.log", maxBytes=1_000_000,
                                                   backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(message)s")
    _lock = _single_instance()  # noqa: F841 -- held open for the process lifetime
    lcu, pid, seq = Client(), uuid.uuid4().hex[:12], 0
    sent_hash, sent_at, game_at, sent_rank = None, 0.0, 0.0, None
    log.info("poller %s started", pid)
    while True:
        snap = {"status": "idle"}
        try:
            snap = snapshot(lcu)
            h = hashlib.md5(json.dumps(snap, sort_keys=True).encode()).hexdigest()
            now = time.time()
            if h != sent_hash or now - sent_at >= HEARTBEAT:
                seq += 1
                if post({"pollerId": pid, "seq": seq, "capturedAt": now, **snap}):
                    sent_hash, sent_at = h, now
            if snap["status"] == "idle" and now - game_at >= POLL_GAME:
                game_at = now
                seq += 1
                poll_game(lcu, seq, now, poller=pid)
                # Every change is posted (plus the first read, the baseline): the
                # Hub matches each to the game that ended before it.
                rank = ranked(lcu)
                if rank and rank != sent_rank and post({**rank, "capturedAt": now}, HUB_RANK):
                    sent_rank = rank
        except Exception:                   # pythonw has no stderr: name it, keep polling
            log.exception("poll failed")
        time.sleep(POLL_DRAFT if snap["status"] == "draft" else POLL_IDLE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one reading, then exit")
    ap.add_argument("--dry", action="store_true", help="print instead of posting")
    a = ap.parse_args()
    if not a.once:
        run()
        return 0
    snap = snapshot(Client())
    body = {"pollerId": "once", "seq": 1, "capturedAt": time.time(), **snap}
    if a.dry:
        print(f"status: {snap['status']}")
        print(f"ranked: {ranked(Client())}")
        if snap["status"] == "draft":
            print(json.dumps(body)[:2000])
        return 0
    return 0 if post(body) else 1


if __name__ == "__main__":
    sys.exit(main())

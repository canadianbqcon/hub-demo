"""The live champ select feed: what the Windows poller posts, held for the Draft page.

The League client's local API listens on 127.0.0.1 Windows-side only, so
`lcu_poller.py` (Windows Python) reads it and posts an envelope here every time
the session changes, plus a heartbeat every 5 s:

    {pollerId, seq, capturedAt, status: "idle"|"draft", session?, runes?, queueId?}

`pollerId` is random per poller start and `seq` counts up within it, so an
older post that arrives late is refused rather than rolling the page back.
Silence is not idle: a poller that dies sends nothing, so the page reads
"offline" once the last heartbeat is older than OFFLINE_AFTER, and the saved
session file is replay data only, never shown as live.

Only loopback callers are accepted. The Hub binds 0.0.0.0 for LAN and
Tailscale, and a Windows-side POST to 127.0.0.1 reaches WSL as 127.0.0.1
(measured, tests/fixtures/forge_draft/probe-notes.md "loopback"), so the
address check is enough and no shared token is needed.

In game, the poller posts each player's keystone and items to `accept_ingame`;
`match_items` turns that into "this enemy runs this archetype". Both that and the
page's manual archetype picks live in memory only, cleared with the draft.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

# A heartbeat comes every 5 s; three missed in a row reads as offline. Lower
# flags a sleeping laptop sooner but trips on one slow post.
OFFLINE_AFTER = 15.0
# The LCU session body is about 20 KB in a ten-player draft; 1 MB is a body
# nobody legitimate sends.
MAX_BODY = 1_000_000
LOOPBACK = frozenset({"127.0.0.1", "::1"})

# LCU position names on the left, the Hub's role names (bake_stats.ROLES) on the right.
_ROLES = {"top": "top", "jungle": "jungle", "middle": "mid", "bottom": "bot",
          "utility": "support"}

# No post for this long ends the in-game state: the game is over or the poller died.
INGAME_SILENCE = 300.0

SESSION_FILE = vault_root() / "data" / "forge-draft-session.json"

_lock = threading.Lock()
_seen: dict[str, int] = {}          # pollerId -> highest seq accepted
_state: dict = {}                   # the latest accepted envelope, parsed
_loaded = False
_ingame: dict = {}                  # {gameId, seq, at, players}
_picks: dict[str, str] = {}         # champion -> archetype id he chose on the page


class NotDraft(ValueError):
    """A champ select that is not a 5v5 Summoner's Rift draft (Arena, ARAM-style
    modes with more seats). The page treats it as no draft at all."""


def _role(pos) -> str | None:
    return _ROLES.get(str(pos or "").lower()) or None


def parse(session, runes=None, queue_id=None) -> dict:
    """The LCU session as the engine reads it. Raises ValueError on a shape the
    parser does not know, which the page shows as LCU_SHAPE instead of guessing."""
    if not isinstance(session, dict):
        raise ValueError("session is not an object")
    me_cell = session.get("localPlayerCellId")
    mine, theirs = session.get("myTeam"), session.get("theirTeam")
    if not isinstance(me_cell, int) or not isinstance(mine, list) or not isinstance(theirs, list):
        raise ValueError("missing localPlayerCellId, myTeam or theirTeam")
    if len(mine) > 5 or len(theirs) > 5:
        raise NotDraft(f"{len(mine)}v{len(theirs)} is not a 5v5 draft")

    picks: dict[int, int] = {}
    bans: set[int] = set()
    banned_by: dict[int, int] = {}   # seat cellId -> the champion that seat banned
    acts = session.get("actions") or []
    if not isinstance(acts, list):
        raise ValueError("actions is not a list")
    for turn in acts:
        for a in (turn if isinstance(turn, list) else [turn]):
            if not isinstance(a, dict) or not a.get("completed") or not a.get("championId"):
                continue
            if a.get("type") == "pick" and isinstance(a.get("actorCellId"), int):
                picks[a["actorCellId"]] = a["championId"]
            elif a.get("type") == "ban":
                bans.add(a["championId"])
                if isinstance(a.get("actorCellId"), int):
                    banned_by[a["actorCellId"]] = a["championId"]
    b = session.get("bans") or {}
    for key in ("myTeamBans", "theirTeamBans"):
        bans.update(c for c in (b.get(key) or []) if c)

    def seat(p: dict) -> dict:
        if not isinstance(p, dict) or not isinstance(p.get("cellId"), int):
            raise ValueError("a team slot has no cellId")
        cell = p["cellId"]
        if cell in picks:
            # a late-phase trade changes the seat's championId, never the old pick action
            champ, provisional = p.get("championId") or picks[cell], False
        elif not acts and p.get("championId"):
            champ, provisional = p["championId"], False      # a mode with no actions list
        else:
            champ = p.get("championId") or p.get("championPickIntent") or None
            provisional = champ is not None
        return {"cellId": cell, "role": _role(p.get("assignedPosition")),
                "championId": champ, "provisional": provisional,
                "ban": banned_by.get(cell),
                "spells": [p.get("spell1Id") or 0, p.get("spell2Id") or 0]}

    allies = [seat(p) for p in mine]
    me = next((s for s in allies if s["cellId"] == me_cell), None)
    if me is None:
        raise ValueError("localPlayerCellId is not on myTeam")
    allies = [s for s in allies if s is not me]
    me = {"cellId": me["cellId"], "role": me["role"],
          "championId": None if me["provisional"] else me["championId"],
          "hover": me["championId"] if me["provisional"] else None,
          "ban": me["ban"], "spells": me["spells"]}
    # Enemies only once locked: a hover on their side is not visible, and a
    # championId there before the pick completes would be a guess.
    # Each enemy carries the ban its seat made, which the engine reads as a role hint.
    enemies = [{"championId": p.get("championId"), "likelyRole": None,
                "cellId": p.get("cellId"), "ban": banned_by.get(p.get("cellId"))}
               for p in theirs if isinstance(p, dict) and p.get("championId")]
    # Enemy seats still picking, so the page can show their ban before they lock.
    enemy_bans = [banned_by[p["cellId"]] for p in theirs if isinstance(p, dict)
                  and not p.get("championId") and p.get("cellId") in banned_by]
    perks = (runes or {}).get("selectedPerkIds") if isinstance(runes, dict) else None
    return {"me": me, "allies": allies, "enemies": enemies, "bans": sorted(bans),
            "pendingEnemyBans": enemy_bans,
            "runes": perks if isinstance(perks, list) else None,
            # None (an old poller) reads ranked and the page says so
            "queueId": queue_id if isinstance(queue_id, int) and not isinstance(queue_id, bool) else None}


def _write(record: dict) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SESSION_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, SESSION_FILE)


def _load_once() -> None:
    """The last saved session, as replay, once per process."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        rec = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(rec, dict):
        # a pre-filter save of an odd mode (more than 4 allies) is not a draft to replay
        if len(((rec.get("draft") or {}).get("allies")) or []) > 4:
            rec["draft"] = None
        _state.update(rec, heartbeat=None)


def reset() -> None:
    """Forget everything in memory (tests, and a Hub that swaps SESSION_FILE)."""
    global _loaded
    with _lock:
        _seen.clear()
        _state.clear()
        _ingame.clear()
        _picks.clear()
        _loaded = False


def accept(envelope, remote: str, now: float) -> tuple[int, str]:
    """Take one poller post. Returns (HTTP status, short message)."""
    if remote not in LOOPBACK:
        return 403, "loopback only"
    if not isinstance(envelope, dict):
        return 400, "expected a JSON object"
    pid, seq, status = envelope.get("pollerId"), envelope.get("seq"), envelope.get("status")
    if not isinstance(pid, str) or not pid:
        return 400, "missing pollerId"
    if not isinstance(seq, int) or isinstance(seq, bool):
        return 400, "missing seq"
    if status not in ("idle", "draft"):
        return 400, "status must be idle or draft"

    with _lock:
        _load_once()
        last = _seen.get(pid)
        if last is not None and seq < last:
            return 409, "stale seq"
        _seen[pid] = seq
        _state["heartbeat"] = now
        if last == seq:
            return 200, "duplicate"

        draft, error = _state.get("draft"), None
        # A new champ select: last game's reads and picks are done. The session's game id
        # says so when it can, since the poller reports one failed read as idle (a blip
        # must not wipe his picks) and a dead poller never reports the idle in between.
        session = envelope.get("session")
        sid = session.get("gameId") if isinstance(session, dict) else None
        last_sid = _state.get("sessionGame")
        if status == "draft" and ((sid and last_sid and sid != last_sid)
                                  or (_state.get("status") != "draft" and not (sid and sid == last_sid))):
            _ingame.clear()
            _picks.clear()
        if status == "draft" and sid:
            _state["sessionGame"] = sid
        if status == "draft":
            try:
                draft = parse(envelope.get("session"), envelope.get("runes"), envelope.get("queueId"))
            except NotDraft:
                status = "idle"                 # another mode: keep the last real draft as replay
            except (ValueError, TypeError, AttributeError) as exc:   # any odd shape, never a 500
                draft, error = None, f"LCU_SHAPE: {exc}"
        changed = (status != _state.get("status") or draft != _state.get("draft")
                   or error != _state.get("error"))
        _state.update(pollerId=pid, seq=seq, capturedAt=envelope.get("capturedAt"),
                      status=status, draft=draft, error=error)
        if changed:
            _write({k: _state.get(k) for k in
                    ("pollerId", "seq", "capturedAt", "status", "draft", "error")}
                   | {"session": scrub(envelope.get("session")) if status == "draft" else None})
    return 200, "ok"


# The saved session is debug-only (nothing reads it back) and the vault autosaves it to
# git, so the chat token and account ids never reach disk (security review 2026-11-04).
_SECRET = {"chatDetails", "puuid", "summonerId", "gameName", "tagLine", "playerAlias",
           "obfuscatedPuuid", "obfuscatedSummonerId", "nameVisibilityType", "internalName"}


def scrub(o):
    if isinstance(o, dict):
        return {k: scrub(v) for k, v in o.items() if k not in _SECRET}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    return o


def state(now: float) -> dict:
    """What the page reads. `live` only while heartbeats arrive; otherwise the
    last draft comes back flagged as replay."""
    with _lock:
        _load_once()
        hb = _state.get("heartbeat")
        fresh = hb is not None and now - hb <= OFFLINE_AFTER
        if not fresh:
            status = "offline"
        else:
            status = "live" if _state.get("status") == "draft" else "idle"
        error = _state.get("error") if fresh else "POLLER_OFFLINE"
        return {"live": status == "live", "status": status, "seq": _state.get("seq"),
                "capturedAt": _state.get("capturedAt"), "draft": _state.get("draft"),
                "replay": status != "live", "error": error}


def check_post(content_length, proxied: bool, remote_addr) -> tuple[int, str] | None:
    """The size and caller rules every poster/page POST shares, or None when it passes.
    `tailscale serve` proxies the tailnet to 127.0.0.1, so a tailnet device arrives
    as loopback too; the proxy's headers give it away and it reads as not loopback."""
    if content_length is None:
        return 411, "length required"
    if content_length > MAX_BODY:
        return 413, "body too large"
    if proxied or (remote_addr or "") not in LOOPBACK:
        return 403, "loopback only"
    return None


def match_items(player: dict, archetypes: list[dict]) -> str | None:
    """The archetype this player's keystone and items point at, or None. The keystone
    must match and both core items must be owned, in any order; two matches (a tie)
    or none keep the current pick. `items` holds completed items only."""
    items = {i for i in (player.get("items") or []) if isinstance(i, int)}
    hits = {a["id"] for a in archetypes
            if a.get("keystone") == player.get("keystone") and all(c in items for c in a.get("core") or [None])}
    return hits.pop() if len(hits) == 1 else None


def accept_ingame(body, remote: str, now: float) -> tuple[int, str]:
    """One in-game post from the poller: {gameId, seq, capturedAt, players: [{riotId,
    team, champion, keystone, items}]}. Stale seq is dropped, a new game id replaces
    the state, and INGAME_SILENCE seconds without a post clears it first. seq only
    means anything within one poller, which restarts at 0."""
    if remote not in LOOPBACK:
        return 403, "loopback only"
    if not isinstance(body, dict):
        return 400, "expected a JSON object"
    gid, seq, players = body.get("gameId"), body.get("seq"), body.get("players")
    if not isinstance(gid, (str, int)) or isinstance(gid, bool) or gid == "":
        return 400, "missing gameId"
    if not isinstance(seq, int) or isinstance(seq, bool):
        return 400, "missing seq"
    if not isinstance(players, list) or not all(isinstance(p, dict) for p in players):
        return 400, "players must be a list of objects"
    with _lock:
        if _ingame and now - _ingame["at"] > INGAME_SILENCE:
            _ingame.clear()
        pid = body.get("pollerId")
        if _ingame.get("gameId") == gid and _ingame.get("pollerId") == pid and seq <= _ingame["seq"]:
            return 409, "stale seq"
        _ingame.clear()                          # same game moves on, a new game id starts over
        _ingame.update(gameId=gid, pollerId=pid, seq=seq, at=now, players=players)
    return 200, "ok"


def ingame_players(now: float) -> list[dict]:
    """The latest in-game players, or [] once silent for INGAME_SILENCE."""
    with _lock:
        if not _ingame or now - _ingame["at"] > INGAME_SILENCE:
            return []
        return list(_ingame["players"])


def set_pick(champion, archetype_id) -> tuple[int, str]:
    """His manual archetype choice for one champion; an empty id clears it."""
    if not isinstance(champion, str) or not champion:
        return 400, "missing champion"
    if archetype_id not in (None, "") and not isinstance(archetype_id, str):
        return 400, "archetypeId must be a string"
    with _lock:
        if archetype_id:
            _picks[champion] = archetype_id
        else:
            _picks.pop(champion, None)
    return 200, "ok"


def picks() -> dict[str, str]:
    with _lock:
        return dict(_picks)

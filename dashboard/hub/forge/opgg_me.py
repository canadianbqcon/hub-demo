"""Sam's own OP.GG numbers, for the Stats surface.

Where the rest of the tool reads how a champion performs *in general* — coachless
WPA, lolalytics win rates, Riot's notes — this reads how he performs on it. The
build shelf and the record of playing what is on it are the two halves of the
same question, so Stats is a peer tab of Champions and Patch rather than a panel
hanging off one of them.

The source is OP.GG's own MCP server, which is open, unauthenticated, plain HTTP
JSON-RPC, and carries the derived layer (op_score, tier context) the Riot API
makes you compute yourself. See wiki/decisions/opgg-mcp-for-league-stats in the
vault for why it beat the Riot API and the three third-party wrappers.

Two things about that server shape this file:

  it answers in a Python-class-shaped text blob, not JSON —
      `LolGetSummonerProfile(Data(Summoner("CanadianBacon",225,[...])))` with a
      header naming each class's fields in order. Built for a model to read.
      `decode()` below turns it back into dicts; it is the whole reason this is a
      module and not four lines inside api.py.

  it returns the response SHAPE when you omit `desired_output_fields` — the
      schema listing with no values in it. Naming fields is not an optimisation
      here, it is the difference between data and a class diagram. Every call
      below names them, and an unmatched name is dropped silently by the server
      (it reports them back under `_field_diagnostics`, which `decode()` keeps).
"""

from __future__ import annotations

import ast
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://mcp-api.op.gg/mcp"

# Whose numbers. An env override rather than a config file: there is one player,
# and the day there are two this becomes a route parameter, not a settings page.
RIOT_ID = os.environ.get("FORGE_RIOT_ID", "CanadianBacon#Pork")
REGION = os.environ.get("FORGE_RIOT_REGION", "NA")

# OP.GG itself only re-reads a summoner every few minutes, and the page is opened
# far more often than a game finishes. The cache is on disk rather than in memory
# so a Hub restart does not cost a round trip, and so the last good answer
# survives the server being unreachable.
TTL = 900
TIMEOUT = 20

_PROFILE_FIELDS = [
    "data.summoner.{game_name,tagline,level,profile_image_url,updated_at}",
    "data.summoner.ladder_rank.{rank,total}",
    "data.summoner.league_stats[].{game_type,win,lose}",
    "data.summoner.league_stats[].tier_info.{tier,division,lp,tier_image_url}",
    "data.summoner.previous_seasons[].season_id",
    "data.summoner.previous_seasons[].tier_info.{tier,division,lp,tier_image_url}",
    "data.summoner.most_champions.{game_type,season_id,play,win,lose}",
    "data.summoner.most_champions.champion_stats[].{champion_name,play,win,lose,"
    "kill,death,assist,op_score,game_length_second,minion_kill,neutral_minion_kill}",
]

_MATCH_FIELDS = [
    "data.game_history[].{id,created_at,game_type,game_length_second}",
    "data.game_history[].participants[].{champion_name,position,team_key}",
    "data.game_history[].participants[].stats.{kill,death,assist,result,op_score,"
    "op_score_rank,minion_kill,neutral_minion_kill,total_damage_dealt_to_champions}",
]

_LITERALS = {"null": None, "true": True, "false": False}


def decode(text: str) -> dict:
    """The class-shaped blob back into dicts.

    The header lines (`class Summoner: level,league_stats`) are the field order;
    the expression below them is positional. So this is a plain AST walk with the
    header as the key list — `ast` is used rather than a regex because the values
    are quoted strings that can contain commas and parentheses (champion names,
    URLs, Riot IDs), and splitting on those is how you lose "Kai'Sa".

    `null`/`true`/`false` come through as bare names, since the blob is
    JSON-flavoured Python and valid as neither.
    """
    head, _, expr = text.partition("\n\n")
    fields: dict[str, list[str]] = {}
    for line in head.splitlines():
        if not line.startswith("class "):
            continue
        name, _, rest = line[6:].partition(":")
        fields[name.strip()] = [f.strip() for f in rest.split(",") if f.strip()]

    def walk(node):
        if isinstance(node, ast.Call):
            names = fields.get(getattr(node.func, "id", ""), [])
            return {(names[i] if i < len(names) else f"_{i}"): walk(a)
                    for i, a in enumerate(node.args)}
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return [walk(e) for e in node.elts]
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return _LITERALS.get(node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            v = walk(node.operand)
            return -v if isinstance(v, (int, float)) else v
        return None

    out = walk(ast.parse(expr.strip(), mode="eval").body)
    if not isinstance(out, dict):
        raise ValueError(f"decode: top-level expression is not a class call: {expr[:80]!r}")
    return out


def call(tool: str, timeout: float = TIMEOUT, **args) -> dict:
    """One JSON-RPC tool call, decoded. Raises on anything that is not an answer."""
    game_name, _, tag_line = RIOT_ID.partition("#")
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": dict(
            game_name=game_name, tag_line=tag_line, region=REGION, **args)},
    }).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.loads(r.read().decode())
    if "error" in payload:
        raise RuntimeError(payload["error"].get("message", "op.gg error"))
    return decode(payload["result"]["content"][0]["text"])


def _pct(win, lose):
    total = (win or 0) + (lose or 0)
    return round(100 * (win or 0) / total, 1) if total else None


def _kda(k, d, a):
    return round(((k or 0) + (a or 0)) / d, 2) if d else None


def _rank(entry: dict) -> dict | None:
    """A queue's standing, flattened. Unplayed queues carry a null tier."""
    tier = (entry.get("tier_info") or {}).get("tier")
    if not tier:
        return None
    t = entry["tier_info"]
    return {
        "queue": entry.get("game_type"),
        "tier": tier,
        "division": t.get("division"),
        "lp": t.get("lp"),
        "emblem": t.get("tier_image_url"),
        "win": entry.get("win"),
        "lose": entry.get("lose"),
        "winrate": _pct(entry.get("win"), entry.get("lose")),
    }


def _champ(row: dict) -> dict:
    """One champion's season line, with the per-game averages already taken.

    Averaged here rather than on the page because OP.GG sends every one of these
    as a season TOTAL — 989 kills on Viego, not 9.9 — and a total read as an
    average is the kind of wrong that looks plausible on screen.
    """
    n = row.get("play") or 0
    per = (lambda v: round((v or 0) / n, 1)) if n else (lambda v: None)
    mins = ((row.get("game_length_second") or 0) / 60) or None
    cs = (row.get("minion_kill") or 0) + (row.get("neutral_minion_kill") or 0)
    return {
        "champion": row.get("champion_name"),
        "play": n,
        "win": row.get("win"),
        "lose": row.get("lose"),
        "winrate": _pct(row.get("win"), row.get("lose")),
        "kill": per(row.get("kill")),
        "death": per(row.get("death")),
        "assist": per(row.get("assist")),
        "kda": _kda(row.get("kill"), row.get("death"), row.get("assist")),
        "opScore": round((row.get("op_score") or 0) / n, 2) if n else None,
        "csPerMin": round(cs / mins, 1) if mins else None,
    }


def _match(game: dict) -> dict:
    """One game, from the single participant OP.GG returns (him, never the lobby)."""
    p = (game.get("participants") or [{}])[0]
    s = p.get("stats") or {}
    secs = game.get("game_length_second") or 0
    cs = (s.get("minion_kill") or 0) + (s.get("neutral_minion_kill") or 0)
    return {
        "id": game.get("id"),
        "at": game.get("created_at"),
        "queue": game.get("game_type"),
        "seconds": secs,
        "champion": p.get("champion_name"),
        "position": p.get("position"),
        "win": s.get("result") == "WIN",
        "result": s.get("result"),
        "kill": s.get("kill"),
        "death": s.get("death"),
        "assist": s.get("assist"),
        "kda": _kda(s.get("kill"), s.get("death"), s.get("assist")),
        "opScore": s.get("op_score"),
        "opRank": s.get("op_score_rank"),
        "cs": cs,
        "csPerMin": round(cs / (secs / 60), 1) if secs else None,
        "damage": s.get("total_damage_dealt_to_champions"),
    }


def fetch() -> dict:
    """Both calls, folded into the one shape the page renders."""
    prof = call("lol_get_summoner_profile", desired_output_fields=_PROFILE_FIELDS)
    hist = call("lol_list_summoner_matches", limit=20,
                desired_output_fields=_MATCH_FIELDS)

    s = ((prof.get("data") or {}).get("summoner")) or {}
    most = s.get("most_champions") or {}
    ladder = s.get("ladder_rank") or {}
    games = ((hist.get("data") or {}).get("game_history")) or []

    return {
        "riotId": RIOT_ID,
        "region": REGION,
        "opggUrl": f"https://op.gg/lol/summoners/{REGION.lower()}/{RIOT_ID.replace('#', '-')}",
        "name": s.get("game_name"),
        "tagline": s.get("tagline"),
        "level": s.get("level"),
        "avatar": s.get("profile_image_url"),
        "updatedAt": s.get("updated_at"),
        "ladder": {"rank": ladder.get("rank"), "total": ladder.get("total")}
                  if ladder.get("rank") else None,
        "ranks": [r for r in map(_rank, s.get("league_stats") or []) if r],
        "seasons": [{
            "season": p.get("season_id"),
            "tier": (p.get("tier_info") or {}).get("tier"),
            "division": (p.get("tier_info") or {}).get("division"),
            "lp": (p.get("tier_info") or {}).get("lp"),
            "emblem": (p.get("tier_info") or {}).get("tier_image_url"),
        } for p in (s.get("previous_seasons") or []) if (p.get("tier_info") or {}).get("tier")],
        "season": {
            "id": most.get("season_id"),
            "queue": most.get("game_type"),
            "play": most.get("play"),
            "win": most.get("win"),
            "lose": most.get("lose"),
            "winrate": _pct(most.get("win"), most.get("lose")),
        },
        "champions": [_champ(c) for c in (most.get("champion_stats") or [])],
        "matches": [_match(g) for g in games],
    }


_LOBBY_FIELDS = [
    "data.game_detail.teams[].{key,banned_champions_names[]}",
    "data.game_detail.teams[].participants[].{champion_name,position,team_key,is_target}",
    "data.game_detail.teams[].participants[].stats.result",
]
_POSITION = {"TOP": "top", "JUNGLE": "jungle", "MID": "mid", "ADC": "bot", "SUPPORT": "support"}


def lobby(game_id: str, created_at: str) -> dict:
    """One past game's ten seats and bans, for the mock draft's Past game picker.

    The match list only ever carries his own row; the detail call is the one that
    has the lobby, and `focus_riot_id` flags his seat (`is_target`)."""
    d = call("lol_get_summoner_game_detail", game_id=game_id, created_at=created_at,
             focus_riot_id=RIOT_ID, desired_output_fields=_LOBBY_FIELDS)
    return _lobby(((d.get("data") or {}).get("game_detail") or {}).get("teams") or [])


def _lobby(teams: list) -> dict:
    seats = [p for t in teams for p in (t.get("participants") or [])]
    me = next((p for p in seats if p.get("is_target")), None)
    if not me:
        raise ValueError("his seat is not in this game")
    side = me.get("team_key")
    seat = lambda p: {"champion": p.get("champion_name"), "role": _POSITION.get(p.get("position"))}
    order = list(_POSITION.values())
    by_role = lambda p: order.index(seat(p)["role"]) if seat(p)["role"] in order else 9
    return {
        "me": seat(me),
        "win": (me.get("stats") or {}).get("result") == "WIN",
        "allies": [seat(p) for p in sorted(seats, key=by_role) if p.get("team_key") == side and p is not me],
        "enemies": [seat(p) for p in sorted(seats, key=by_role) if p.get("team_key") != side],
        "bans": [n for t in teams for n in (t.get("banned_champions_names") or []) if n],
    }


def read(cache: Path, force: bool = False) -> dict:
    """The page's answer: cached if fresh, refetched if not, stale if OP.GG is down.

    A stale answer beats an empty page — the numbers move a few times a day, so
    yesterday's are still broadly true, and `stale` says so on the page rather
    than pretending. Only a cold cache plus a dead server is an error.
    """
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = None

    age = time.time() - cached["fetchedAt"] if cached and cached.get("fetchedAt") else None
    if cached and not force and age is not None and age < TTL:
        return dict(cached, stale=False, age=round(age))

    try:
        fresh = fetch()
    except (urllib.error.URLError, OSError, ValueError, KeyError, RuntimeError) as e:
        if cached:
            return dict(cached, stale=True, age=round(age) if age else None,
                        error=f"{type(e).__name__}: {e}")
        raise

    fresh["fetchedAt"] = time.time()
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(fresh, indent=1), encoding="utf-8")
    except OSError:
        pass  # a cache that cannot be written is slower, not broken
    return dict(fresh, stale=False, age=0)


def demo():
    """Self-check: the decoder against a real OP.GG blob, shapes and all."""
    blob = (
        'class Top: data\n'
        'class Data: summoner\n'
        'class Summoner: name,level,league_stats,note\n'
        'class LeagueStat: game_type,tier_info,win,lose\n'
        'class TierInfo: tier,division,lp\n'
        '\n'
        'Top(Data(Summoner("Kai\'Sa, the (Void) One",225,'
        '[LeagueStat("SOLORANKED",TierInfo("PLATINUM",4,0),94,87),'
        'LeagueStat("ARENA",TierInfo(null,null,null),null,null)],null)))'
    )
    got = decode(blob)
    s = got["data"]["summoner"]
    assert s["name"] == "Kai'Sa, the (Void) One", s["name"]   # commas/parens in a string survive
    assert s["level"] == 225 and s["note"] is None
    assert len(s["league_stats"]) == 2
    assert s["league_stats"][0]["tier_info"] == {"tier": "PLATINUM", "division": 4, "lp": 0}
    assert s["league_stats"][1]["tier_info"]["tier"] is None   # null, not the string  # pyright: ignore[reportOptionalSubscript]  # decode() returns Any-shaped dicts; this self-test asserts the None its own type can't rule out

    rank0 = _rank(s["league_stats"][0])
    assert rank0 and rank0["winrate"] == 51.9
    assert _rank(s["league_stats"][1]) is None                 # unplayed queue drops out

    c = _champ({"champion_name": "Viego", "play": 100, "win": 56, "lose": 44,
                "kill": 989, "death": 599, "assist": 477, "op_score": 547,
                "game_length_second": 180000, "minion_kill": 12000,
                "neutral_minion_kill": 18000})
    assert c["kill"] == 9.9 and c["death"] == 6.0            # totals become averages
    assert c["kda"] == 2.45 and c["opScore"] == 5.47
    assert c["winrate"] == 56.0 and c["csPerMin"] == 10.0

    assert _champ({"play": 0, "kill": 0, "death": 0})["kda"] is None   # no games, no divide

    m = _match({"id": "x", "game_length_second": 1800, "game_type": "NORMAL",
                "participants": [{"champion_name": "Master Yi", "position": "JUNGLE",
                                  "stats": {"kill": 16, "death": 5, "assist": 1,
                                            "result": "WIN", "minion_kill": 36,
                                            "neutral_minion_kill": 213}}]})
    assert m["win"] is True and m["kda"] == 3.4 and m["cs"] == 249 and m["csPerMin"] == 8.3

    p = lambda c, pos, side, me=False: {"champion_name": c, "position": pos, "team_key": side,
                                         "is_target": me, "stats": {"result": "WIN" if side == "RED" else "LOSE"}}
    lb = _lobby([{"key": "BLUE", "banned_champions_names": ["Leona", None],
                  "participants": [p("Thresh", "SUPPORT", "BLUE"), p("Ahri", "MID", "BLUE")]},
                 {"key": "RED", "banned_champions_names": ["Yasuo"],
                  "participants": [p("Jinx", "ADC", "RED"), p("Viego", "JUNGLE", "RED", True),
                                   p("Shen", "TOP", "RED")]}])
    assert lb["me"] == {"champion": "Viego", "role": "jungle"} and lb["win"] is True
    assert [a["role"] for a in lb["allies"]] == ["top", "bot"]           # his side only, role order
    assert [e["champion"] for e in lb["enemies"]] == ["Ahri", "Thresh"]
    assert lb["bans"] == ["Leona", "Yasuo"]                              # null ban slots dropped
    try:
        _lobby([{"participants": [p("Ahri", "MID", "BLUE")]}])
        raise AssertionError("no target seat must raise")
    except ValueError:
        pass
    print("opgg_me demo ok")


if __name__ == "__main__":
    demo()

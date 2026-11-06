"""Close-call judge: one batched Haiku call per poll decides which 0.78-to-0.88
cosine pairs (recorded by cluster.assign) are the same event, and applies the
yeses through cluster.merge. Every failure leaves the pairs split: wrong merges
are worse than splits, and Move to on /news is the manual override.
"""

from __future__ import annotations

import json
import sys

from finances.autocat import _api_key, cost
from news import cluster, db

MODEL = "claude-haiku-5-5"
CAP = 100  # close calls judged per poll; the rest stay split (average poll has ~7)

_RULE = ("Each numbered pair has a new headline and a story (a list of headlines already "
         "grouped as one story). Decide whether the new headline reports the same specific "
         "event as the story, not merely the same topic, outlet type or public figure. "
         "Answer only when sure; leave out any pair you are unsure about. "
         "Put the numbers of the pairs that are the same event in `same`.")
# Structured output, as finances/autocat does: no fenced or chatty reply can reject a batch.
_FORMAT = {"type": "json_schema", "schema": {
    "type": "object", "properties": {"same": {"type": "array", "items": {"type": "integer"}}},
    "required": ["same"], "additionalProperties": False}}


def parse_reply(text: str, n: int) -> set[int] | None:
    """Exactly {"same": [distinct ints, each in 1..n]} (bool is not an int
    here); anything else is None and the whole batch is rejected."""
    try:
        data = json.loads(text.strip())
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or set(data) != {"same"} or not isinstance(data["same"], list):
        return None
    data = data["same"]
    if any(type(x) is not int or not 1 <= x <= n for x in data):
        return None
    if len(set(data)) != len(data):
        return None
    return set(data)


def _build(conn, close_calls: list[dict], out: dict) -> tuple[list[dict], list[dict]]:
    """(calls sent, pair payloads) for the first CAP close calls."""
    calls, pairs = [], []
    for c in close_calls[:CAP]:
        item = conn.execute("SELECT title FROM items WHERE id = ?", (c["item_id"],)).fetchone()
        if item is None:
            out["stale"] += 1
            continue
        others = [r["title"] for r in conn.execute(
            "SELECT title FROM items WHERE cluster_id = ? AND title != ? ORDER BY id LIMIT 4",
            (c["candidate"], c["witness"]))]
        calls.append(c)
        pairs.append({"n": len(calls), "new": item["title"], "story": [c["witness"]] + others})
    return calls, pairs


def _ask(client, pairs: list[dict]):
    from news.digest_api import UNTRUSTED  # lazy: digest_api -> cli -> poll -> judge would cycle
    return client.messages.create(
        model=MODEL, max_tokens=8192,  # thinking counts here too: ~55-70 tokens per pair, so 1024 cut off batches past ~16
        output_config={"format": _FORMAT},
        system=[{"type": "text", "text": _RULE + "\n\n" + UNTRUSTED}],
        messages=[{"role": "user", "content": json.dumps({"pairs": pairs})}])


def _apply(conn, calls: list[dict], yes: set[int], sources: dict) -> int:
    """Merge each yes pair in recording order; returns how many were stale."""
    stale = 0
    redirect: dict[int, int] = {}   # cluster merged away this run -> where it went
    owned = {c["new_cluster"]: {c["item_id"]} for c in calls}  # items a new cluster may hold
    for i, c in enumerate(calls, 1):
        if i not in yes:
            continue
        new = c["new_cluster"]
        cand = c["candidate"]
        while cand in redirect:
            cand = redirect[cand]
        item = conn.execute("SELECT cluster_id, pinned FROM items WHERE id = ?",
                            (c["item_id"],)).fetchone()
        members = conn.execute("SELECT id, source_id, pinned FROM items WHERE cluster_id = ?",
                               (new,)).fetchall()
        cand_lanes = {sources.get(m["source_id"], {}).get("lane", "") for m in conn.execute(
            "SELECT source_id FROM items WHERE cluster_id = ?", (cand,))}
        ok = (item is not None and item["cluster_id"] == new and not item["pinned"]
              and cand != new
              and {m["id"] for m in members} <= owned[new]
              and not any(m["pinned"] for m in members)
              and conn.execute("SELECT 1 FROM clusters WHERE id = ?", (cand,)).fetchone()
              and all(cluster._lane_compatible(sources.get(m["source_id"], {}).get("lane", ""),
                                               cand_lanes) for m in members))
        if not ok:
            stale += 1
            continue
        cluster.merge(conn, new, cand, sources)
        redirect[new] = cand
        if cand in owned:
            owned[cand] |= owned[new]
    return stale


def run(close_calls: list[dict], sources: dict, client=None) -> dict:
    """Judge this poll's close calls and merge the approved pairs. `yes` and `no`
    count answers from an accepted reply (a stale yes is also counted in
    `stale`); a rejected or failed batch counts in `judge_rejected` only."""
    out = {"close_calls": len(close_calls), "judged_yes": 0, "judged_no": 0,
           "judge_rejected": 0, "stale": 0, "over_cap": max(0, len(close_calls) - CAP),
           "judge_cost_usd": 0.0}
    if not close_calls:
        return out
    try:
        _run(close_calls, sources, client, out)
    except Exception as e:  # noqa: BLE001 -- a judge bug leaves every pair split, cost kept
        print(f"news judge crashed: {type(e).__name__}: {e}", file=sys.stderr)
        out["judged_yes"] = out["judged_no"] = 0
        out["judge_rejected"] = min(len(close_calls), CAP) - out["stale"]
    return out


def _run(close_calls: list[dict], sources: dict, client, out: dict) -> None:
    with db._cache() as conn:
        calls, pairs = _build(conn, close_calls, out)
    if not calls:
        return
    n = len(calls)
    if client is None:
        key = _api_key()
        if not key:
            out["judge_rejected"] = n
            return
        import anthropic
        client = anthropic.Anthropic(api_key=key, timeout=60)
    try:
        resp = _ask(client, pairs)
    except Exception as e:
        print(f"news judge failed: {e}", file=sys.stderr)
        out["judge_rejected"] = n
        return
    out["judge_cost_usd"] = cost(MODEL, resp.usage)
    text = "".join(b.text for b in resp.content if b.type == "text")
    yes = parse_reply(text, n) if resp.stop_reason == "end_turn" else None
    if yes is None:
        out["judge_rejected"] = n
        return
    out["judged_yes"], out["judged_no"] = len(yes), n - len(yes)
    if yes:
        with db._cache() as conn:
            out["stale"] += _apply(conn, calls, yes, sources)

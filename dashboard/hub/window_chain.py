"""Reopen the Claude five-hour usage window as soon as the current one expires.

Why this exists. The window is not on a fixed schedule: it opens on the first
request after a quiet stretch and closes five hours later, and nothing restarts
it until the next request. So a gap between sessions pushes every later window
back by the length of that gap — stop for an hour after a window ends and the
third window arrives eleven hours after the first, not ten. Spending one cheap
token at each boundary keeps the chain tight, which means a reset always lands
inside a long working day instead of an hour after it ends.

An unused window costs nothing. Nothing carries over and nothing is consumed by
opening one, so a firing that is slept through leaves the account exactly where
it would have been. That is what makes this worth automating: the downside of a
wasted firing is only the firing's own tokens, measured at ~450.

Why this is not a PYTHON_JOB. That category must never shell out to `claude` —
the point of it is keeping the LLM out of the unattended write path. This job
does invoke claude, but with no tools, no vault context, no settings, no hooks
and no side effects; it exists purely to consume a token. It is its own
category rather than a hole in that rule, and it takes the scheduler's flock
itself so it can never race a live session.

Two files, one writer each, both WSL-side because /mnt/c is ~243x slower and
the statusline touches its file on every render:

  ~/.claude/.window-reset  statusline WRITES, this module READS.
                           The real boundary, straight from Anthropic.
  ~/.claude/.window-chain  this module WRITES, statusline READS.
                           Heartbeat, last firing, provisional boundary.
"""

import fcntl
import json
import os
import subprocess
import time
from pathlib import Path

CLAUDE_DIR = Path(os.path.expanduser("~/.claude"))
RESET_PATH = CLAUDE_DIR / ".window-reset"
CHAIN_PATH = CLAUDE_DIR / ".window-chain"

# The ping runs here. --safe-mode already suppresses CLAUDE.md discovery, but an
# empty directory means there is also no project config anywhere near it.
PING_CWD = CLAUDE_DIR / ".window-chain-cwd"

WINDOW_SECONDS = 5 * 3600

# Never fire early. Firing one second before the boundary spends a token inside
# the OLD window and does not chain, which is the only failure that actually
# costs something; being half a minute late costs nothing at all. So the bias is
# deliberately late.
FIRE_BUFFER = 30

# A firing that fails must not take the chain dark for five hours, so failure
# stamps a short retry instead of a full window.
RETRY_AFTER = 900

# The statusline reads the heartbeat to colour its `5h:` label and treats
# anything older than 900s as "not running", so beat well inside that. Five
# minutes rather than every 30s tick keeps this near 288 writes a day.
HEARTBEAT_INTERVAL = 300

# Opening a fresh five-hour window buys nothing once the seven-day budget is
# spent, so stand down rather than paying for windows that cannot be used.
DEFAULT_WEEKLY_STAND_DOWN = 95

# Measured 2026-09-10: 451 tokens, $0.00073 a firing. The naive call (no --tools,
# default system prompt) was 17.8k tokens and $0.0101 — 40x more — because the
# tool schemas and the standard system prompt dominate a request this small.
PING_ARGS = [
    "-p", "ok",
    "--model", "haiku",
    "--safe-mode",              # no CLAUDE.md, skills, plugins, hooks, MCP
    "--no-session-persistence",  # never clutter the session picker
    "--tools", "",              # the tool schemas are most of the token cost
    "--system-prompt", "Reply with exactly: ok",
]


def _read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def _write_json_atomic(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh)
    os.replace(tmp, path)


def effective_expiry(reset_state, chain_state):
    """The boundary to fire against. Two sources; the later one wins.

    The statusline captures Anthropic's real expiry, which is authoritative but
    only appears while an interactive session renders. A headless ping renders
    no statusline, so once the chain fires unattended it stamps a provisional
    boundary and rides that until a real session corrects it. Taking the max
    means a stale provisional can never drag a freshly captured real boundary
    backwards, and a real boundary always wins once it is newer.
    """
    real = (reset_state or {}).get("five_resets_at") or 0
    prov = (chain_state or {}).get("provisional_until") or 0
    try:
        return max(float(real), float(prov))
    except (TypeError, ValueError):
        return 0.0


def should_fire(reset_state, chain_state, now, weekly_stand_down=DEFAULT_WEEKLY_STAND_DOWN):
    """Pure decision: fire now, or not, and why. Returns (bool, reason)."""
    expiry = effective_expiry(reset_state, chain_state)
    if not expiry:
        return False, "no window boundary captured yet"
    if now < expiry + FIRE_BUFFER:
        return False, f"window live for another {max(0, int(expiry - now))}s"
    pct = (reset_state or {}).get("seven_pct")
    if pct is not None and weekly_stand_down is not None and pct >= weekly_stand_down:
        return False, f"stood down: weekly budget at {pct}% (limit {weekly_stand_down}%)"
    return True, "window expired"


def fire_ping(claude_bin, env=None, timeout=120):
    """Spend one Haiku token to open a fresh window. Returns (ok, detail)."""
    PING_CWD.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [claude_bin, *PING_ARGS],
            cwd=str(PING_CWD),
            env=env,
            stdin=subprocess.DEVNULL,  # never inherit a TTY; matches headless rule
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode == 0:
            return True, (proc.stdout or "").strip()[:200]
        detail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-200:]
        return False, detail or f"exit {proc.returncode}"
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as exc:
        return False, f"launch error: {type(exc).__name__}: {exc}"


def _touch_heartbeat(chain_state, now):
    """Prove liveness to the statusline without writing on every 30s tick."""
    try:
        last = float((chain_state or {}).get("heartbeat") or 0)
    except (TypeError, ValueError):
        last = 0
    if now - last < HEARTBEAT_INTERVAL:
        return chain_state or {}
    state = dict(chain_state or {})
    state["heartbeat"] = int(now)
    _write_json_atomic(CHAIN_PATH, state)
    return state


def tick(job, claude_bin, lock_path, env=None, now=None, _fire=None):
    """One scheduler tick. Returns a run record when it fired, else None.

    A tick that decides not to fire is a no-op, not a run, so it is never
    logged — otherwise the run log would gain 2,880 lines a day saying nothing.
    """
    now = time.time() if now is None else now
    fire = _fire or fire_ping

    reset_state = _read_json(RESET_PATH)
    chain_state = _touch_heartbeat(_read_json(CHAIN_PATH) or {}, now)

    ok, reason = should_fire(
        reset_state, chain_state, now,
        job.get("weekly_stand_down", DEFAULT_WEEKLY_STAND_DOWN),
    )
    if not ok:
        return None

    # Take the scheduler's own lock so a firing can never race a live session or
    # another scheduled run. Non-blocking: if something else holds it, the next
    # tick tries again in 30s, which is well inside the tolerance for being late.
    Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None  # not a failure; just try on the next tick

        # Stamp the short retry BEFORE firing. A crash or a kill mid-firing then
        # costs 15 minutes of delay rather than five hours of a dark chain.
        state = dict(chain_state)
        state["provisional_until"] = int(now + RETRY_AFTER)
        _write_json_atomic(CHAIN_PATH, state)

        started = time.time()
        fired_ok, detail = fire(claude_bin, env)
        finished = time.time()

        state["provisional_until"] = int(
            finished + (WINDOW_SECONDS if fired_ok else RETRY_AFTER)
        )
        state["heartbeat"] = int(finished)
        state["last_fire"] = {
            "at": int(started),
            "ok": bool(fired_ok),
            "detail": detail,
            "duration_s": round(finished - started, 1),
        }
        _write_json_atomic(CHAIN_PATH, state)

        return {
            "job": "window-chain",
            "scheduled_time": str(int(effective_expiry(reset_state, chain_state))),
            "date": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
            "status": "ok" if fired_ok else "failed",
            "outcome": f"{reason}; ping {'succeeded' if fired_ok else 'failed'}: {detail}",
        }
    finally:
        os.close(lock_fd)

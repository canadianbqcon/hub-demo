"""Live Claude terminals the Viewer can send an item to, and the send itself.

A terminal is an interactive Claude session running in a herdr tab. `claude agents
--json` lists the sessions; the pane comes from HERDR_PANE_ID in the process
environment, the tab label (`claude #N`) from `herdr tab list`, the topic from the
terminal-title hook's state. Sending types one line into the pane with `herdr pane
run` (text, then Enter): an idle session starts on it at once, a busy one queues it
like anything he types. Claude's own peer socket is not used: its wire format is
internal to Claude Code.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

TITLES = Path.home() / ".claude" / "terminal-title-state"
TIMEOUT = 5  # seconds per CLI call
_CTRL = re.compile(r"[\x00-\x1f\x7f]")  # a newline would submit early; strip every control char


def _run(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT, check=True).stdout


def _env(pid: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:  # exited, or not ours
        return {}
    return dict(kv.split("=", 1) for kv in raw.decode(errors="replace").split("\0") if "=" in kv)


def _title(session_id: str) -> str:
    try:
        return json.loads((TITLES / f"{session_id}.json").read_text()).get("title") or ""
    except (OSError, ValueError):
        return ""


def terminals() -> list[dict]:
    """Newest first: {pane, label, title, status} for each Claude session in a herdr tab."""
    sessions = json.loads(_run("claude", "agents", "--json"))
    tabs = {t["tab_id"]: t["label"] for t in json.loads(_run("herdr", "tab", "list"))["result"]["tabs"]}
    out = []
    for s in sorted(sessions, key=lambda s: s.get("startedAt", 0), reverse=True):
        if s.get("kind") != "interactive" or not s.get("pid"):
            continue
        env = _env(s["pid"])
        pane, tab = env.get("HERDR_PANE_ID"), env.get("HERDR_TAB_ID")
        if not pane or tab not in tabs:
            continue
        out.append({"pane": pane, "label": tabs[tab], "title": _title(s.get("sessionId", "")),
                    "status": s.get("status") or ""})
    return out


def send(pane: str, text: str) -> bool:
    """Type text + Enter into pane, only if it is a live Claude terminal right now."""
    if pane not in {t["pane"] for t in terminals()}:
        return False
    _run("herdr", "pane", "run", pane, _CTRL.sub(" ", text))
    return True

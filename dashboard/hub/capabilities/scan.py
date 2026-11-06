"""Disk scan for the capabilities module.

Ports the read-list from vault-code/bin/cross-agent-registry.py so the Hub
page can show the same data live, without depending on that generator's
output file (skills/capability-registry.md) being up to date. Every glob
path is existence-checked at scan time; an absent path yields an empty
list rather than an error.
"""

from __future__ import annotations

import glob
import json
import os
import re

HOME = os.path.expanduser("~")
NAME_RE = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)
DESC_RE = re.compile(r"^description:\s*(.+?)\s*$", re.MULTILINE)

# Purpose buckets for MY skills only (vault-authored). Priority-ordered,
# first-match-wins; "Misc utilities" is the catch-all. Order is by
# usefulness, not alphabetical: personal-skill-use buckets first
# (most-used to least), then misc, then dev tooling.
#
# Plugin-sourced and agy-sourced skills never reach this classifier -- they
# are grouped by provenance in _all_skills()/collect() instead, so no
# plugin name needs to appear here even though older versions of this file
# listed GSD/Superpowers/impeccable/etc. by hand.
CATEGORIES = [
    "Integrations & data pipelines",
    "Research",
    "Auditing & review",
    "Design & UX",
    "Misc utilities",
    "Dev tooling (MCP / skill-building)",
]

_AUDITING_NAMES = {"adversarial", "audit", "code-audit", "context-audit"}

_DESIGN_NAMES: set[str] = set()  # ponytail: no personally-authored design skill yet

_INTEGRATIONS_NAMES = {
    "gmail", "gmail-clean", "icloud", "finance", "job", "job-intake",
    "job-research", "recap", "reconcile", "ingest", "yt",
}

_RESEARCH_NAMES = {"research-max", "research-min", "retackle"}

_DEV_TOOLING_NAMES = {"session-to-skill", "onboard-domain", "vault-protocol", "dashboard"}

# Function-based bucket for each plugin/tool, keyed by the group name
# _plugin_name()/_installed_plugin_skills() produce. Unlisted plugins fall
# back to "Misc utilities" -- most plugins are single-purpose as a whole,
# so classifying by plugin (not per-skill) is the accurate-enough level.
_PLUGIN_CATEGORY = {
    "superpowers": "Dev tooling (MCP / skill-building)",
    "ponytail": "Dev tooling (MCP / skill-building)",
    "skill-creator": "Dev tooling (MCP / skill-building)",
    "plugin-dev": "Dev tooling (MCP / skill-building)",
    "mcp-server-dev": "Dev tooling (MCP / skill-building)",
    "hookify": "Dev tooling (MCP / skill-building)",
    "claude-md-management": "Dev tooling (MCP / skill-building)",
    "claude-code-setup": "Dev tooling (MCP / skill-building)",
    "example-plugin": "Dev tooling (MCP / skill-building)",
    "session-report": "Dev tooling (MCP / skill-building)",
    "pyright-lsp": "Dev tooling (MCP / skill-building)",
    "security-guidance": "Auditing & review",
    "frontend-design": "Design & UX",
    "impeccable": "Design & UX",
}


def classify(name: str) -> str:
    """Map a personal (mine) skill name to one of CATEGORIES, first-match-wins."""
    base = name.split(":")[-1]
    if base in _AUDITING_NAMES:
        return "Auditing & review"
    if base in _DESIGN_NAMES:
        return "Design & UX"
    if base in _INTEGRATIONS_NAMES:
        return "Integrations & data pipelines"
    if base in _RESEARCH_NAMES:
        return "Research"
    if base in _DEV_TOOLING_NAMES:
        return "Dev tooling (MCP / skill-building)"
    return "Misc utilities"


def read_skill(path: str) -> tuple[str, str]:
    """Return (name, description) from a SKILL.md, falling back to the dir name."""
    name = os.path.basename(os.path.dirname(path))
    desc = ""
    try:
        with open(path, encoding="utf-8") as fh:
            head = fh.read(2000)
        m = NAME_RE.search(head)
        if m:
            name = m.group(1).strip().split(":")[-1]
        d = DESC_RE.search(head)
        if d:
            first = d.group(1).strip()
            if first in (">", "|", ">-", "|-"):
                # YAML block scalar: description continues on the following
                # indented lines. Grab them and fold into one line.
                lines = head[d.end():].splitlines()
                block = []
                for line in lines:
                    if line.strip() == "" or line.startswith((" ", "\t")):
                        block.append(line.strip())
                    else:
                        break
                desc = " ".join(w for w in block if w)
            else:
                desc = first.strip('"').strip("'")
    except OSError:
        pass
    return name, desc


def scan_skills(pattern: str) -> list[dict]:
    """Glob a SKILL.md pattern -> sorted list of {name, description, path}."""
    rows = []
    for path in sorted(glob.glob(pattern)):
        name, desc = read_skill(path)
        rows.append({"name": name, "description": desc, "path": path})
    return rows


def tilde(path: str) -> str:
    """Shorten an absolute path back to ~/ form for readable display."""
    if path.startswith(HOME):
        return "~" + path[len(HOME):]
    return path


def _presence(paths: tuple[str, ...]) -> list[dict]:
    return [{"path": tilde(p), "present": os.path.exists(p)} for p in paths]


_MARKETPLACE_ROOT = os.path.join(HOME, ".claude/plugins/marketplaces") + os.sep
_HOME_SKILLS_ROOT = os.path.join(HOME, ".claude/skills") + os.sep


def _plugin_name(path: str) -> str:
    """Derive a display name for the plugin/tool a plugin-sourced row came from."""
    if path.startswith(_MARKETPLACE_ROOT):
        # .../marketplaces/<marketplace>/plugins/<plugin>/skills/<skill>/SKILL.md
        parts = path[len(_MARKETPLACE_ROOT):].split(os.sep)
        if len(parts) >= 3 and parts[1] == "plugins":
            return parts[2]
    if path.startswith(_HOME_SKILLS_ROOT):
        # .../.claude/skills/<name>/SKILL.md -- installed directly, not via
        # the marketplace cache (e.g. graphify, impeccable).
        name = path[len(_HOME_SKILLS_ROOT):].split(os.sep)[0]
        return name
    return "other"


def _installed_plugin_skills() -> list[dict]:
    """Scan skills for plugins actually installed & enabled (installed_plugins.json).

    The marketplaces/ tree is a browsable catalog checkout -- it holds every
    plugin in the marketplace whether or not it's installed, which is why
    math-olympiad and cwc-makers show up there. Installed, in-use plugins
    (superpowers, ponytail, security-guidance, ...) instead live under
    plugins/cache/<marketplace>/<plugin>/<version>/, keyed by installPath in
    this manifest -- so it's the only reliable signal for "actually active".
    """
    manifest = os.path.join(HOME, ".claude/plugins/installed_plugins.json")
    rows: list[dict] = []
    if not os.path.exists(manifest):
        return rows
    try:
        with open(manifest, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return rows
    for key, installs in data.get("plugins", {}).items():
        plugin_name = key.split("@")[0]
        for inst in installs:
            install_path = inst.get("installPath")
            if not install_path:
                continue
            found = scan_skills(os.path.join(install_path, "skills/*/SKILL.md"))
            for r in found:
                r["plugin"] = plugin_name
            rows += found
    return rows


def _mine_skills(vault: str) -> list[dict]:
    """Personal (vault-authored) skills: the vault's own skill folders, plus any
    entries listed in .agents/skills.json (agy-side pointers into the vault)."""
    mine: list[dict] = []
    mine += scan_skills(os.path.join(vault, ".claude/skills/*/SKILL.md"))
    mine += scan_skills(os.path.join(vault, "skills/*/SKILL.md"))
    mine += scan_skills(os.path.join(vault, ".agents/skills/*/SKILL.md"))
    skills_json = os.path.join(vault, ".agents/skills.json")
    if os.path.exists(skills_json):
        try:
            with open(skills_json, encoding="utf-8") as fh:
                entries = json.load(fh).get("entries", [])
            for e in entries:
                rel = e.get("path", "")
                base = os.path.normpath(os.path.join(vault, ".agents", rel))
                mine += scan_skills(os.path.join(base, "*/SKILL.md"))
        except (OSError, ValueError):
            pass
    for r in mine:
        r["source"] = "mine"
    return mine


def _plugin_skills() -> list[dict]:
    """Plugin-sourced skills, deduped by (plugin, name).

    Installed-plugin rows go first: a plugin can have both a marketplace
    catalog checkout (browsable, not necessarily active) and an installed
    cache copy of the same skill (e.g. frontend-design, skill-creator) --
    the plugin+name dedup below keeps whichever copy is seen first.
    """
    plugin: list[dict] = []
    installed = _installed_plugin_skills()
    for r in installed:
        r["source"] = "plugin"
    plugin += installed
    # The marketplaces/ tree is a browsable catalog of every plugin the
    # marketplace offers, installed or not (see _installed_plugin_skills
    # docstring) -- it must never be scanned here, or uninstalled plugins
    # like math-olympiad/cwc-makers leak back in as if they were active.
    catalog: list[dict] = []
    catalog += scan_skills(os.path.join(HOME, ".claude/skills/*/SKILL.md"))
    for r in catalog:
        r["source"] = "plugin"
        r["plugin"] = _plugin_name(r["path"])
    plugin += catalog
    # claude.ai account skills (docs, pdf, pptx, ...) sync one level deeper,
    # under skills/synced/<bucket>/<skill>/; Claude Code lists them as
    # anthropic-skills:<name>, so the group takes that name.
    synced = scan_skills(os.path.join(HOME, ".claude/skills/synced/*/*/SKILL.md"))
    for r in synced:
        r["source"] = "plugin"
        r["plugin"] = "anthropic-skills"
    plugin += synced
    seen_plugin_skill: set[tuple[str, str]] = set()
    deduped_plugin = []
    for r in plugin:
        key = (r["plugin"], r["name"])
        if key in seen_plugin_skill:
            continue
        seen_plugin_skill.add(key)
        deduped_plugin.append(r)
    return deduped_plugin


def _agy_skills() -> list[dict]:
    agy: list[dict] = []
    agy += scan_skills(os.path.join(HOME, ".gemini/config/skills/*/SKILL.md"))
    agy += scan_skills(os.path.join(HOME, ".gemini/antigravity-cli/builtin/skills/*/SKILL.md"))
    for r in agy:
        r["source"] = "agy"
    return agy


def _all_skills(vault: str) -> list[dict]:
    """Scan every known skill source, tag each row's provenance, and dedupe.

    Provenance ("mine" / "plugin" / "agy") is inferred purely from which
    directory a SKILL.md lives under -- see the source-groups below -- not
    from the skill's own name, since name-based guessing is what made
    plugin-authored skills (graphify, impeccable, math-olympiad, ...) leak
    into personal purpose buckets before.

    Dedup is by realpath, not the raw glob path: personal skills mirrored
    into the neutral skills/ folder via a symlink under .claude/skills/
    (e.g. explain, retackle) resolve to the same file and must collapse to
    one row, not show up twice.
    """
    mine = _mine_skills(vault)
    plugin = _plugin_skills()
    agy = _agy_skills()

    seen: set[str] = set()
    deduped = []
    for r in mine + plugin + agy:
        real = os.path.realpath(r["path"])
        if real in seen:
            continue
        seen.add(real)
        deduped.append(r)
    return deduped


def collect(vault: str) -> dict:
    """Scan every known skill source and bucket by purpose, mine first.

    Returns {"categories": {label: [rows...]}, "system_status": {label: [presence rows...]}}.
    Each category's rows are personal (mine) skills first, then plugin
    skills for that same function appended at the bottom (row["source"] ==
    "plugin" marks them; the frontend renders that tail as a nested,
    collapsed "Plugins" sub-group with a chip naming row["plugin"]).
    "Agy skills" is a separate bucket outside this purpose grouping.
    """
    rows = _all_skills(vault)

    categories: dict[str, list[dict]] = {c: [] for c in CATEGORIES}
    for row in rows:
        if row["source"] == "mine":
            categories[classify(row["name"])].append(row)
    for cat in CATEGORIES:
        categories[cat].sort(key=lambda r: r["name"])

    plugin_by_cat: dict[str, list[dict]] = {c: [] for c in CATEGORIES}
    for row in rows:
        if row["source"] == "plugin":
            cat = _PLUGIN_CATEGORY.get(row["plugin"], "Misc utilities")
            plugin_by_cat[cat].append(row)
    for cat in CATEGORIES:
        plugin_by_cat[cat].sort(key=lambda r: (r["plugin"], r["name"]))
        categories[cat] = categories[cat] + plugin_by_cat[cat]

    categories["Agy skills"] = sorted(
        (r for r in rows if r["source"] == "agy"), key=lambda r: r["name"])

    system_status = {
        "Claude Code hook sources": _presence((
            os.path.join(vault, ".claude/settings.json"),
            os.path.join(HOME, ".claude/settings.json"),
        )),
        "Claude Code mcp / config": _presence((os.path.join(HOME, ".claude.json"),)),
        "agy hook sources": _presence((os.path.join(vault, ".agents/hooks.json"),)),
        "agy mcp / config": _presence((
            os.path.join(HOME, ".gemini/config/mcp_config.json"),
            os.path.join(vault, ".agents/skills.json"),
            os.path.join(HOME, ".gemini/antigravity-cli/settings.json"),
        )),
    }

    return {"categories": categories, "system_status": system_status}

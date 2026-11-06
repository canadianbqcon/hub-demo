"""Resolve blueprints to their live CSS, for readers that cannot render the page.

The read-first consumer is usually an agent reading blueprints.json off disk, and
that file deliberately holds no CSS. Left at that, "draws from here" hands the
builder markup with no styling. So the resolution is available three ways: the page,
`GET /blueprints/api/blueprints.json?resolved=1`, and this module.

    python -m blueprints.resolve            # every blueprint, summarised
    python -m blueprints.resolve modal      # one blueprint, with its full CSS

Everything is generated from disk at call time. Nothing is stored, so nothing goes
stale — which is the whole reason the CSS is not in the JSON in the first place.
"""

from __future__ import annotations

import json
import os
import sys

from . import extract

_HERE = os.path.dirname(os.path.abspath(__file__))
_HUB = os.path.dirname(_HERE)


def load() -> dict:
    with open(os.path.join(_HERE, "blueprints.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _names(entry: dict) -> list[str]:
    out = list(entry["classes"])
    for sel in entry.get("descendants", []):
        out.extend(extract.classes_in(sel))
    return out


def _css(rules: list) -> list[dict]:
    return [{"selector": r.selector, "body": r.body, "at_rule": r.at_rule} for r in rules]


def _theme_css(entry: dict, themes: dict | None) -> dict:
    """Each theme's own rules for the piece; `themes` is {theme: parsed rules} or None."""
    names = _names(entry)
    return {t: _css(extract.rules_for(names, src, (themes or {}).get(t))) for t, src in extract.THEMES.items()}


def resolve(entry: dict, parsed: list | None = None, themes: dict | None = None) -> dict:
    """One blueprint plus the CSS behind it, read fresh off disk."""
    rules = extract.rules_for(_names(entry), entry["source"], parsed)
    return {
        **{k: v for k, v in entry.items()},
        "css": _css(rules),
        "theme_css": _theme_css(entry, themes),
        "tokens": extract.tokens_in(rules),
    }


def resolve_origin(entry: dict, parsed: list | None = None, themes: dict | None = None) -> dict:
    """One origin plus its live CSS and its skeleton text, read fresh off disk.

    Same shape as resolve(), plus `skeleton`: the authored file only names the
    skeleton's PATH (blueprints.json stays small and never goes stale on a markup
    edit), so this is where the path becomes the text a reader actually wants —
    the same inline-at-read-time move the CSS itself already makes.
    """
    rules = extract.rules_for(_names(entry), entry["source"], parsed)
    with open(os.path.join(_HUB, entry["skeleton"]), encoding="utf-8") as fh:
        skeleton = fh.read()
    return {
        **{k: v for k, v in entry.items()},
        "css": _css(rules),
        "theme_css": _theme_css(entry, themes),
        "tokens": extract.tokens_in(rules),
        "skeleton": skeleton,
    }


def resolve_derivative(entry: dict, lines: dict[str, int]) -> dict:
    """One derivative plus its page mods' live line count, read fresh off disk."""
    return {**{k: v for k, v in entry.items()}, "page_mods_lines": lines.get(entry["page_mods"], 0)}


def resolve_all() -> dict:
    data = load()
    covered = set()
    for e in list(data["blueprints"]) + list(data.get("origins", [])):
        covered |= set(_names(e))
    # each shared file parsed once per call, not once per blueprint that cites it
    parsed = {src: extract.rules(src) for src in extract.SHARED}
    themes = {t: extract.rules(src) for t, src in extract.THEMES.items()}
    inherits = data.get("liquid_inherits", {})
    derivs = data.get("derivatives", [])
    lines = extract.line_counts([e["page_mods"] for e in derivs])
    blueprints = [resolve(e, parsed.get(e["source"]), themes) for e in data["blueprints"]]
    origins = [resolve_origin(e, parsed.get(e["source"]), themes) for e in data.get("origins", [])]
    for r in blueprints + origins:
        r["liquid_inherits"] = inherits.get(r["id"], "")
    return {
        "blueprints": blueprints,
        "origins": origins,
        "derivatives": [resolve_derivative(e, lines) for e in derivs],
        "undocumented": sorted(
            {c for rs in parsed.values() for r in rs for c in extract.classes_in(r.selector)}
            - covered
        ),
        "baselines": data["baselines"],
    }


def _markup(entry: dict) -> str:
    """What a page author types. Empty for the controls topbar.jsx draws."""
    if entry.get("markup"):
        return entry["markup"] + f"\n  (verbatim from {entry['markup_from']})"
    live = entry.get("live") or {}
    return ("  none -- topbar.jsx draws this at runtime; the page writes no "
            f"markup for it. Rendered DOM: /blueprints, {live.get('sel', '?')}")


def _render(entry: dict) -> str:
    lines = [f"# {entry['name']}  ({entry['id']})", "",
             entry["purpose"], "",
             f"USE WHEN  {entry['use_when']}", f"DON'T     {entry['dont']}", "",
             "MARKUP", _markup(entry), "",
             f"TOKENS    {', '.join(entry['tokens']) or 'none'}", "",
             f"CSS  ({entry['source']})"]
    for r in entry["css"]:
        head = f"  {r['selector']} {{" if not r["at_rule"] else f"  [{r['at_rule']}]  {r['selector']} {{"
        lines.append(head)
        for decl in (d.strip() for d in r["body"].split(";")):
            if decl:
                lines.append(f"      {decl};")
        lines.append("  }")
    return "\n".join(lines)


def _render_origin(entry: dict) -> str:
    lines = [f"# {entry['name']}  ({entry['id']})", "",
             entry["purpose"], "",
             *([f"EXTENDS   {entry['extends']}  (link its stylesheet first)", ""] if entry.get("extends") else []),
             f"USE WHEN  {entry['use_when']}", f"DON'T     {entry['dont']}", "",
             "SKELETON", entry["skeleton"], "",
             f"TOKENS    {', '.join(entry['tokens']) or 'none'}", "",
             f"CSS  ({entry['source']})"]
    for r in entry["css"]:
        head = f"  {r['selector']} {{" if not r["at_rule"] else f"  [{r['at_rule']}]  {r['selector']} {{"
        lines.append(head)
        for decl in (d.strip() for d in r["body"].split(";")):
            if decl:
                lines.append(f"      {decl};")
        lines.append("  }")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    data = resolve_all()
    if len(argv) > 1:
        wanted = argv[1]
        for e in data["blueprints"]:
            if e["id"] == wanted:
                print(_render(e))
                return 0
        for e in data["origins"]:
            if e["id"] == wanted:
                print(_render_origin(e))
                return 0
        have = [e["id"] for e in data["blueprints"]] + [e["id"] for e in data["origins"]]
        print(f"no blueprint '{wanted}'. have: {', '.join(have)}", file=sys.stderr)
        return 1
    for e in data["blueprints"]:
        print(f"{e['id']:<18} {len(e['css']):>2} rules  {len(e['tokens']):>2} tokens   {e['purpose']}")
    for e in data["origins"]:
        print(f"{e['id']:<18} {len(e['css']):>2} rules  {len(e['tokens']):>2} tokens   {e['purpose']}")
    if data["undocumented"]:
        print(f"\nundocumented ({len(data['undocumented'])}): {', '.join(data['undocumented'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

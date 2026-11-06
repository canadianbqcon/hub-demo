"""Read the shared CSS layer off disk: which classes exist, and what each rule says.

Everything here is derived from `static/css/base.css` + `chrome.css` at call time.
Nothing is cached to disk and nothing is copied into blueprints.json — a blueprint
names classes, and the CSS behind them is read fresh on every request. Copied CSS
text goes stale in silence; extracted CSS cannot.

Two findings from the adversarial review are baked into the shapes here, and both
look like harmless simplifications if you don't know the history:

1. `classes_in()` captures EVERY class in a selector, not the first one. Taking
   only the first is the obvious reading of "what class is this rule about", and
   it dropped 23 of chrome.css's 48 classes — `.status .clock` recorded `status`
   and lost `clock`. The catalog's undocumented-tray check runs on this function,
   so a first-class-only scan would have been permanently blind to exactly the
   descendants most likely to get copied.

2. `rules_for()` returns each rule WITH its enclosing at-rule. The innermost-rule
   regex already finds rules nested in @media without parsing brace depth (the
   wrapper simply fails to match as a rule) — chrome.css declares .launch-panel
   twice and both come back. What is lost without `at_rule` is which is which:
   two contradictory bodies, nothing saying one is max-width 640px.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

_HUB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# theme-switch.js is a CSS source, not a script we happen to ship: it injects
# #hub-universal-css at runtime and that stylesheet is where the real chrome
# lives. Scanning only the two .css files left .hub-back, .module-launcher,
# .theme-picker-*, the is-* state classes and the whole --ctl-h control-height
# system invisible to the catalog, so the blueprints were structurally
# incomplete and nothing said so.
SHARED = (
    "static/css/base.css",
    "static/css/chrome.css",
    "static/css/components.css",
    "static/css/origins/tabbed-3-pane.css",
    "static/css/origins/entry-3-pane.css",
    "static/css/origins/tabbed-reader.css",
    "static/js/theme-switch.js",
)

# one scoped file per theme (THEMING-SPEC Rule 1); a blueprint's own version under a
# theme is that file's rules naming its classes.
THEMES = {
    "cobalt": "static/css/themes/cobalt.css",
    "liquid": "static/css/themes/liquid.css",
}

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"//[^\n]*")
# `var css = <string literals joined with +>;` ending at the <style> element build.
_INJECTED = re.compile(r"var css\s*=(.*?);\s*var el = document\.createElement", re.S)
_STR = re.compile(r'"([^"\\]*)"' + r"|'([^'\\]*)'")
# innermost rule: a selector with no braces in it, then a body with no braces in it.
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_CLASS = re.compile(r"\.([A-Za-z][\w-]*)")
_AT = re.compile(r"@[a-z-]+[^{}]*\{", re.I)


class Rule(NamedTuple):
    selector: str
    body: str
    at_rule: str  # "" for a top-level rule, else the @media/@supports condition
    source: str


def _injected_css(js: str) -> str:
    """The stylesheets theme-switch.js builds as strings and injects into <head>.

    Two of them: the theme picker's, and #hub-universal-css (the whole topbar).

    ponytail: joins the quoted literals of each `var css = ... ;` concatenation
    instead of parsing JS. Holds because that block is plain literals + comments and
    has no escapes; if it ever grows a template literal or a computed piece, this
    returns less CSS and the self-check below goes red rather than lying.
    """
    out = []
    for m in _INJECTED.finditer(js):
        body = _LINE_COMMENT.sub("", _COMMENT.sub("", m.group(1)))
        out.append("".join(a or b for a, b in _STR.findall(body)))
    return "\n".join(out)


def _read(rel: str) -> str:
    with open(os.path.join(_HUB, rel), encoding="utf-8") as fh:
        raw = fh.read()
    if rel.endswith(".js"):
        return _injected_css(raw)
    return _COMMENT.sub("", raw)


def classes_in(selector: str) -> set[str]:
    """Every class named anywhere in a selector, across all its comma-separated parts."""
    return set(_CLASS.findall(selector))


_COMBINATOR = re.compile(r"[\s>+~]+")


def _top_level_commas(selector: str) -> list[str]:
    """Split a selector list on its own commas, not the ones inside :is()/:not()."""
    parts, depth, cur = [], 0, ""
    for ch in selector:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return parts + [cur]


def is_bare_override(selector: str, roots: set[str]) -> bool:
    """True when this rule re-styles a shared class without scoping it to a module.

    Scoping is reuse and always has been -- `.work-grid .launch-tile` in work.css is
    the pattern the rule file names. The test that reads this was flagging the scoped
    form too, so its own printed advice ("scope to the shared one") could not make it
    pass, and the baseline could never reach zero without an ignore list.

    The discriminator is the LEADING compound of each comma-separated part: if the
    thing sitting leftmost is made only of shared classes, nothing module-owned is
    narrowing it and the rule reaches the shared component everywhere the sheet
    loads. `.frow-pip.hub-dot` is qualified, `body.acct .topbar` is descended, and
    `[data-theme="cobalt"] .topbar` is narrowed by an attribute -- all reuse.
    """
    for part in _top_level_commas(selector):
        head = _COMBINATOR.split(part.strip(), maxsplit=1)[0]
        names = set(_CLASS.findall(head))
        if names and names <= roots:
            return True
    return False


_BRACE = re.compile(r"[{}]")


def _at_rules(css: str) -> dict[int, str]:
    """Map each `{` offset to the innermost at-rule open around it ("" if none).

    One pass with a stack. The old per-rule walk re-scanned every earlier at-rule
    for every rule, O(n*m), and ran once per blueprint: 70 blueprints x 657 rules
    made the resolved page take ~10s on /mnt/c.
    """
    out: dict[int, str] = {}
    stack: list[str] = []
    last = 0
    for m in _BRACE.finditer(css):
        if m.group() == "}":
            if stack:
                stack.pop()
        else:
            out[m.start()] = next((a for a in reversed(stack) if a), "")
            prelude = css[last:m.start()].rsplit(";", 1)[-1].strip()
            stack.append(" ".join(prelude.split()) if prelude.startswith("@") else "")
        last = m.end()
    return out


def rules(source: str | None = None) -> list[Rule]:
    """Every innermost rule in the shared layer (or in one named file)."""
    out: list[Rule] = []
    for rel in ([source] if source else SHARED):
        css = _read(rel)
        at = _at_rules(css)
        for m in _RULE.finditer(css):
            sel = " ".join(m.group(1).split())
            if not sel or sel.startswith("@"):
                continue
            out.append(Rule(sel, m.group(2).strip(), at.get(m.end(1), ""), rel))
    return out


def rules_for(names: list[str], source: str | None = None,
              parsed: list[Rule] | None = None) -> list[Rule]:
    """Every rule whose selector mentions any of `names`, in file order.

    `parsed` is rules(source) already read this request, so a caller resolving
    many blueprints parses each file once instead of once per blueprint.
    """
    want = set(names)
    return [r for r in (rules(source) if parsed is None else parsed)
            if classes_in(r.selector) & want]


def shared_classes() -> set[str]:
    """Every class declared anywhere in the shared layer."""
    return {c for r in rules() for c in classes_in(r.selector)}


def tokens_in(rules_: list[Rule]) -> list[str]:
    """The CSS custom properties these rules consume, deduped, in first-seen order.

    Derived, never authored — a blueprint that listed its own tokens would be one
    more thing to keep true.
    """
    seen: dict[str, None] = {}
    for r in rules_:
        for t in re.findall(r"var\((--[\w-]+)", r.body):
            seen.setdefault(t, None)
    return list(seen)


def module_stylesheets() -> list[str]:
    """Every non-shared, non-theme, non-vendor stylesheet under the hub.

    The theme files are excluded because THEMING-SPEC Rule 1 freezes them verbatim;
    they are allowed to speak about any class. Vendor code is not ours to govern.
    """
    out = []
    level = [_HUB]
    # Breadth-first, each level's directory listings in parallel: a listing costs
    # ~30ms on /mnt/c and a serial os.walk over ~65 dirs was ~2s of the budget panel.
    with ThreadPoolExecutor(max_workers=16) as pool:
        while level:
            nxt = []
            for files, subdirs in pool.map(_list_dir, level):
                out.extend(f for f in files if f not in SHARED)
                nxt.extend(subdirs)
            level = nxt
    return sorted(out)


def _list_dir(path: str) -> tuple[list[str], list[str]]:
    """(css files as hub-relative paths, subdirs worth descending) for one directory.

    vendor/, themes/, caches and dot-dirs are never descended: none hold governed CSS.
    """
    files, subdirs = [], []
    with os.scandir(path) as it:
        for e in it:
            if e.is_dir():
                if (not e.is_symlink() and e.name not in ("vendor", "themes", "__pycache__")
                        and not e.name.startswith(".")):
                    subdirs.append(e.path)
            elif e.name.endswith(".css"):
                files.append(os.path.relpath(e.path, _HUB).replace(os.sep, "/"))
    return files, subdirs


def stylesheet_lines() -> dict[str, int]:
    """Line count per module stylesheet -- the page-CSS budget's unit.

    ponytail: lines, not rules. Gameable by minification, and the author here is
    Claude under a rule rather than an adversary; the page shows the number, so a
    suspicious drop is visible. If it is ever gamed, switch to counting what
    module_rules() returns -- the parser is already there.
    """
    return line_counts(module_stylesheets())


def line_counts(rels: list[str]) -> dict[str, int]:
    """Line count per file, read in parallel: /mnt/c open latency dominates, not bytes."""
    def count(rel: str) -> int:
        try:
            with open(os.path.join(_HUB, rel), encoding="utf-8") as fh:
                return sum(1 for _ in fh)
        except FileNotFoundError:
            return 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        return dict(zip(rels, pool.map(count, rels), strict=False))


def module_rules(rel: str) -> list[Rule]:
    """Innermost rules of one module stylesheet. Same shape as rules(), no at-rule walk."""
    with open(os.path.join(_HUB, rel), encoding="utf-8") as fh:
        css = _COMMENT.sub("", fh.read())
    out = []
    for m in _RULE.finditer(css):
        sel = " ".join(m.group(1).split())
        if sel and not sel.startswith("@"):
            out.append(Rule(sel, m.group(2).strip(), "", rel))
    return out


if __name__ == "__main__":
    # ponytail: self-check, not a suite. Asserts the two review findings above,
    # which is exactly what regresses if someone "simplifies" this file.
    cls = shared_classes()
    assert len(cls) > 40, f"scan collapsed to {len(cls)} classes; is it first-class-only again?"
    assert {"clock", "tile-name", "src"} <= cls, "descendant classes dropped from the scan"
    lp = rules_for(["launch-panel"])
    assert len(lp) >= 2, f"expected .launch-panel in and out of @media, got {len(lp)}"
    assert any(r.at_rule for r in lp), "at-rule context lost — the two bodies are indistinguishable"
    assert "--bg-elev" in tokens_in(lp), "token derivation broken"
    # the runtime-injected half: invisible until 2026-08-31, which is why every
    # blueprint written before that date was missing the real chrome vocabulary.
    assert {"hub-back", "module-launcher", "theme-picker-btn", "is-active"} <= cls, \
        "theme-switch.js's injected stylesheet is not being scanned"
    assert "--ctl-h" in _read("static/js/theme-switch.js"), "injected CSS extraction returned nothing useful"
    # the scoping rule: reuse and drift look almost identical and the difference is
    # which end of the selector the module owns.
    assert is_bare_override(".topbar", {"topbar"})
    assert not is_bare_override(".work-grid .launch-tile", {"launch-tile"})
    print(f"ok — {len(cls)} shared classes, {len(rules())} rules, "
          f"{len(module_stylesheets())} module stylesheets")

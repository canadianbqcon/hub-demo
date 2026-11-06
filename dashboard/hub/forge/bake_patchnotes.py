#!/usr/bin/env python3
"""Bake Riot's own patch notes into data/forge-patch-notes.json.

    python3 bake_patchnotes.py            # the live patch
    python3 bake_patchnotes.py 26.15      # a named one

Why this exists at all: build_diff.py reads Data Dragon and can only see the
numbers Data Dragon exposes, which is stats and gold. Patch 26.16 shipped
Sundered Sky with Health 400 -> 450 AND its healing cut from 100%/6% to 90%/4%,
and the recipe stripped of a Ruby Crystal. The diff saw the health line, called
it a change, and the landing page read as if a nerfed item had been buffed. The
passive is not in the data, so no amount of diffing recovers it. Riot's notes
are the only place the whole change is written down, so this reads them.

The page is server-rendered and its markup is stable and semantic:

    <h2>                        a section (Champions, Items, Runes, Systems, ...)
    .patch-change-block         one entry (a champion, an item, a rune)
      h3.change-title           its name
      blockquote.context        the designer's reasoning
      h4.change-detail-title    a group inside it (Base Stats, "Q - Tactical Sweep")
      ul > li                   <strong>Field</strong>: old => <strong>new</strong>

Systems blocks carry no h3 - the h4 groups ARE the entries - so a block without
one is flattened, each group becoming an entry of its own.

build_diff.py READS this file as the source for its item changes, and falls back
to Data Dragon only for items Riot did not write up. That was the other half of
the problem described above: the diff was not merely missing the healing cut on
Sundered Sky, it was publishing the item as a BUFF off the health line alone.
Nothing here writes into forge-patch-diff.json; the dependency runs one way.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup, Tag

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

SITE = "https://www.leagueoflegends.com/en-us/news/game-updates"
DDRAGON = "https://ddragon.leagueoflegends.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Riot's own arrow between the old value and the new one.
ARROW = "⇒"


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", "replace")


def live_ddragon() -> str:
    req = urllib.request.Request(f"{DDRAGON}/api/versions.json",
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())[0]


def candidates(ddragon: str) -> list[tuple[str, str]]:
    """(patch, url) guesses for the notes matching a Data Dragon version.

    The two numbering schemes do not agree and never announced that they would:
    Data Dragon serves 16.16.1 while the notes for the same patch are titled
    26.16, because the notes major is the calendar year and Data Dragon's is the
    old sequential season count. Rather than hardcode the offset - which is
    exactly the kind of constant that goes silently wrong at a new year - guess
    both majors against both slug shapes and let the page itself confirm which
    one was right. Six HEADs at bake time, once a patch.
    """
    major, minor = ddragon.split(".")[:2]
    year = date.today().year % 100
    majors = dict.fromkeys([str(year), str(year - 1), major])  # ordered, deduped
    out = []
    for maj in majors:
        for slug in (f"league-of-legends-patch-{maj}-{minor}-notes",
                     f"patch-{maj}-{minor}-notes"):
            out.append((f"{maj}.{minor}", f"{SITE}/{slug}/"))
    return out


def find_notes(patch: str | None) -> tuple[str, str, str]:
    """(patch, url, html). A candidate counts only when the page comes back AND
    declares the patch it is for, so a redirect to some other article cannot be
    mistaken for a hit."""
    if patch:
        maj, minor = patch.split(".")[:2]
        tries = [(patch, f"{SITE}/league-of-legends-patch-{maj}-{minor}-notes/"),
                 (patch, f"{SITE}/patch-{maj}-{minor}-notes/")]
    else:
        tries = candidates(live_ddragon())

    for want, url in tries:
        try:
            html = get(url)
        except urllib.error.HTTPError as exc:
            print(f"  {exc.code} {url}")
            continue
        if f'id="{want}"' not in html and f">Patch {want}" not in html:
            print(f"  200 but no patch {want} on the page: {url}")
            continue
        print(f"  found patch {want}: {url}")
        return want, url, html
    raise SystemExit("no patch notes page answered — pass the patch explicitly, "
                     "e.g. python3 bake_patchnotes.py 26.16")


def text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def icon(node) -> str | None:
    img = node.find("img")
    return img.get("src") if img else None


def changes(ul) -> list[dict]:
    """One bullet: `<strong>Field</strong>: old => <strong>new</strong>`.

    The shape is not guaranteed - some bullets are a flat sentence with no arrow
    at all ("Affected Champions: Akshan, Aphelios, ...") - so anything that does
    not split cleanly is kept whole in `line` rather than forced into columns.
    """
    out = []
    for li in ul.find_all("li", recursive=False):
        line = text(li)
        field = text(li.find("strong")) if li.find("strong") else ""
        field = field.rstrip(":").strip()
        rest = line[len(field):].lstrip(": ").strip() if line.startswith(field) else line
        if ARROW in rest:
            was, _, now = rest.partition(ARROW)
            out.append({"field": field, "from": was.strip(), "to": now.strip()})
        else:
            out.append({"field": field, "line": rest or line})
    return out


def groups(block) -> list[dict]:
    """The h4 subheadings inside one block, each with the bullets under it.

    Bullets before the first h4 (an item's whole change list, usually) land in an
    unnamed leading group so nothing is dropped for want of a heading.
    """
    out, cur = [], {"name": None, "icon": None, "context": None, "changes": []}
    for el in block.find_all(["h4", "ul", "blockquote"], recursive=True):
        if el.name == "h4":
            if cur["changes"] or cur["name"]:
                out.append(cur)
            cur = {"name": text(el), "icon": icon(el), "context": None, "changes": []}
        elif el.name == "blockquote" and cur["name"] and not cur["context"]:
            cur["context"] = text(el)
        elif el.name == "ul":
            cur["changes"].extend(changes(el))
    if cur["changes"] or cur["name"]:
        out.append(cur)
    return out


def _is_change_block(el) -> bool:
    if not isinstance(el, Tag) or el.name != "div":
        return False
    classes = el.get("class") or []
    if "patch-change-block" not in classes and "white-stone" not in classes:
        return False
    # a .white-stone wrapping a .patch-change-block would be counted twice
    return not el.find("div", class_="patch-change-block")


def _append_block_entries(el, sections: list[dict]) -> None:
    """One change block -> one or more entries, appended onto `sections[-1]`."""
    title = el.find("h3", class_="change-title")
    blocks = groups(el)
    # the context directly under the h3, i.e. before any h4 took over
    lead = el.find("blockquote", class_="context")
    context = text(lead) if lead else None

    if title:
        named = [g for g in blocks if g["name"] or g["changes"]]
        sections[-1]["entries"].append({
            "name": text(title),
            "icon": icon(el),
            "context": context,
            "groups": named,
        })
        return

    # Systems and friends: no entry title, so each h4 is its own entry
    for g in blocks:
        if not g["changes"]:
            continue
        sections[-1]["entries"].append({
            "name": g["name"] or text(el)[:60],
            "icon": g["icon"],
            "context": g["context"] or context,
            "groups": [{"name": None, "icon": None, "context": None,
                        "changes": g["changes"]}],
        })


def parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find(id="patch-notes-container")
    if root is None:
        raise SystemExit("the page has no #patch-notes-container — markup changed")

    sections: list[dict] = []
    for el in root.descendants:
        if getattr(el, "name", None) == "h2":
            name = text(el)
            if name and name != "\xa0":
                sections.append({"name": name, "entries": []})
            continue
        if not sections or not _is_change_block(el):
            continue
        _append_block_entries(el, sections)

    return [s for s in sections if s["entries"]]


def main() -> int:
    patch = sys.argv[1] if len(sys.argv) > 1 else None
    print("looking for the patch notes")
    patch, url, html = find_notes(patch)

    soup = BeautifulSoup(html, "html.parser")
    when = soup.find("time")
    title = soup.find("h1")
    # html.parser lowercases attribute names, so Riot's camelCase dateTime
    # arrives as datetime; read both rather than betting on the parser
    stamp = (when.get("datetime") or when.get("dateTime") or "") if when else ""

    sections = parse(html)
    out = {
        "patch": patch,
        "title": text(title) if title else f"Patch {patch} Notes",
        "url": url,
        "date": stamp[:10] or None,
        "ddragon": live_ddragon(),
        "sections": sections,
    }

    dest = vault_root() / "data" / "forge-patch-notes.json"
    dest.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False) + "\n",
                    encoding="utf-8")

    print(f"\n{dest}")
    for s in sections:
        print(f"  {s['name']:24} {len(s['entries'])} entries, "
              f"{sum(len(g['changes']) for e in s['entries'] for g in e['groups'])} changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

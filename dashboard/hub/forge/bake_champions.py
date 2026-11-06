"""The champion page store: one row per champion from read sources.

Wiki ability text and patch history, Data Dragon identity, and the calculator's
own numbers beside them. A field comes from a source or stays missing; nothing
here writes champion prose or picks between two sources silently.
"""
import argparse
import ast
import hashlib
import html as html_lib
import itertools
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bake_traits as bt  # noqa: E402
import notes_read  # noqa: E402
from vault_path import vault_root  # noqa: E402

OUT = vault_root() / "data" / "forge-champions.json"
WORK = vault_root() / "data" / "forge-champions.work.json"
LOCK = Path.home() / ".cache" / "forge-champions.lock"  # per machine: data/ syncs, so a PID there means nothing
ARCHETYPES = bt.ARCH_LIVE
CATALOG = Path(__file__).resolve().parent / "frontend" / "static" / "catalog.json"
# The calculator's code and the item data it reads: a change reruns every page calc, which no other key sees.
# ponytail: this file is in it, so a wiki-reader edit reruns calc too; calc is local and minutes, not requests
ENGINE = hashlib.sha256(b"".join(Path(f).read_bytes() for f in (bt.__file__, bt.ft.__file__, __file__, bt.ITEM_PASSIVES, CATALOG)
                                 if Path(f).exists())).hexdigest()[:12]
API = "https://wiki.leagueoflegends.com/en-us/api.php"
PAGE = "https://wiki.leagueoflegends.com/en-us/"
DDRAGON = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion/{id}.json"
MODULE = "Module:ChampionData/data"
UA = {"User-Agent": "vault-forge-champions/1.0 (personal study page)"}
PARSER = 6
PAUSE = 1
TIMEOUT = 30
RETRIES = 3
BATCH = 50
MAX_FAILED = 0.05
CHECKPOINT = 60  # seconds between work-file saves during a run
PARTS = ("identity", "stats", "abilities", "history", "calc")
# The wiki keeps one page for a slot whose real kit is several; no parameter says so.

# ---- ability text


def _lines(page):
    page = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", page, flags=re.S)
    page = re.sub(r"</(div|p|li|tr|td|th|dt|dd|h\d)>|<br\s*/?>", "\n", page)
    text = html_lib.unescape(re.sub(r"<[^>]+>", "", page))
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n") if ln.strip()]


def _blurb(lines):
    """The ability's `blurb` parameters, spaces out: the rendered page runs them
    together, so a blurb line is matched as a piece of this, not as an equal."""
    found = (
        lines[i + 1] for i, ln in enumerate(lines[:-1])
        if re.fullmatch(r"blurb\d?", ln) and not lines[i + 1].startswith("Blurb paragraph")
    )
    return "".join(found).replace(" ", "")


def _description_key(lines):
    """Start of the `description` parameter: prose above it is blurb, including the
    recast sentence the wiki writes itself, which no blurb parameter holds."""
    for i, ln in enumerate(lines[:-1]):
        if ln == "description" and not lines[i + 1].startswith("Description paragraph"):
            return lines[i + 1].replace(" ", "")[:30]
    return ""


def _param(lines, name):
    return next((lines[i + 1] for i, ln in enumerate(lines[:-1]) if ln == name), None)


def _join_split_numbers(lines):
    out = []
    for ln in lines:
        if out and re.search(r"(?:^|/ )\d+\.$", out[-1]) and re.match(r"\d", ln):
            out[-1] += ln
        else:
            out.append(ln)
    return out


def read_ability(page):
    """One `Template:Data <champ>/<form>` render. Raises ValueError on any other page."""
    lines = _lines(page)
    if "Spell pages" not in lines or "Edit" not in lines:
        raise ValueError("not an ability data page")
    i = lines.index("Edit") + 1
    if i >= len(lines):
        raise ValueError("ability page has no name")
    name = lines[i]
    i += 1
    fields = {}
    while i + 1 < len(lines) and lines[i].endswith(":") and lines[i].isupper():
        fields[lines[i][:-1]] = lines[i + 1]
        i += 2
    pages = lines.index("Spell pages")
    end = lines.index("Notes/General Details") if "Notes/General Details" in lines else pages
    blurb = _blurb(lines[pages:])
    body = _join_split_numbers(lines[i:end])
    key = _description_key(lines[pages:])
    start = next((n for n, ln in enumerate(body) if key and ln.replace(" ", "").startswith(key)), 0)
    text, blurbs, ranks = [], [], []
    k = 0
    while k < len(body):
        ln = body[k]
        k += 1
        if ln[0] in '"“':
            continue
        if ln.endswith(":") and k < len(body):
            ranks.append({"label": ln[:-1], "values": body[k]})
            k += 1
        elif k > start and ln.replace(" ", "") not in blurb:
            text.append(ln)
        else:
            blurbs.append(ln)
    notes = []
    if "NOTICE TO API USERS:" in lines:
        start = lines.index("NOTICE TO API USERS:") + 2
        stop = lines.index("Map-Specific Differences") if "Map-Specific Differences" in lines else pages
        notes = lines[start:stop]
    return {
        "name": name,
        "slot": _param(lines[pages:], "skill"),
        "cost": fields.get("COST"),
        "cooldown": fields.get("COOLDOWN") or fields.get("STATIC COOLDOWN"),
        "cast": fields.get("CAST TIME"),
        "range": fields.get("RANGE") or fields.get("TARGET RANGE"),
        "speed": fields.get("SPEED"),
        "fields": fields,
        "text": text or blurbs[1:] or blurbs,  # no description: the first line runs the rest together
        "ranks": ranks,
        "notes": notes,
    }


# ---- wiki markup

_TEMPLATE = re.compile(r"\{\{([^{}|]+)((?:\|[^{}]*)?)\}\}")
_FIRST = {"fd", "as", "tt", "sbc", "Sbc", "ci", "ri", "ui", "bi", "mi3", "nie"}
_SECOND = {"ii", "si", "sti", "tip"}
_POSSESSIVE = {"iis", "cis"}
_LIST_SEP = re.compile(r"\s*;\s*")


def _ap_ends(args):
    """An `ap` as the verdict rule reads it: its run, or its two endpoints."""
    if any(not re.fullmatch(r"[\d.]+%?", a.strip()) for a in (args if len(args) > 1 else [])):
        return None
    if len(args) > 1:
        return " / ".join(a.strip() for a in args)
    if not re.fullmatch(r"[\d.]+%?(?: to [\d.]+%?(?: \d+)?)?", args[0].strip()):
        return None  # "60/4 to 180/4" is arithmetic, not a run
    # "35 to 65 3": the last token counts the ranks. "~" marks a template's span, so a
    # literal "6 to 2 seconds" in the prose stays unread.
    return re.sub(r"^(\S+) to (\S+)(?: \d+)?$", r"\1 ~ \2", args[0].strip())


def _pp_ends(inner):
    """A `pp` as the verdict rule reads it: its run, or its two ends by level, the key
    (`%`) on each. None on a formula or running steps, so the line stays unread."""
    parts = inner.split("|")
    key = next((p.split("=", 1)[1].strip() for p in parts if re.match(r"\s*key\s*=", p)), "")
    text = next((p.strip() for p in parts if not re.match(r"\s*\w+\s*=", p)), "")
    span = re.fullmatch(r"(\S+) to (\S+)(?: for \d+)?", text)
    vals = [span[1], span[2]] if span else [re.sub(r" for \d+$", "", p) for p in _LIST_SEP.split(text)]
    nums = [_number(v) for v in vals]
    if None in nums:
        return None
    return (" ~ " if span else " / ").join(_show(n) + key for n in nums)


def _number(text):
    """A number or a product, as `ap` and `pp` take them. None on anything else."""
    try:
        return math.prod(float(p) for p in text.strip().split("*"))
    except ValueError:
        return None


def _show(value):
    return f"{round(value, 4):g}"


def _ap(args):
    """Wiki `ap`: "46 to 30" fills the ranks between, five unless a count follows."""
    if len(args) > 1:
        return " / ".join(a.strip() for a in args)
    text = args[0].strip()
    span = re.fullmatch(r"(\S+) to (\S+)(?: (\d+))?", text)
    if not span:
        value = _number(text)
        return text if value is None else _show(value)
    lo, hi, n = _number(span[1]), _number(span[2]), int(span[3] or 5)
    if lo is None or hi is None or n < 2:
        return text
    return " / ".join(_show(lo + (hi - lo) * i / (n - 1)) for i in range(n))


def _rounded(text):
    value = _number(text)
    return text if value is None else f"{round(value, 2):g}"


def _pp_steps(parts, args):
    """"0;then + 30; then + 5*x" over "0 to 20": a running total. Its two ends, or
    None on a step this does not read."""
    total, steps = _number(parts[0]), [re.sub(r"^then \+\s*", "", p) for p in parts[1:]]
    span = re.match(r"(\d+) to (\d+)", args[1]) if len(args) > 1 else None
    for step in steps:
        each = _number(step.removesuffix("*x"))
        if total is None or each is None or (step.endswith("*x") and not span):
            return None
        total += each * (int(span[2]) - int(span[1]) - len(steps) + 1 if step.endswith("*x") else 1)
    return [parts[0], _show(total)]


def _pp(args, named):
    """Wiki `pp`: up to five values in a row, more as their two ends, then what they
    follow unless `showtype=false`."""
    key = named.get("key", "")
    text = args[0].strip()
    row = re.fullmatch(r"(\S+ to \S+) for ([2-5])", text)
    parts = _ap([f"{row[1]} {row[2]}"]).split(" / ") if row else _LIST_SEP.split(text)
    parts = [re.sub(r" for \d+$", "", p) for p in parts]
    many = len(parts) > 5 or " to " in parts[0] or " to " in parts[-1] or "changedisplay" in named
    if any("then" in p for p in parts):
        parts, many = _pp_steps(parts, args) or parts, True
    if many:
        lo, hi = parts[0].split(" to ")[0], parts[-1].split(" to ")[-1]
        shown = f"{_rounded(lo)}{key} – {_rounded(hi)}{key}"
    else:
        shown = " / ".join(p + key for p in parts)
    return shown if named.get("showtype") == "false" else f"{shown} (based on {named.get('type', 'level')})"


def _owner(name):
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _ability(name, args, owned):
    """`ai` and its kin: a third argument is the wording, else the ability's name.
    A slot letter stays a letter: the wiki looks its name up, this reader does not."""
    shown = args[2] if len(args) > 2 else args[0]
    if name in ("ais", "cais"):
        shown = _owner(shown)
    return f"{_owner(args[1])} {shown}" if owned and len(args) > 1 else shown


def _template(m):
    name = m.group(1).strip()
    parts = m.group(2).split("|")[1:]
    named = dict(
        (p.split("=", 1)[0].strip(), p.split("=", 1)[1].strip())
        for p in parts if re.match(r"\s*\w+\s*=", p)
    )
    args = [p for p in parts if not re.match(r"\s*\w+\s*=", p)]
    if name == "times":
        return "×"
    if name == "minus":
        return "-"
    if name == "tip" and "icononly" in named:
        return ""
    if not args:
        return m.group(0)
    if name == "ap":
        return _ap(args)
    if name == "pp":
        return _pp(args, named)
    if name == "ft":
        return f"{args[0]} ({args[1]})" if len(args) > 1 else args[0]
    if name in _FIRST:
        return args[0]
    if name in _SECOND:
        return args[1] if len(args) > 1 else args[0]
    if name == "csl":
        return args[2] if len(args) > 2 else f"{args[1]} {args[0]}" if len(args) > 1 else args[0]
    if name in ("ai", "ais", "cai", "cais"):
        return _ability(name, args, name.startswith("c"))
    if name in _POSSESSIVE:
        return _owner(args[0])
    if name in ("cci", "ccib"):
        return args[-1]
    return m.group(0)


def reduce_markup(text):
    """Wikitext to the text it shows. A template with no rule stays visible, so a
    new one reads as itself on the page and in the sweep, never as a guess."""
    text = re.sub(r"<ref[^>]*/>|<ref.*?</ref>|<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"</?[a-z]+\s*/?>|\[\[File:[^\]]*\]\]", "", text)
    while True:
        next_text = _TEMPLATE.sub(_template, text)
        if next_text == text:
            break
        text = next_text
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    return re.sub(r"\s+", " ", text.replace("'''", "").replace("''", "")).strip()


# ---- verdicts

# Named fields, the whole name. A word match reads "Self slow" and "Cooldown refund"
# as their nearest stat and gets the direction backwards.
_VERDICT_FIELDS = frozenset(x.strip() for x in """
    mana cost, energy cost, health cost, cooldown, static cooldown, cast time,
    base health, health growth, health per level,
    base armor, armor growth, armor per level,
    base magic resistance, magic resistance growth, magic resistance per level,
    base attack damage, attack damage growth, attack damage per level,
    base attack speed, attack speed ratio, attack speed growth, attack speed per level,
    base mana, mana growth, mana per level, maximum energy,
    base health regeneration, base health regen, health regeneration growth, health regen growth,
    base mana regeneration, mana regeneration growth,
    base mana regen, mana regen growth, mana regen per level, mana regeneration per level,
    health regen per level, health regeneration per level, base health regen per 5,
    base movement speed, attack range,
    base damage, bonus damage, minimum damage, maximum damage, minimum base damage,
    maximum base damage, base damage per hit, magic damage, physical damage, true damage,
    minimum true damage, collision damage, bonus monster damage,
    base heal, healing, base shield
""".split(","))
# Under an ability these can name a slow, a target's stat or a stacking bonus.
_STAT_FIELDS = frozenset(("movement speed", "armor", "attack speed", "attack damage",
                          "magic resistance", "health", "mana", "range"))
# Shapes whose direction is the champion's own power: a ratio, damage dealt, healing,
# shields, crowd control on the target. Anything naming the self, a refund or a
# reduction can point either way, so it stays unread.
_VERDICT_SHAPE = re.compile(
    r"(?!.*\b(?:self|refund|reduction|taken|penalty)\b)"
    r"(?:.* )?(?:ratio|damage(?: per \w+)?|heal(?:ing)?|shield(?: strength)?|slow|"
    r"(?:slow|stun|root|knock-?up|knockback|charm|fear|taunt|silence|suppression|sleep|"
    r"polymorph|blind|ground|shield|stealth|invisibility|camouflage) duration|"
    r"bonus attack speed|bonus movement speed|(?:bonus |cast )?range|(?:missile|projectile) speed)"
    r"(?: against (?:champions|monsters|minions|large monsters|epic monsters))?")
_RUN = r"[\d.]+%?(?: ?(?:/|~) ?[\d.]+%?)*"
# A unit after the numbers, the same on both sides or written once.
_UNIT = r"(?: seconds?| units| ?%? ?(?:[Bb]onus |maximum |missing |total )?(?:AP|AD|armor|health|magic resistance|mana))?"
_VERDICT_LINE = re.compile(
    rf"(.+?) (?:(?:increased|reduced) to )?({_RUN})({_UNIT})(?: at all ranks)?"
    rf" from ({_RUN})({_UNIT})(?: at all ranks)?\.?"
)


def _bare(unit):
    return re.sub(r"\bbonus ", "", unit.lower())


def _run(text):
    return [p.strip() for p in re.split(r" ~ |/", text)]


def _verdict_field(field, on):
    f = field.lower()
    return (f in _VERDICT_FIELDS or (on == "Stats" and f in _STAT_FIELDS)
            or bool(_VERDICT_SHAPE.fullmatch(f)))


def line_verdict(raw, on=None):
    """"buff", "nerf", "mixed" or None. Only a whole `<field> increased|reduced to X
    from Y` line with a field of known direction gets one; direction is arithmetic on
    the wiki's numbers."""
    body = re.sub(r"^\*+\s*(?:\{\{sbc\|Undocumented:\}\}\s*)?", "", raw).replace("'''", "")
    body = re.sub(r"\{\{pp\|([^{}]*)\}\}", lambda m: _pp_ends(m.group(1)) or m.group(0), body)
    body = re.sub(r"\{\{fd\|([^{}|]*)\}\}", r"\1", body)
    body = re.sub(r"\{\{ap\|([^{}]*)\}\}", lambda m: _ap_ends(m.group(1).split("|")) or m.group(0), body)
    # {{as|40%|AD}} is the wiki's short form of "40% AD": its parts join with a space
    body = re.sub(r"\{\{as\|([^{}]*)\}\}", lambda m: m.group(1).replace("|", " "), body)
    if "{{" in body or "[[" in body:
        return None
    m = _VERDICT_LINE.fullmatch(body.strip())
    if not m:
        return None
    field, new, unit_new, old, unit_old = (g.strip() if g else "" for g in m.groups())
    # the old side of a ratio is written "40% AD" for "40% bonus AD"; "bonus" is not a unit change
    if unit_new and unit_old and _bare(unit_new) != _bare(unit_old):
        return None
    if not _verdict_field(field, on):
        return None
    new, old = _run(new), _run(old)
    if len(new) == 1:
        new = new * len(old)
    if len(old) == 1:
        old = old * len(new)
    return notes_read.change_verdict(field, " / ".join(old), " / ".join(new))


# ---- patch history


def read_history(wikitext):
    """Patches in page order, newest first. Raises ValueError with no patch heading."""
    rows = wikitext.split("\n")
    patches, cur, on = [], None, None
    for i, ln in enumerate(rows):
        if re.match(r"==\s*See also", ln):
            break
        if ln.startswith(";"):
            cur = {"patch": reduce_markup(ln[1:]), "lines": []}
            patches.append(cur)
            on = None
            continue
        if cur is None or not ln.strip():
            continue
        if ln.startswith("*") and not ln.startswith("**"):
            if i + 1 < len(rows) and rows[i + 1].startswith("**"):
                on = reduce_markup(ln[1:])
                continue
            on = None
        elif not ln.startswith("*") and (ln[0] in "=<{[" or ln.startswith("__")):
            continue
        text = reduce_markup(re.sub(r"^\*+\s*", "", ln))
        if text:
            cur["lines"].append({"on": on, "text": text, "raw": ln, "verdict": line_verdict(ln, on)})
    if not patches:
        raise ValueError("no patch heading")
    return patches


# ---- patch release dates (mark 2026-11-05-024817:7)

_MONTHS = "January February March April May June July August September October November December".split()
_ROW_DATE = re.compile(rf"({'|'.join(_MONTHS)})'*\s+(\d{{1,2}})'*\s*<br\s*/?>\s*(\d{{4}})")
_ROW_VER = re.compile(r"\[\[(V\d[\w.]*\w)(?:\|[^\]]*)?\]\]")
PATCH_VER = re.compile(r"\bV\d[\w.]*\w")


def read_patch_dates(index, cycles):
    """{"V25.24": "2025-12-03"} from the wiki's Patch page (`index`, naming one page per
    annual cycle) and those cycle pages' tables ({title: wikitext}). A row is a date cell
    then a [[V..]] link."""
    out = {}
    for title in re.findall(r"\[\[(Patch/[^|\]]+)", index):
        for row in (cycles.get(title) or "").split("\n|-"):
            d, v = _ROW_DATE.search(row), _ROW_VER.search(row)
            if d and v:
                out.setdefault(v.group(1), f"{d.group(3)}-{_MONTHS.index(d.group(1)) + 1:02d}-{int(d.group(2)):02d}")
    return out


def fetch_patch_dates(fetch):
    index = fetch.contents(["Patch"]).get("Patch") or ""
    return read_patch_dates(index, fetch.contents(re.findall(r"\[\[(Patch/[^|\]]+)", index)))


def patch_date(label, dates):
    """A history heading's release date, by the first version in it ("V25.S1.3 - February
    5th Hotfix" reads V25.S1.3's). ponytail: a hotfix shows its patch's date."""
    m = PATCH_VER.search(label or "")
    return dates.get(m.group(0)) if m else None


# ---- the wiki's champion table


_LUA_TOKEN = re.compile(r'''--[^\n]*|\s+|"(?:[^"\\]|\\.)*"|[{}=,;\[\]]|[^\s{}=,;\[\]"]+''')
_LUA_MATH = {ast.Add: float.__add__, ast.Sub: float.__sub__, ast.Mult: float.__mul__, ast.Div: float.__truediv__}


def _lua_number(token):
    """A number, or arithmetic like Riot's `84+1000/17`, with no eval and no powers."""
    def walk(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in _LUA_MATH:
            return _LUA_MATH[type(node.op)](walk(node.left), walk(node.right))
        raise ValueError(f"not a number: {token}")
    value = walk(ast.parse(token, mode="eval").body)
    return int(value) if value.is_integer() and re.fullmatch(r"-?\d+", token) else value


def _lua_value(toks, i):
    t = toks[i]
    if t == "{":
        return _lua_table(toks, i + 1)
    if t[0] == '"':
        return re.sub(r"\\(.)", r"\1", t[1:-1]), i + 1
    if t in ("true", "false", "nil"):
        return {"true": True, "false": False, "nil": None}[t], i + 1
    return _lua_number(t), i + 1


def _lua_table(toks, i):
    """A table with no keys is a list. One with keys is a dict, and a value with no key
    takes the next free number: the wiki writes `{[1] = "a", "b"}` and means both."""
    keyed, plain = {}, []
    while toks[i] != "}":
        if toks[i] in (",", ";"):
            i += 1
        elif toks[i] == "[":
            key, i = _lua_value(toks, i + 1)
            if toks[i:i + 2] != ["]", "="]:
                raise ValueError("no = after a key")
            keyed[str(key)], i = _lua_value(toks, i + 2)
        elif toks[i + 1] == "=":
            keyed[toks[i]], i = _lua_value(toks, i + 2)
        else:
            value, i = _lua_value(toks, i)
            plain.append(value)
    if not keyed:
        return plain, i + 1
    free = (n for n in itertools.count(1) if str(n) not in keyed)
    return {**keyed, **{str(n): v for n, v in zip(free, plain)}}, i + 1


def read_module(text):
    """`Module:ChampionData/data`, a Lua table, as dicts."""
    toks = [m.group() for m in _LUA_TOKEN.finditer(text)]
    toks = [t for t in toks if not t.isspace() and not t.startswith("--")]
    if "{" not in toks:
        raise ValueError("no Lua table")
    try:
        return _lua_value(toks, toks.index("{"))[0]
    except (IndexError, SyntaxError, TypeError, ValueError) as e:
        raise ValueError(f"Lua table not read: {e}") from e


_STATS = {"hp": "hp", "mp": "mp", "armor": "arm", "mr": "mr", "hp5": "hp5", "mp5": "mp5",
          "ad": "dam", "as": "as"}


def wiki_stats(row):
    stats = row["stats"]
    out = {k: [stats.get(f"{v}_base"), stats.get(f"{v}_lvl")] for k, v in _STATS.items()}
    return {**out, "range": stats.get("range"), "ms": stats.get("ms")}


def _named(module_row, slot):
    named = module_row.get(f"skill_{slot.lower()}") or {}
    return list(named.values()) if isinstance(named, dict) else named


def _covered(named, forms):
    """A table name some read form already answers: the form itself on any key (Hwei's
    Severing Bolt is read under W), its short name (Aphelios's `Calibrum, the Sniper
    Rifle`), or a numbered icon variant (`Emberstrike 2` is `{{ai|variant=2}}`, no page)."""
    base = re.sub(r" \d+$", "", named)
    return any(f in (named, base) or f.split(", ")[0] == named for f in forms)


def slot_coverage(rows, name, module_row, moved=None):
    """What was read per slot, and what is not. `moved` maps a form the table names to
    the page it redirects to: Shen's `Twilight Assault 2` is that page."""
    moved, out = moved or {}, {}
    every = [r["form"] for r in rows]
    for slot in "IQWER":
        read = [r["form"] for r in rows if r["slot"] == slot]
        unread = [f for f in _named(module_row, slot) if not _covered(moved.get(f, f), every)]
        gap = None
        if not read:
            gap = "no form read"
        elif unread:
            gap = "named by the wiki, no page read: " + ", ".join(unread)
        out[slot] = {"read": read, "gap": gap}
    return out


# ---- fetching


class WikiStopped(Exception):
    """A persistent 429: no more wiki requests this run."""


class Removed(Exception):
    """A 200 saying the page is not there."""


def _read(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


class Fetcher:
    """One request at a time, paced and counted. After a persistent 429 every wiki
    call stops at once; Data Dragon is another host and carries on."""

    def __init__(self):
        self.requests = 0
        self.stopped = None

    def json(self, url):
        last = None
        for _ in range(RETRIES):
            time.sleep(PAUSE)
            self.requests += 1
            try:
                return json.loads(_read(url))
            except HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code == 429:
                    ra = str(e.headers.get("Retry-After") or "0")
                    time.sleep(int(ra) if ra.isdigit() else 0)
                elif e.code < 500:
                    break
            except (URLError, TimeoutError, json.JSONDecodeError) as e:
                last = str(e)
        if last == "HTTP 429":
            raise WikiStopped(f"wiki stopped the run: {last}")
        raise OSError(f"{last} on {url}")

    def wiki(self, **params):
        if self.stopped:
            raise WikiStopped(self.stopped)
        try:
            out = self.json(API + "?" + urllib.parse.urlencode({"format": "json", **params}))
        except WikiStopped as e:
            self.stopped = str(e)
            raise
        if not isinstance(out, dict):
            raise ValueError("wiki answer is not an object")
        if "error" in out:
            if out["error"].get("code") == "missingtitle":
                raise Removed()
            raise ValueError(f"wiki error {out['error'].get('code')}")
        return out

    def _pages(self, titles, **params):
        """{asked title: page} for one batch, redirects followed. A missing page is None."""
        ask = "|".join(titles)
        out = self.wiki(action="query", redirects=1, titles=ask, **params)["query"]
        moved = {m["from"]: m["to"] for m in out.get("normalized", []) + out.get("redirects", [])}
        pages = {p["title"]: p for p in out.get("pages", {}).values()}
        found = {}
        for title in titles:
            real = title
            while real in moved:
                real = moved[real]
            page = pages.get(real, {})
            found[title] = None if "missing" in page or not page else page
        return found

    def revisions(self, titles):
        """{title: (final title, lastrevid)}, or None for a page not there."""
        out = {}
        for i in range(0, len(titles), BATCH):
            pages = self._pages(titles[i:i + BATCH], prop="info")
            out.update({t: p and (p["title"], p["lastrevid"]) for t, p in pages.items()})
        return out

    def contents(self, titles):
        """{title: wikitext}, batches of 50; a title not there is left out."""
        out = {}
        for i in range(0, len(titles), BATCH):
            pages = self._pages(titles[i:i + BATCH], prop="revisions", rvprop="ids|content", rvslots="main")
            for title, page in pages.items():
                if page:
                    out[title] = page["revisions"][0]["slots"]["main"]["*"]
        return out

    def render(self, title):
        return self.wiki(action="parse", page=title, prop="text", redirects=1)["parse"]["text"]["*"]


# ---- calculator rows


def _rank_row(rank, slot, k):
    row = {"rank": rank, "unknown": sorted(k["unknown"]), "unread": k["unread"]}
    cast = next((c for c in k["casts"] if c.name == slot), None)
    if cast:   # Vayne W has none: its numbers are in effects
        row.update(lines=cast.lines, cooldown=cast.cooldown, castTime=cast.cast_time, charges=cast.charges,
                   hard=cast.hard, soft=cast.soft)
    if k["effects"]:   # an infinite cooldown is the timeline's "once"; JSON has no Infinity
        row["effects"] = [{**e, "cooldown": None, "once": True} if e.get("cooldown") == math.inf else e
                          for e in k["effects"]]
    if k.get("estimated"):   # numbers read on STACKS typical: the page labels them, never "computed"
        row["estimated"] = sorted(k["estimated"])
        row["stacks"] = [dict(bt.STACKS[h]) for h in sorted(k["stacks"]) if h in bt.STACKS]
    return row


def calc_archetype(binj, arch, src):
    """`fight_for`'s inputs for one archetype, then `kit()` itself, one call per slot
    per rank with the other slots unlearned, so `unknown` belongs to that spell."""
    rec = bt._record(binj)
    melee = bt._base(rec, "attackRangeModifiable") < bt.MELEE_BELOW
    ids = bt.item_ids(arch)
    items = bt.item_stats(ids, src["catalog"], src["passives"], melee)
    bt.convert_stats(rec, items, ids, src["passives"])
    stats = bt.ref_stats(rec, items)
    by_rank, unknown = {}, set()
    for i, (slot, spell) in enumerate(zip("QWER", bt._spells(binj, rec))):
        if not spell:
            continue
        rows = []
        for rank in range(1, (bt.level_count(spell) or (3 if slot == "R" else 5)) + 1):
            ranks = tuple(rank if j == i else 0 for j in range(4))
            k = bt.kit(binj, src["strings"], ranks, stats, items["haste"], ranged=not melee,
                       target_hp=src["target"].hp)
            rows.append(_rank_row(rank, slot, k))
            unknown |= k["unknown"]
        by_rank[slot] = rows
    ranks = bt.ranks_for(arch, bt.rank_caps(bt._spells(binj, rec)))
    return {"context": {"level": bt.LEVEL, "archetype": arch["id"], "keystone": arch.get("keystone"),
                        "items": bt._names(ids, src["catalog"]), "haste": items["haste"],
                        "ranks": list(ranks) if ranks else None, "targetHp": src["target"].hp},
            "byRank": by_rank, "unknown": sorted(unknown)}


# ---- disagreement check: identified fields only, never a number search

_PLAIN_RUN = re.compile(r"(\d+(?:\.\d+)?(?: / \d+(?:\.\d+)?)*)(?: (mana|energy))?", re.I)
_NEAR = 0.01
_COMPARED = ("hp", "mp", "armor", "mr", "ad", "as")


def _compare(field, text, values, unit=False):
    out = {"field": field, "wiki": text, "state": "not comparable"}
    m = _PLAIN_RUN.fullmatch(text or "")
    if not m or bool(m.group(2)) != unit or not values or None in values:
        return out
    run = [float(x) for x in m.group(1).split(" / ")]
    if len(run) not in (1, len(values)):
        return out
    same = all(abs(a - b) < _NEAR for a, b in zip(run * len(values) if len(run) == 1 else run, values))
    return {**out, "bin": values, "state": "verified" if same else "differs"}


def ability_check(ability, spell, binj=None):
    """Cooldown against the calculator's wait (the recharge on a charge spell, else
    `Cooldown.values`, else `cooldownTime`, rank 1 at index 1), against the wiki's RECHARGE
    when it states one, else its cooldown; a passive with no cooldown
    field reads its `PassiveCooldown` (Zilean I). Cost against manaValues (rank 1 at index 0,
    also holds energy): the calculator reads no cost, and `mana` lags it on 11 spells.
    Range against the calculator's range reader, and against the wiki's TARGET RANGE when
    it states one (Hwei E, Lucian Q: RANGE there is another quantity)."""
    fields = {"cooldown": None, "cost": None, "range": None}
    if spell is not None:
        n = bt.level_count(spell) or 1
        cd = [bt.wait(spell, r) for r in range(1, n + 1)] if bt.cooldowns(spell) else []
        if not cd:
            cd = next(((d.get("values") or [])[1:n + 1] for d in spell.get("DataValues") or []
                       if d.get("name", "").lower() == "passivecooldown"), [])
        fields = {"cooldown": cd, "cost": ((spell.get("manaValues") or {}).get("values") or [])[:n],
                  "range": [bt.real_range(spell, r, binj) for r in range(1, n + 1)]}
        fields = {k: v if len(v) == n else None for k, v in fields.items()}
    wiki = ability.get("fields") or {}
    # a charge spell's wiki cooldown is the gap between charges; its RECHARGE is the wait
    return [_compare("cooldown", wiki.get("RECHARGE") or ability.get("cooldown"), fields["cooldown"]),
            _compare("cost", ability.get("cost"), fields["cost"], unit=True),
            _compare("range", wiki.get("TARGET RANGE") or ability.get("range"), fields["range"]),
            {"field": "damage", "state": "not comparable"}]


def bind_spells(abilities, binj, strings):
    """Each wiki form's bin spell, by display name, else by being its slot's only form.
    None means no identified spell, so nothing on that form can be verified."""
    spells = bt._spells(binj, bt._record(binj))

    def name_of(spell):
        key = (((spell.get("mClientData") or {}).get("mTooltipData") or {}).get("mLocKeys") or {}).get("keyName")
        return (strings.get(key.lower()) or "").lower() if key else ""

    named = {}
    for spell in [v["mSpell"] for v in binj.values() if isinstance(v, dict) and isinstance(v.get("mSpell"), dict)] + spells:
        full = name_of(spell)
        if full:   # a two-form spell reads `own form / other form` (all 44 on the roster)
            named[full] = named[full.split(" / ")[0]] = spell
    passive = bt.passive_spell(binj, bt._record(binj))
    if name_of(passive):   # the passive itself over a same-named sibling (Zilean's ZileanPassiveChannel)
        named[name_of(passive)] = passive
    slots = [a["slot"] for a in abilities]
    out = []
    for a in abilities:
        spell = named.get((a.get("name") or "").lower().removeprefix("transform "))
        if spell is None and a["slot"] in tuple("QWER") and slots.count(a["slot"]) == 1:
            spell = spells["QWER".index(a["slot"])] or None
        out.append(spell)
    return out


def calc_stats(rec):
    """Base stats as the calculator reads them, [base, per level], in the wiki's keys."""
    res = rec.get("primaryAbilityResource") or {}
    pair = lambda a, b, r=rec: [bt._base(r, a), bt._base(r, b)]  # noqa: E731
    # no arType, or Riot's 2 None and 14 Other (Bel'Veth's meter), means no bar (Viego's
    # 10000 is a placeholder); no base value means no number (Yasuo's flow), and `_base`
    # would turn that absence into 0
    has_bar = res.get("arType") not in (None, 2, 14) and "{726ee5cd}" in res
    bar = pair("{726ee5cd}", "{6216bf7b}", res) if has_bar else [None, None]
    return {"hp": pair("baseHPModifiable", "hpPerLevelModifiable"),
            "mp": bar,
            "armor": pair("baseArmorModifiable", "armorPerLevelModifiable"),
            "mr": pair("baseMR", "mrPerLevel"),
            "ad": pair("baseDamageModifiable", "damagePerLevelModifiable"),
            "as": pair("attackSpeedModifiable", "attackSpeedPerLevelModifiable"),
            "range": bt._base(rec, "attackRangeModifiable"), "ms": bt._base(rec, "baseMoveSpeedModifiable")}


def stats_check(wiki, calc):
    rows = []

    def one(field, a, b):
        state = "not comparable" if a is None or b is None else "verified" if abs(a - b) < _NEAR else "differs"
        rows.append({"field": field, "state": state, "wiki": a, "bin": b})

    for key in _COMPARED:
        for label, a, b in zip(("base", "lvl"), wiki.get(key) or (None, None), calc[key]):
            one(f"{key} {label}", a, b)
    one("range", wiki.get("range"), calc["range"])
    one("ms", wiki.get("ms"), calc["ms"])
    return rows


def _once(load):
    """A failed load stays failed for the run, so 173 champions do not each retry it."""
    got = []

    def call():
        if not got:
            try:
                got.append((load(), None))
            except (OSError, ValueError, KeyError) as e:
                got.append((None, e))
        if got[0][1]:
            raise got[0][1]
        return got[0][0]
    return call


def _calc_sources():
    return bt.load_all()


def _read_calc(row, champ, version, arch_store, sources):
    """Calc for every archetype of every mode, plus the two check columns that need the
    bin. `row`'s stats and abilities are filled in place, keeping one read of the bin."""
    src = sources()
    name = champ["n"]
    binj = src["bins"].get(name)
    if binj is None:
        raise ValueError("no game file")
    by = {}
    for mode in (arch_store.get("modes") or {}).values():
        for role, entry in (mode.get(name) or {}).items():
            for arch in entry.get("archetypes") or []:
                key = f"{role}/{arch['id']}"
                try:
                    by[key] = calc_archetype(binj, arch, src)
                except Exception as e:  # one archetype's odd bin never stops the bake
                    by[key] = {"error": repr(e)}
    mine = calc_stats(bt._record(binj))
    stats = (row.get("stats") or {}).get("value")
    if stats:
        stats.update(calculator=mine, check=stats_check(stats["wiki"], mine))
    forms = (row.get("abilities") or {}).get("value") or []
    for form, spell in zip(forms, bind_spells(forms, binj, src["strings"])):
        form["check"] = ability_check(form, spell, binj)
    unknown = sorted({u for a in by.values() for u in a.get("unknown", ())})
    return {"value": {"byArchetype": by, "unknown": unknown},
            "src": _src("calculator", bt.BIN_URL.format(c=champ["i"].lower()), version=arch_store.get("generation"),
                        patch=version)}


# ---- store


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _url(title):
    return PAGE + urllib.parse.quote(title.replace(" ", "_"), safe="/:")


def _src(name, url, **rest):
    return {"name": name, "url": url, "fetched": _now(), **rest}


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def _failed_part(old, err):
    """Last good value stays and says so; null only when it was never read."""
    if old and old.get("value") is not None:
        return {**old, "stale": True, "error": err}
    return {"value": None, "error": err, "src": None}


def _refresh(row, part, key, read):
    """Fetch one component when its key moved. Returns its error or None."""
    old = row.get(part)
    if old and old.get("key") == key and "error" not in old:
        return None
    try:
        row[part] = {**read(), "key": key}
        return None
    except Removed:
        err = "removed at source"
    except WikiStopped as e:
        err = str(e)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
        err = f"{type(e).__name__}: {e}"
    row[part] = _failed_part(old, err)
    return err


def _forms(page, home):
    """(template prefix, forms): the page's declared forms, then the five slots."""
    found = re.findall(r"\{\{Data ([^/|}]+)/([^|}]+)\|Ability", page)
    prefix = found[0][0] if found else home
    names = [f for p, f in found if p == prefix]
    return prefix, list(dict.fromkeys(names + list("IQWER")))


def _read_abilities(fetch, name, home, titles, revs, old, module_row, moved=None):
    """`titles` are the final template titles in page order, `revs` their revisions."""
    if not titles:
        raise ValueError("no ability forms on the champion page")
    was = {a["template"]: a for a in (old or {}).get("value") or []}
    was_revs = ((old or {}).get("src") or {}).get("revisions", {})
    same_parser = ((old or {}).get("key") or {}).get("parser") == PARSER
    rows = []
    for title in titles:
        if same_parser and title in was and was_revs.get(title) == revs[title]:
            rows.append(was[title])
            continue
        ability = read_ability(fetch.render(title))
        form = title.split("/", 1)[1]
        rows.append({**ability, "form": form, "template": title, "url": _url(title)})
    return {"value": rows, "slots": slot_coverage(rows, name, module_row, moved),
            "src": _src("wiki", _url(home), revisions=revs)}


def _bake_row(champ, version, row, fetch, ctx):
    """One champion. Returns its failures, part by part."""
    name, errors = champ["n"], {}
    module = ctx["module"] or {}
    module_rev = ctx["revs"].get(MODULE)
    module_row = module.get(name) if ctx["module"] is not None else None

    def note(part, err):
        if err:
            errors[part] = err

    def identity():
        if module_row is None:
            raise ValueError("no wiki row") if ctx["module"] is not None else OSError("wiki table not read")
        dd = fetch.json(DDRAGON.format(version=version, id=champ["i"]))["data"][champ["i"]]
        return {"value": {
            "title": module_row.get("title"), "tags": dd.get("tags"), "resource": module_row.get("resource"),
            "released": module_row.get("date"), "changes": module_row.get("changes"), "lore": dd.get("lore"),
            "allyTips": dd.get("allytips"), "enemyTips": dd.get("enemytips"),
            "partype": dd.get("partype"), "icons": _icons(dd),
        }, "src": _src("ddragon+wiki", _url(name), version=version, lastrevid=module_rev)}

    def stats():
        if module_row is None:
            raise ValueError("no wiki row")
        return {"value": {"wiki": wiki_stats(module_row)},
                "src": _src("wiki", _url(MODULE), lastrevid=module_rev)}

    note("identity", _refresh(row, "identity", {"dd": version, "rev": module_rev, "parser": PARSER}, identity))
    note("stats", _refresh(row, "stats", {"rev": module_rev, "parser": PARSER}, stats))

    page_info = ctx["revs"].get(name)
    titles = ctx["forms"].get(name, [])
    form_revs = {t: ctx["revs"][t] for t in titles if ctx["revs"].get(t)}

    def abilities():
        if page_info is None:
            raise Removed()
        if name in ctx["page_errors"]:
            raise ctx["page_errors"][name]
        return _read_abilities(fetch, name, page_info[0], titles, form_revs, row.get("abilities"), module_row or {},
                               ctx.get("moved", {}).get(name))

    key = {"page": page_info and page_info[1], "forms": form_revs, "parser": PARSER}
    note("abilities", _refresh(row, "abilities", key, abilities))

    hist = f"{name}/Patch history"
    hist_info = ctx["revs"].get(hist)

    def history():
        if hist_info is None and hist in ctx["revs"]:
            raise Removed()
        if hist in ctx["history_error"]:
            raise ctx["history_error"][hist]
        return {"value": read_history(ctx["history"][hist]),
                "src": _src("wiki", _url(hist_info[0]), lastrevid=hist_info[1])}

    note("history", _refresh(row, "history", {"rev": hist_info and hist_info[1], "parser": PARSER}, history))
    arch = ctx.get("archetypes") or {}
    key = {"dd": version, "generation": arch.get("generation"), "parser": PARSER, "engine": ENGINE,
           # when each was read, not only its key: a re-read after a failure drops the calc columns
           **{p: [(row.get(p) or {}).get("key"), ((row.get(p) or {}).get("src") or {}).get("fetched")]
              for p in ("stats", "abilities")}}
    note("calc", _refresh(row, "calc", key, lambda: _read_calc(row, champ, version, arch, ctx["calc_sources"])))
    return errors


def _icons(dd):
    return {"spells": [s["image"]["full"] for s in dd.get("spells", [])],
            "passive": (dd.get("passive") or {}).get("image", {}).get("full")}


def _gather(names, rows, fetch):
    """Everything that batches: revisions, the table, champion pages, histories. A
    failure here lands on the components that needed it, not on the run."""
    ctx = {"module": None, "revs": {}, "forms": {}, "history": {}, "history_error": {}, "page_errors": {}, "moved": {}}
    hist = {n: f"{n}/Patch history" for n in names}
    ctx["revs"] = fetch.revisions([MODULE] + names + list(hist.values()))
    stale = lambda row, part, key: (row.get(part) or {}).get("key", {}).get(key)  # noqa: E731
    text = fetch.contents([MODULE])
    ctx["module"] = read_module(text[MODULE])
    ctx["revs"][MODULE] = ctx["revs"][MODULE] and ctx["revs"][MODULE][1]
    pages = [n for n in names if ctx["revs"].get(n)]
    want_hist = [
        t for n, t in hist.items() if ctx["revs"].get(t)
        and (stale(rows.get(n, {}), "history", "rev") != ctx["revs"][t][1]
             or stale(rows.get(n, {}), "history", "parser") != PARSER
             or "error" in (rows.get(n, {}).get("history") or {}))
    ]
    fresh = [n for n in pages if stale(rows.get(n, {}), "abilities", "page") != ctx["revs"][n][1]
             or stale(rows.get(n, {}), "abilities", "parser") != PARSER
             or "error" in (rows.get(n, {}).get("abilities") or {})]
    try:
        ctx["history"] = fetch.contents(want_hist)
        for t in want_hist:
            ctx["history"].get(t) or ctx["history_error"].setdefault(t, OSError("history page empty"))
    except (WikiStopped, OSError, ValueError, KeyError) as e:
        ctx["history_error"] = {t: e for t in want_hist}
    try:
        got = fetch.contents(fresh)
    except (WikiStopped, OSError, ValueError, KeyError) as e:
        got, ctx["page_errors"] = {}, {n: e for n in fresh}
    templates, asked = {}, {}
    for n in pages:
        src = (rows.get(n, {}).get("abilities") or {}).get("value") or []
        if n in got:
            prefix, forms = _forms(got[n], ctx["revs"][n][0])
            templates[n] = [f"Template:Data {prefix}/{f}" for f in forms]
        else:
            templates[n] = [a["template"] for a in src]
            prefix = templates[n][0].split("/")[0].removeprefix("Template:Data ") if src else n
        # the table's forms too: most redirect to a form read, a real page gets read
        asked[n] = {f: f"Template:Data {prefix}/{f}" for s in "IQWER" for f in _named(ctx["module"].get(n) or {}, s)}
        templates[n] += asked[n].values()
    all_forms = [t for ts in templates.values() for t in ts]
    try:
        form_revs = fetch.revisions(all_forms) if all_forms else {}
    except (WikiStopped, OSError, ValueError, KeyError) as e:
        form_revs, ctx["page_errors"] = {}, {**ctx["page_errors"], **{n: e for n in pages}}
    for n, ts in templates.items():
        final = {}
        for t in ts:
            if form_revs.get(t):
                final.setdefault(form_revs[t][0], form_revs[t][1])
        ctx["forms"][n] = list(final)
        ctx["revs"].update(final)
        ctx["moved"][n] = {f: form_revs[t][0].split("/", 1)[1] for f, t in asked[n].items() if form_revs.get(t)}
    return ctx


def _publish(store, names):
    """Over 5% of this run's champions failed, or no row at all: nothing goes live."""
    if not store["champions"]:
        return "no rows"
    bad = sum(n in store["failed"] and not all(
        (store["champions"][n].get(p) or {}).get("value") is not None
        for p in PARTS
    ) or n in store["failed"] and "wiki stopped" not in " ".join(store["failed"][n].values())
        for n in names)
    if bad > MAX_FAILED * len(names):
        return f"{bad} of {len(names)} champions failed"
    _write(OUT, store)
    WORK.unlink(missing_ok=True)
    return None


def _lock():
    try:
        os.kill(int(LOCK.read_text()), 0)
        return False
    except PermissionError:  # alive, owned by another user
        return False
    except (OSError, ValueError):
        pass
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()))
    return True


def run(champs, version, only=None):
    if not _lock():
        print("another champion bake is running", file=sys.stderr)
        return 3
    try:
        return _bake(champs, version, only)
    finally:
        LOCK.unlink(missing_ok=True)


def _bake(champs, version, only):
    base = _load(WORK) or _load(OUT) or {}
    store = {"parser": PARSER, "fetched": _now(), "champions": base.get("champions", {}),
             "failed": base.get("failed", {}), "patchDates": base.get("patchDates", {})}
    todo = [c for c in champs if not only or c["n"] in only]
    names = [c["n"] for c in todo]
    fetch = Fetcher()
    rows = store["champions"]
    try:
        ctx = _gather(names, rows, fetch)
    except (WikiStopped, OSError, ValueError, KeyError) as e:
        print(f"wiki table not read: {e}", file=sys.stderr)
        if not rows:
            return 1
        ctx = {"module": None, "revs": {}, "forms": {}, "history": {}, "history_error": {}, "page_errors": {}}
        ctx["failed"] = str(e)
    ctx.update(archetypes=_load(ARCHETYPES), calc_sources=_once(_calc_sources))
    try:
        store["patchDates"] = fetch_patch_dates(fetch) or store["patchDates"]
    except (WikiStopped, OSError, ValueError, KeyError) as e:   # last good dates stay
        print(f"patch dates not read: {e}", file=sys.stderr)
    _write(WORK, store)
    saved = time.monotonic()
    try:
        for champ in todo:
            name = champ["n"]
            row = rows.setdefault(name, {})
            errors = _bake_row(champ, version, row, fetch, ctx)
            store["failed"].pop(name, None)
            if errors:
                store["failed"][name] = errors
            store["requests"] = fetch.requests
            if time.monotonic() - saved > CHECKPOINT:   # the store is 14 MB: not after every champion
                _write(WORK, store)
                saved = time.monotonic()
    finally:
        _write(WORK, store)   # ponytail: a SIGKILL loses at most CHECKPOINT seconds of rows
    store["generation"] = f"{version}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    _report(store, names)
    problem = _publish(store, names)
    if problem:
        print(f"not published: {problem}", file=sys.stderr)
        return 1
    return 0


def _report(store, names):
    rows = [store["champions"][n] for n in names]
    print(f"{len(rows)} champions, {store.get('requests', 0)} requests, {len(store['failed'])} failed")
    for part in PARTS:
        read = sum((r.get(part) or {}).get("value") is not None for r in rows)
        stale = sum(bool((r.get(part) or {}).get("stale")) for r in rows)
        print(f"  {part}: {read} read, {stale} stale")
    checks = [c for r in rows for c in ((r.get("stats") or {}).get("value") or {}).get("check", [])]
    checks += [c for r in rows for a in (r.get("abilities") or {}).get("value") or [] for c in a.get("check", [])]
    print("  check:", {s: sum(c["state"] == s for c in checks) for s in ("verified", "differs", "not comparable")})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--champ", action="append", help="champion display name; repeatable")
    args = ap.parse_args()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    missing = set(args.champ or ()) - {c["n"] for c in catalog["champs"]}
    if missing:
        sys.exit(f"not in the catalog: {sorted(missing)}")
    return run(catalog["champs"], catalog["ver"], args.champ)


if __name__ == "__main__":
    sys.exit(main())

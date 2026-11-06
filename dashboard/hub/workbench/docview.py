"""Spec and plan docs as a glance card plus folding sections (Workbench pick
'Glance spec, diff plan with step notes', 2026-10-15).

Spec: goal and change counts on top, every ## section folds to a one-line
summary; Files and Explicitly not built render as +/~/- change rows.
Plan: goal, task count and size bar on top, the header sections fold, and
each ### Task is a diff hunk: file lines, a visible 'how' line, every step
folding to its first sentence.

A section's summary is its leading `Summary:` line when the author wrote one,
else its first sentence. Anything this cannot parse falls back to plain
Markdown, so an odd doc reads the way it did before.
"""

from __future__ import annotations

import html
import re

import markdown

_EXT = ["tables", "fenced_code"]
e = html.escape

GLYPH = {"add": "+", "edit": "~", "del": "−", "test": "✓"}
WORD = {"add": "new", "edit": "edit", "del": "cut", "test": "test"}
_VERB = [
    ("del", ("delete", "remove", "drop")),
    ("add", ("create", "add", "new")),
    ("test", ("test",)),
]
_SUMMARY_RE = re.compile(r"^\s*(?:\*\*)?Summary:(?:\*\*)?\s*(.+)$", re.M)
_TASK_RE = re.compile(r"^Task (\d+):\s*(.+?)(?:\s+~(\d+)k)?\s*$")


def md(text: str) -> str:
    # a list straight after a paragraph needs a blank line for Python-Markdown; checkboxes read as plain steps
    text = re.sub(r"(?m)^(\s*)- \[[ xX]\] ", r"\1- ", text)
    text = re.sub(r"(?m)^(?!\s*(?:[-*]\s|\d+\.\s|\|)).+\n(?=\s*- )", lambda m: m.group(0) + "\n", text)
    return markdown.markdown(text, extensions=_EXT)


def md_inline(text: str) -> str:
    out = md(text).strip()
    return out[3:-4] if out.startswith("<p>") and out.endswith("</p>") and out.count("<p>") == 1 else out


def split(text: str, level: int):
    """(preamble, [(heading, body)]) at one heading level, ignoring fenced code."""
    marker = "#" * level + " "
    pre, parts, cur, fence = [], [], None, False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        if not fence and line.startswith(marker):
            cur = [line[len(marker):].strip(), []]
            parts.append(cur)
        elif cur is None:
            pre.append(line)
        else:
            cur[1].append(line)
    return "\n".join(pre).strip(), [(h, "\n".join(b).strip()) for h, b in parts]


def plain(text: str) -> str:
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"^\s*(#+|[-*]|\d+\.|\|)\s*", "", t, flags=re.M)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)|\[\[([^\]|]*)(?:\|[^\]]*)?\]\]", lambda m: m.group(1) or m.group(2) or "", t)
    return re.sub(r"\s+", " ", re.sub(r"[`*]", "", t)).strip()


_TAG_RE = re.compile(r"^(?:Sam|from disk|waived by Sam)\s*[:.\u2014-]\s*", re.I)


def gist(text: str, cap: int = 150) -> str:
    """First sentence of the first prose paragraph (tables, code, headings and a leading **Date:** skipped), clipped."""
    paras = [q for q in re.split(r"\n\s*\n", re.sub(r"```.*?```", "", text, flags=re.S)) if q.strip()]
    prose = [q for q in paras if not q.lstrip().startswith(("|", "#"))]
    p = _TAG_RE.sub("", plain(re.sub(r"^\*\*Date:\*\*[^.]*\.\s*", "", (prose or paras or [""])[0].strip())))
    s = re.split(r"(?<=[.!?])\s", p, maxsplit=1)[0].rstrip(";:.")
    return s if len(s) <= cap else s[: cap - 1].rsplit(" ", 1)[0] + "…"


def take_summary(body: str):
    """(summary or None, body without the Summary line)."""
    m = _SUMMARY_RE.search(body)
    if not m or body[: m.start()].strip():
        return None, body
    return plain(m.group(1)), body[m.end():].strip()


def change_kind(line: str) -> str:
    word = plain(line).split(" ", 1)[0].lower()
    for kind, verbs in _VERB:
        if word.startswith(verbs):
            return kind
    return "edit"


def bullets(body: str):
    return [l[2:].strip() for l in body.splitlines() if l.startswith(("- ", "* "))]


def chip(label, kind=""):
    return f'<span class="dv-chip{" is-" + kind if kind else ""}">{e(str(label))}</span>'


def change_row(kind, inner_html, note_html=""):
    note = f'<span class="dv-note">{note_html}</span>' if note_html else ""
    return (f'<li class="dv-ch is-{kind}"><span class="dv-g" aria-hidden="true">{GLYPH[kind]}</span>'
            f'<span class="dv-w">{WORD[kind]}</span><span class="dv-t">{inner_html}</span>{note}</li>')


def files_rows(body: str):
    rows, counts = [], {"add": 0, "edit": 0, "del": 0, "test": 0}
    for b in bullets(body):
        k = change_kind(b)
        counts[k] += 1
        # the verb is shown as the tag, so drop it (and a '(rewrite)' after it) from the row text
        rest = re.sub(r"^(?:create|add|new|edit|change|rename|move|update|delete|remove|drop|test)\w*\s*(?:\([^()]*\)\s*)?", "", b, count=1, flags=re.I) or b
        m = re.match(r"(.*?)\s*\(([^()]*)\)\s*$", rest)
        main, note = (m.group(1), m.group(2)) if m and m.group(1) else (rest, "")
        rows.append(change_row(k, md_inline(main), md_inline(note) if note else ""))
    return rows, counts


def cut_rows(body: str):
    out = []
    for b in bullets(body):
        what, sep, why = b.partition(": ")
        if not sep:
            what, sep, why = b.partition(". ")
        out.append(change_row("del", md_inline(what), md_inline(why) if why else ""))
    return out


def ul(rows):
    return '<ul class="dv-changes">' + "".join(rows) + "</ul>"


def stat_chips(c):
    return "".join(chip(f"{GLYPH[k]}{c[k]}", k) for k in ("add", "edit", "del") if c.get(k)) or ""


def fold(name, summary, chips_html, body_html, open_=False):
    return (f'<details class="dva-fold"{" open" if open_ else ""}><summary><span class="dva-n">{e(name)}</span>'
            f'<span class="dva-s">{e(summary)}</span><span class="dva-c">{chips_html}</span></summary>'
            f'<div class="dva-body">{body_html}</div></details>')


def meta_line(pre: str, skip=()):
    items = []
    for k, v in re.findall(r"^\*\*([^*:]+):\*\*\s*(.+)$", pre, re.M):
        if k.strip().lower() not in skip:
            items.append(f'<span><b>{e(k.strip())}</b> {md_inline(v)}</span>')
    return f'<p class="dv-meta">{"".join(items)}</p>' if items else ""


def wb(body_html):
    return f'<div class="wb-doc">{body_html}</div>'


# ── spec ────────────────────────────────────────────────────────────────


def render_spec(text: str) -> str | None:
    pre, sections = split(text, 2)
    if len(sections) < 2:
        return None
    folds, total = [], {"add": 0, "edit": 0, "del": 0, "test": 0}
    stats, goal = [], None
    for name, body in sections:
        summary, body = take_summary(body)
        low = name.lower()
        chips_html, open_ = "", False
        if low == "files" and bullets(body):
            rows, c = files_rows(body)
            for k in total:
                total[k] += c[k]
            lead = re.split(r"(?m)^[-*] ", body, maxsplit=1)[0].strip()
            body_html = (wb(md(lead)) if lead else "") + ul(rows)
            chips_html = stat_chips(c)
            summary = summary or ", ".join(f"{c[k]} {w}" for k, w in (("add", "new"), ("edit", "edited"), ("del", "removed")) if c[k]) or gist(body)
            open_ = True
        elif low.startswith("explicitly not built") and bullets(body):
            rows = cut_rows(body)
            body_html = ul(rows)
            chips_html = chip(f"{len(rows)} cut", "del")
            stats.append(chip(f"{len(rows)} not built"))
        else:
            if low == "interview":
                _, topics = split(body, 3)
                g = next((b for h, b in topics if h.lower() == "goal"), None)
                goal = gist(g, 240) if g else None
                if topics:
                    chips_html = chip(f"{len(topics)} topics")
                    tags = [b.lstrip().lower() for _, b in topics]
                    n_b = sum(t.startswith("sam") for t in tags)
                    n_d = sum(t.startswith("from disk") for t in tags)
                    summary = summary or f"{len(topics)} topics" + (f": {n_b} from Sam, {n_d} from disk" if n_b + n_d else "")
            elif low == "check":
                n = len(re.findall(r"(?m)^\d+\. ", body))
                if n:
                    chips_html = chip(n)
                    stats.append(chip(f"{n} checks"))
            elif low.startswith("failure modes"):
                n = max(0, len(re.findall(r"(?m)^\|", body)) - 2)
                if n:
                    chips_html = chip(n)
                    stats.append(chip(f"{n} failure modes"))
                    summary = summary or (gist(body) if not body.lstrip().startswith("|") else f"{n} failure modes, each with its posture")
            body_html = wb(md(body))
        folds.append(fold(name, summary or gist(body), chips_html, body_html, open_))
    title_free = re.sub(r"(?m)^# .*$", "", pre)
    goal = goal or next((gist(p, 240) for p in re.split(r"\n\s*\n", title_free) if p.strip() and not p.lstrip().startswith("**")), None)
    goal = goal[:1].upper() + goal[1:] if goal else goal
    change = "".join(chip(f"{GLYPH[k]}{total[k]} {w}", k) for k, w in (("add", "new"), ("edit", "edited"), ("del", "removed")) if total[k])
    glance = (f'<div class="dva-glance">{f"<p class=dva-goal>{e(goal)}</p>" if goal else ""}'
              f'<div class="dva-stats">{change}{"".join(stats)}</div>{meta_line(title_free)}</div>')
    return f'<div class="dv dva">{glance}<div class="dva-list">{"".join(folds)}</div></div>'


# ── plan ────────────────────────────────────────────────────────────────


def task_files(body: str):
    m = re.search(r"(?m)^\*\*Files:\*\*\s*\n((?:[ \t]*- .+\n?)+)", body)
    if not m:
        return [], body
    out = []
    for line in m.group(1).splitlines():
        low = plain(line).lower()
        kind = "del" if low.startswith(("delete", "remove")) else "add" if low.startswith("create") else "test" if low.startswith("test") else "edit"
        paths = re.findall(r"`([^`]+)`", line) or [re.sub(r"^\W*\w+:?\s*", "", plain(line))]
        out += [(kind, p) for p in paths]
    return out, body[: m.start()] + body[m.end():]


def task_steps(body: str):
    """[(label, gist, full markdown)] for each '- [ ] **Step ...**' block; rest is the prose around them."""
    blocks = re.split(r"(?m)^- \[[ xX]\] ", body)
    steps = []
    for blk in blocks[1:]:
        m = re.match(r"\*\*(.+?)\*\*\s*(.*)", blk, re.S)
        if m:
            label, rest = m.group(1).strip(" :."), m.group(2).strip()
        else:
            label, rest = "", blk.strip()
        steps.append((label, gist(rest, 130) if rest else "", rest))
    return steps, blocks[0].strip()


def diffstat(c):
    blocks = "".join(f'<i class="is-{k}"></i>' for k in ("add", "edit", "del") for _ in range(min(c[k], 12)))
    nums = "".join(f'<span class="dve-n is-{k}">{GLYPH[k]}{c[k]}</span>' for k in ("add", "edit", "del") if c[k])
    return f'{nums}<span class="dve-blk">{blocks}</span>'


def hunk(t, open_):
    c = {"add": 0, "edit": 0, "del": 0}
    for k, _ in t["files"]:
        if k in c:
            c[k] += 1
    stat = diffstat(c) if any(c.values()) else '<span class="dve-plain">no file changes</span>'
    lines = "".join(f'<div class="dve-l is-{k}"><span>{GLYPH[k]}</span><code>{e(p)}</code></div>' for k, p in t["files"])
    steps = "".join(
        f'<details class="dvx-step"><summary><span class="dvx-sn">{i + 1}</span><b>{e(l or f"Step {i + 1}")}</b><span class="dvx-sg">{e(g)}</span></summary>'
        f'<div class="dvx-sb wb-doc">{md(r)}</div></details>' for i, (l, g, r) in enumerate(t["steps"]))
    prose = wb(md(t["prose"])) if t["prose"] else ""
    size = f'  ~{t["k"]}k' if t["k"] else ""
    how = f'<span class="dvx-how">{e(t["how"])}</span>' if t["how"] else ""
    return (f'<details class="dve-h"{" open" if open_ else ""}><summary><span class="dve-car">▸</span>'
            f'<span class="dve-t">Task {t["n"]}  {e(t["name"])}{size}</span><span class="dve-st">{stat}</span>{how}</summary>'
            f'<div class="dve-b">{lines}{prose}{f"<div class=dvx-steps>{steps}</div>" if steps else ""}</div></details>')


def render_plan(text: str) -> str | None:
    pre, sections = split(text, 2)
    tasks, folds = [], []
    for name, body in sections:
        lead, subs = split(body, 3)
        mine = [(h, b) for h, b in subs if _TASK_RE.match(h)]
        if not mine:
            summary, body = take_summary(body)
            folds.append(fold(name, summary or gist(body), "", wb(md(body))))
            continue
        # ### blocks before the first task belong with the section's lead; after it, with the task above
        first = next(i for i, (h, _) in enumerate(subs) if _TASK_RE.match(h))
        lead = "\n\n".join([lead] + [f"### {h}\n\n{b}" for h, b in subs[:first]]).strip()
        if lead:
            summary, lead = take_summary(lead)
            folds.append(fold(name, summary or gist(lead), "", wb(md(lead))))
        for h, b in subs[first:]:
            m = _TASK_RE.match(h)
            if not m:
                tasks[-1]["prose"] += f"\n\n### {h}\n\n{b}"
                continue
            summary, b = take_summary(b)
            files, b = task_files(b)
            steps, prose = task_steps(b)
            # no Summary line: prose that isn't just the Interfaces block, else the step labels
            how = summary or (gist(prose, 170) if plain(prose) and not prose.lstrip().startswith("**Interfaces") else
                              " · ".join(l for l, _, _ in steps if l))
            tasks.append(dict(n=int(m.group(1)), name=m.group(2).strip(), k=int(m.group(3) or 0),
                              files=files, steps=steps, prose=prose, how=how))
    if not tasks:
        return None
    goal_m = re.search(r"^\*\*Goal:\*\*\s*(.+)$", pre, re.M)
    goal = gist(goal_m.group(1), 260) if goal_m else None
    goal = goal[:1].upper() + goal[1:] if goal else goal
    total = sum(t["k"] for t in tasks)
    runs = re.search(r"\*\*Runs as:\*\*\s*(\w+)", pre)
    c = {"add": 0, "edit": 0, "del": 0}
    for t in tasks:
        for k, _ in t["files"]:
            if k in c:
                c[k] += 1
    bar = "".join(f'<span class="dv-seg" style="flex:{t["k"]}" title="Task {t["n"]}"><b>{t["n"]}</b></span>' for t in tasks) if total and all(t["k"] for t in tasks) else ""
    stats = (chip(f"{len(tasks)} tasks") + (chip(f"~{total}k") if total else "") + (chip(f"runs as {runs.group(1)}") if runs else "")
             + "".join(chip(f"{GLYPH[k]}{c[k]} {w}", k) for k, w in (("add", "new"), ("edit", "edited"), ("del", "removed")) if c[k]))
    title_free = re.sub(r"(?m)^# .*$", "", pre)
    arch = re.search(r"^\*\*Architecture:\*\*\s*(.+)$", pre, re.M)
    head_fold = fold("Architecture", gist(arch.group(1)), "", wb(md(arch.group(1)))) if arch else ""
    glance = (f'<div class="dva-glance">{f"<p class=dva-goal>{e(goal)}</p>" if goal else ""}<div class="dva-stats">{stats}</div>'
              f'{meta_line(title_free, skip=("goal", "architecture", "runs as"))}{f"<div class=dv-bar>{bar}</div>" if bar else ""}</div>')
    hunks = "".join(hunk(t, i < 2) for i, t in enumerate(tasks))
    return f'<div class="dv dva dve">{glance}<div class="dva-list">{head_fold}{"".join(folds)}</div>{hunks}</div>'


def render(text: str, kind: str) -> str | None:
    """Layout HTML for a spec or plan, or None to fall back to plain Markdown."""
    try:
        return render_plan(text) if kind == "plan" else render_spec(text)
    except Exception:  # ponytail: a parse slip must never blank a doc; plain Markdown is the floor
        return None

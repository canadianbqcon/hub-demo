"""Mark mode CLI: the /marks skill's only door into data/marks/.

  list [--open]                 sessions and marks as JSON (--open drops fixed marks)
  show <session> <n>            one mark as JSON, with absolute PNG paths
  aftershot <session> <n> [--click SEL]
                                re-render the mark's url/viewport/scroll into NN-after.png, cut to the before crop's frame;
                                --click opens a view the page keeps in memory first (a mark over a Hub PDF picks its own)
  set <session> <n> <status> [--note TEXT]
                                open | fixing | fixed; --note says what changed (Workbench walk-through)
  doc <session> <n>             for a mark over a PDF in the Hub (jobs resume or cover letter viewer): the
                                file, its editable .html source, the page, and the text under the mark
  close <session> <n>           record his close in the ledger, delete the mark's PNGs and entry; exit 1 naming any file that stuck
  wait <session> <n>...         block until each of these fixed marks has his Workbench answer, then print
                                {"closed": [n...], "sent_back": [{n, comment, reply}...]}
  watch [--skip SESSION:N ...]  block until any mark, in any session, is open or sent back, then print
                                [{session, n, status, comment, reply, options}...]; the /marks cycle's wake-up
                                (options true: his Make options click, run /workbench in its own tab)

Nothing else deletes marks. Design: docs/specs/2026-10-12-hub-mark-mode-design.md §5.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from marks import render, store  # noqa: E402

STATUSES = ("open", "fixing", "fixed")


def _with_paths(session, mark):
    folder = store.marks_root() / session
    out = dict(mark, session=session)
    for kind in ("crop", "full", "after"):
        p = folder / f"{mark['n']:02d}-{kind}.png"
        out[kind] = str(p) if p.exists() else None
    return out


def _mark(session, n):
    for m in store.load(session)["marks"]:
        if m["n"] == n:
            return m
    raise KeyError(f"no mark {n} in {session}")


def wait(session, ns, poll=10, root=None):
    """Block until none of marks `ns` (the ones put on the walk-through) is
    still `fixed` (Close removes the mark, Send back flips it to `fixing` with
    a reply), then report both. Taking ns, not a snapshot of what is fixed when
    the wait starts, keeps an answer clicked before the wait began. A session
    folder gone entirely means every mark was closed."""
    def marks():
        try:
            return store.load(session, root)["marks"]
        except FileNotFoundError:
            return []
    start = set(ns)
    while True:
        now = marks()
        if not any(m["n"] in start and m.get("status") == "fixed" for m in now):
            break
        time.sleep(poll)
    left = {m["n"]: m for m in now}
    return {
        "closed": sorted(n for n in start if n not in left),
        "sent_back": [{"n": n, "comment": left[n].get("comment"), "reply": left[n].get("reply")}
                      for n in sorted(start) if n in left and left[n].get("reply")],
    }


def watch(skip=(), poll=10, root=None):
    """Block until some mark needs Claude: a new one (`open`) or one he sent
    back (`fixing` with his reply). `skip` holds SESSION:N marks another tab owns
    (an option set); a skip holds only while the mark is as it was when the watch
    started, so his next send-back on it still wakes the watch. A mark set aside
    for him is answered on the mark instead (`set ... fixing --note`), which clears
    his reply; 2026-11-03, two skipped marks sat unanswered on his side for hours."""
    held = {}
    while True:
        due = []
        for s in store.list_sessions(open_only=True, root=root):
            for m in s["marks"]:
                key = f'{s["session"]}:{m["n"]}'
                state = (m.get("status"), m.get("reply"), m.get("options"))
                if key in skip and held.setdefault(key, state) == state:   # first poll fixes what "as it was" means
                    continue
                if not (m.get("status") == "open" or (m.get("status") == "fixing" and m.get("reply"))):
                    continue
                due.append({"session": s["session"], "n": m["n"], "status": m.get("status"),
                            "comment": m.get("comment"), "reply": m.get("reply"), "options": bool(m.get("options"))})
        if due:
            return due
        time.sleep(poll)


_PDF_TAG = re.compile(r'data-pdf="([^"]+)"[^>]*?data-page="(\d+)"')
_RESUME_VIEW = re.compile(r"^/jobs/api/resumes/(\d+)/view$")


def _resume_file(url, root=None):
    """The vault file behind a jobs viewer URL, read from data/jobs.db; None for any other URL."""
    m = _RESUME_VIEW.match(url)
    if not m:
        return None
    vault = Path(root) if root else store.vault_root()
    con = sqlite3.connect(f"file:{vault / 'data' / 'jobs.db'}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT file_path FROM resumes WHERE id = ?", (int(m.group(1)),)).fetchone()
    finally:
        con.close()
    return vault / row[0] if row else None


def doc(mark, resolve=_resume_file):
    """Where a mark over a pdf.js page lands in the document. The viewer tags each page
    canvas with data-pdf and data-page (jobs-surfaces-a.jsx renderPdf); the mark's rect,
    taken as a share of that canvas's rect, is the same share of the PDF page.
    None when the mark is not over a tagged PDF page.
    A passage mark (kind "doc", from the resume pop-out) names the file and page itself and
    its text is the quote he highlighted."""
    d = mark.get("doc")
    if isinstance(d, dict) and d.get("pdf"):
        pdf = resolve(d["pdf"])
        ok = bool(pdf and pdf.exists())
        html = pdf.with_suffix(".html") if ok else None
        return {"url": d["pdf"], "page": d.get("page"), "share": None, "pdf": str(pdf) if ok else None,
                "html": str(html) if html and html.exists() else None, "text": mark.get("quote")}
    for e in mark.get("elements") or []:
        t = _PDF_TAG.search(e.get("html") or "")
        b = e.get("rect") or {}
        if not t or not b.get("w") or not b.get("h"):
            continue
        r = mark["rect"]
        share = lambda v, o, n: min(1.0, max(0.0, (v - o) / n))  # noqa: E731
        box = (share(r["x"], b["x"], b["w"]), share(r["y"], b["y"], b["h"]),
               share(r["x"] + r["w"], b["x"], b["w"]), share(r["y"] + r["h"], b["y"], b["h"]))
        out = {"url": t.group(1), "page": int(t.group(2)), "share": [round(v, 4) for v in box],
               "pdf": None, "html": None, "text": None}
        pdf = resolve(t.group(1))
        if pdf and pdf.exists():
            import fitz
            out["pdf"] = str(pdf)
            html = pdf.with_suffix(".html")
            out["html"] = str(html) if html.exists() else None
            with fitz.open(pdf) as d:
                pg = d[min(out["page"], len(d)) - 1]
                W, H = pg.rect.width, pg.rect.height
                clip = fitz.Rect(box[0] * W, box[1] * H, box[2] * W, box[3] * H)
                # whole lines the mark touches: a clip cuts glyphs at its edge, and a whole line is what
                # gets searched for in the .html source
                lines = {}
                for w in pg.get_text("words"):
                    if fitz.Rect(w[:4]).intersects(clip):
                        lines.setdefault((w[5], w[6]), [])
                for w in pg.get_text("words"):
                    if (w[5], w[6]) in lines:
                        lines[(w[5], w[6])].append(w[4])
                out["text"] = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
        return out
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="marks")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").add_argument("--open", action="store_true")
    for name in ("show", "aftershot", "close", "doc"):
        p = sub.add_parser(name)
        p.add_argument("session")
        p.add_argument("n", type=int)
        if name == "aftershot":
            # marks saved before the look was recorded: say which theme and surface he was on
            p.add_argument("--theme")
            p.add_argument("--surface")
            p.add_argument("--click")
    p = sub.add_parser("set")
    p.add_argument("session")
    p.add_argument("n", type=int)
    p.add_argument("status", choices=STATUSES)
    p.add_argument("--note")
    p = sub.add_parser("wait")
    p.add_argument("session")
    p.add_argument("n", type=int, nargs="+")
    # extend: "--skip a --skip b" keeps both (plain nargs kept only the last, so a skipped mark woke the watch)
    sub.add_parser("watch").add_argument("--skip", nargs="*", action="extend", default=[])
    a = ap.parse_args(argv)

    if a.cmd == "list":
        out = [dict(s, marks=[_with_paths(s["session"], m) for m in s["marks"]])
               for s in store.list_sessions(open_only=a.open)]
        print(json.dumps(out, indent=2))
        return 0
    if a.cmd == "show":
        print(json.dumps(_with_paths(a.session, _mark(a.session, a.n)), indent=2))
        return 0
    if a.cmd == "doc":
        out = doc(_mark(a.session, a.n))
        if out is None:
            print("not over a PDF page in the Hub", file=sys.stderr)
            return 1
        print(json.dumps(out, indent=2))
        return 0
    if a.cmd == "aftershot":
        m = _mark(a.session, a.n)
        look = dict(m.get("look") or {}, **{k: v for k, v in (("theme", a.theme), ("surface", a.surface)) if v})
        shot = render.shoot(m["url"], m["viewport"], m.get("scroll") or {"x": 0, "y": 0}, m["rect"], look=look, store=m.get("store"),
                            highlight=False, click=a.click or render.view_click(m))
        if shot is None:
            print("aftershot failed: render returned nothing (Hub down, Chrome missing or a /login landing)",
                  file=sys.stderr)
            return 1
        store.save_after(a.session, a.n, shot[1])
        print(_with_paths(a.session, _mark(a.session, a.n))["after"])
        return 0
    if a.cmd == "set":
        # a fresh fix clears the last send-back's reply so the walk-through asks again; the reply moves to
        # `answered`, the words this fix answers, which the walk-through shows as what he said
        extra = {}
        if a.note:
            m = _mark(a.session, a.n)
            extra = {"fix_note": a.note, "reply": None, "options": None,
                     "answered": m.get("reply") if m.get("reply") and not m.get("options") else m.get("answered")}
        store.set_status(a.session, a.n, a.status, **extra)
        return 0
    if a.cmd == "wait":
        print(json.dumps(wait(a.session, a.n)))
        return 0
    if a.cmd == "watch":
        print(json.dumps(watch(set(a.skip))))
        return 0
    from workbench import store as wb_store  # package import: bare "store" is marks'
    try:
        stuck = store.decide(a.session, a.n, "close", reply=None,
                             record=lambda s, n, v, _w, snap: wb_store.record_mark(s, n, v, "closed from terminal", snap))
    except store.NotWaiting:
        print(f"mark {a.n} is not fixed, nothing changed", file=sys.stderr)
        return 2
    except store.LedgerError:
        print("could not record the verdict, nothing changed", file=sys.stderr)
        return 3
    except (KeyError, FileNotFoundError):
        print(f"no mark {a.n}", file=sys.stderr)
        return 4
    for p in stuck:
        print(f"could not delete {p}; mark {a.n} kept", file=sys.stderr)
    return 1 if stuck else 0


if __name__ == "__main__":
    sys.exit(main())

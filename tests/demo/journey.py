#!/usr/bin/env python3
"""Outbound journey (spec Check 5, plan Task 12), headless Chrome.

  python3 tests/demo/journey.py --base http://127.0.0.1:5099 --pid <server pid> [--shots DIR]

Walks every page, presses each control whose label names an outside service, and
exits 0 only when:
  - the server never held a connection to a non-loopback address (sampled with
    `ss` for the server pid and its children the whole run),
  - every switched-off call (403 with the demo note) put the note on screen,
  - the console has no uncaught errors and no same-origin request failed.
A screenshot of each page goes to --shots.
"""
import argparse
import ipaddress
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

PAGES = json.loads((Path(__file__).resolve().parent / "page_apis.json").read_text())
# Labels of controls that reach Claude, Google, a bank, mail or a public API in the real Hub.
OUTSIDE = re.compile(r"\b(sync|refresh|research|ask|summar|draft|send|categori[sz]e|fetch|poll|"
                     r"generate|run|price|search|connect|import|digest|analy[sz]e|rewrite)", re.I)
SKIP = re.compile(r"\b(delete|remove|reset|sign out|log ?out)\b", re.I)


def pids_of(root: int) -> set[int]:
    out = {root}
    kids = subprocess.run(["pgrep", "-P", str(root)], capture_output=True, text=True).stdout.split()
    for k in kids:
        out |= pids_of(int(k))
    return out


def outside_conns(pids: set[int]) -> list[str]:
    rows = subprocess.run(["ss", "-tnpH"], capture_output=True, text=True).stdout.splitlines()
    bad = []
    for row in rows:
        # whole pid numbers: a substring test took pid=98581 (Chrome) for 8581
        if not {int(x) for x in re.findall(r"pid=(\d+),", row)} & pids:
            continue
        peer = row.split()[4].rsplit(":", 1)[0].strip("[]")
        try:
            if not ipaddress.ip_address(peer.split("%")[0]).is_loopback:
                bad.append(row)
        except ValueError:
            bad.append(row)
    return bad


def open_page(pg, url):
    # ponytail: "load" plus a settle wait, since some pages keep a poll open and never go idle
    pg.goto(url, wait_until="load")
    pg.wait_for_timeout(1500)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--pid", type=int, required=True, help="server process (gunicorn master)")
    ap.add_argument("--shots", type=Path, default=Path("journey-shots"))
    ap.add_argument("--max-clicks", type=int, default=8, help="per page")
    a = ap.parse_args(argv)
    a.shots.mkdir(parents=True, exist_ok=True)
    origin = urlsplit(a.base).netloc

    conns, stop = [], threading.Event()

    def watch():
        while not stop.is_set():
            conns.extend(outside_conns(pids_of(a.pid)))
            time.sleep(0.2)
    threading.Thread(target=watch, daemon=True).start()

    problems, pressed, noted = [], 0, 0
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        for page in PAGES:
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            demo_403 = []
            pg.on("pageerror", lambda e, page=page: problems.append(f"{page}: uncaught {e}"))
            def on_console(m, page=page):
                if m.type == "error" and "status of 403" not in m.text:
                    problems.append(f"{page}: console {m.text[:200]}")
            pg.on("console", on_console)
            def on_failed(r, page=page):  # ERR_ABORTED is the next navigation cancelling a poll
                if urlsplit(r.url).netloc == origin and "ERR_ABORTED" not in (r.failure or ""):
                    problems.append(f"{page}: request failed {r.url} {r.failure}")
            pg.on("requestfailed", on_failed)

            def on_resp(r, page=page, demo_403=demo_403):
                if urlsplit(r.url).netloc != origin:
                    return
                if r.status == 403:
                    demo_403.append(r.url)
                elif r.status >= 400:
                    problems.append(f"{page}: {r.status} {r.url}")
            pg.on("response", on_resp)
            open_page(pg, a.base + page)
            if not pg.locator("#demo-banner").count():
                problems.append(f"{page}: no demo banner")
            if not page.startswith("/guide/"):
                # open on a first visit, with the tour loaded; Escape tucks it away
                # (and is remembered), so the presses below are not under it
                try:
                    pg.locator("#demo-guide .gd-step").first.wait_for(timeout=5000)
                except Exception:  # noqa: BLE001
                    problems.append(f"{page}: guide panel did not open with the tour")
                pg.keyboard.press("Escape")
                try:  # wait out the slide, or its close button is counted below and then hides
                    pg.locator("#demo-guide").wait_for(state="hidden", timeout=3000)
                except Exception:  # noqa: BLE001
                    problems.append(f"{page}: guide panel did not close on Escape")
                if pg.locator("#demo-guide-tab:visible").count() != 1:
                    problems.append(f"{page}: guide panel did not tuck into its tab")
            pg.screenshot(path=str(a.shots / f"{page.strip('/').replace('/', '_') or 'home'}.png"))

            labels = []
            for el in pg.locator("button:visible, [role=button]:visible").all():
                t = (el.inner_text() or el.get_attribute("aria-label") or el.get_attribute("title") or "").strip()
                if t and OUTSIDE.search(t) and not SKIP.search(t) and t not in labels:
                    labels.append(t)
            for t in labels[:a.max_clicks]:
                open_page(pg, a.base + page)
                demo_403.clear()
                el = pg.get_by_role("button", name=t, exact=True).first
                if not el.count():
                    continue
                try:
                    el.click(timeout=3000)
                except Exception:  # noqa: BLE001 - covered or detached; not this check's concern
                    continue
                pressed += 1
                pg.wait_for_timeout(1200)
                if demo_403:
                    if pg.locator(".demo-note").count():
                        noted += 1
                    else:
                        problems.append(f"{page}: '{t}' got a demo 403 but no note on screen")
            pg.close()
        b.close()
    stop.set()
    time.sleep(0.3)
    for c in sorted(set(conns)):
        problems.append(f"outside connection: {c}")
    print(f"journey: {len(PAGES)} pages, {pressed} controls pressed, {noted} demo notes shown")
    for line in problems:
        print(f"  {line}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

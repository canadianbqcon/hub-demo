"""Demo layer for the public Hub demo. Exists only in the exported repo.

app.py (patched by the export) calls cut() as its first line, install(app)
right after the Flask app is made, and finish(app) after every blueprint is
registered. Only when DEMO_MODE=1.

cut: refuses every non-loopback socket connect and every process except
the one node call jsx_build makes. install: puts the endpoint guard and the
reset gate in front of every request. finish: checks every registered endpoint is classified in
endpoints.json (boot fails otherwise), adds /healthz and the banner, restores
the fake data, and warms the JSX cache.
"""
from __future__ import annotations

import datetime as dt
import functools
import html
import ipaddress
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

from flask import Response, jsonify, request

HUB = Path(__file__).resolve().parent
ENDPOINTS = json.loads((HUB / "endpoints.json").read_text())
REPO_URL = "https://github.com/canadianbqcon/hub-demo"
DEMO_MESSAGE = ("In the real Hub this runs Claude or a Google, bank or mail service. "
                "Switched off in the demo.")
SKIP_METHODS = {"HEAD", "OPTIONS"}


def vault() -> Path:
    return Path(os.environ["VAULT_PATH"]).resolve()


def log(msg: str) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    try:
        with open(vault() / "demo.log", "a") as f:
            f.write(f"{stamp} {msg}\n")
    except OSError:
        pass


# ---------------------------------------------------------------- network cut

def _loopback(address) -> bool:
    if isinstance(address, (str, bytes)):  # AF_UNIX path
        return True
    host = address[0] if address else ""
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False  # a hostname that is not localhost


class DemoBlocked(OSError):
    pass


# Render sets this to the service's public hostname. The keep-awake ping in
# finish() may reach it, and only it: Render's free tier sleeps after 15 idle
# minutes and a visitor then waits 50 s or more for the wake.
SELF_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
_self_ips: set[str] = set()  # what SELF_HOST resolved to; connect allows these
# ponytail: these are Render edge IPs shared with other Render apps; no visitor-reachable
# route makes an outbound call (all are integration-class), so only the ping uses them.


def _allowed(address) -> bool:
    if _loopback(address):
        return True
    return isinstance(address, tuple) and bool(address) and address[0] in _self_ips


def _cut_network() -> None:
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_gai = socket.getaddrinfo

    def connect(self, address):
        if not _allowed(address):
            log(f"refused connect {address!r}")
            raise DemoBlocked(f"demo: outside network is switched off ({address!r})")
        return real_connect(self, address)

    def connect_ex(self, address):
        if not _allowed(address):
            log(f"refused connect_ex {address!r}")
            raise DemoBlocked(f"demo: outside network is switched off ({address!r})")
        return real_connect_ex(self, address)

    def getaddrinfo(host, *a, **kw):
        h = host.decode() if isinstance(host, bytes) else (host or "")
        if SELF_HOST and h == SELF_HOST:
            res = real_gai(host, *a, **kw)
            _self_ips.update(r[4][0] for r in res)
            return res
        if not _loopback((h,)):
            log(f"refused lookup {h!r}")
            raise socket.gaierror(f"demo: outside network is switched off ({h!r})")
        return real_gai(host, *a, **kw)

    real_sendto, real_sendmsg = socket.socket.sendto, socket.socket.sendmsg

    def sendto(self, data, *a):
        address = a[-1]  # sendto(data, address) or sendto(data, flags, address)
        if not _loopback(address):
            log(f"refused sendto {address!r}")
            raise DemoBlocked(f"demo: outside network is switched off ({address!r})")
        return real_sendto(self, data, *a)

    def sendmsg(self, buffers, ancdata=(), flags=0, address=None):
        if address is not None and not _loopback(address):
            log(f"refused sendmsg {address!r}")
            raise DemoBlocked(f"demo: outside network is switched off ({address!r})")
        return real_sendmsg(self, buffers, ancdata, flags, *([address] if address is not None else []))

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    # unconnected UDP never calls connect
    socket.socket.sendto = sendto
    socket.socket.sendmsg = sendmsg
    socket.getaddrinfo = getaddrinfo
    # separate C resolvers that make their own DNS queries
    for name in ("gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
        real = getattr(socket, name)

        def resolver(host, *a, _real=real, _name=name):
            h = host.decode() if isinstance(host, bytes) else (host or "")
            if not _loopback((h,)):
                log(f"refused {_name} {h!r}")
                raise socket.gaierror(f"demo: outside network is switched off ({h!r})")
            return _real(host, *a)
        setattr(socket, name, resolver)
    # create_connection goes through getaddrinfo and connect, so it is covered.


# ---------------------------------------------------------------- process cut

def _node_call(args) -> bool:
    """The one process the demo runs: jsx_build's node transpile."""
    try:
        import jsx_build
    except ImportError:
        return False
    if isinstance(args, (str, bytes)) or len(args) != 5:
        return False
    return (Path(str(args[0])).name == "node" and args[1] == "-e"
            and args[2] == jsx_build._NODE and Path(str(args[3])) == jsx_build.BABEL)


def _cut_processes() -> None:
    real_popen = subprocess.Popen

    # subprocess itself starts the child through os.posix_spawn (or
    # _fork_exec), so the os-level refusals let through only a call made from
    # inside an allowed DemoPopen on the same thread.
    inside = threading.local()

    class DemoPopen(real_popen):
        def __init__(self, args, *a, **kw):
            if not _node_call(args):
                log(f"refused process {str(args)[:120]!r}")
                raise DemoBlocked("demo: running programs is switched off")
            inside.ok = True
            try:
                super().__init__(args, *a, **kw)
            finally:
                inside.ok = False

    subprocess.Popen = DemoPopen

    def refuse(name):
        real = getattr(os, name.split(".", 1)[1])

        def _f(*a, **kw):
            if getattr(inside, "ok", False):
                return real(*a, **kw)
            log(f"refused {name}")
            raise DemoBlocked(f"demo: {name} is switched off")
        return _f

    # ponytail: _posixsubprocess.fork_exec (multiprocessing's spawn) is not cut; no Hub
    # code uses multiprocessing or os.fork (checked 2026-11-06). Wrap it if that changes.
    for name in ("system", "popen", "posix_spawn", "posix_spawnp", "execv", "execve",
                 "execvp", "execvpe", "execl", "execle", "execlp", "execlpe",
                 "spawnv", "spawnve", "spawnvp", "spawnvpe", "startfile"):
        if hasattr(os, name):
            setattr(os, name, refuse(f"os.{name}"))


# ---------------------------------------------------------------- endpoint guard

def endpoint_keys(app) -> set[str]:
    keys = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        for m in rule.methods - SKIP_METHODS:
            keys.add(f"{m} {rule.rule}")
    return keys


def check_endpoints(app) -> None:
    missing = sorted(endpoint_keys(app) - set(ENDPOINTS))
    if missing:
        raise RuntimeError("demo: unclassified endpoints, add them to endpoints.json: "
                           + ", ".join(missing))


_ESCAPE = re.compile(r"(^|[\\/])\.\.([\\/]|$)|^[\\/~]|^[A-Za-z]:|\x00")


def _escapes(value) -> bool:
    return isinstance(value, str) and bool(_ESCAPE.search(value))


def _all_strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from _all_strings(k)
            yield from _all_strings(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _all_strings(x)


def _guard():
    if request.url_rule is None or request.method == "OPTIONS":
        return None
    if request.url_rule.endpoint == "static":
        return None
    method = "GET" if request.method == "HEAD" else request.method  # Flask runs the GET view
    entry = ENDPOINTS.get(f"{method} {request.url_rule.rule}")
    if entry is None:  # fail closed; finish() makes this unreachable at boot
        return jsonify(demo=DEMO_MESSAGE), 403
    if entry.get("class") == "integration":
        log(f"blocked integration {request.method} {request.path}")
        return jsonify(demo=DEMO_MESSAGE), 403
    if entry.get("path-pinned"):
        values = list(_all_strings(request.view_args or {}))
        values += [v for _, v in request.args.items(multi=True)]
        values += [v for _, v in request.form.items(multi=True)]
        values += list(_all_strings(request.get_json(force=True, silent=True)))
        # ponytail: no live upload route is path-pinned today (both are integration);
        # this covers one that is reclassified local-write with path-pinned set
        values += [f.filename or "" for _, f in request.files.items(multi=True)]
        if any(_escapes(v) for v in values):
            return jsonify(error="path outside the demo folder"), 400
    return None


# ---------------------------------------------------------------- reset

PRISTINE = "pristine"
# @d<+N>: the date N days from the reset day ("2026-11-05" for @d-1).
# @t<+N>: the timestamp N hours from the reset moment ("2026-11-06 09:00:00").
# ponytail: a fixed time of day is written "@d-2 14:30:00"; epoch-int columns
# are not rewritten, add an @e token if the seeder meets one.
_OFFSET = re.compile(r"@([dt])([+-]\d+|0)")
_gate = threading.Condition()
_state = {"resetting": False, "inflight": 0, "last": None, "ready": False}
# In-process caches the reset clears: (module, attribute). Dicts are cleared,
# lru_cache functions get cache_clear(), a throttle timestamp goes to -inf
# (no request runs during a reset, so the module's own lock is not needed).
CACHES = [
    ("recipes.store", "_cache"),
    ("recipes.store", "_stamps"),  # else an unchanged stamp skips the re-parse
    ("recipes.store", "_last_sweep"),  # else recipes stay empty for its 2 s sweep throttle
    ("finances.debt_source", "*"),
    ("automations.api", "*"),
    ("trips.place_photos", "_cache"),
]


def _clear_caches() -> None:
    for modname, attr in CACHES:
        mod = sys.modules.get(modname)
        if mod is None:
            continue
        names = [attr] if attr != "*" else list(vars(mod))
        for n in names:
            obj = getattr(mod, n, None)
            if isinstance(obj, dict) and attr != "*":
                obj.clear()
            elif isinstance(obj, float) and attr != "*":
                setattr(mod, n, float("-inf"))
            elif isinstance(obj, functools._lru_cache_wrapper):  # never probe proxies like flask.request
                obj.cache_clear()


def _materialize(con: sqlite3.Connection, now: dt.datetime) -> None:
    """Rewrite @d / @t offset tokens in every text cell to real dates."""
    now = now.astimezone(dt.timezone.utc).replace(microsecond=0, tzinfo=None)

    def sub(m):
        n = int(m.group(2))
        if m.group(1) == "d":
            return (now.date() + dt.timedelta(days=n)).isoformat()
        return (now + dt.timedelta(hours=n)).isoformat(sep=" ")

    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        " AND sql NOT LIKE 'CREATE VIRTUAL%'")]
    for t in tables:
        cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
        for c in cols:
            # keyed on the value, not rowid, so WITHOUT ROWID tables work too
            vals = [r[0] for r in con.execute(
                f'SELECT DISTINCT "{c}" FROM "{t}" WHERE typeof("{c}")=\'text\' AND "{c}" LIKE \'%@%\'')]
            for val in vals:
                if _OFFSET.search(val):
                    con.execute(f'UPDATE "{t}" SET "{c}"=? WHERE "{c}"=?', (_OFFSET.sub(sub, val), val))


def _restore(now: dt.datetime) -> None:
    root = vault()
    pristine = root / PRISTINE
    data = root / "data"
    # checked first: the cleanup below deletes whatever pristine/ lacks
    if not any(pristine.glob("*.db")):
        raise RuntimeError(f"pristine set missing or holds no .db: {pristine}")
    data.mkdir(exist_ok=True)
    for src_path in sorted(pristine.glob("*.db")):
        src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
        dst = sqlite3.connect(data / src_path.name, timeout=30)
        try:
            src.backup(dst)
            _materialize(dst, now)
            dst.commit()
        finally:
            src.close()
            dst.close()
    # Anything a visitor added is removed: in data/, whatever is neither a
    # pristine DB (or its journal) nor in pristine/data; at the root, whatever
    # is not in pristine (data/, pristine/ and the log stay).
    keep = {p.name for p in pristine.glob("*.db")}
    keep |= {k + s for k in keep for s in ("-journal", "-wal", "-shm")}
    pdata = pristine / "data"
    for p in list(data.rglob("*")):
        rel = p.relative_to(data)
        if p.is_file() and str(rel) not in keep and not (pdata / rel).is_file():
            p.unlink()
    for p in root.iterdir():
        if p.name not in {"data", PRISTINE, "demo.log"} and not (pristine / p.name).exists():
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    # Every other pristine entry is a file tree the pages read. data/ is
    # merged (the live DBs sit there); any other folder is replaced whole.
    for entry in sorted(pristine.iterdir()):
        if entry.suffix == ".db":
            continue
        if entry.is_file():
            shutil.copy2(entry, root / entry.name)
        elif entry.name == "data":
            shutil.copytree(entry, data, dirs_exist_ok=True)
        else:
            shutil.rmtree(root / entry.name, ignore_errors=True)
            shutil.copytree(entry, root / entry.name)
    _clear_caches()
    bad = []
    for db in sorted(data.glob("*.db")):
        con = sqlite3.connect(db, timeout=30)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                bad.append(db.name)
        finally:
            con.close()
    if bad:
        raise RuntimeError(f"integrity_check failed: {bad}")


def reset(now: dt.datetime | None = None, wait: float = 30.0) -> bool:
    """Exclusive restore from pristine. True when the demo is ready afterwards."""
    now = now or dt.datetime.now(dt.timezone.utc)
    with _gate:
        if _state["resetting"]:
            return False
        _state["resetting"] = True
        was_ready = _state["ready"]
        _state["ready"] = False
        if not _gate.wait_for(lambda: _state["inflight"] == 0, timeout=wait):
            # a request is still writing; keep serving what is there, retry later
            _state["resetting"] = False
            _state["ready"] = was_ready
            _state["failed_at"] = now  # the backoff spaces out the retries
            _gate.notify_all()
            log("reset deferred: requests still in flight")
            return False
    try:
        _restore(now)
        ok = True
    except Exception as e:  # noqa: BLE001 - any failure keeps the demo closed
        log(f"reset failed: {e}")
        ok = False
    with _gate:
        _state["resetting"] = False
        _state["ready"] = ok
        if ok:
            _state["last"] = now
        else:
            _state["failed_at"] = now
        _gate.notify_all()
    if ok:
        log("reset ok")
    return ok


RETRY_AFTER = 60  # seconds between restore attempts after a failed one


def _last_midnight(now: dt.datetime) -> dt.datetime:
    now = now.astimezone(dt.timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _now() -> dt.datetime:  # tests patch this
    return dt.datetime.now(dt.timezone.utc)


def _before():
    now = _now()
    last = _state["last"]
    failed = _state.get("failed_at")
    backoff = failed is not None and (now - failed).total_seconds() < RETRY_AFTER
    if not _state["ready"] or last is None or last < _last_midnight(now):
        if not _state["resetting"] and not backoff:
            reset(now)
    with _gate:
        _gate.wait_for(lambda: not _state["resetting"], timeout=30)
        if _state["resetting"] or not _state["ready"]:
            if request.path == "/healthz":
                return Response("resetting", 503)
            return Response("Demo data is resetting, try again in a moment.", 503)
        _state["inflight"] += 1
        request.environ["demo.counted"] = True
    return _guard()


def _after_teardown(_exc):
    if request.environ.pop("demo.counted", False):
        with _gate:
            _state["inflight"] -= 1
            _gate.notify_all()


# ---------------------------------------------------------------- banner

BANNER = (
    '<div id="demo-banner" role="note" style="position:sticky;top:0;z-index:2147483000;'
    'display:flex;flex-wrap:wrap;gap:.35em .9em;justify-content:center;align-items:center;'
    'padding:.4em .8em;font:13px/1.35 system-ui,sans-serif;background:#1f2a44;color:#f3f5fa">'
    '<span>Demo with fake data, shared by all visitors, resets daily</span>'
    '<span aria-hidden="true">&middot;</span><span>Built by Brendan Quan</span>'
    '<span aria-hidden="true">&middot;</span>'
    '<a id="demo-guide-link" href="/guide/" style="color:#9cc3ff">Guide</a>'
    '<span aria-hidden="true">&middot;</span>'
    f'<a href="{html.escape(REPO_URL)}" style="color:#9cc3ff">Source code</a></div>'
)
# A switched-off route answers 403 {"demo": ...}; this shows that note beside the
# control the visitor last pressed, so the page never just looks broken.
# Shown only within 5 s of a press: pages also call outside services on load
# (status checks, polls), and a note nobody asked for reads as an error.
NOTE_JS = """<script>(()=>{let last=null,at=0;
addEventListener('pointerdown',e=>{last=e.target.closest('button,a,[role=button],input,select')||e.target;at=Date.now()},true);
const f=window.fetch;window.fetch=async(...a)=>{const r=await f(...a);
if(r.status===403){r.clone().json().then(j=>{if(j&&j.demo&&Date.now()-at<5000)show(j.demo)}).catch(()=>{})}return r};
function show(msg){const n=document.createElement('div');n.className='demo-note';n.setAttribute('role','status');
n.textContent=msg;n.style.cssText='position:fixed;z-index:2147483001;max-width:300px;padding:.5em .75em;'
+'font:13px/1.35 system-ui,sans-serif;background:#1f2a44;color:#f3f5fa;border-radius:8px;box-shadow:0 4px 16px #0004';
const b=last&&last.isConnected?last.getBoundingClientRect():null;
const x=b?Math.min(b.left,innerWidth-310):12,y=b?(b.bottom+8>innerHeight-60?b.top-60:b.bottom+8):innerHeight-70;
n.style.left=Math.max(8,x)+'px';n.style.top=Math.max(8,y)+'px';document.body.appendChild(n);setTimeout(()=>n.remove(),6000)}
})()</script>"""
# The Guide as a frosted side panel over every page (except /guide/ itself).
# Styles and behaviour live in guide/frontend/panel.css and panel.js; the tour
# body is fetched from /guide/panel. The Hub's asset stamp rewrites ?v= to the file time.
PANEL = (
    '<link rel="stylesheet" href="/guide/static/guide.css?v=1">'
    '<link rel="stylesheet" href="/guide/static/panel.css?v=1">'
    '<aside id="demo-guide" class="is-closed" aria-label="Guide"><header><span>Guide</span>'
    '<button class="dg-x" type="button" aria-label="Close guide">&times;</button></header>'
    '<div class="dg-body"></div></aside>'
    '<button id="demo-guide-tab" type="button" aria-controls="demo-guide" aria-expanded="false" hidden>Guide</button>'
    '<script src="/guide/static/panel.js?v=1" defer></script>'
)
_BODY = re.compile(rb"<body[^>]*>", re.I)


def _banner(resp):
    if not resp.mimetype == "text/html" or resp.status_code != 200:
        return resp
    if "Content-Encoding" in resp.headers:
        return resp
    resp.direct_passthrough = False
    data = resp.get_data()
    if b'id="demo-banner"' in data:
        return resp
    m = _BODY.search(data)
    if not m:
        return resp
    extra = BANNER + NOTE_JS + ("" if request.path.startswith("/guide/") else PANEL)
    resp.set_data(data[:m.end()] + extra.encode() + data[m.end():])
    return resp


# ---------------------------------------------------------------- calendar
# Google Calendar is integration-class, so the home schedule would sit empty.
# These stand in for it: (day offset from today, start, end, title, location,
# Google colorId; never "11": Tomato events become tasks.db rows on every
# /api/home read). Start None = all-day. Same fake persona as the seeders.
CAL_EVENTS = [
    (-6, "09:30", "10:00", "Team Standup", "Larkspur Labs", "7"),
    (-5, "18:00", "23:30", "Shift at Juniper & Co", "Juniper & Co", "6"),
    (-4, "12:30", "13:30", "Lunch with Priya Nair", "Little Goat Diner", ""),
    (-3, "19:00", "21:00", "Climbing with Marcus", "First Ascent Avondale", "2"),
    (-2, "09:30", "10:00", "Team Standup", "Larkspur Labs", "7"),
    (-1, "17:00", "23:00", "Shift at Juniper & Co", "Juniper & Co", "6"),
    (0, "09:30", "10:00", "Team Standup", "Larkspur Labs", "7"),
    (0, "13:00", "14:00", "Quarterly ops review", "Larkspur Labs", ""),
    (0, "18:30", "20:00", "Dinner with Elena Ortiz", "Avec", ""),
    (1, None, None, "Rent due", "", ""),
    (1, "08:00", "09:00", "Gym", "", "2"),
    (1, "17:00", "23:30", "Shift at Juniper & Co", "Juniper & Co", "6"),
    (2, "10:00", "10:45", "Phone screen: Product Ops role", "Video call", "5"),
    (2, "19:30", "22:00", "Trivia night", "The Whistler", ""),
    (3, "09:30", "10:00", "Team Standup", "Larkspur Labs", "7"),
    (3, "15:00", "15:30", "Dentist", "Lakeview Dental", ""),
    (4, "11:00", "13:00", "Farmers market with Hana", "Green City Market", "2"),
    (5, None, None, "Lisbon trip planning", "", ""),
    (5, "17:00", "23:30", "Shift at Juniper & Co", "Juniper & Co", "6"),
    (6, "09:30", "10:00", "Team Standup", "Larkspur Labs", "7"),
    (7, "12:00", "13:00", "Coffee with Dev Chandra", "Intelligentsia", ""),
]


# Google's modern event colours by colorId; "" is the calendar's own (lavender)
CAL_HEX = {"": "#7986cb", "2": "#33b679", "5": "#f6bf26", "6": "#f4511e", "7": "#039be5"}


def _demo_week_events(days: int = 7, days_back: int = 0) -> list[dict]:
    import gcal
    today = dt.date.today()  # home_data buckets on local date.today() too
    out = []
    for i, (off, start, end, title, loc, color) in enumerate(CAL_EVENTS):
        if not -days_back <= off <= days:
            continue
        day = today + dt.timedelta(days=off)
        if start is None:
            span = {"start": {"date": day.isoformat()},
                    "end": {"date": (day + dt.timedelta(days=1)).isoformat()}}
        else:
            # each its own offset, so a week across a DST change stays on the clock
            at = lambda hm: dt.datetime.combine(day, dt.time.fromisoformat(hm)).astimezone().isoformat()
            span = {"start": {"dateTime": at(start)}, "end": {"dateTime": at(end)}}
        # the Hub tints from _color, which the real fetch resolves to Google's hex
        out.append(gcal._week_event_row({"id": f"demo-ev-{i}", "summary": title, "location": loc,
                                         "colorId": color, "_color": CAL_HEX.get(color, CAL_HEX[""]),
                                         "_cal_id": "primary", **span}))
    out.sort(key=lambda e: (e["date"], e["start_dt"]))
    return out


# ---------------------------------------------------------------- entry points

def cut() -> None:
    """First line of app.py: nothing imported after it can reach out."""
    if not _state.get("cut"):
        _cut_network()
        _cut_processes()
        _state["cut"] = True


def install(app) -> None:
    cut()
    app.before_request_funcs.setdefault(None, []).insert(0, _before)
    app.teardown_request(_after_teardown)


def _keep_awake() -> None:
    import time
    import urllib.request
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen(f"https://{SELF_HOST}/healthz", timeout=60).close()
        except Exception as e:  # noqa: BLE001 - next round tries again
            log(f"keep-awake ping failed: {e}")


def finish(app) -> None:
    if SELF_HOST:
        threading.Thread(target=_keep_awake, daemon=True, name="keep-awake").start()
    from guide import api as guide_api
    import hub_modules
    app.register_blueprint(guide_api.bp)
    if hub_modules.MODULES[0].get("href") != "/guide/":
        hub_modules.MODULES.insert(0, guide_api.MODULE)  # same list app.py serves

    @app.route("/healthz")
    def healthz():
        ok = _state["ready"]
        return Response("ok" if ok else "resetting", 200 if ok else 503, mimetype="text/plain")

    # Registered last, so Flask runs it first among after_request hooks:
    # before the asset stamp and the gzip hook see the page.
    app.after_request(_banner)
    # The real check refreshes the token with Google, which the cut refuses, so
    # the status bar showed an orange "gmail · reconnect". Show it as connected,
    # like gcal (a token file); every Gmail route is integration-class anyway.
    import gmail
    gmail.is_authenticated = lambda: True
    # Home only: a global gcal.is_authenticated would switch on the trips and
    # tasks calendar writes. home_data calls these two and nothing else on gcal.
    import types
    import home_data
    home_data.gcal = types.SimpleNamespace(is_authenticated=lambda: True,
                                           fetch_week_events=_demo_week_events)
    check_endpoints(app)
    reset()
    # Render's free instance has 512 MB and one node transpile peaks near 126 MB, so
    # jsx_build.warm()'s four at once got the process killed at every boot. The
    # Docker build transpiles every .jsx into jsx-cache.json, so the server never
    # starts node; without that file (a local run) it warms as the Hub does.
    try:
        import jsx_build
        prebuilt = HUB.parents[1] / "jsx-cache.json"
        if prebuilt.exists():
            for p, js in json.loads(prebuilt.read_text()).items():
                f = Path(p)
                if f.exists():
                    jsx_build._cache[f] = (f.stat().st_mtime, js)
        else:
            jsx_build.warm()
    except Exception as e:  # noqa: BLE001
        log(f"jsx warm failed: {e}")


__all__ = ["cut", "install", "finish", "reset", "check_endpoints", "CACHES", "DEMO_MESSAGE"]

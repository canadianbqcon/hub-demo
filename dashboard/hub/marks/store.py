"""Mark mode store: one folder per marking session under data/marks/.

Each session holds marks.json (header plus a marks array), NN-crop.png,
NN-full.png and NN-after.png per mark, and a .lock file. Every
read-modify-write takes an exclusive flock on <session>/.lock and writes
marks.json through a temp file plus os.replace, so the Save API and the
close CLI never tear each other's writes. Mark numbers come from the
header's monotonic next_n, never the array length, so a closed mark's number
is not reused. Design: docs/specs/2026-10-12-hub-mark-mode-design.md §3-5.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# dashboard/ on sys.path → vault_path (same import as workbench/store.py).
if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

_CODE_REPO = Path(__file__).resolve().parents[3]


def marks_root(root=None) -> Path:
    if root:
        return Path(root)
    env = os.environ.get("MARKS_ROOT")
    return Path(env) if env else vault_root() / "data" / "marks"


# Session names arrive from the browser; anything else could walk out of data/marks.
_SESSION_RE = re.compile(r"\d{4}-\d{2}-\d{2}-\d{6}-[A-Za-z0-9._-]+")


def _folder(session, root=None) -> Path:
    if not isinstance(session, str) or not _SESSION_RE.fullmatch(session):
        raise ValueError(f"bad mark session name: {session!r}")
    return marks_root(root) / session


def _git(*args):
    """Output of a git read in the code repo, or None on any failure."""
    try:
        r = subprocess.run(["git", "-C", str(_CODE_REPO), *args],  # noqa: S607  git on PATH, fixed argv
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def _header(machine, started=None) -> dict:
    status = _git("status", "--porcelain")
    return {
        "started": started or datetime.now().isoformat(timespec="seconds"),
        "machine": machine,
        "next_n": 1,
        "code_commit": _git("rev-parse", "--short", "HEAD"),
        "dirty": None if status is None else bool(status),
        "marks": [],
    }


def _write(folder: Path, data: dict) -> None:
    tmp = folder / "marks.json.tmp"
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, folder / "marks.json")


@contextmanager
def _locked(folder: Path, create_machine=None):
    """Hold the session lock and yield the folder. With create_machine set, a
    missing folder is recreated with a fresh header; otherwise it raises
    FileNotFoundError. The inode check retries when a close deleted the folder
    between our open() and flock(), so we never lock an orphaned file."""
    while True:
        if create_machine is not None:
            folder.mkdir(parents=True, exist_ok=True)
        elif not folder.is_dir():
            raise FileNotFoundError(f"no such mark session: {folder.name}")
        fd = os.open(folder / ".lock", os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                same = os.fstat(fd).st_ino == os.stat(folder / ".lock").st_ino
            except FileNotFoundError:
                same = False
            if not same:
                continue
            if create_machine is not None and not (folder / "marks.json").exists():
                _write(folder, _header(create_machine))
            yield folder
            return
        finally:
            os.close(fd)


def _read(folder: Path) -> dict:
    return json.loads((folder / "marks.json").read_text())


def session_name(machine=None) -> str:
    machine = re.sub(r"[^A-Za-z0-9._-]", "-", machine or socket.gethostname())
    return f"{datetime.now():%Y-%m-%d-%H%M%S}-{machine}"


def new_session(machine=None, root=None) -> str:
    name = session_name(machine)
    with _locked(_folder(name, root), create_machine=name.split("-", 4)[-1]):
        pass
    return name


def add_mark(session, meta, crop=None, full=None, root=None) -> int:
    folder = _folder(session, root)
    # A closed-out session's folder is gone: recreate it with a fresh header.
    # next_n restarts at 1 then, which is acceptable because every old mark
    # and PNG went with the folder. Machine is recovered from the name.
    machine = session.split("-", 4)[-1]
    with _locked(folder, create_machine=machine):
        data = _read(folder)
        # a retry of a save whose response was lost: same client id, same mark
        cid = meta.get("cid")
        for m in data["marks"] if cid else ():
            if m.get("cid") == cid:
                return m["n"]
        n = data["next_n"]
        if crop is not None:
            (folder / f"{n:02d}-crop.png").write_bytes(crop)
        if full is not None:
            (folder / f"{n:02d}-full.png").write_bytes(full)
        data["marks"].append({**meta, "n": n,
                              "created": datetime.now().isoformat(timespec="seconds"),
                              "status": "open"})
        data["next_n"] = n + 1
        _write(folder, data)
        return n


def load(session, root=None) -> dict:
    return _read(_folder(session, root))


def list_sessions(open_only=False, root=None) -> list:
    base = marks_root(root)
    out = []
    for d in sorted(base.iterdir()) if base.is_dir() else []:
        if not (d / "marks.json").is_file():
            continue
        try:
            data = _read(d)
        except (OSError, ValueError):
            continue
        if open_only:
            data["marks"] = [m for m in data["marks"] if m.get("status") != "fixed"]
            if not data["marks"]:
                continue
        out.append({"session": d.name, **data})
    return out


def _find(data, n):
    for m in data["marks"]:
        if m["n"] == n:
            return m
    raise KeyError(f"no mark {n}")


def set_status(session, n, status, root=None, **fields) -> None:
    """fields ride along on the mark: fix_note (what changed, shown on the
    Workbench walk-through) and reply (his send-back words)."""
    folder = _folder(session, root)
    with _locked(folder):
        data = _read(folder)
        _find(data, n).update(fields, status=status)
        _write(folder, data)


def save_after(session, n, png, root=None) -> None:
    folder = _folder(session, root)
    with _locked(folder):
        _find(_read(folder), n)
        (folder / f"{n:02d}-after.png").write_bytes(png)


# his Make options click: the reply a woken /marks session reads, and the ledger comment
OPTIONS_REPLY = "make options"


class NotWaiting(Exception):
    """The mark is not `fixed`: it was already answered, or never fixed."""


class LedgerError(Exception):
    """The ledger write failed; the mark was left as it was."""


def close(session, n, root=None) -> list:
    """Delete the mark's PNGs and entry. A PNG that cannot be deleted is
    returned and the entry kept. The folder goes when its last mark does, or
    stays with an empty header if a leftover file will not delete."""
    folder = _folder(session, root)
    with _locked(folder):
        data = _read(folder)
        _find(data, n)
        return _close_locked(folder, data, n)


def decide(session, n, verdict, reply=None, record=None, root=None) -> list:
    """His answer to a fixed mark, ledger row first. Under the session lock:
    refuse unless the mark is `fixed` (NotWaiting), build the snapshot, call
    `record` (a failure raises LedgerError with the mark untouched), then
    apply the change: close deletes the mark, send_back sets `fixing` with
    `reply`, options sets `fixing` with `options` and reply "make options",
    or "make options: <his note>" when he typed one (a
    sent_back row, so the ledger needs no new verdict and `watch` wakes on it
    unchanged). Returns the files a close could not delete; the row stands and
    the mark stays `fixed`, so a repeat Close finishes and adds a second row."""
    if record is None:
        # package import: a bare "import store" would collide with marks' own store
        from workbench import store as wb_store
        record = wb_store.record_mark
    folder = _folder(session, root)
    with _locked(folder):
        data = _read(folder)
        m = _find(data, n)
        if m.get("status") != "fixed":
            raise NotWaiting(f"mark {n} is {m.get('status')}, not fixed")
        after = folder / f"{n:02d}-after.png"
        snapshot = {"v": 1, "n": n, **{k: m.get(k) for k in ("url", "comment", "kind", "fix_note")},
                    "status_before": m["status"],
                    "after_sha256": hashlib.sha256(after.read_bytes()).hexdigest() if after.is_file() else None}
        close_it = verdict == "close"
        if verdict == "options":
            reply = f"{OPTIONS_REPLY}: {reply}" if reply else OPTIONS_REPLY
        try:
            record(session, n, "approved" if close_it else "sent_back", reply, snapshot)
        except Exception as e:
            raise LedgerError(str(e)) from e
        if close_it:
            return _close_locked(folder, data, n)
        m.update(status="fixing", reply=reply, options=verdict == "options" or None)
        _write(folder, data)
        return []


def _close_locked(folder, data, n) -> list:
    stuck = []
    for kind in ("crop", "full", "after"):
        p = folder / f"{n:02d}-{kind}.png"
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            stuck.append(str(p))
    if stuck:
        return stuck
    data["marks"] = [m for m in data["marks"] if m["n"] != n]
    _write(folder, data)  # the mark is closed from here on
    if data["marks"]:
        return []
    # Last mark: drop the folder while still holding the lock; waiters
    # see a different inode (or none) and retry. A file that will not go
    # (Explorer, a stray subfolder) keeps the folder with its empty header,
    # put back unless an add_mark already started a fresh one.
    order = {"marks.json": 1, ".lock": 2}
    try:
        for f in sorted(folder.iterdir(), key=lambda f: order.get(f.name, 0)):
            f.unlink()
        folder.rmdir()
    except OSError:
        try:
            with open(folder / "marks.json", "x") as fh:
                json.dump(data, fh, indent=2)
        except OSError:
            pass
    return []

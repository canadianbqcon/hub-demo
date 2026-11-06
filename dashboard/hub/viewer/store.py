"""Viewer store: one folder per shown item under data/viewer/, no database.

Publish is staged (.staging/<id>/ then one os.replace into place), the feed is
an in-memory list rebuilt when the folder mtime changes, and prune() removes
anything older than 30 days. Loose files dropped in the folder root show as
upload items without being moved. RAW previews: the embedded JPEG when it is
big enough, else a detached child runs rawpy.postprocess.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import io
import json
import logging
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageOps

# dashboard/ on sys.path -> vault_path (same idiom as artifacts/api.py).
if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

log = logging.getLogger(__name__)

ROOT = vault_root() / "data" / "viewer"
ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}-[a-z0-9-]{1,40}$")
RAW_EXT = {".cr3", ".cr2", ".arw", ".nef", ".dng", ".raf", ".orf", ".rw2"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v"}

KEEP_DAYS = 30
BIG_EDGE = 3000
MAKING_SECS = 600
SIDECARS = (".thumb.jpg", ".preview.jpg", ".sig")  # .previews/<loose name><suffix>; only the jpgs are served
SEEN_FLOOR = 1767225600  # 2026-01-01, before the Viewer existed: an earlier "first seen" is a bad value
NO_RAWPY = "failed: rawpy not installed"
_TRANSIENT = {errno.EACCES, errno.EPERM, errno.EBUSY, errno.EIO, errno.EAGAIN, errno.ENOENT, errno.ETXTBSY,
              errno.ENOSPC, errno.EROFS}  # disk full or remounted: recovers once fixed
_HUB_DIR = Path(__file__).resolve().parent.parent

_cache = None  # (root, mtime_ns, built_at, items)
_rebuild = threading.Lock()
_seen_cache = None  # ((path, mtime_ns), {name: [first_seen, sig]})
_last_prune = 0.0
RETRY_SECS = 60
# loose name -> (sig, last passing failure, status, thumb it saved). Keyed by name like the
# thumb file it describes, so a newer version's try replaces an older one's and none can claim it
_tries: dict[str, tuple] = {}
# commit's prune runs outside _rebuild. ponytail: in-process only; the CLI's publish is
# another process and can still write seen.json from an older scan, which only ever
# makes an arrival time later (never an early delete). flock + scan inside it if that bites.
_seen_lock = threading.Lock()
_unsaved: dict = {}  # arrival entries not yet in seen.json
_pending: dict[str, list[tuple[str, str, str | None]]] = {}  # staging path -> [(stored, orig, src)] in add order


# ---- helpers ---------------------------------------------------------------

def _id_time(name: str) -> datetime | None:
    try:
        return datetime.strptime(name[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def _file_kind(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in IMAGE_EXT or ext in RAW_EXT:
        return "photo"
    return "video" if ext in VIDEO_EXT else "file"


def _win(p: Path) -> str:
    """/mnt/c/x/y -> C:\\x\\y, the form he can paste into Explorer."""
    s = str(p)
    m = re.match(r"^/mnt/([a-z])(/.*)?$", s)
    return f"{m.group(1).upper()}:{(m.group(2) or '/').replace('/', chr(92))}" if m else s


def _sig(st: os.stat_result) -> str:
    return f"{st.st_size}:{st.st_mtime_ns}"


def _read_seen(set_aside: bool = True) -> tuple[dict, bool]:
    """(seen.json as {name: [first_seen, sig]}, writable). {} when it does not exist
    yet. On a passing read error: the last good copy of this file, not writable,
    so a caller never overwrites arrival times it could not read."""
    global _seen_cache, _unsaved
    path = ROOT / ".previews" / "seen.json"
    try:
        m = path.stat().st_mtime_ns
        if _seen_cache and _seen_cache[0] == (str(path), m):
            return _seen_cache[1], True
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, True
    except ValueError as e:  # corrupt for good: set it aside so it gets rewritten
        if not set_aside:  # a file request reads without _seen_lock, so it never moves the file
            return _last_seen(path), False
        bad = path.with_name(f"seen.json.bad.{time.time_ns()}")  # one per corruption, never overwritten
        log.warning("viewer: seen.json corrupt, moved to %s: %s", bad.name, e)
        try:
            os.replace(path, bad)
        except OSError:
            return _last_seen(path), False
        # rewritten from this process's last good times: they go in as unsaved entries, so
        # the empty copy differs from what gets written and the write happens.
        # ponytail: a process with no good copy (CLI, fresh Hub) restarts every loose file's
        # clock at now, which only ever deletes later; recover from the .bad file if that bites
        _unsaved = {**_last_seen(path), **_unsaved}
        return {}, True
    except OSError as e:
        # a file request reads on every fetch: only the scan's read logs at warning
        (log.warning if set_aside else log.debug)("viewer: seen.json unreadable, not touching it: %s", e)
        return _last_seen(path), False

    def when(t):
        return (isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t)
                and SEEN_FLOOR < t < time.time() + 86400)
    seen = {}
    for k, v in (raw.items() if isinstance(raw, dict) else ()):
        if when(v):
            seen[k] = [float(v), None]  # older {name: time} format: keep the time, adopt the file
        elif isinstance(v, list) and len(v) == 2 and when(v[0]) and isinstance(v[1], str):
            seen[k] = v
    if set_aside:  # only the scan's read, under _seen_lock, caches; resolve never writes it
        _seen_cache = ((str(path), m), seen)
    return seen, True


def _last_seen(path: Path) -> dict:
    return _seen_cache[1] if _seen_cache and _seen_cache[0][0] == str(path) else {}


def _stats(entries) -> dict[str, os.stat_result | None]:
    """stat() of each loose file, skipping one removed since the scandir; None for one
    that cannot be stat'd just now (held), so its arrival entry is kept, not dropped."""
    out = {}
    for e in entries:
        try:
            if e.is_file(follow_symlinks=False):
                out[e.name] = e.stat()
        except FileNotFoundError:
            pass
        except OSError:  # held on the Windows side
            out[e.name] = None
    return out


def _scan():
    """(entries, stats, first_seen, seen.json read) for the folder root, the scan and the
    seen.json update under one lock so no caller records an older view over a newer one."""
    with _seen_lock:
        with os.scandir(ROOT) as it:
            entries = [e for e in it if not e.name.startswith(".") and not _link(e)]
        stats = _stats(entries)
        return (entries, stats, *_first_seen(stats))


def _link(e: os.DirEntry) -> bool:
    try:
        return e.is_symlink()
    except OSError:  # held: kept, and _stats marks it unstat-able
        return False


def _first_seen(stats: dict[str, os.stat_result | None]) -> tuple[dict[str, float], bool]:
    """Only through _scan, which holds _seen_lock. When each loose file first showed up, and whether seen.json was read. Their
    mtime can't be used: Explorer keeps it on copy and move, so an old photo would
    expire the moment it lands. Entries are [time, size:mtime]; a different file
    under the same name starts over. Records new ones as now and forgets the ones gone."""
    global _unsaved
    disk, writable = _read_seen()
    now = time.time()
    fresh = {}
    for n, st in stats.items():
        if st is None:  # held this scan: keep its entry as it is
            if e := disk.get(n) or _unsaved.get(n):
                fresh[n] = e
            continue
        sig = _sig(st)
        # seen.json's entry when it is this file, else the time this process gave it but
        # could not save, so a file keeps one arrival time through a read or write outage
        e = next((e for e in (disk.get(n), _unsaved.get(n)) if e and e[1] in (None, sig)), None)
        fresh[n] = [e[0] if e else now, sig]
    _unsaved = fresh
    if writable:
        try:
            if fresh != disk:
                _save_seen(fresh)
            _unsaved = {}
        except OSError as e:  # another writer won, or it is held; the next rebuild records it
            log.info("viewer: seen.json not written: %s", e)
    # a held file's kept entry may belong to an older file of that name: never acted on
    return {n: v[0] for n, v in fresh.items() if stats.get(n)}, writable


def _save_seen(data: dict) -> None:
    global _seen_cache
    path = ROOT / ".previews" / "seen.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, data)
    _seen_cache = ((str(path), path.stat().st_mtime_ns), data)  # the fallback is what was written last


def _write_json(path: Path, data: dict) -> None:
    _write_bytes(path, json.dumps(data, indent=2).encode("utf-8"))


def _drop(tmp: Path) -> None:
    """Remove a temp file after a failed write, never masking that write's error."""
    try:
        tmp.unlink(missing_ok=True)
    except OSError as e:  # held: hidden, so nothing reads it; logged so it can be found
        log.info("viewer: temp %s left behind: %s", tmp, e)


def _write_bytes(out: Path, data: bytes) -> None:
    """Every store write: temp + rename, so a write that fails midway never leaves a cut-off
    file. Hidden and unique, so two writers never share a temp and no upload name matches it."""
    tmp = out.with_name(f".{out.name}.{os.getpid()}.{secrets.token_hex(3)}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, out)
    except BaseException:
        _drop(tmp)
        raise


def _jpeg(im: Image.Image, quality: int) -> bytes:
    b = io.BytesIO()
    im.save(b, "JPEG", quality=quality)
    return b.getvalue()


def _checker(size: tuple[int, int]) -> Image.Image:
    """The grey checkerboard a transparent picture's thumb sits on, so it never reads as black."""
    bg = Image.new("RGB", size, (204, 204, 204))
    draw = ImageDraw.Draw(bg)
    for y in range(0, size[1], 8):
        for x in range((y // 8) % 2 * 8, size[0], 16):
            draw.rectangle((x, y, x + 7, y + 7), fill=(153, 153, 153))
    return bg


def _save_thumb(src, out: Path) -> None:
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        w, h = im.size
        if h > 3 * w:  # a long screenshot: its top, not a sliver
            im = im.crop((0, 0, w, w * 4 // 3))
        elif w > 4 * h:  # a panorama: its middle
            cw = h * 4 // 3
            im = im.crop(((w - cw) // 2, 0, (w - cw) // 2 + cw, h))
        alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
        im = im.convert("RGBA" if alpha else "RGB")
        im.thumbnail((320, 320))
        if alpha:
            bg = _checker(im.size)
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        data = _jpeg(im, 80)
    _write_bytes(out, data)


_FLIP = {3: Image.Transpose.ROTATE_180, 5: Image.Transpose.ROTATE_90, 6: Image.Transpose.ROTATE_270}


def _embedded(path: Path) -> bytes | None:
    """The JPEG a RAW carries inside it, upright, or None when it has none."""
    import rawpy  # ImportError is handled by the caller

    try:
        with rawpy.imread(str(path)) as raw:
            t = raw.extract_thumb()
            flip = raw.sizes.flip
    except Exception as e:
        if "Thumbnail" in type(e).__name__:
            return None
        raise
    if t.format != rawpy.ThumbFormat.JPEG:  # pyright: ignore[reportPrivateImportUsage]
        return None
    data = bytes(t.data)
    if flip in _FLIP:
        # LibRaw's flip, checked against postprocess on portrait ARWs (5 = ROTATE_90). Sony's
        # JPEG carries an Orientation tag, which exif_transpose already honours: only tagless ones turn
        with Image.open(io.BytesIO(data)) as im:
            if im.getexif().get(0x0112) not in range(2, 9):  # none, 0 or "normal": the RAW's flip decides
                data = _jpeg(im.transpose(_FLIP[flip]), 92)
    return data


def _prepare(d: Path, name: str, out: Path, sync_any: bool = False) -> dict:
    """Make the thumb (and RAW preview) for d/name into out/. Returns names and a status."""
    res = {"preview": None, "thumb": None, "status": "none"}
    p = d / name
    ext = p.suffix.lower()
    try:
        out.mkdir(exist_ok=True)
        if ext in IMAGE_EXT:
            _save_thumb(p, out / (name + ".thumb.jpg"))
            res["thumb"] = name + ".thumb.jpg"
        elif ext in RAW_EXT:
            data = _embedded(p)
            if data is None:
                res["status"] = "failed: no embedded preview" if sync_any else "making"
                return res
            _save_thumb(io.BytesIO(data), out / (name + ".thumb.jpg"))
            res["thumb"] = name + ".thumb.jpg"
            with Image.open(io.BytesIO(data)) as im:
                big = max(im.size) >= BIG_EDGE
            if big or sync_any:
                _write_bytes(out / (name + ".preview.jpg"), data)  # the page may be fetching it
                res["preview"] = name + ".preview.jpg"
                res["status"] = "ready"
            else:
                res["status"] = "making"
    except ImportError:
        res["status"] = NO_RAWPY
    except Exception as e:
        # the source could not be read just now (held open, EIO): worth another try.
        # PIL decode errors are OSErrors with no errno; rawpy's read error is its own type.
        # A held thumb or preview being written (or .previews) is retried the same way.
        if (isinstance(e, OSError) and e.errno in _TRANSIENT) or type(e).__name__ == "LibRawIOError":
            log.info("viewer: %s not readable or writable now: %s", p, e)
            res["status"], res["retry"] = "failed: could not read or save it just now", True
            return res
        log.warning("viewer: preview failed for %s: %s", p, e)
        if ext in RAW_EXT:
            res["status"] = f"failed: {e}"[:200]
    return res


def _combine(statuses: list[str]) -> str:
    """One item-level status from the per-RAW ones."""
    for s in statuses:
        if s.startswith("failed"):
            return s
    if "making" in statuses:
        return "making"
    return "ready" if "ready" in statuses else "none"


def _public(meta: dict, d: Path) -> dict:
    iid = meta["id"]

    def url(n):
        return f"/viewer/file/{iid}/{quote(n)}" if n else None

    files = []
    for f in meta["files"]:
        try:
            size = (d / f["name"]).stat().st_size
        except OSError:
            size = 0
        files.append({
            "name": f["name"], "orig": f.get("orig") or f["name"],
            "label": f.get("label") or f["name"], "size": size,
            "src": f.get("src"), "path": _win(d / f["name"]),
            "url": url(f["name"]), "thumb_url": url(f.get("thumb")),
            "preview_url": url(f.get("preview")), "kind": _file_kind(f["name"]),
        })
    return {
        "id": iid, "kind": meta["kind"], "title": meta["title"],
        "created": meta.get("created") or "", "source": meta.get("source") or "",
        "url": meta.get("url"), "framable": meta.get("framable"),
        "preview_status": _status(meta), "files": files,
    }


def _status(meta: dict) -> str:
    """The item's preview status; a "making" with no progress for MAKING_SECS reads as
    failed, since a preview child killed outright (OOM, SIGKILL) never writes its result.
    Progress is time.time() at commit and at each finished preview, so a long batch worked
    one RAW at a time is not cut off."""
    st = meta.get("preview_status") or "none"
    if st == "making":
        try:
            t = meta.get("progress")
            if not isinstance(t, (int, float)):  # an item from before progress existed
                t = datetime.fromisoformat(meta.get("created") or "").timestamp()
            if time.time() - t > MAKING_SECS:
                return "failed: preview did not finish"
        except (ValueError, TypeError):
            pass
    return st


def _load(d: Path) -> dict:
    meta = json.loads((d / "item.json").read_text(encoding="utf-8"))
    if not isinstance(meta, dict) or meta["id"] != d.name:
        raise ValueError("bad item.json")
    if not isinstance(meta["files"], list) or not all(
            isinstance(f, dict) and isinstance(f.get("name"), str) for f in meta["files"]):
        raise ValueError("files not a list of named entries")
    if not isinstance(meta["kind"], str) or not isinstance(meta["title"], str):
        raise ValueError("kind/title not strings")
    return _public(meta, d)


def _loose(entry: os.DirEntry, st: os.stat_result, seen: float) -> dict:
    name, sig = entry.name, _sig(st)
    # the id and the ?v= on its URLs change with the file, so a replaced photo is
    # a new card and the browser fetches the new picture instead of its cached one
    iid = "loose-" + hashlib.sha1(f"{name}{sig}".encode()).hexdigest()[:10]
    prev = ROOT / ".previews"
    res = {"preview": None, "thumb": None, "status": "none"}
    if os.path.splitext(name)[1].lower() in IMAGE_EXT | RAW_EXT:
        th, pv = prev / (name + ".thumb.jpg"), prev / (name + ".preview.jpg")
        # <name>.sig holds the size:mtime the thumb was made from (or failed at) and the
        # status: the file is only decoded again once it changes (a half-copied file
        # changes size), never because of clocks (camera mtimes in the future, WSL drift)
        mark = prev / (name + ".sig")
        try:
            got, _, why = mark.read_text().partition("\n")
        except (OSError, ValueError):
            got = why = ""
        if got == sig and why.startswith("failed"):
            res["status"] = why
        elif got == sig and th.exists():
            res["thumb"] = name + ".thumb.jpg"
            if pv.exists():
                res["preview"], res["status"] = name + ".preview.jpg", "ready"
        elif (tr := _tries.get(name)) and tr[0] == sig and time.monotonic() - tr[1] < RETRY_SECS:
            # failed passingly moments ago: not decoded again yet. The thumb only when that
            # attempt saved it (a preview write was held), never an older version's
            res["status"], res["thumb"] = tr[2:]
            if res["status"] == "ready" and pv.exists():  # decoded fine, only its .sig was held
                res["preview"] = name + ".preview.jpg"
        else:
            # the old .sig goes before any decode, since the decode rewrites the thumb; held,
            # nothing is decoded, so it can never vouch for another version's thumb
            try:
                mark.unlink(missing_ok=True)
                # ponytail: loose RAWs use the embedded JPEG whatever its size; no background upgrade
                res = _prepare(ROOT, name, prev, sync_any=True)
            except OSError as e:
                log.info("viewer: %s not removed: %s", mark.name, e)
                res = {**res, "status": "failed: could not read or save it just now", "retry": True}
            if not res["thumb"] and not res["status"].startswith("failed"):
                res["status"] = "failed: could not make a preview"
            if res.get("retry"):
                # ponytail: a passing error writes no .sig and is tried again at most once per
                # RETRY_SECS, never given up on, so it recovers once released; a file
                # damaged for good costs one decode a minute while the Viewer is open
                # (monotonic: WSL clock steps). A thumb an earlier try of this same version
                # saved still counts (thumbs are written by rename, so never cut off)
                tr = _tries.get(name)
                res["thumb"] = res["thumb"] or (tr[3] if tr and tr[0] == sig else None)
                _tries[name] = (sig, time.monotonic(), res["status"], res["thumb"])
            else:
                _tries.pop(name, None)
                if res["status"] != NO_RAWPY:  # rawpy missing is retried every rebuild
                    try:  # half-written, it just won't match and the file is tried again
                        mark.write_text(f"{sig}\n{res['status']}")
                    except (OSError, ValueError) as e:
                        log.info("viewer: %s not written: %s", mark.name, e)
                        # no .sig to stop a decode every rebuild: wait RETRY_SECS like any held write
                        _tries[name] = (sig, time.monotonic(), res["status"], res["thumb"])
    u = lambda n: f"/viewer/file/loose/{quote(n)}?v={quote(sig)}" if n else None  # noqa: E731
    return {
        "id": iid, "kind": "upload", "title": name,
        "created": datetime.fromtimestamp(seen).isoformat(timespec="seconds"),
        "source": "You", "url": None, "framable": None, "preview_status": res["status"],
        "files": [{
            "name": name, "orig": name, "label": name, "size": st.st_size,
            "src": None, "path": _win(ROOT / name),
            "url": u(name), "thumb_url": u(res["thumb"]), "preview_url": u(res["preview"]),
            "kind": _file_kind(name),
        }],
    }


# ---- publish ---------------------------------------------------------------

def stage(title: str) -> tuple[str, Path]:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "item"
    (ROOT / ".staging").mkdir(parents=True, exist_ok=True)
    while True:
        item_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}-{slug}"
        d = ROOT / ".staging" / item_id
        try:
            d.mkdir()  # exclusive: a clash retries with a new suffix
        except FileExistsError:
            continue
        _pending[str(d)] = []
        return item_id, d


def _reserved(name: str) -> bool:
    """Names the store writes itself inside an item folder (temp files are hidden,
    and upload names lose leading dots). Case-blind: /mnt/c folders are."""
    name = name.lower()
    return name == "item.json" or name.endswith((".thumb.jpg", ".preview.jpg"))


def add_file(staging: Path, src: Path | BinaryIO, orig_name: str) -> str:
    orig = orig_name.replace("\\", "/").rsplit("/", 1)[-1].strip().lstrip(".") or "file"
    stem, ext = os.path.splitext(orig)
    name, n = orig, 1
    taken = {p.name.lower() for p in staging.iterdir()}
    while _reserved(name) or name.lower() in taken:
        n += 1
        name = f"{stem}-{n}{ext}"
    with open(staging / name, "xb") as out:
        if isinstance(src, (str, Path)):
            with open(src, "rb") as f:
                shutil.copyfileobj(f, out, 1 << 20)
        else:
            shutil.copyfileobj(src, out, 1 << 20)
    src_path = _win(Path(src).resolve()) if isinstance(src, (str, Path)) else None
    _pending.setdefault(str(staging), []).append((name, orig, src_path))
    return name


def commit(item_id, staging, *, kind, title, source, labels=None, url=None, framable=None) -> dict:
    staging = Path(staging)
    order = _pending.pop(str(staging), None)
    if order is None:
        order = [(p.name, p.name, None) for p in sorted(staging.iterdir()) if p.name != "item.json"]
    labels = labels or []
    files, statuses, making = [], [], []
    for i, (name, orig, src) in enumerate(order):
        r = _prepare(staging, name, staging)
        if r.get("retry"):  # a RAW gets the background child, which reads it again and
            # fills in the thumb; another image shows itself without one
            r["status"] = "making" if Path(name).suffix.lower() in RAW_EXT else "none"
        statuses.append(r["status"])
        if r["status"] == "making":
            making.append(name)
        files.append({"name": name, "orig": orig, "src": src, "label": labels[i] if i < len(labels) else name,
                      "preview": r["preview"], "thumb": r["thumb"]})
    meta = {"id": item_id, "kind": kind, "title": title,
            "created": datetime.now().isoformat(timespec="microseconds"), "source": source,
            "files": files, "url": url, "framable": framable,
            "preview_status": _combine(statuses), "progress": time.time()}
    _write_json(staging / "item.json", meta)
    final = ROOT / item_id
    os.replace(staging, final)
    global _cache
    _cache = None
    prune()
    if making:
        # one child works the RAWs in turn: each full demosaic holds ~300 MB, so fifty at once can OOM WSL
        try:
            subprocess.Popen(
                [sys.executable, "-m", "viewer.store", "--make-previews", str(final), *making],
                cwd=_HUB_DIR, start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            for name in making:
                _finish_preview(final, name, None, f"failed: {e}"[:200])
    return _public(meta, final)


def publish(paths: list[Path], *, title=None, labels=None, source="Claude") -> dict:
    paths = [Path(p) for p in paths]
    kinds = {_file_kind(p.name) for p in paths}
    kind = kinds.pop() if len(kinds) == 1 else "file"
    title = title or paths[0].name
    item_id, staging = stage(title)
    try:
        for p in paths:
            add_file(staging, p, p.name)
        return commit(item_id, staging, kind=kind, title=title, source=source, labels=labels)
    except BaseException:
        discard(staging)
        raise


def discard(staging: Path) -> None:
    """Throw away a staged item that will never be committed."""
    _pending.pop(str(staging), None)
    shutil.rmtree(staging, ignore_errors=True)


# ---- RAW background preview ------------------------------------------------

def _finish_preview(d: Path, name: str, preview: str | None, failure: str | None) -> None:
    """Record a finished (or failed) preview in item.json, atomically."""
    # The driver works one RAW at a time, but a hand rerun or a second driver may overlap; the lock keeps each update.
    try:
        with open(d / ".item.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            _update_preview(d, name, preview, failure)
    except FileNotFoundError:
        return  # item pruned meanwhile


def _update_preview(d: Path, name: str, preview: str | None, failure: str | None) -> None:
    meta_path = d / "item.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return  # item pruned or unreadable: nothing to update
    # any other read error (held) raises, so the child exits non-zero and the driver retries the record
    raws = [f for f in meta["files"] if os.path.splitext(f["name"])[1].lower() in RAW_EXT]
    for f in meta["files"]:
        if f["name"] == name and preview:
            f["preview"] = preview
            if not f.get("thumb"):
                try:
                    _save_thumb(d / preview, d / (name + ".thumb.jpg"))
                    f["thumb"] = name + ".thumb.jpg"
                except Exception as e:
                    log.warning("viewer: thumb failed for %s: %s", name, e)
    if failure:
        meta["preview_status"] = failure
    elif all(f.get("preview") for f in raws):
        meta["preview_status"] = "ready"
    meta["progress"] = time.time()  # this clock, like "created": a drvfs mtime is stamped by Windows
    _write_json(meta_path, meta)


def _make_previews(item_dir: str, names: list[str]) -> None:
    """The item's one background child: each RAW in its own process, in turn, so a crash or
    an OOM kill on one costs that preview only and the rest still get theirs. Its log and
    the children's tracebacks go to <item>/.preview.log (hidden, never served, pruned with it)."""
    d = Path(item_dir)
    for name in names:
        try:
            try:
                err = open(d / ".preview.log", "ab")
            except OSError:  # a held log never costs the preview
                err = open(os.devnull, "wb")
            with err:
                try:
                    # a hung decode never blocks the rest; under MAKING_SECS, so start-up and
                    # recording fit before the feed calls the item stuck
                    rc = subprocess.run(
                        [sys.executable, "-m", "viewer.store", "--make-preview", item_dir, name],
                        cwd=_HUB_DIR, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=err, timeout=MAKING_SECS // 2).returncode
                except subprocess.TimeoutExpired:
                    rc = None
            if rc != 0:
                # the preview is written whole by rename before it is recorded: one that exists
                # only lost its record (item.json held) and is recorded now, not failed
                pv = d / (name + ".preview.jpg")
                if pv.is_file():
                    _finish_preview(d, name, pv.name, None)
                else:
                    _finish_preview(d, name, None, "failed: preview did not finish")
        except Exception as e:  # item.json held, say: the next RAW is still worked
            log.warning("viewer: preview of %s not recorded: %s", name, e)


def _make_preview(item_dir: str, name: str) -> None:
    d = Path(item_dir)
    out = d / (name + ".preview.jpg")
    try:
        import rawpy
        with rawpy.imread(str(d / name)) as raw:
            rgb = raw.postprocess(use_camera_wb=True)
        _write_bytes(out, _jpeg(Image.fromarray(rgb), 92))
    except ImportError:
        return _finish_preview(d, name, None, NO_RAWPY)
    except Exception as e:
        return _finish_preview(d, name, None, f"failed: {e}"[:200])
    _finish_preview(d, name, out.name, None)


# ---- read side -------------------------------------------------------------

def _fresh(c, m, now) -> bool:
    # a background preview rewrites item.json one level down, which the root
    # mtime does not see, so while one is in flight every poll rebuilds
    # (_status turns a "making" past MAKING_SECS into failed, which ends this)
    return bool(c and c[0] == str(ROOT) and c[1] == m and now - c[2] < 30
                and not any(i["preview_status"] == "making" for i in c[3]))


def feed() -> list[dict]:
    global _cache, _last_prune
    ROOT.mkdir(parents=True, exist_ok=True)
    m, now = ROOT.stat().st_mtime_ns, time.time()
    if _cache and _fresh(_cache, m, now):
        return _cache[3]
    # ponytail: one rebuild at a time, so overlapping polls wait for it instead of
    # decoding the same loose files in parallel; a first big drop still blocks that one poll
    with _rebuild:
        if _cache and _fresh(_cache, m, now):
            return _cache[3]
        if now - _last_prune > 3600:
            prune()
        cutoff = datetime.now() - timedelta(days=KEEP_DAYS)
        items = []
        entries, stats, seen, _ = _scan()
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    t = _id_time(e.name)
                    if ID_RE.match(e.name) and t and t >= cutoff:
                        items.append(_load(Path(e.path)))
                elif (st := stats.get(e.name)) and datetime.fromtimestamp(seen[e.name]) >= cutoff:
                    items.append(_loose(e, st, seen[e.name]))
            except Exception as ex:
                log.warning("viewer: skipping %s: %s", e.name, ex)
        items.sort(key=lambda i: (i["created"], i["id"]), reverse=True)
        _cache = (str(ROOT), m, now, items)
        return items


def resolve(item_id: str, name: str) -> Path | None:
    if not isinstance(item_id, str) or not isinstance(name, str):
        return None
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
        return None
    cutoff = datetime.now() - timedelta(days=KEEP_DAYS)
    try:
        if item_id == "loose":
            if name.startswith("."):
                return None
            p = base = ROOT / name
            if not p.is_file():
                p = ROOT / ".previews" / name
                base = ROOT / re.sub(r"\.(thumb|preview)\.jpg$", "", name)
                if base.name == name or not base.is_file():
                    return None
            first = _read_seen(set_aside=False)[0].get(base.name)
            if first and datetime.fromtimestamp(first[0]) < cutoff:
                return None
        else:
            t = _id_time(item_id) if ID_RE.match(item_id) else None
            if not t or t < cutoff:
                return None
            d = ROOT / item_id
            if d.is_symlink():
                return None
            meta = json.loads((d / "item.json").read_text(encoding="utf-8"))
            listed = set()
            for f in meta["files"]:
                listed.update(f.get(k) for k in ("name", "preview", "thumb"))
            if name not in listed:
                return None
            p = d / name
        if p.is_symlink() or not p.is_file():
            return None
        if ROOT.resolve() not in p.resolve().parents:
            return None
        return p
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def prune(now: datetime | None = None) -> int:
    global _last_prune
    now = now or datetime.now()
    _last_prune = time.time()
    cutoff = now - timedelta(days=KEEP_DAYS)
    removed = 0

    def rm(p: Path) -> bool:
        nonlocal removed
        try:
            shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
            removed += 1
            return True
        except OSError as e:
            log.info("viewer: prune skipped %s: %s", p, e)
            return False

    gone = []

    try:
        # a loose file ages from when it first showed up here, never from its own mtime
        entries, stats, seen, read = _scan()
    except OSError as e:  # commit runs this after the item is live: never fail the publish
        log.info("viewer: prune skipped: %s", e)
        return 0
    # seen.json unread: its stand-in may be stale, so no loose file is deleted on it
    if not read:
        seen = {}
    for e in entries:
        try:
            if e.is_dir(follow_symlinks=False):
                t = _id_time(e.name) if ID_RE.match(e.name) else None
                if t and t < cutoff:  # a name it cannot date is never touched
                    rm(Path(e.path))
            elif e.name in seen and datetime.fromtimestamp(seen[e.name]) < cutoff:
                # the scan is over: a file dropped over this one since then is a new file
                # ponytail: stat-then-unlink still leaves a sub-ms gap; no atomic unlink-if on POSIX
                st = stats[e.name]
                if st is None or _sig(os.stat(e.path)) != _sig(st):  # unstat-able: left alone
                    continue
                if rm(Path(e.path)):
                    gone.append((e.name, _sig(st)))
                for suffix in SIDECARS:
                    (ROOT / ".previews" / (e.name + suffix)).unlink(missing_ok=True)
        except OSError:
            continue
    if gone:
        _forget(gone)
    _sweep_previews(stats, now)
    staging = ROOT / ".staging"
    old = []
    try:  # same as the scan: never fail the publish over the staging sweep
        with os.scandir(staging) as it:
            for e in it:
                try:
                    if now.timestamp() - e.stat().st_mtime > 86400:
                        old.append(Path(e.path))
                except OSError:  # committed meanwhile, or held: the others are still swept
                    continue
    except OSError as e:
        if not isinstance(e, FileNotFoundError):
            log.info("viewer: staging sweep skipped: %s", e)
    for p in old:
        rm(p)
    return removed


def _sweep_previews(stats: dict, now: datetime) -> None:
    """Thumbs, previews and .sig files whose loose file left by hand (a delete or move in
    Explorer, not prune), and dead temp files. A day old first, so nothing in flight goes;
    seen.json and its set-aside copies are never touched. Not counted in prune's total."""
    prev = ROOT / ".previews"
    try:
        with os.scandir(prev) as it:
            names = [e.name for e in it]
    except OSError:
        return
    for n in names:
        if n.startswith("seen.json"):
            continue
        if n.endswith(".tmp"):
            orphan = True  # no write takes a day
        else:
            suffix = next((x for x in SIDECARS if n.endswith(x)), None)
            orphan = bool(suffix) and n[:-len(suffix)] not in stats  # a held file is in stats as None: kept
        if not orphan:
            continue
        p = prev / n
        try:
            if now.timestamp() - p.stat().st_mtime > 86400 and not p.is_dir():
                p.unlink()
        except OSError as e:
            log.info("viewer: prune skipped %s: %s", p, e)


def _forget(gone: list[tuple[str, str]]) -> None:
    """Drop the arrival entries of loose files prune deleted, so the same file moved back
    in (Explorer keeps its mtime, so the same sig) starts a new 30 days, not the old ones."""
    global _unsaved
    gone_map = dict(gone)

    def was(n, v):  # this entry is the deleted file's (an older-format entry fits any file)
        return n in gone_map and v[1] in (None, gone_map[n])
    with _seen_lock:
        disk, writable = _read_seen()  # first: a corrupt copy's rebuild refills _unsaved
        _unsaved = {n: v for n, v in _unsaved.items() if not was(n, v)}
        for n in gone_map:  # its thumb and preview are gone with it
            _tries.pop(n, None)
        if not writable:
            return
        # after a set-aside seen.json is gone and the other files' times sit in _unsaved:
        # written now, so a process that exits (the CLI's publish) does not lose them
        keep = {n: v for n, v in {**_unsaved, **disk}.items() if not was(n, v)}
        if keep == disk:
            return
        try:
            _save_seen(keep)
            _unsaved = {}
        except OSError as e:
            # ponytail: the stale entry stays until the next scan misses the file and drops it;
            # a file moved back before that scan inherits the old time. Retry here if that bites
            log.info("viewer: seen.json not updated after prune: %s", e)


def uploads(since: datetime | None = None) -> list[dict]:
    if since is not None and since.tzinfo:
        since = since.astimezone().replace(tzinfo=None)
    out = []
    for it in feed():
        if it["kind"] != "upload":
            continue
        if since and datetime.fromisoformat(it["created"]) < since:
            continue
        out.append({"id": it["id"], "title": it["title"], "created": it["created"], "paths": paths(it)})
    return out


def paths(it: dict) -> list[str]:
    """Absolute stored paths of a feed item's files."""
    base = ROOT if it["id"].startswith("loose-") else ROOT / it["id"]
    return [str(base / f["name"]) for f in it["files"]]


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--make-previews":
        try:
            logging.basicConfig(filename=Path(sys.argv[2]) / ".preview.log", level=logging.INFO)
        except OSError:  # held or pruned: the RAWs are still worked
            logging.basicConfig(level=logging.INFO)
        _make_previews(sys.argv[2], sys.argv[3:])
    elif len(sys.argv) == 4 and sys.argv[1] == "--make-preview":
        logging.basicConfig(level=logging.INFO)  # stderr, which the driver points at .preview.log
        _make_preview(sys.argv[2], sys.argv[3])

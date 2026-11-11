"""Workbench Hub blueprint: routes under /workbench.

Specs and plans are read live off disk and rendered to HTML with Python-
Markdown; approvals are appended to data/workbench.db through workbench.store.
No init() needed: store.py resolves the vault via vault_path.vault_root()
directly (artifacts/forge pattern). Design doc: docs/specs/
2026-09-24-build-creation-mode-design.md §3.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import tempfile
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import markdown
from flask import Blueprint, Response, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent))
import docview  # noqa: E402
import store  # noqa: E402

bp = Blueprint(
    "workbench",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/workbench",
)

_FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
_MD_EXTENSIONS = ["tables", "fenced_code"]

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_TASK_SIZE_RE = re.compile(r"^### Task \d+:.*~(\d+)k\s*$", re.MULTILINE)
_RUNS_AS_RE = re.compile(r"\*\*Runs as:\*\*\s*(\w+)")

_LIST_KINDS = ("spec", "plan")


def _render_markdown(text: str) -> str:
    return markdown.markdown(text, extensions=_MD_EXTENSIONS)


# ── Page ──────────────────────────────────────────────────────────────────


@bp.route("/")
def index():
    page = _FRONTEND_DIR / "workbench.html"
    if page.is_file():
        return page.read_text(encoding="utf-8")
    # ponytail: real page is Task 4; this keeps /workbench alive meanwhile.
    return Response(
        "<html><body><h1>Workbench</h1><p>Coming soon.</p></body></html>",
        mimetype="text/html",
    )


# ── docs listing ─────────────────────────────────────────────────────────


def _doc_summary(kind: str, path: Path) -> dict:
    # path is already under the resolved root: a per-file resolve() cost ~9 lstats
    # each on /mnt/c, which was a third of the list's 2s.
    raw = path.read_bytes()  # one read: the hash must be of the exact bytes store.doc_hash sees
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    stem = path.stem
    m = _DATE_RE.match(stem)
    date = m.group(1) if m else None
    slug = stem[m.end():] if m else stem
    if slug.endswith("-design"):
        slug = slug[: -len("-design")]
    title_m = _TITLE_RE.search(text)
    item = {
        "filename": path.name,
        "path": str(path),
        "slug": slug,
        "title": title_m.group(1).strip() if title_m else stem,
        "date": date,
        "_mtime": path.stat().st_mtime,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    if kind == "plan":
        runs_m = _RUNS_AS_RE.search(text)
        item["runs_as"] = runs_m.group(1) if runs_m else None
        sizes = [int(n) for n in _TASK_SIZE_RE.findall(text)]
        item["task_size_k"] = sum(sizes) if sizes else None
    return item


@bp.route("/api/docs", methods=["GET"])
def api_docs():
    kind = request.args.get("kind")
    if kind not in _LIST_KINDS:
        return jsonify({"error": f"kind must be one of {_LIST_KINDS}"}), 400
    root = store._roots()[kind].resolve()
    # A plan's `-gates.md` sibling rides along in /api/doc, never as its own row.
    with os.scandir(root) as it:
        paths = [root / e.name for e in it
                 if e.name.endswith(".md") and e.is_file() and not e.name.endswith("-gates.md")]
    # threads, not a loop: each open/stat is ~5ms of /mnt/c latency, not CPU.
    with ThreadPoolExecutor(max_workers=16) as pool:
        items = list(pool.map(lambda f: _doc_summary(kind, f), paths))
    items.sort(key=lambda d: (d["date"] or "", d["_mtime"]), reverse=True)
    for d in items:
        del d["_mtime"]
    return jsonify(items)


# ── single doc, rendered ────────────────────────────────────────────────


def _infer_kind(path_str: str):
    """Which root (spec or plan) path_str resolves under, or (None, resolved)
    if it lands outside both: the same containment check store._validate_doc_path
    uses, just without a kind given up front."""
    resolved = Path(path_str).resolve()
    roots = store._roots()
    for kind in _LIST_KINDS:
        root = roots[kind].resolve()
        if resolved == root or root in resolved.parents:
            return kind, resolved
    return None, resolved


@bp.route("/api/doc", methods=["GET"])
def api_doc():
    path_param = request.args.get("path", "")
    if not path_param:
        return jsonify({"error": "path required"}), 400
    kind, resolved = _infer_kind(path_param)
    if kind is None:
        return jsonify({"error": f"path must be under the specs or plans root: {path_param}"}), 400
    if not resolved.is_file():
        return jsonify({"error": f"not found: {resolved}"}), 404

    text = resolved.read_text(encoding="utf-8")
    # glance + folding sections; plain Markdown when the doc does not parse
    html = docview.render(text, kind) or _render_markdown(text)
    payload = {
        "path": str(resolved),
        "kind": kind,
        "html": html,
        "sha256": store.doc_hash(resolved),
    }
    if kind == "plan":
        gates_path = resolved.with_name(resolved.stem + "-gates.md")
        if gates_path.is_file():
            payload["gates_html"] = _render_markdown(gates_path.read_text(encoding="utf-8"))
    return jsonify(payload)


# ── decide ───────────────────────────────────────────────────────────────


@bp.route("/api/decide", methods=["POST"])
def api_decide():
    data = request.get_json(force=True, silent=True) or {}
    slug = data.get("slug")
    kind = data.get("kind")
    path = data.get("path")
    rendered_sha256 = data.get("rendered_sha256")
    verdict = data.get("verdict")
    choice = data.get("choice")
    comment = data.get("comment")

    if not slug:
        return jsonify({"error": "slug required"}), 400
    if kind not in store.KINDS:
        return jsonify({"error": f"kind must be one of {store.KINDS}"}), 400
    if verdict not in store.VERDICTS:
        return jsonify({"error": f"verdict must be one of {store.VERDICTS}"}), 400
    if verdict == "sent_back" and not comment:
        return jsonify({"error": "comment required for sent_back"}), 400

    doc_path = None
    if path:
        try:
            doc_path = store._validate_doc_path(kind, path)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    try:
        row = store.record(
            slug,
            kind,
            doc_path,
            verdict,
            choice=choice,
            comment=comment,
            expected_sha256=rendered_sha256,
        )
    except store.StaleDocument as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 503

    return jsonify(row), 201


# ── history ──────────────────────────────────────────────────────────────


@bp.route("/api/history", methods=["GET"])
def api_history():
    # Doc snapshots (whole spec/plan text, ~1.9 MB of the 2.25 MB list on 2026-11-03) stay
    # server-side until a row is opened (/api/history/snapshot); mark snapshots are small
    # JSON the list itself reads, so they ride along.
    with store._conn() as conn:
        rows = conn.execute(
            "SELECT id, seq, build_slug, kind, doc_path, doc_sha256, verdict, choice, comment,"
            " CASE WHEN kind = 'mark' THEN snapshot END AS snapshot, decided_at"
            " FROM decisions ORDER BY decided_at DESC, rowid DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/api/history/snapshot", methods=["GET"])
def api_history_snapshot():
    with store._conn() as conn:
        row = conn.execute("SELECT snapshot FROM decisions WHERE id = ?",
                           (request.args.get("id", ""),)).fetchone()
    if row is None:
        return jsonify({"error": "no such decision"}), 404
    return jsonify({"snapshot": row["snapshot"]})


@bp.route("/api/short-titles", methods=["POST"])
def api_short_titles():
    """{title: 2-4 word name} for the build list; see names.py."""
    import names
    titles = (request.get_json(silent=True) or {}).get("titles")
    if not isinstance(titles, list):
        return jsonify({"error": "titles must be a list"}), 400
    return jsonify(names.short_names(titles))


# ── options (UI option sets from /workbench) ──────────────────────────────

_OPTION_FILES = ("head.html", "styles.css", "options.html")
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL)


def _option_dir(set_slug: str):
    """The option folder for set_slug, or None if it escapes the options
    root or does not exist. Same containment check as decide."""
    if not set_slug:
        return None
    try:
        folder = store._validate_doc_path("design", store._roots()["design"] / set_slug)
    except ValueError:
        return None
    if folder == store._roots()["design"].resolve() or not folder.is_dir():
        return None
    return folder


def _read(f: Path) -> str | None:
    try:
        return f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# set dir -> (file stat signature, sha256): a set is rehashed only when a file in
# it is added, removed or rewritten, not on every list load
READY_STAMP_SINCE = 1794274800  # 2026-11-10 UTC, when shot_set.py began writing ready.txt
#
# Both caches are keyed on a digest of the set's file signature and kept on native disk
# (_CACHE_FILE), so a Hub restart does not re-read all 93 MB of sets to rehash them:
# that made the first Workbench load after each restart 3.3 s (2026-11-10, ~19 restarts
# that day). ponytail: one JSON file, rewritten when a set changed; never pruned beyond
# dropping sets that are gone.
_HASH_CACHE: dict[str, tuple[str, str]] = {}
_META_CACHE: dict[str, tuple[str, list]] = {}
_CACHE_FILE = Path.home() / ".cache" / "hub-workbench-options.json"
_loaded_from_disk = False


def _persists(root: Path) -> bool:
    # test vaults live under the temp dir; they must not overwrite the real cache
    return not str(root.resolve()).startswith(tempfile.gettempdir())


def _load_caches(root: Path) -> None:
    global _loaded_from_disk
    if _loaded_from_disk or not _persists(root):
        return
    _loaded_from_disk = True
    try:
        disk = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        for k, v in disk.get("hash", {}).items():
            _HASH_CACHE.setdefault(k, tuple(v))
        for k, v in disk.get("meta", {}).items():
            _META_CACHE.setdefault(k, tuple(v))
    except (OSError, ValueError, AttributeError, TypeError):
        pass


def _save_caches(root: Path, live: set[str]) -> None:
    if not _persists(root):
        return
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "hash": {k: v for k, v in _HASH_CACHE.items() if k in live},
            "meta": {k: v for k, v in _META_CACHE.items() if k in live},
        }), encoding="utf-8")
        tmp.replace(_CACHE_FILE)
    except OSError:
        pass                     # the disk copy is only a speed-up


def _files(top: str):
    """(dir, name, stat) for every file under top. scandir's entry.stat is ~3x
    faster than os.walk + os.stat on /mnt/c (0.3 s against 0.9 s for 749 files,
    threaded, 2026-11-10)."""
    with os.scandir(top) as it:
        for e in it:
            try:
                if e.is_dir(follow_symlinks=False):
                    yield from _files(e.path)
                else:
                    yield top, e.name, e.stat(follow_symlinks=False)
            except OSError:
                continue         # removed mid-walk


def _option_item(d: Path, real_root: Path) -> dict:
    newest = 0
    sig = set()
    build_sig = None
    ready_at = None
    for top, name, st in _files(str(d)):
        if top == str(d) and name == "build.txt":
            build_sig = (st.st_mtime_ns, st.st_size)
            continue
        if top == str(d) and name == "ready.txt":
            ready_at = st.st_mtime
            continue
        newest = max(newest, st.st_mtime)
        sig.add((top, name, st.st_mtime_ns, st.st_size))
    sig = hashlib.md5(json.dumps(sorted(sig)).encode(), usedforsecurity=False).hexdigest()
    # The three reads below were 0.75 s of every list (228 reads on /mnt/c,
    # 2026-10-22) for files the walk above already stat'd, so they are kept
    # against those stats the same way the hash is.
    meta_key = f"{sig}|{build_sig}"
    meta = _META_CACHE.get(str(d))
    if meta and meta[0] == meta_key:
        title, build, cards = meta[1]
    else:
        head = _read(d / "head.html")
        m = _H1_RE.search(head) if head else None
        title = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else d.name
        build = (_read(d / "build.txt") or "").strip() or None  # a bad link fails open: ungrouped
        cards = len(_CARD_RE.findall(_read(d / "options.html") or ""))
        _META_CACHE[str(d)] = (meta_key, [title, build, cards])
    hit = _HASH_CACHE.get(str(d))
    if hit and hit[0] == sig:
        sha256 = hit[1]
    else:
        try:
            sha256 = store.doc_hash(d)
            _HASH_CACHE[str(d)] = (sig, sha256)
        except OSError:  # a set being rewritten mid-walk: no hash this load, never a failed list
            sha256 = None
    return {
        "slug": d.name,
        "build": build,
        "path": str(real_root / d.name),
        "title": title,
        "cards": cards,
        # shot_set.py stamps ready.txt on a passing check: a set still being written (or edited since)
        # stays out of Waiting on you. Sets last written before the stamp existed count as ready.
        "ready": cards > 0 and (ready_at >= newest if ready_at is not None else newest < READY_STAMP_SINCE),
        "mtime": newest,
        "sha256": sha256,
    }


@bp.route("/api/options", methods=["GET"])
def api_options():
    root = store._roots()["design"]
    dirs = [d for d in (root.iterdir() if root.is_dir() else [])
            if d.is_dir() and not d.name.startswith(".")]
    real_root = root.resolve()
    # The walk is latency-bound on the Windows drive, not CPU-bound: run the sets side by side.
    _load_caches(root)
    before = (dict(_HASH_CACHE), dict(_META_CACHE))
    with ThreadPoolExecutor(max_workers=16) as ex:
        items = list(ex.map(lambda d: _option_item(d, real_root), dirs))
    live = {str(d) for d in dirs}
    if before != (_HASH_CACHE, _META_CACHE) or not live >= set(_HASH_CACHE):
        _save_caches(root, live)
    items.sort(key=lambda d: d["mtime"], reverse=True)
    return jsonify(items)


@bp.route("/api/option", methods=["GET"])
def api_option():
    folder = _option_dir(request.args.get("set", ""))
    if folder is None:
        return jsonify({"error": "set must name a folder under the options root"}), 400
    payload = {"slug": folder.name, "path": str(folder), "sha256": store.doc_hash(folder)}
    for name in _OPTION_FILES:
        f = folder / name
        payload[name.split(".")[0]] = f.read_text(encoding="utf-8") if f.is_file() else ""
    return jsonify(payload)


@bp.route("/api/option/asset", methods=["GET"])
def api_option_asset():
    """A file under a set's assets/ folder: lossless stills, and the css/js a
    live preview injects into its iframe. send_from_directory refuses paths
    that climb out of assets/."""
    folder = _option_dir(request.args.get("set", ""))
    if folder is None:
        return jsonify({"error": "set must name a folder under the options root"}), 400
    return send_from_directory(folder / "assets", request.args.get("path", ""), max_age=0)


# Cards are sibling <article class="opt"> blocks; the page letters them in
# document order, so card N here is letter N there.
_CARD_RE = re.compile(r'(?=<article\b[^>]*\bclass="[^"]*\bopt\b)')


_H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.DOTALL)


class CardMismatch(ValueError):
    """The card at a letter is not the one the page showed there."""


def card_title(card: str) -> str:
    m = _H2_RE.search(card)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip() if m else ""


def drop_cards(text: str, letters, titles=None) -> str:
    """options.html with the cards at these letters removed. Raises
    ValueError on a letter that names no card or a drop of every card, and
    CardMismatch when titles (parallel to letters) name a different card
    at that letter: the page's letters are positions, so this is the check
    that the card he clicked is the card removed."""
    head, *cards = _CARD_RE.split(text)
    if titles is not None and len(titles) != len(letters):
        raise ValueError("titles must match letters one to one")
    idx = set()
    for k, L in enumerate(letters):
        i = ord(str(L).upper()) - ord("A") if len(str(L)) == 1 else -1
        if not 0 <= i < len(cards):
            raise ValueError(f"no option {L!r} (set has {len(cards)})")
        if titles is not None and card_title(cards[i]) != re.sub(r"\s+", " ", str(titles[k])).strip():
            raise CardMismatch(f"option {L} is now {card_title(cards[i])!r}, not {titles[k]!r}")
        idx.add(i)
    if cards and len(idx) == len(cards):
        raise ValueError("cannot delete every option in a set")
    return head + "".join(c for i, c in enumerate(cards) if i not in idx)


@bp.route("/api/option/delete", methods=["POST"])
def api_option_delete():
    data = request.get_json(force=True, silent=True) or {}
    folder = _option_dir(data.get("set", ""))
    if folder is None:
        return jsonify({"error": "set must name a folder under the options root"}), 400
    letters = data.get("letters") or []
    if not letters:
        return jsonify({"error": "letters required"}), 400
    if data.get("sha256") != store.doc_hash(folder):
        return jsonify({"error": "option set changed since it was rendered"}), 409
    f = folder / "options.html"
    try:
        f.write_text(drop_cards(f.read_text(encoding="utf-8"), letters, data.get("titles")), encoding="utf-8")
    except CardMismatch as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"sha256": store.doc_hash(folder)})

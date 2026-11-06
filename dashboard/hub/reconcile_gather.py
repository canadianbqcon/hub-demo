"""Read-only gather of pending-item counts across vault surfaces.

LLM-free and deterministic: called by the Hub scheduler's gather job.
NEVER shells out to `claude`. Each surface counter is isolated so a failure
records {"error": "..."} and flips top-level status to "partial" rather than
propagating as a silent zero.

Security guarantee: this module is the scheduled gather path. It issues NO
external writes and NEVER invokes `claude`. Read-only file, HTTP GET, and
read-only `git` queries only.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Bootstrap sys.path so this module is importable standalone.
# Pattern mirrors icloud_ingest.py / paystub_ingest.py (parents[2] from
# dashboard/hub/finances/ reaches dashboard/; we are one level up so parents[1]
# reaches dashboard/).
_HUB = Path(__file__).resolve().parent          # dashboard/hub/
_DASHBOARD = _HUB.parent                         # dashboard/
_FINANCES = _HUB / "finances"                    # dashboard/hub/finances/

for _p in (str(_DASHBOARD), str(_FINANCES)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import icloud_ingest          # noqa: E402  # pyright: ignore[reportMissingImports]  (in dashboard/hub/finances/, not a declared pyright extraPath — sys.path handles it at runtime)
import memo_ingest             # noqa: E402  (in dashboard/)
from finances import book      # noqa: E402  (in dashboard/hub/)
from vault_path import icloud_root, vault_root   # noqa: E402  (in dashboard/)

_SURFACES = [
    "files", "icloud", "memos", "ynab", "inbox", "raw", "gmail", "todo", "downloads",
    "unmerged",
]

# Branch every other local branch is measured against. A branch holding commits
# not in this one is finished work that never landed.
_TRUNK = "main"

# Path to the gmail read-only token. Defined at module level so tests can patch
# `rg._GMAIL_TOKEN_PATH` without touching the filesystem.
_GMAIL_TOKEN_PATH = Path.home() / ".config" / "vault-api" / "gmail_readonly_token.json"

# Marker file that flags a Downloads subfolder as a Claude-managed process
# folder (see the process-folder convention in the vault's CLAUDE-file-delivery.md).
# Excludes unrelated folders Sam keeps in Downloads himself (e.g. Spotify/).
_DOWNLOADS_MARKER = ".claude-process"
_DOWNLOADS_STALE_DAYS = 14
_DOWNLOADS_CONSOLIDATED = "Claude Mockups"

# A planner task key on a line of its own inside a marker's hold block:
# kebab slug + the 4-hex suffix tasks.py appends (e.g. polish-glass-…-b947).
_HOLD_KEY_RE = re.compile(r"^\s*([a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{4})\s*$", re.M)


# ---------------------------------------------------------------------------
# Surface counters -- real read-only bodies wired here.
# Each is a standalone callable; gather_counts() resolves them via globals()
# at call time so a test monkeypatch of rg._count_<name> takes effect.
# ---------------------------------------------------------------------------

def _count_files() -> int:
    """Loose PC files /file-sort would act on (placed by a rule or left unsure)."""
    from automations import file_sort
    return len(file_sort.plan())


def _count_icloud() -> int:
    """Candidate files in the user's iCloud Drive root (image/PDF suffix only)."""
    return len(icloud_ingest.list_unprocessed(icloud_root()))


def _count_memos() -> int:
    """Unprocessed voice-memo JSON files in the VaultMemos drop folder."""
    return len(memo_ingest.read_pending_memos())


def _count_ynab() -> int:
    """Book transactions needing attention (unapproved / uncategorized / memo-blank).

    Raises when the book is not set up so the surface records an error rather
    than a silent 0 (book.fetch_unreviewed returns [] on error).
    """
    if not book.is_configured():
        raise RuntimeError("book not set up")
    return len(book.fetch_unreviewed())


def _count_inbox() -> int:
    """Non-empty bullet items under the `## Items` section of vault inbox.md.

    Scoped to `## Items` so the bullets in the `## Rules` section are not counted
    as pending captures — otherwise an empty inbox reports a false positive equal
    to the number of rule bullets (the gather's honest-count contract).
    """
    inbox = Path(vault_root()) / "inbox.md"
    if not inbox.exists():
        return 0
    count = 0
    in_items = False
    for line in inbox.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            # Enter the Items section on its heading; any other heading exits it.
            in_items = stripped.lower().lstrip("#").strip() == "items"
            continue
        if not in_items:
            continue
        # A bullet is "- " followed by non-whitespace content.
        if stripped.startswith("- ") and stripped[2:].strip():
            count += 1
    return count


def _count_raw() -> int:
    """Files awaiting ingest in vault raw/uningested/.

    raw/uningested/ is the canonical staging area: after a successful ingest
    and audit, files move to raw/ingested/YYYY-MM/ (per raw/CLAUDE.md).
    Hidden files (dot-prefix) are excluded.
    """
    raw_dir = Path(vault_root()) / "raw" / "uningested"
    if not raw_dir.exists():
        return 0
    return sum(
        1 for p in raw_dir.iterdir()
        if p.is_file() and not p.name.startswith(".")
    )


def _gmail_service():
    """Return a gmail readonly service object. Separated so tests can patch it."""
    _svc_dir = str(Path.home() / ".config" / "vault-api")
    if _svc_dir not in sys.path:
        sys.path.insert(0, _svc_dir)
    # services.py lives at ~/.config/vault-api/, a machine-local credentials
    # dir outside the repo — same rationale as the import in _count_ynab above.
    from services import gmail_readonly   # noqa: F401  # pyright: ignore[reportMissingImports]
    return gmail_readonly()


def _known_inbox_ids() -> set:
    """Message ids `/gmail` has already processed, from its known-inbox ledger.

    A KEEP decision deliberately leaves the message in the inbox, so total inbox
    size is not "pending" — an email Sam parked on purpose would count as a
    loose end forever. The ledger is the existing record of that choice; anything
    keyed there has been triaged. Missing/corrupt ledger degrades to an empty set
    (count everything) rather than silently reporting zero pending.
    """
    ledger = (Path(vault_root()) / ".claude" / "skills" / "gmail" / "known-inbox.json")
    try:
        data = json.loads(ledger.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    # ponytail: value-shape check skips the bookkeeping keys (last_rectification_run)
    # without hardcoding their names.
    return {k for k, v in data.items() if isinstance(v, dict)}


def _count_gmail() -> int:
    """Untriaged inbox messages via the read-only Gmail token.

    Inbox messages minus the ones `/gmail` already processed (see
    _known_inbox_ids) — so deliberate KEEPs do not read as pending work.

    Raises RuntimeError("token pending") if the token file is absent so the
    surface records {"error": "..."} rather than {"count": 0}.
    """
    if not _GMAIL_TOKEN_PATH.exists():
        raise RuntimeError("token pending")
    svc = _gmail_service()
    known = _known_inbox_ids()
    pending, page = 0, None
    while True:
        result = svc.users().messages().list(
            userId="me", labelIds=["INBOX"], maxResults=500, pageToken=page,
        ).execute()
        pending += sum(
            1 for m in (result.get("messages") or []) if m.get("id") not in known
        )
        page = result.get("nextPageToken")
        if not page:
            return pending


def _count_todo() -> int:
    """Unchecked items ( - [ ] ) in vault claude-work-planner.md."""
    planner = Path(vault_root()) / "wiki" / "notes" / "claude-work-planner.md"
    if not planner.exists():
        raise RuntimeError("claude-work-planner.md not found")
    return sum(
        1 for line in planner.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- [ ]")
    )


_WSL_DOWNLOADS = Path("/app/home/Downloads")


def _downloads_root() -> Path:
    """Sam's Downloads folder on whichever machine this is running on.

    The PC runs under WSL, where Downloads is the Windows one under /mnt/c; the
    Mac has an ordinary ~/Downloads. This was hardcoded to the WSL path, so on
    the Mac `scan_dirs` came back empty and `_count_downloads` returned a clean
    0 -- indistinguishable from "no stale folders", with no error recorded
    (found by the 2026-09-10 sweep). Separated for test monkeypatching.
    """
    if _WSL_DOWNLOADS.exists():
        return _WSL_DOWNLOADS
    return Path.home() / "Downloads"


def _active_task_keys() -> set[str]:
    """Task keys still open in the planner. Empty set if tasks.db is unreadable."""
    try:
        import tasks  # noqa: E402  # pyright: ignore[reportMissingImports]  (dashboard/hub/, resolved by sys.path at runtime)
        return {t["id"] for t in tasks.list_active()}
    except Exception:
        return set()


def _marker_holds(marker: Path, active: set[str]) -> bool:
    """True when the marker declares a hold whose named tasks are still open.

    A marker may pin its folder against the staleness sweep by naming the tasks
    that must close first -- the `HELD BY DECISION` block written when Sam
    rules that a stale-looking folder's work is still live. Task keys are
    matched one per line, so the surrounding prose is free-form. Once every
    named task is closed the hold lapses on its own and the folder rejoins the
    count; a marker naming no recognizable key never holds.
    """
    try:
        text = marker.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if "HELD" not in text.upper():
        return False
    return any(k in active for k in _HOLD_KEY_RE.findall(text))


def _count_downloads() -> int:
    """Claude-managed Downloads process folders eligible for the 14-day sweep.

    A process folder is any subdirectory carrying the `.claude-process`
    marker (dropped when the folder is created per the
    process-folder convention in CLAUDE-file-delivery.md) -- this
    excludes unrelated folders Sam keeps in Downloads himself (e.g.
    Spotify/). "Pending" here means stale (no file in the folder touched in
    the last 14 days), not the total number of process folders.

    Scans both Downloads/ root (still-active folders) and Downloads/Claude
    Mockups/ (folders already relocated after 3 days idle) -- the stage ->
    move -> delete convention (2026-09-07) relocates a folder once it's idle
    past 3 days, but the 14-day clock reads file mtimes, which survive the
    move, so a folder counts the same wherever it currently sits.

    A folder whose marker declares a live hold is excluded even when stale --
    the cleanup gate is task completion, not age.
    """
    root = _downloads_root()
    scan_dirs = [d for d in (root, root / _DOWNLOADS_CONSOLIDATED) if d.exists()]
    if not scan_dirs:
        return 0
    cutoff = datetime.now().timestamp() - (_DOWNLOADS_STALE_DAYS * 86400)
    active = _active_task_keys()
    count = 0
    for scan_dir in scan_dirs:
        for entry in scan_dir.iterdir():
            if not entry.is_dir():
                continue
            marker = entry / _DOWNLOADS_MARKER
            if not marker.exists():
                continue
            if _marker_holds(marker, active):
                continue
            if _newest_mtime(entry) < cutoff:
                count += 1
    return count


def _newest_mtime(folder: Path) -> float:
    """Newest file mtime in a process folder, marker excluded (marker's own if empty)."""
    return max(
        (f.stat().st_mtime for f in folder.rglob("*")
         if f.is_file() and f.name != _DOWNLOADS_MARKER),
        default=(folder / _DOWNLOADS_MARKER).stat().st_mtime,
    )


def _repo_roots() -> list[Path]:
    """The two git repos Sam works in: the vault and its sibling code repo.

    Mirrors vault_map/db.py's _code_root resolution — the machine-local pointer
    file first, a `vault-code` sibling as the fallback. A path that is not a git
    checkout is dropped, so a machine holding only one of the pair still counts.
    """
    root = Path(vault_root())
    pointer = Path.home() / ".config" / "vault-api" / "code_path"
    try:
        code = Path(pointer.read_text(encoding="utf-8").strip())
    except OSError:
        code = root.parent / "vault-code"
    if not code.is_dir():
        code = root.parent / "vault-code"
    return [p for p in (root, code) if (p / ".git").exists()]


def _unmerged_branches() -> list[tuple[str, str]]:
    """(repo name, branch) for every local branch holding commits not in main.

    Finished work nobody merged: a branch that was built, tested and then left
    behind. Deliberately says NOTHING about the remote — not ahead/behind, not
    fetch staleness, not the working tree. Local branch vs. local trunk only.

    `git branch --no-merged main` is the whole check: it lists branches whose
    tip is not an ancestor of main, and excludes main itself. A repo with no
    `main` raises, so the surface records an error rather than a silent zero.
    """
    found: list[tuple[str, str]] = []
    for repo in _repo_roots():
        out = subprocess.run(
            [shutil.which("git") or "git", "-C", str(repo), "branch", "--no-merged", _TRUNK,
             "--format=%(refname:short)"],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout
        found += [(repo.name, b.strip()) for b in out.splitlines() if b.strip()]
    return found


def _count_unmerged() -> int:
    """Local branches holding work that never landed in main."""
    # ponytail: a worktree in detached HEAD is invisible to --no-merged; every
    # worktree here is checked out on a branch, so add a `git worktree list`
    # pass only if a detached one ever strands work.
    return len(_unmerged_branches())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def gather_counts() -> dict:
    """Gather pending-item counts from all surfaces. Always returns a dict.

    Resolves each counter via globals() at call time so a test that
    monkeypatches rg._count_<name> takes effect without a module reload.

    A surface that raises records {"error": "..."} and flips the top-level
    status to "partial". It NEVER records {"count": 0} on a failure -- a
    failed gather must never read as a clean zero.
    """
    surfaces: dict = {}
    status = "ok"
    for name in _SURFACES:
        try:
            surfaces[name] = {"count": int(globals()[f"_count_{name}"]())}
        except Exception as exc:
            surfaces[name] = {"error": str(exc) or exc.__class__.__name__}
            status = "partial"
    return {"status": status, "generated": _now_iso(), "surfaces": surfaces}


def write_manifest(counts: dict, drafts_dir: Path) -> Path:
    """Write counts dict as a timestamped JSON manifest. Returns the path."""
    drafts_dir = Path(drafts_dir)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    stamp = counts.get("generated", "manifest").replace(":", "-")
    out = drafts_dir / f"{stamp}.json"
    out.write_text(json.dumps(counts, indent=2))
    return out


def _now_iso() -> str:
    return datetime.now().isoformat()

"""Resume file handling: path safety, artifact cleanup, reveal-in-file-manager.

Everything here is filesystem and host-OS work, which the four-layer rule in
wiki/notes/dashboard-code-structure keeps out of the routes layer ("Routes /
Views ... what MUST NOT enter: raw SQL, file I/O, business calculations").
api.py used to hold all of it inline; the routes now only translate the results
into HTTP status codes.

Not a db_*.py module on purpose: none of this touches jobs.db. It sits in the
service layer, between the routes and the disk.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(
        0, str(Path(__file__).resolve().parents[2])
    )  # dashboard/, for vault_path
from vault_path import vault_root

_VAULT_ROOT = vault_root()

# Resume files may only ever live under this directory. The vault root holds
# secrets (.env, OAuth tokens, the databases), so containment-in-vault is NOT a
# safe bound for a file-serving endpoint — containment in this leaf dir is.
RESUME_ROOT = (_VAULT_ROOT / "data" / "resumes").resolve()
ALLOWED_RESUME_EXTS = {".pdf", ".docx"}


def resolve_resume_path(stored: str | None) -> Path | None:
    """Resolve a stored resume path to a real file under RESUME_ROOT.

    Returns the resolved Path only if the path is safe: non-empty, no null
    byte, not absolute, no `..` segment, lands inside RESUME_ROOT after
    resolution, and carries an allowed extension. Otherwise returns None.
    Stored paths are vault-root-relative (e.g. ``data/resumes/base/x.docx``),
    so the join is against _VAULT_ROOT but the result must sit under RESUME_ROOT.
    """
    if not stored or "\x00" in stored:
        return None
    candidate = Path(stored)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = (_VAULT_ROOT / candidate).resolve()
    if not resolved.is_relative_to(RESUME_ROOT):
        return None
    if resolved.suffix.lower() not in ALLOWED_RESUME_EXTS:
        return None
    return resolved


def unlink_resume_artifacts(stored: str | None) -> None:
    """Delete a resume's file on disk plus its same-stem render intermediate.

    The resume pipeline writes a ``.pdf`` (the kept artifact, stored in
    ``file_path``) and leaves a same-stem ``.html`` render leftover beside it.
    Removing a resume row should take both, so nothing is stranded on disk.

    Safety: only ever touches files that resolve under RESUME_ROOT, and never
    the shared ``base/`` master templates (those are reused across every
    tailored resume and are not tied to a single application). Missing files,
    paths outside RESUME_ROOT, and OS errors are silently ignored — file
    cleanup must never block the database delete.
    """
    resolved = resolve_resume_path(stored)
    if resolved is None:
        return
    if (RESUME_ROOT / "base") in resolved.parents:
        return
    for f in (resolved, resolved.with_suffix(".html")):
        try:
            if f.is_relative_to(RESUME_ROOT) and f.exists():
                f.unlink()
        except OSError:
            pass


def _windows_short_path(winpath: str) -> str | None:
    """Return the 8.3 short (space-free) form of a Windows path, or None.

    ``explorer.exe /select`` mis-parses any target containing a space — it
    splits at the first space and silently falls back to the default folder
    (Documents). The vault root has spaces ("Demo Files", "Obsidian Vault"),
    so before selecting we convert to the 8.3 short form, which has none.
    Looked up through the Windows shell (``Scripting.FileSystemObject``).
    Returns None if the lookup fails or 8.3 names are disabled for the volume
    (in which case the short form still contains a space) — the caller then
    degrades to opening the containing folder without a selection.
    """
    powershell = shutil.which("powershell.exe")  # the hub-dashboard unit's PATH carries the Windows dirs
    if not powershell:
        return None
    safe = winpath.replace("'", "''")  # escape single quotes for the PS literal
    try:
        out = subprocess.run(
            [powershell, "-NoProfile", "-Command",
             f"(New-Object -ComObject Scripting.FileSystemObject)"
             f".GetFile('{safe}').ShortPath"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    short = out.stdout.strip()
    if out.returncode != 0 or not short or " " in short:
        return None
    return short


def reveal_in_file_manager(path: Path) -> tuple[bool, str]:
    """Open the host OS file manager with ``path`` highlighted in its folder.

    The dashboard server runs inside WSL but Sam opens files from Windows,
    so the common case launches Windows Explorer: convert the WSL path to a
    ``C:\\`` path via ``wslpath -w``, take its 8.3 short form (see
    ``_windows_short_path`` — explorer's /select can't handle the spaces in the
    vault path), and call ``explorer.exe /select,<shortpath>``. If 8.3 names are
    unavailable, fall back to opening the containing folder (no selection, but
    still reliable). Explorer returns exit code 1 even on success, so the return
    code is ignored. macOS uses ``open -R``. Returns (ok, message).
    """
    is_wsl = "microsoft" in Path("/proc/version").read_text().lower() \
        if Path("/proc/version").exists() else False
    try:
        if is_wsl:
            explorer = shutil.which("explorer.exe")
            if not explorer:
                return False, "explorer.exe not found on this WSL host"
            wslpath = shutil.which("wslpath") or "/usr/bin/wslpath"
            win = subprocess.run(
                [wslpath, "-w", str(path)],
                capture_output=True, text=True, timeout=5,
            )
            if win.returncode != 0:
                return False, f"wslpath failed: {win.stderr.strip()}"
            winpath = win.stdout.strip()
            # explorer.exe exits 1 even on success; fire-and-forget, don't check rc
            short = _windows_short_path(winpath)
            if short:
                subprocess.Popen([explorer, f"/select,{short}"])
                return True, winpath
            # 8.3 names disabled / lookup failed — /select would choke on the
            # spaces, so open the containing folder (a plain quoted folder path
            # is parsed fine) without a file selection.
            parent = subprocess.run(
                [wslpath, "-w", str(path.parent)],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            subprocess.Popen([explorer, parent])
            return True, f"{winpath} (folder only — 8.3 short names unavailable)"
        if sys.platform == "darwin":
            opener = shutil.which("open") or "/usr/bin/open"
            subprocess.Popen([opener, "-R", str(path)])
            return True, str(path)
        return False, "reveal-in-file-manager is only supported on WSL and macOS"
    except Exception as exc:  # noqa: BLE001 — surface any launch failure to the UI
        return False, str(exc)

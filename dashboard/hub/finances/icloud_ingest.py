# vault-code/dashboard/hub/finances/icloud_ingest.py
"""Mechanical, testable helpers for the /icloud general-inbox handler.

Claude does the content parse and shows results for Sam to confirm; this
module handles only the deterministic parts: listing candidates, routing files
to raw/, staging receipts as pending memos, and md5-verified preserve+remove.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402
import memo_ingest  # noqa: E402

CANDIDATE_SUFFIXES = {".heic", ".png", ".jpg", ".jpeg", ".pdf"}


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes(), usedforsecurity=False).hexdigest()


def list_unprocessed(icloud_dir: Path) -> list[Path]:
    """Return candidate files in icloud_dir, newest mtime first.

    Candidates: regular files whose name does not start with '.' and whose
    suffix (lowercased) is in CANDIDATE_SUFFIXES. Subdirectories and hidden
    files are skipped. Non-existent dir returns [].
    """
    if not icloud_dir.exists():
        return []
    results = []
    for p in icloud_dir.iterdir():
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        if p.suffix.lower() not in CANDIDATE_SUFFIXES:
            continue
        results.append(p)
    results.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return results


EXIF_DATETIME_ORIGINAL = 36867  # PIL/EXIF tag id for DateTimeOriginal


def _capture_time(p: Path) -> str | None:
    """EXIF DateTimeOriginal for p as its raw 'YYYY:MM:DD HH:MM:SS' string, or None.

    Lexical order on that format is chronological order, so no parsing is needed.
    Returns None for anything without readable EXIF (PDFs, stripped images, a
    file PIL cannot open) — the caller falls back to mtime for those.
    """
    try:
        import pillow_heif
        from PIL import Image

        pillow_heif.register_heif_opener()
        with Image.open(p) as img:
            exif = img.getexif()
        raw = exif.get(EXIF_DATETIME_ORIGINAL) if exif else None
    except Exception:
        return None
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def page_order(paths: list[Path]) -> list[Path]:
    """Return paths in capture order — EXIF DateTimeOriginal first, mtime as fallback.

    A multi-page document photographed page by page must be read in the order the
    pages were shot. Neither filename nor mtime gives that: iCloud rewrites mtime
    to the sync time, which can reorder or flatten a whole batch. So EXIF capture
    time wins wherever it exists.

    Files with EXIF sort ahead of files without, so a partially-stripped batch
    keeps its readable pages in true order instead of interleaving them with
    guesses. Ties (same capture second, or both mtime-only) break on filename so
    the result is stable.
    """
    def key(p: Path):
        cap = _capture_time(p)
        # Uniform tuple shape (int, str, float, str) so branches stay comparable;
        # the mtime slot must be numeric, a stringified float mis-sorts (9.0 > 10.0).
        return (0, cap, 0.0, p.name) if cap else (1, "", p.stat().st_mtime, p.name)

    return sorted(paths, key=key)


def route_to_raw(src: Path, dest_name: str) -> Path:
    """Copy src into vault_root()/raw/<dest_name>, md5-verified. Return dest Path.

    dest_name must resolve to a path inside raw/ (no '..' / absolute-path
    traversal) — it flows from caller-supplied text, not a trusted constant.
    On md5 mismatch after copy: unlinks the bad dest and raises IOError.
    """
    raw_dir = Path(vault_root()) / "raw"
    dest = (raw_dir / dest_name).resolve()
    if not dest.is_relative_to(raw_dir.resolve()):
        raise ValueError(f"dest_name escapes raw/: {dest_name!r}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    if _md5(src) != _md5(dest):
        dest.unlink()
        raise IOError(f"md5 mismatch copying {src} -> {dest}")
    return dest


def route_to_inbox(text: str) -> None:
    """Append a bullet item to vault_root()/inbox.md."""
    inbox = Path(vault_root()) / "inbox.md"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    with inbox.open("a", encoding="utf-8") as f:
        f.write(f"\n- {text.strip()}\n")


def stage_receipt(amount: float, payee: str, date_iso: str, memo: str) -> None:
    """Stage a receipt as a pending transaction memo for /ynab to classify later."""
    memo_ingest.write_transaction_memo(
        transcript=memo,
        recorded_at=date_iso,
        lat=None,
        lon=None,
        location_label=payee,
        vendor_guess=payee,
        amount_guess=amount,
        category_guess="",
        payment_method_guess="",
    )


def preserve_and_remove(src: Path, preserved_dir: Path) -> Path:
    """Copy src to preserved_dir/src.name (md5-verified), then delete src.

    On md5 mismatch: unlinks the bad dest and raises IOError. The original src
    is NOT deleted on mismatch. On success: src is deleted and dest is returned.
    """
    preserved_dir.mkdir(parents=True, exist_ok=True)
    dest = preserved_dir / src.name
    shutil.copy2(src, dest)
    if _md5(src) != _md5(dest):
        dest.unlink()
        raise IOError(f"md5 mismatch preserving {src} -> {dest}")
    src.unlink()
    return dest


POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
_RESTART_PS = (
    "$d='C:\\Program Files (x86)\\Common Files\\Apple\\Internet Services'; "
    "Stop-Process -Name iCloudDrive,iCloudServices -Force -EA 0; Start-Sleep 3; "
    # Hidden: this runs from the 06:00/18:00 file-sort job and must never pull
    # focus from a fullscreen game. Both are tray apps, so nothing is lost.
    "Start-Process \"$d\\iCloudServices.exe\" -WindowStyle Hidden; Start-Sleep 10; "
    "if (-not (Get-Process iCloudDrive -EA 0)) { Start-Process \"$d\\iCloudDrive.exe\" -WindowStyle Hidden }; "
    "Start-Sleep 10; [bool](Get-Process iCloudDrive -EA 0)"
)


def restart_sync() -> bool:
    """Restart iCloud for Windows so a silently stalled download resumes.

    2026-10-28: ten screenshots sat on Apple's side until a manual restart, four
    hours after a reboot. iCloudServices does not relaunch iCloudDrive, so both
    are started. Returns whether iCloudDrive is running afterwards.
    """
    import subprocess
    r = subprocess.run([POWERSHELL, "-NoProfile", "-Command", _RESTART_PS],
                       capture_output=True, text=True, timeout=90)
    return r.stdout.strip().endswith("True")

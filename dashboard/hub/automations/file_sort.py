"""File sorter: moves new loose files from the drop spots into Demo Files.

LLM-free, so the scheduler can run it unattended (job `file-sort`). A file moves
only when a rule places it with confidence: installers, photos, screenshots,
video, audio, RAW, and documents whose name says what they are. Everything else
stays where it is and comes back as `unsure` for /file-sort, where Claude reads
it and asks.

Safety: only top-level files of each source (folders are never touched, so
Claude's Downloads process folders and anything he keeps there stay put); a
file touched in the last MIN_AGE is skipped (a download still landing); a name
clash gets " (2)", never an overwrite; nothing is ever deleted. Every move is
appended to log/file-sort.jsonl with src and dest, which is the undo record.

CLI:
    python3 file_sort.py            # dry run, prints the plan as JSON
    python3 file_sort.py --apply    # move every placed file, print the result
    python3 file_sort.py --move SRC DEST_DIR   # one move, DEST_DIR under Demo Files
"""
import json
import re
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # dashboard/, for vault_path
from vault_path import vault_root  # noqa: E402

QM = Path("/app/files")
USER = Path("/app/home")
# Every place a download, save dialog or capture lands by default. App-owned
# libraries (Medal on D:\Medal and E:\Clips) are left out on purpose: moving
# their files breaks the app. iCloud Drive is /icloud's, run from /file-sort.
SOURCES = [
    QM / "00-Downloads",
    USER / "Desktop",
    QM / "01-Personal" / "05-Documents",
    QM / "01-Personal" / "04-Media" / "Pictures",
    USER / "Pictures" / "Screenshots",
    USER / "Music",
    USER / "Videos",
    USER / "Videos" / "Captures",
    USER / "Videos" / "Screen Recordings",
]
# MicroQ camera SD card. Copied from, never moved from: the card stays a backup.
CARD = Path("/mnt/f")
MIN_AGE = 15 * 60

MEDIA = Path("01-Personal/04-Media")
ADMIN = Path("01-Personal/02-Admin")
INSTALLERS = Path("03-Applications/Installers")
SCREENSHOTS = MEDIA / "Pictures/Screenshots"
PHOTOS = MEDIA / "Photos"
VIDEOS = MEDIA / "Videos"
MUSIC = MEDIA / "Music"
RAWS = MEDIA / "RAWS"
FINANCE = ADMIN / "Finance"
TAXES = FINANCE / "Taxes"
JOB_HUNT = Path("02-Work/02-Job Hunt")
COLLEGE = Path("02-Work/01-College")

SKIP_NAMES = {"desktop.ini", "thumbs.db"}
SKIP_EXT = {".lnk", ".url", ".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload"}
INSTALLER_EXT = {".exe", ".msi", ".msix", ".msixbundle", ".appx"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}
RAW_EXT = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".aiff"}
DOC_EXT = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".pptx", ".txt", ".rtf", ".odt"}

# YYYYMMDD_HHMMSS exactly: Facebook saves are 8 digits_15 digits and must not match.
CAMERA_RE = re.compile(r"^(img|pxl|dsc|dscn|dji|gopr)[_-]?\d|^(19|20)\d{6}_\d{6}(?!\d)", re.I)
SCREENSHOT_RE = re.compile(r"screen ?shot", re.I)
SCREEN_REC_RE = re.compile(r"screen ?recording", re.I)
# (?<![a-z]) instead of \b: underscores are word characters, so \bresume misses Sam_Rivera_Resume.
_W = r"(?<![a-z]){}(?![a-z])"
TAX_RE = re.compile(_W.format(r"(w-?2|1099(-[a-z]+)?|1040|tax(es)?)"), re.I)
FINANCE_RE = re.compile(_W.format(r"(receipt|invoice|order[-_ ]?confirmation)"), re.I)
JOB_RE = re.compile(_W.format(r"(resume|cv|cover[-_ ]?letter|certificate|offer[-_ ]?letter)"), re.I)
COLLEGE_RE = re.compile(_W.format(r"(transcript|syllabus|diploma)"), re.I)
YEAR_RE = re.compile(r"(?<!\d)(20\d\d)(?!\d)")


def place(path: Path, source: Path) -> tuple[Path | None, str]:
    """(destination folder relative to Demo Files, reason), or (None, reason) when unsure."""
    ext, stem = path.suffix.lower(), path.stem
    from_shots = source.name == "Screenshots"
    from_recordings = source.name in ("Captures", "Screen Recordings")
    if ext in INSTALLER_EXT:
        return INSTALLERS, "installer"
    if ext in RAW_EXT:
        day = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
        return RAWS / day, "camera RAW"
    if ext in IMAGE_EXT:
        if from_shots or SCREENSHOT_RE.search(stem):
            return SCREENSHOTS, "screenshot"
        if CAMERA_RE.search(stem):
            return PHOTOS, "camera photo"
        return None, "image with no camera or screenshot name"
    if ext in VIDEO_EXT:
        return VIDEOS, "screen recording" if from_recordings or SCREEN_REC_RE.search(stem) else "video"
    if ext in AUDIO_EXT:
        return MUSIC, "audio"
    if ext in DOC_EXT:
        if TAX_RE.search(stem):
            year = YEAR_RE.search(stem)
            return (TAXES / year.group(1) if year else TAXES), "tax document"
        if FINANCE_RE.search(stem):
            return FINANCE, "receipt or invoice"
        if JOB_RE.search(stem):
            return JOB_HUNT, "job hunt document"
        if COLLEGE_RE.search(stem):
            return COLLEGE, "college document"
        return None, "document the name does not place"
    return None, f"no rule for {ext or 'files without an extension'}"


def candidates(sources=None, now=None):
    """(file, its source) for every loose file old enough to sort."""
    now = now or time.time()
    for source in sources or SOURCES:
        if not source.is_dir():
            continue
        for p in sorted(source.iterdir()):
            if not p.is_file() or p.name.startswith(".") or p.name.lower() in SKIP_NAMES:
                continue
            if p.suffix.lower() in SKIP_EXT or now - p.stat().st_mtime < MIN_AGE:
                continue
            yield p, source


def plan(sources=None, now=None, root=QM):
    """One row per candidate: src, dest (absolute, or None when unsure), why."""
    rows = []
    for p, source in candidates(sources, now):
        dest, why = place(p, source)
        rows.append({"src": str(p), "dest": str(root / dest) if dest else None, "why": why})
    return rows


def _free_name(dest_dir: Path, name: str) -> Path:
    target = dest_dir / name
    n = 2
    while target.exists():
        target = dest_dir / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    return target


def move(src, dest_dir, run_id="manual", root=QM, log_path=None) -> Path:
    """Move one file into dest_dir (created if missing) without overwriting, and log it."""
    src, dest_dir = Path(src), Path(dest_dir)
    if not src.is_file():
        raise FileNotFoundError(src)
    if not dest_dir.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError(f"{dest_dir} is outside {root}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = _free_name(dest_dir, src.name)
    shutil.move(str(src), str(target))
    log_path = Path(log_path or Path(vault_root()) / "log" / "file-sort.jsonl")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "run": run_id,
                            "src": str(src), "dest": str(target)}) + "\n")
    return target


def sweep_card(card=None, root=QM, log_path=None, run_id="manual") -> list:
    """Copy every RAW on the camera card that the RAWS master lacks; [] when no card.

    A RAW counts as present when any date folder under RAWS holds the same name and
    size, because some older shoots are filed a day off from the file timestamp.
    """
    card = Path(CARD if card is None else card)
    if not card.is_dir():
        return []
    raws = Path(root) / RAWS
    have = {(p.name.lower(), p.stat().st_size) for p in raws.rglob("*") if p.is_file()} if raws.is_dir() else set()
    log_path = Path(log_path or Path(vault_root()) / "log" / "file-sort.jsonl")
    copied = []
    for p in sorted(card.rglob("*")):
        if p.suffix.lower() not in RAW_EXT or p.name.startswith(".") or not p.is_file():
            continue
        st = p.stat()
        if (p.name.lower(), st.st_size) in have:
            continue
        dest_dir = raws / datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = _free_name(dest_dir, p.name)
        shutil.copy2(p, target)
        have.add((p.name.lower(), st.st_size))
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "run": run_id,
                                "src": str(p), "dest": str(target), "copy": True}) + "\n")
        copied.append({"src": str(p), "dest": str(target)})
    return copied


def run(sources=None, now=None, root=QM, log_path=None) -> dict:
    """Move every placed file; return a run record with the unsure ones listed."""
    run_id = uuid.uuid4().hex[:8]
    moved, unsure, failed = [], [], []
    for row in plan(sources, now, root):
        if not row["dest"]:
            unsure.append({"src": row["src"], "why": row["why"]})
            continue
        try:
            moved.append({"src": row["src"], "dest": str(move(row["src"], row["dest"], run_id, root, log_path))})
        except OSError as exc:  # a file open in another app: leave it, the next run retries
            failed.append({"src": row["src"], "error": str(exc)})
    try:
        copied = sweep_card(root=root, log_path=log_path, run_id=run_id) if sources is None else []
    except OSError as exc:  # card pulled mid-copy: the next run picks up the rest
        copied = []
        failed.append({"src": str(CARD), "error": str(exc)})
    return {"status": "failed" if failed and not moved and not copied else "ok", "run": run_id,
            "moved": moved, "copied": copied, "unsure": unsure, "failed": failed,
            "outcome": f"{len(moved)} moved, {len(unsure)} unsure, {len(failed)} failed"
                       + (f", {len(copied)} copied from card" if copied else "")}


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--move"] and len(args) == 3:
        print(move(args[1], args[2]))
    elif args == ["--apply"]:
        print(json.dumps(run(), indent=1))
    elif not args:
        print(json.dumps(plan(), indent=1))
    else:
        sys.exit(__doc__)

"""Single source of truth for locating the Obsidian vault from code.

The code repo (this one) and the vault are sibling folders synced as two
git repos. Code depends on the vault one-way: it reads wiki/ nodes and
reads/writes the SQLite databases under the vault's data/. Nothing in the
vault references this repo.

Resolution order:
1. VAULT_PATH environment variable (set in the systemd units; export it
   for ad-hoc runs to point at a test vault).
2. ~/.config/vault-api/vault_path — a one-line machine-local pointer file,
   same home as the credential symlinks. Each machine writes its own.

No hardcoded machine paths here, so PC and Mac share this file unchanged.
"""

import os
from pathlib import Path

_POINTER_FILE = Path.home() / ".config" / "vault-api" / "vault_path"


def vault_root() -> Path:
    env = os.environ.get("VAULT_PATH")
    if env:
        root = Path(env).expanduser()
        if root.is_dir():
            return root.resolve()
        raise FileNotFoundError(f"VAULT_PATH is set but not a directory: {env}")
    try:
        raw = _POINTER_FILE.read_text().strip()
    except FileNotFoundError:
        raise FileNotFoundError(
            "Cannot locate the vault: VAULT_PATH is unset and "
            f"{_POINTER_FILE} does not exist. Write the vault's absolute "
            "path into that file (one line) or export VAULT_PATH."
        ) from None
    root = Path(raw).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"{_POINTER_FILE} points at a missing directory: {raw}")
    return root.resolve()


_WSL_ICLOUD = Path("/app/home/iCloudDrive")


def icloud_root() -> Path:
    """Sam's iCloud Drive root on whichever machine this is running on.

    Same shape as reconcile_gather._downloads_root: the PC runs under WSL and
    reaches iCloud through /mnt/c, the Mac has it under Mobile Documents. The
    three callers each hardcoded the WSL path, so on the Mac the folder simply
    did not exist and every iCloud/memo counter returned a clean 0 --
    indistinguishable from "nothing waiting", with no error recorded (the same
    false-zero the Downloads counter was fixed for on 2026-09-10).

    ICLOUD_DRIVE overrides, for tests and for a relocated drive.
    """
    env = os.environ.get("ICLOUD_DRIVE")
    if env:
        return Path(env).expanduser()
    if _WSL_ICLOUD.exists():
        return _WSL_ICLOUD
    return Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"

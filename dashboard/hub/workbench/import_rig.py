#!/usr/bin/env python3
"""Import the Option Rig's recoverable history into Workbench.

Reads data/workbench/rig-migration/receipt.json (plan Task 1). Every readable
version whose fragments were recovered from git (rig-migration/parts/<label>/)
becomes an option set at data/workbench/options/rig-<label>/ plus one
`design / approved` row whose comment marks it imported. The artifact itself is
never touched here: the receipt says not every version was readable, so per the
spec it stays as a frozen archive.

    python3 import_rig.py            import (idempotent: skips sets already imported)
    python3 import_rig.py --dry-run  print what would be imported
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store  # noqa: E402

FRAGMENTS = ("head.html", "styles.css", "options.html")

# The pick per decision, from log/log.md. None = not recorded anywhere.
PICKS = {
    "trip-card-frame": "A",
    "hub-topbar-layout": "E",
    "hub-topbar-bottom-strip": None,
}


def plan(vault: Path):
    mig = vault / "data/workbench/rig-migration"
    receipt = json.loads((mig / "receipt.json").read_text())
    out = []
    for v in receipt["versions"]:
        if not v["readable"]:
            continue
        label = Path(v["saved_path"]).stem
        parts = mig / "parts" / label
        if not all((parts / f).is_file() for f in FRAGMENTS):
            continue
        out.append((label, parts, vault / "data/workbench/options" / f"rig-{label}", v))
    return receipt, out


def main():
    vault = store.vault_root()
    receipt, todo = plan(vault)
    dry = "--dry-run" in sys.argv
    for label, parts, dest, v in todo:
        slug = f"rig-{label}"
        if store.current(slug, "design") is not None:
            print(f"skip {slug}: already imported")
            continue
        print(f"{'would import' if dry else 'import'} {slug} <- {v['source']}")
        if dry:
            continue
        dest.mkdir(parents=True, exist_ok=True)
        for f in FRAGMENTS:
            shutil.copyfile(parts / f, dest / f)
        pick = PICKS.get(label)
        store.record(
            slug, "design", dest, "approved", choice=pick,
            comment=f"imported from the Option Rig artifact ({v['label']}); "
                    + ("pick from log/log.md" if pick else "pick not recorded"),
        )
    missing = [v["label"] for v in receipt["versions"] if not v["readable"]]
    print(f"{len(todo)} readable imported; unreadable, artifact kept: {', '.join(missing)}")


if __name__ == "__main__":
    main()

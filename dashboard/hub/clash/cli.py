"""Clash CLI: python3 -m clash.cli refresh-data [--tarball PATH]."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # dashboard/: vault_path, sqlite_helpers

from clash import gamedata

PKG = "clash-of-clans-data"
try:
    from vault_path import vault_root
    DB_PATH = vault_root() / "data" / "clash.db"
except Exception:  # ponytail: import fallback; tests monkeypatch DB_PATH
    DB_PATH = Path("clash.db")


def _stored_ids() -> set[int]:
    """data_ids in structure and upgrade; empty when the db or a table is missing."""
    if not DB_PATH.exists():
        return set()
    c = sqlite3.connect(str(DB_PATH))
    try:
        ids = set()
        for t in ("structure", "upgrade"):
            try:
                ids |= {r[0] for r in c.execute(f"SELECT DISTINCT data_id FROM {t}")}
            except sqlite3.OperationalError:
                pass
        return ids
    finally:
        c.close()


def _known_ids(home: Path) -> set[int]:
    ids = set()
    for f in home.rglob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(d, dict) and d.get("dataId") is not None:
            ids.add(d["dataId"])
    return ids


def _version_line(pkg: Path) -> str:
    ver = json.loads((pkg / "package.json").read_text())["version"]
    m = re.search(r"## \[%s\] - (\S+)" % re.escape(ver), (pkg / "CHANGELOG.md").read_text()) if (pkg / "CHANGELOG.md").exists() else None
    return f"{ver} {m.group(1) if m else 'unknown'}"


def refresh_data(tarball: str | None = None) -> int:
    live = gamedata.GAMEDATA
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if tarball is None:
            r = subprocess.run(["npm", "pack", PKG, "--silent"], cwd=tmp, capture_output=True, text=True)
            if r.returncode:
                print(f"refresh-data: npm pack failed: {r.stderr.strip()}", file=sys.stderr)
                return 1
            tarball = str(tmp / r.stdout.strip().splitlines()[-1])
        try:
            with tarfile.open(tarball) as t:
                t.extractall(tmp / "x", filter="data")
            pkg = tmp / "x" / "package"
            home = pkg / "data" / "home"
            new = _known_ids(home)
            version = _version_line(pkg)
        except Exception as e:
            print(f"refresh-data: package does not load: {e}", file=sys.stderr)
            return 1
        missing = sorted(_stored_ids() - new)
        if missing:
            print(f"refresh-data: new package lacks stored data_ids {missing}; gamedata unchanged", file=sys.stderr)
            return 1
        stage = live.parent / (live.name + ".new")
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        shutil.copytree(home, stage / "home")
        (stage / "VERSION").write_text(version + "\n")
        prev = live.parent / (live.name + ".prev")
        shutil.rmtree(prev, ignore_errors=True)
        if live.exists():
            live.rename(prev)
        stage.rename(live)
    gamedata.reload()
    print(f"refresh-data: now {version}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="clash.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("refresh-api")
    pa.add_argument("--tag")
    p = sub.add_parser("refresh-data")
    p.add_argument("--tarball")
    a = ap.parse_args(argv)
    if a.cmd == "refresh-data":
        return refresh_data(a.tarball)
    if a.cmd == "refresh-api":
        from clash import coc_api, db as cdb
        cdb.init(DB_PATH)
        res = {}
        with cdb.conn() as c:
            tags = [a.tag] if a.tag else [r[0] for r in c.execute("SELECT tag FROM account")]
            for t in tags:
                res[t] = coc_api.refresh(c, t)
        print(json.dumps(res[a.tag] if a.tag else res, indent=2))
        return 0


if __name__ == "__main__":
    sys.exit(main())

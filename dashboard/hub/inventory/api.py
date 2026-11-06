"""Inventory Hub blueprint: reads data/inventory/<machine>/ files, starts the scanner, runs a stored uninstall.

Files only, no database. An uninstall never takes a command from the request: the body
names a program key and the argv is looked up in the local machine's programs.json.
"""

from __future__ import annotations

import json
import logging
import platform
import socket
import subprocess
import threading
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from automations.api import _cross_site

bp = Blueprint("inventory", __name__, template_folder="frontend",
               static_folder="frontend/static", url_prefix="/inventory")
log = logging.getLogger(__name__)

SCAN_BIN = Path(__file__).resolve().parents[3] / "bin" / "inventory-scan"  # <vault-code>/bin
UNINSTALL_TIMEOUT = 600
_data_dir: Path | None = None


def init(vault_path) -> None:
    global _data_dir
    _data_dir = Path(vault_path) / "data" / "inventory"


def local_machine() -> str:
    if platform.system() == "Darwin":
        try:
            out = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return socket.gethostname()


def _err(msg, status):
    return jsonify({"error": msg}), status


def _read(machine: str, name: str):
    """(data, None) or (None, (response, status)). Missing machine folder is 404; bad JSON 422."""
    if not machine or "/" in machine or "\\" in machine or ".." in machine or machine.startswith("."):
        return None, _err("bad machine name", 400)
    assert _data_dir is not None, "init() not called"
    folder = _data_dir / machine
    if not folder.is_dir():
        return None, _err("unknown machine", 404)
    path = folder / name
    if not path.is_file():
        return None, _err(f"{name} not found", 404)
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (ValueError, OSError) as e:
        return None, _err(f"{name}: {e}", 422)


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def run_uninstall(argv):
    """Module-level so tests patch it. Returns (exit code, combined output)."""
    p = subprocess.run(argv, capture_output=True, text=True, timeout=UNINSTALL_TIMEOUT)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _start_scan() -> None:
    subprocess.Popen([str(SCAN_BIN)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


@bp.route("/")
def index():
    return render_template("inventory.html")


@bp.route("/api/machines")
def api_machines():
    me = local_machine()
    out = []
    assert _data_dir is not None, "init() not called"
    for folder in sorted(p for p in _data_dir.iterdir() if p.is_dir()) if _data_dir.is_dir() else []:
        prog = _load(folder / "programs.json", {})
        counts: dict = {}
        for r in prog.get("programs") or []:
            counts[r.get("cat")] = counts.get(r.get("cat"), 0) + 1
        out.append({"machine": folder.name, "local": folder.name == me, "scanned": prog.get("scanned"),
                    "exporters": _load(folder / "scanned.json", {}), "counts": counts})
    return jsonify(out)


@bp.route("/api/programs/<machine>")
def api_programs(machine):
    data, bad = _read(machine, "programs.json")
    return bad if bad else jsonify(data)


@bp.route("/api/manual/<machine>")
def api_manual(machine):
    data, bad = _read(machine, "manual.json")
    return bad if bad else jsonify(data)


@bp.route("/api/scan", methods=["POST"])
def api_scan():
    if bad := _cross_site():
        return bad
    try:
        _start_scan()
    except OSError as e:
        return _err(f"scanner did not start: {e}", 503)
    return jsonify({"started": True}), 202


@bp.route("/api/uninstall", methods=["POST"])
def api_uninstall():
    if bad := _cross_site():
        return bad
    key = (request.get_json(silent=True) or {}).get("key")
    if not isinstance(key, str) or not key:
        return _err("key required", 400)
    me = local_machine()
    assert _data_dir is not None, "init() not called"
    path = _data_dir / me / "programs.json"
    prog = _load(path, {}) if path.is_file() else {}
    row = next((r for r in prog.get("programs") or [] if r.get("key") == key), None)
    if row is None:
        return _err("unknown key for this computer", 400)
    argv = row.get("uninstall")
    if not argv:
        return _err("no uninstall command stored for this program", 409)
    try:
        code, output = run_uninstall(argv)
    except (OSError, subprocess.SubprocessError) as e:
        return _err(f"uninstall failed to run: {e}", 502)
    threading.Thread(target=_safe_scan, daemon=True).start()
    return jsonify({"ok": code == 0, "exit": code, "output": output[-2000:]})


def _safe_scan() -> None:
    try:
        _start_scan()
    except OSError:
        log.exception("inventory rescan did not start")

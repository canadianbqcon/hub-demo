"""API keys: seed os.environ from dashboard/.env once, then read it."""

import importlib.util
import os
import pathlib
import sys

_DASHBOARD = str(pathlib.Path(__file__).resolve().parents[2])
_seeded = False


def key(name: str) -> str | None:
    global _seeded
    if not _seeded:
        if _DASHBOARD not in sys.path:
            sys.path.append(_DASHBOARD)  # append: hub-local names must keep winning
        # by path: a bare `import services` can resolve to ~/.config/vault-api/services.py, which has no _load_env
        spec = importlib.util.spec_from_file_location("_dashboard_services", _DASHBOARD + "/services.py")
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {_DASHBOARD}/services.py")
        services = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(services)
        services._load_env()
        _seeded = True
    return os.environ.get(name) or None

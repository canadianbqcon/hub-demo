"""Public surface for the jobs database.

Split into sections 2026-07-29 (was 1550 lines). Import from here, not the
db_* modules. This is the only name every caller and test binds against.
"""
from __future__ import annotations

from .db_applications import *  # noqa: F401,F403
from .db_core import _conn, _row, _today, _touch_app, application_count, init  # noqa: F401
from .db_glossary import *  # noqa: F401,F403
from .db_materials import *  # noqa: F401,F403
from .db_people import *  # noqa: F401,F403
from .db_process import *  # noqa: F401,F403

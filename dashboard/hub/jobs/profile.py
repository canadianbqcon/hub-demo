"""Candidate-profile parsing: candidate_profile.md -> positions / education / tools.

Markdown-table parsing is domain logic, not request handling, so per the
four-layer rule in wiki/notes/dashboard-code-structure it does not belong in a
route body (where it used to live, all ~75 lines of it). The route is now a
one-liner that jsonifies what this returns.

Not a db_*.py module on purpose: the source of truth here is a Markdown file
next to this package, not jobs.db.
"""

from __future__ import annotations

import re
from pathlib import Path

PROFILE_PATH = Path(__file__).parent / "candidate_profile.md"

# Words dropped when building a position's stable id, so "The Upper East Side
# Medical Center, Inc." and its role collapse to a short readable slug.
_SLUG_STOPWORDS = {
    "the",
    "inc",
    "llc",
    "corp",
    "corporation",
    "upper",
    "east",
    "side",
    "university",
    "of",
    "and",
    "medical",
    "center",
    "irving",
}


def _slug(s: str, n: int = 2) -> str:
    words = re.sub(r"[^\w\s]", "", s.lower()).split()
    filtered = [w for w in words if w not in _SLUG_STOPWORDS] or words
    return "_".join(filtered[:n])


def load_candidate_profile() -> dict:
    """Read candidate_profile.md and return the shape the jobs UI consumes.

    ``{"positions": [{id, company, role, dates, details}], "education": str,
    "tools": str}``. A missing file yields the same shape, empty — the intake
    surface then just has nothing to match against, rather than erroring.

    Positions come from the one Markdown table whose header is
    ``| Dates | Role | Company |``; the table ends at the first line that does
    not start with a pipe. A parenthesised tail on the company cell
    ("Acme (contract)") is split off into ``details``.
    """
    if not PROFILE_PATH.exists():
        return {"positions": [], "education": "", "tools": ""}

    text = PROFILE_PATH.read_text(encoding="utf-8")

    positions = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if "| Dates | Role | Company |" in stripped:
            in_table = True
            continue
        if in_table:
            if not stripped.startswith("|"):
                in_table = False
                continue
            m = re.match(
                r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", stripped
            )
            if not m:
                continue
            dates, role, company = (
                m.group(1).strip(),
                m.group(2).strip(),
                m.group(3).strip(),
            )
            if not re.search(r"[a-zA-Z0-9]", dates):
                continue
            if dates.lower() == "dates":
                continue
            details_m = re.search(r"\(([^)]+)\)", company)
            details = details_m.group(1) if details_m else ""
            company_clean = re.sub(r"\s*\([^)]+\)", "", company).strip()
            pos_id = f"{_slug(company_clean, 1)}_{_slug(role, 2)}"
            positions.append(
                {
                    "id": pos_id,
                    "company": company_clean,
                    "role": role,
                    "dates": dates,
                    "details": details,
                }
            )

    edu_m = re.search(r"\*\*Education:\*\*\s*(.+)", text)
    tools_m = re.search(r"\*\*Tools on resume:\*\*\s*(.+)", text)

    return {
        "positions": positions,
        "education": edu_m.group(1).strip() if edu_m else "",
        "tools": tools_m.group(1).strip() if tools_m else "",
    }

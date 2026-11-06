"""File-side content for s_system: capabilities skills, inventory scans, artifacts catalog,
viewer items, and the vault-map tree. Pure, deterministic, invented.

Files are copied raw by the reset (tokens in them are NOT rewritten), so dates here count
from sysdata_wb.ANCHOR.
"""
import json

from sysdata_wb import day, png, wireframe

# ---- capabilities: skills under <vault>/.claude/skills and <vault>/skills --------------------

SKILLS = [  # (folder, name, description)   name drives the purpose bucket in capabilities/scan.py
    ("gmail", "gmail", "Sort the inbox: propose a label or delete for each message and ask before anything irreversible."),
    ("finance", "finance", "Categorize new bank transactions, learn payee rules, and keep the budget book balanced."),
    ("job", "job", "Track a job application from posting to offer: score the fit, draft the cover letter, log each step."),
    ("job-research", "job-research", "Research a company before an interview: culture signals, recent news, likely questions."),
    ("recap", "recap", "Rebuild yesterday from calendar, mail and receipts, then reconcile against what was planned."),
    ("ingest", "ingest", "Turn a dropped file or link into a wiki note with sources, tags and links."),
    ("research-max", "research-max", "Deep research on a question: many sources, cross-checked, written up with a verdict."),
    ("research-min", "research-min", "Quick two-source answer with links, for questions that do not need a full report."),
    ("audit", "audit", "Sweep a folder for stale, duplicate or broken notes and fix what is clear-cut."),
    ("code-audit", "code-audit", "Read a module for bugs, dead code and missing tests; report findings with file and line."),
    ("explain", "explain", "Explain a concept or a piece of code in plain words with one worked example."),
    ("handoff", "handoff", "Write a resume file so the next session picks up exactly where this one stopped."),
    ("onboard-domain", "onboard-domain", "Set up a new area of the vault: folder, index map, scoped rules and a first test."),
    ("session-to-skill", "session-to-skill", "Turn a session that worked well into a reusable skill file."),
    ("dashboard", "dashboard", "Conventions for adding a page or API to the Hub and checking it renders."),
]


def skill_files():
    out = {}
    for folder, name, desc in SKILLS:
        out[f".claude/skills/{folder}/SKILL.md"] = (
            f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n\n{desc}\n\n"
            f"## Steps\n\n1. Read the request and the files it names.\n2. Do the work, then check it.\n"
            f"3. Report what changed and what is left.\n").encode()
    out["skills/plan-week/SKILL.md"] = (
        "---\nname: plan-week\ndescription: Lay out the coming week from the planner, shifts and trips, flagging clashes.\n---\n\n"
        "# plan-week\n\nLay out the coming week from the planner, shifts and trips, flagging clashes.\n").encode()
    out[".claude/settings.json"] = json.dumps({"hooks": {"PostToolUse": [], "Stop": []}, "permissions": {"deny": []}}, indent=2).encode()
    out[".agents/hooks.json"] = json.dumps({"hooks": []}, indent=2).encode()
    out[".agents/skills.json"] = json.dumps({"entries": []}, indent=2).encode()
    return out


# ---- inventory ------------------------------------------------------------------------------

_C = ["Everyday apps", "Creative and media", "Games", "Developer tools", "Drivers and hardware", "Runtimes and system parts"]
_WIN = [  # (name, publisher, cat, size MB, installed offset days)
    ("Mozilla Firefox", "Mozilla", 0, 310, -400), ("Notepad Plus Plus", "Don Ho", 0, 24, -380),
    ("7-Zip", "Igor Pavlov", 0, 5, -500), ("Spotify", "Spotify AB", 1, 420, -300), ("VLC media player", "VideoLAN", 1, 190, -350),
    ("Audacity", "Audacity Team", 1, 95, -200), ("GIMP", "GIMP Team", 1, 1100, -150), ("OBS Studio", "OBS Project", 1, 340, -120),
    ("Steam", "Valve", 2, 3200, -450), ("Factorio", "Wube Software", 2, 2400, -90), ("Stardew Valley", "ConcernedApe", 2, 700, -60),
    ("Visual Studio Code", "Microsoft", 3, 380, -420), ("Git", "Git Development Community", 3, 320, -430),
    ("Python 3.12", "Python Software Foundation", 3, 120, -410), ("Node.js", "OpenJS Foundation", 3, 85, -405),
    ("Docker Desktop", "Docker Inc.", 3, 2900, -240), ("DB Browser for SQLite", "DB4S Team", 3, 60, -180),
    ("Windows Terminal", "Microsoft", 3, 150, -440), ("NVIDIA Graphics Driver", "NVIDIA", 4, 1800, -30),
    ("Realtek Audio Driver", "Realtek", 4, 220, -380), ("Logitech Options", "Logitech", 4, 410, -330),
    ("Intel Wireless Bluetooth", "Intel", 4, 45, -380), ("Microsoft Visual C++ 2015-2022 Redistributable (x64)", "Microsoft", 5, 25, -440),
    (".NET Desktop Runtime 8", "Microsoft", 5, 210, -300), ("Java Runtime Environment 21", "Oracle", 5, 280, -260),
    ("Microsoft Edge WebView2 Runtime", "Microsoft", 5, 410, -20), ("Windows Subsystem for Linux", "Microsoft", 5, 340, -440),
]
_MAC = [
    ("Safari Technology Preview", "Apple", 0, 480, -60), ("Firefox", "Mozilla", 0, 290, -200), ("Zotero", "Corporation for Digital Scholarship", 0, 520, -250),
    ("Spotify", "Spotify AB", 1, 380, -240), ("IINA", "IINA Team", 1, 110, -230), ("Visual Studio Code", "Microsoft", 3, 400, -230),
    ("Homebrew", "Homebrew", 3, 90, -230), ("Git", "Git Development Community", 3, 120, -230), ("Python 3.12", "Python Software Foundation", 3, 130, -220),
    ("Rosetta 2", "Apple", 5, 60, -230), ("Xcode Command Line Tools", "Apple", 5, 1900, -230),
]


def _key(name):
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def _programs(rows, side):
    out = []
    for name, pub, cat, mb, off in rows:
        k = _key(name)
        rec = {"key": k, "name": name, "publisher": pub, "cat": _C[cat], "size": mb, "side": side, "date": day(off)}
        if side == "Windows":
            rec["path"] = f"C:\\Program Files\\{name}"
            rec["uninstall"] = ["winget", "uninstall", "--id", f"Demo.{k}", "--silent"] if cat < 4 else None
            rec["uninstall_text"] = f"winget uninstall --id Demo.{k}" if cat < 4 else ""
            rec["restore"] = f"winget install --id Demo.{k}"
            rec["registry_uninstall"] = f"HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{k}" if cat >= 4 else None
        else:
            rec["path"] = f"/Applications/{name}.app"
            rec["uninstall"] = None
            rec["uninstall_text"] = f"brew uninstall --cask {k}"
            rec["restore"] = f"brew install --cask {k}"
        out.append(rec)
    return out


def inventory_files():
    scanned = f"{day(0)}T07:42:10"
    return {
        "data/inventory/Sam-Desktop/programs.json": json.dumps({"scanned": scanned, "programs": _programs(_WIN, "Windows")}, indent=1).encode(),
        "data/inventory/Sam-Desktop/scanned.json": json.dumps({
            "winget": {"outcome": "ok", "last_success": scanned, "error": None},
            "registry": {"outcome": "ok", "last_success": scanned, "error": None},
            "store apps": {"outcome": "ok", "last_success": scanned, "error": None},
            "brew": {"outcome": "absent", "last_success": None, "error": None}}, indent=1).encode(),
        "data/inventory/Sam-MacBook/programs.json": json.dumps({"scanned": f"{day(-2)}T21:15:40", "programs": _programs(_MAC, "Mac")}, indent=1).encode(),
        "data/inventory/Sam-MacBook/scanned.json": json.dumps({
            "brew": {"outcome": "ok", "last_success": f"{day(-2)}T21:15:40", "error": None},
            "applications folder": {"outcome": "ok", "last_success": f"{day(-2)}T21:15:40", "error": None}}, indent=1).encode(),
    }


# ---- artifacts catalog ----------------------------------------------------------------------

ARTIFACTS = [  # (title, url, offset, category, description, favicon, tool)
    ("Lisbon trip day planner", "https://artifacts.example/lisbon-planner", -2, "Planning", "Three loose days plus the Alfama tram tour, with walking times between stops.", "L", False),
    ("Packing list builder", "https://artifacts.example/packing-list", -9, "Planning", "Pick a trip length and weather, get a checklist that ticks and saves.", "P", True),
    ("Shift pay calculator", "https://artifacts.example/shift-pay", -12, "Finance", "Enter hours and tips for a week of bar shifts and see a pre-tax estimate.", "$", True),
    ("October spending breakdown", "https://artifacts.example/oct-spend", -6, "Finance", "Where the month went, by category, against the budget book.", "O", False),
    ("Cheapest month to fly to Lisbon", "https://artifacts.example/lisbon-fares", -15, "Research", "A fare history comparison for ORD to LIS across eight months.", "F", False),
    ("Standing desk comparison", "https://artifacts.example/desk-compare", -20, "Research", "Five desks scored on stability, noise and price, with the pick.", "D", False),
    ("Interview prep: Harbor & Pine", "https://artifacts.example/hp-prep", -3, "Career", "Likely questions, three stories to tell, and questions to ask the team.", "H", False),
    ("Resume bullet rewriter", "https://artifacts.example/bullets", -11, "Career", "Paste a bullet, get three tighter versions with numbers kept.", "R", True),
    ("Hub tour", "/guide/", -1, "Hub", "The ten-minute tour of every page in this Hub.", "G", False),
    ("Workbench", "/workbench/", -1, "Hub", "Sign off specs, plans and design options.", "W", False),
    ("Recipe scaler", "https://artifacts.example/scaler", -25, "Cooking", "Scale a recipe to any serving count and see grams next to cups.", "S", True),
    ("Braise timing chart", "https://artifacts.example/braise", -18, "Cooking", "Oven temperature and hours by cut, for the five braises on the shortlist.", "B", False),
]


def artifacts_file():
    items = []
    for title, url, off, cat, desc, fav, tool in ARTIFACTS:
        e = {"title": title, "url": url, "updated": day(off), "category": cat, "description": desc, "favicon": fav}
        if tool:
            e["tool"] = True
        items.append(e)
    return {"data/artifacts.json": json.dumps({"artifacts": items}, indent=2).encode()}


# ---- viewer items ---------------------------------------------------------------------------

def viewer_files():
    """data/viewer/<id>/item.json plus the files. Item ids are dated; the Viewer keeps 30 days."""
    out = {}

    def item(iid, kind, title, source, files, created, url=None, framable=None, status="none"):
        for name, data in files.items():
            out[f"data/viewer/{iid}/{name}"] = data
        meta = {"id": iid, "kind": kind, "title": title, "created": created, "source": source,
                "files": [{"name": n, "orig": n, "label": n, "thumb": n if n.endswith(".png") else None, "preview": None} for n in files],
                "url": url, "framable": framable, "preview_status": status, "progress": 0}
        out[f"data/viewer/{iid}/item.json"] = json.dumps(meta, indent=1).encode()

    ink, paper = (44, 42, 40), (232, 228, 222)
    d1, d2, d3, d4 = day(-1).replace("-", ""), day(-2).replace("-", ""), day(-4).replace("-", ""), day(-6).replace("-", "")
    item(f"{d1}-091244-a1b2c3-dusk-palette-swatches", "photo", "Dusk palette swatches", "Claude",
         {"before.png": wireframe("rail", ink, (222, 154, 76), paper), "after.png": wireframe("rail", ink, (110, 190, 140), paper)},
         f"{day(-1)}T09:12:44.000000", status="none")
    item(f"{d2}-161502-d4e5f6-lisbon-day-three", "photo", "Lisbon day three sketch", "Claude",
         {"day3.png": wireframe("topbar", (36, 44, 58), (96, 150, 220), (226, 230, 236))}, f"{day(-2)}T16:15:02.000000")
    item(f"{d3}-102233-0718ab-trips-page", "web", "Trips page", "Claude", {}, f"{day(-4)}T10:22:33.000000", url="/trips/", framable=False)
    item(f"{d4}-193010-9f8e7d-week-notes", "file", "Week notes", "Claude",
         {"week-notes.md": b"# Week notes\n\n- Thursday 2pm call with Harbor & Pine\n- Send the one pager before then\n- Compare the two Lisbon transfer quotes\n"},
         f"{day(-6)}T19:30:10.000000")
    item(f"{day(-3).replace('-', '')}-081500-c0ffee-receipt-scan", "upload", "receipt-scan.png", "Upload",
         {"receipt-scan.png": png(240, 320, [(20, 20, 200, 18, (60, 60, 60)), (20, 56, 160, 8, (170, 170, 170)), (20, 76, 180, 8, (170, 170, 170)), (20, 96, 120, 8, (170, 170, 170)), (20, 260, 200, 16, (60, 60, 60))], bg=(250, 250, 246))},
         f"{day(-3)}T08:15:00.000000")
    return out


# ---- vault map tree -------------------------------------------------------------------------
# folder: (purpose, children dict, files list). file: (name, size bytes, lines, purpose)

def _f(name, size, lines=None, purpose=None):
    return (name, size, lines, purpose)


VAULT_TREE = {
    "wiki": ("Authored notes: concepts, decisions, facts, sources, tasks and maps.", {
        "concepts": ("Ideas worth keeping, one per note.", {}, [_f("budget-envelopes.md", 2400, 48, "How the monthly budget envelopes work."), _f("forecasting-small-samples.md", 3100, 61, "Notes on forecasting with little data."), _f("shift-work-and-sleep.md", 1900, 38, "What helps and what does not on closing shifts.")]),
        "decisions": ("Choices made and why.", {}, [_f("standing-desk-pick.md", 2200, 44, "Why the mid-range desk won."), _f("move-banking-credit-union.md", 1800, 35, "Why checking moved to the credit union.")]),
        "facts": ("Stable facts about Sam and the setup.", {}, [_f("user-profile.md", 1500, 30, "Role, city, schedule and preferences."), _f("home-network.md", 1100, 22, "Router, devices and addresses.")]),
        "sources": ("Notes on articles, books and videos.", {}, [_f("book-thinking-in-systems.md", 2600, 52, "Highlights from the book."), _f("article-forecast-accuracy.md", 1700, 33, "Summary of an article on forecast accuracy.")]),
        "tasks": ("One note per larger task.", {}, [_f("lisbon-trip-prep.md", 2900, 57, "Everything left before the Lisbon flight."), _f("resume-refresh.md", 2100, 41, "Plan for the resume rewrite.")]),
        "maps": ("Index notes that group other notes.", {}, [_f("travel.md", 900, 20, "Trips, packing and bookings."), _f("career.md", 1000, 22, "Applications, stories and prep.")]),
    }, [_f("index.md", 1800, 40, "Top-level index of the wiki.")]),
    "raw": ("Captured inputs waiting to be processed.", {
        "articles": ("Saved web articles.", {}, [_f("2026-10-forecast-accuracy.md", 9800, 190), _f("2026-10-braise-guide.md", 7400, 142)]),
        "receipts": ("Receipt scans and exports.", {}, [_f("2026-10-brightcart.pdf", 52000, None), _f("2026-10-prairie-power.pdf", 38000, None)]),
    }, []),
    "data": ("SQLite databases and exports the Hub reads.", {}, [_f("tasks.db", 262144, None), _f("jobs.db", 524288, None), _f("trips.db", 393216, None), _f("book.db", 1048576, None), _f("mail.db", 786432, None)]),
    "log": ("Operational logs.", {}, [_f("log.md", 14200, 310, "Append-only record of ingests and refactors."), _f("scheduler-runs.jsonl", 8800, 64)]),
    "docs": ("Specs, plans and working docs.", {
        "specs": ("Design specs.", {}, [_f("2026-10-21-dark-theme-tune.md", 3300, 60), _f("2026-10-28-weekly-digest-card.md", 2900, 54)]),
        "plans": ("Implementation plans.", {}, [_f("2026-10-23-dark-theme-tune.md", 3800, 70)]),
    }, []),
    ".claude": ("Claude Code config: skills, hooks and settings.", {
        "skills": ("One folder per skill.", {}, [_f("README.md", 700, 14, "How skills are laid out.")]),
        "hooks": ("Scripts that run on tool events.", {}, [_f("report-check.py", 3200, 80), _f("pending-guard.py", 2600, 64)]),
    }, [_f("settings.json", 1400, 52)]),
}
VAULT_ROOT_FILES = [_f("AGENTS.md", 9800, 160, "Rules every agent follows in this vault."), _f("CLAUDE.md", 6200, 110, "Claude-specific session rules."), _f("inbox.md", 900, 24, "Quick capture list.")]

CODE_TREE = {
    "dashboard": ("The Flask app: the Hub and its modules.", {
        "hub": ("Hub modules, one folder each.", {
            "tasks": ("Planner module.", {}, [_f("api.py", 21000, 540), _f("db.py", 14000, 380)]),
            "jobs": ("Job tracker module.", {}, [_f("api.py", 26000, 690), _f("db.py", 19000, 520)]),
            "trips": ("Trip planner module.", {}, [_f("api.py", 30000, 760), _f("db.py", 24000, 640)]),
            "finances": ("Budget book module.", {}, [_f("book.py", 41000, 1020), _f("autocat.py", 17000, 430)]),
            "workbench": ("Spec and plan sign-off.", {}, [_f("api.py", 15000, 401), _f("store.py", 9800, 255)]),
            "static": ("Shared styles and scripts.", {"css": ("Stylesheets.", {}, [_f("base.css", 28000, 548), _f("chrome.css", 12000, 260)])}, []),
        }, [_f("app.py", 36000, 880, "Flask app: registers every module."), _f("hub_modules.py", 6400, 160)]),
    }, [_f("vault_path.py", 1400, 38), _f("sqlite_helpers.py", 2600, 70)]),
    "db": ("Migrations for every database.", {"migrations": ("SQL migrations, one folder per database.", {}, [_f("001_init.sql", 3100, 90), _f("002_add_status.sql", 600, 14)])}, []),
    "tests": ("Test suite.", {}, [_f("test_tasks.py", 8400, 220), _f("test_jobs.py", 9100, 240), _f("test_trips.py", 10200, 260)]),
}
CODE_ROOT_FILES = [_f("CLAUDE.md", 5200, 96, "Conventions for working on the code."), _f("pyproject.toml", 900, 28)]

FN_BY_TOP = {"wiki": "knowledge", "raw": "ingest", "data": "data", "log": "records", "docs": "knowledge", ".claude": "governance"}
EXT_FN = {".md": "knowledge", ".py": "code", ".css": "code", ".json": "config", ".toml": "config", ".sql": "data", ".db": "data",
          ".jsonl": "records", ".pdf": "asset"}
EXT_LABEL = {".py": "Python module.", ".css": "Stylesheet.", ".json": "JSON data / config.", ".db": "SQLite database file.",
             ".sql": "SQL migration / query.", ".pdf": "PDF document.", ".jsonl": "Line-delimited log.", ".toml": "TOML config."}

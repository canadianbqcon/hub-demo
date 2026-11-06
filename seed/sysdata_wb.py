"""Workbench content for the demo: specs, plans, option sets, mark sessions.

Pure and deterministic. The reset rewrites @d/@t tokens in database cells only,
never in files or file names, so everything here dates itself from the fixed
ANCHOR day (the day the seeder was written) with day(n).
"""
import datetime
import hashlib
import json
import struct
import zlib

# decisions.doc_path must equal the absolute path the Hub resolves, so it needs the
# deployed vault path. ponytail: the Docker image must set VAULT_PATH to this.
VAULT = "/app/demo-vault"
ANCHOR = datetime.date(2026, 11, 6)


def day(n):
    return (ANCHOR + datetime.timedelta(days=n)).isoformat()


def png(w, h, shapes, bg=(245, 245, 242)):
    """Tiny plain PNG: a solid background plus filled rectangles [(x, y, w, h, (r, g, b))]."""
    rows = [[bg] * w for _ in range(h)]
    for x, y, sw, sh, col in shapes:
        for yy in range(max(y, 0), min(y + sh, h)):
            for xx in range(max(x, 0), min(x + sw, w)):
                rows[yy][xx] = col
    raw = b"".join(b"\x00" + b"".join(bytes(p) for p in r) for r in rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def wireframe(layout, ink, accent, paper):
    shapes = []
    if layout == "rail":
        shapes += [(0, 0, 70, 220, ink), (10, 14, 50, 8, accent), (10, 34, 50, 6, paper), (10, 50, 50, 6, paper), (10, 66, 50, 6, paper)]
        for i in range(3):
            shapes.append((84 + i * 90, 16, 80, 60, (255, 255, 255)))
            shapes.append((84 + i * 90, 16, 80, 6, accent))
        shapes += [(84, 92, 260, 112, (255, 255, 255)), (96, 104, 120, 8, ink), (96, 122, 230, 6, (200, 200, 196)), (96, 138, 200, 6, (200, 200, 196))]
    elif layout == "topbar":
        shapes += [(0, 0, 360, 26, ink), (12, 9, 40, 8, accent), (300, 9, 44, 8, paper)]
        for r in range(2):
            for c in range(3):
                shapes.append((14 + c * 114, 40 + r * 84, 104, 74, (255, 255, 255)))
                shapes.append((22 + c * 114, 50 + r * 84, 50, 7, ink))
                shapes.append((22 + c * 114, 66 + r * 84, 84, 5, (200, 200, 196)))
                shapes.append((22 + c * 114, 100 + r * 84, 30, 10, accent))
    else:  # tiles
        for i in range(4):
            shapes.append((14 + i * 86, 14, 78, 36, accent if i == 0 else (255, 255, 255)))
        shapes += [(14, 62, 332, 144, (255, 255, 255))]
        for i in range(5):
            shapes.append((24, 74 + i * 26, 312, 16, (236, 236, 232) if i % 2 else paper))
            shapes.append((30, 78 + i * 26, 70, 7, ink))
    return png(360, 220, shapes, bg=paper)


def _sha(b):
    return hashlib.sha256(b).hexdigest()


# (slug, title, goal, [(Section, body)], decision-kind data) -------------------------------------

SPECS = {
    "dark-theme-tune": ("Dark theme tune", -16, "Make the dark theme easier on the eyes at night without losing contrast on tables.", [
        ("Interview", "### Goal\n\nSam: the dark theme is too blue and the table stripes disappear after 10pm.\n\n### Scope\n\nFrom disk: one stylesheet, `base.css`, owns every surface colour.\n\n### Out\n\nSam: no per-page overrides."),
        ("Files", "- Edit `static/css/base.css` (surface and stripe tokens)\n- Create `static/css/theme-dusk.css` (the new palette)\n- Test `tests/test_theme_tokens.py` (contrast of every token pair)"),
        ("Check", "1. Every text token passes 4.5:1 on its surface.\n2. Table stripes differ by at least 6 lightness points.\n3. The old theme still loads when the dusk file is removed."),
        ("Explicitly not built", "- A theme picker: one palette ships, the switch stays where it is.\n- Per-page colours: they drift."),
    ]),
    "weekly-digest-card": ("Weekly digest card", -9, "A single card on Home that sums up the week: spend, shifts worked, tasks closed.", [
        ("Interview", "### Goal\n\nSam: one glance on Sunday night to see how the week went.\n\n### Sources\n\nFrom disk: tasks, shifts and the budget book already hold every number."),
        ("Files", "- Create `home/digest_card.py` (builds the week's numbers)\n- Edit `static/js/home.jsx` (mount the card)\n- Test `tests/test_digest_card.py`"),
        ("Check", "1. A week with no shifts shows a dash, not zero hours.\n2. Money is shown in the currency it was spent in.\n3. The card loads in under 200 ms."),
        ("Explicitly not built", "- Email delivery: the card lives on the page only.\n- Charts: three numbers and a sentence."),
    ]),
    "shift-swap-board": ("Shift swap board", -5, "A small board where a shift swap is offered, taken and logged.", [
        ("Interview", "### Goal\n\nSam: swaps live in group chats and get lost.\n\n### People\n\nSam: six coworkers, all at one venue."),
        ("Files", "- Create `work/swaps.py` (offer, take, log)\n- Edit `work/api.py` (two routes)\n- Test `tests/test_swaps.py`"),
        ("Check", "1. A taken swap cannot be taken twice.\n2. A swap in the past is refused.\n3. Both people see the change."),
        ("Explicitly not built", "- Notifications: he checks the board himself."),
    ]),
    "receipt-inbox": ("Receipt inbox", -2, "Drop a photo of a receipt and have it waiting beside the matching transaction.", [
        ("Interview", "### Goal\n\nSam: paper receipts pile up before tax time.\n\n### Open\n\nSam: unsure whether a photo should be read for line items."),
        ("Files", "- Create `finances/receipts.py`\n- Edit `static/js/finance.jsx` (an attach button)"),
        ("Check", "1. A receipt attaches to exactly one transaction.\n2. A second attach asks before it replaces."),
        ("Explicitly not built", "- Reading line items: later, once the attach flow settles."),
    ]),
}

PLANS = {
    "dark-theme-tune": ("Dark theme tune", -14, "Ship the dusk palette behind the existing theme switch.", [
        ("Palette tokens", 6, ["static/css/theme-dusk.css"], "Write the surface, stripe and text tokens.", ["Pick the surface ladder", "Write the tokens", "Run the contrast test"]),
        ("Wire the switch", 4, ["static/css/base.css"], "Point the theme switch at the new file.", ["Edit the loader", "Check the old theme still loads"]),
        ("Screens", 3, ["tests/test_theme_tokens.py"], "Check the stripes on the three busiest tables.", ["Open each table", "Compare against the spec"]),
    ]),
    "weekly-digest-card": ("Weekly digest card", -7, "Build the digest numbers, then the card.", [
        ("Digest numbers", 8, ["home/digest_card.py", "tests/test_digest_card.py"], "One function returns the week's figures.", ["Write the query", "Handle the empty week", "Test"]),
        ("Mount the card", 5, ["static/js/home.jsx"], "Show it above the task list.", ["Add the component", "Check the phone width"]),
    ]),
}

OPTION_SETS = {
    # slug: (build, title, intro, [(title, blurb, layout, ink, accent, paper)])
    "dark-theme-tune-1-surfaces": ("dark-theme-tune", "Dark theme: surface ladder", "Three ways to step the dark surfaces.", [
        ("Warm graphite", "Neutral grey with a warm cast; stripes at +8 lightness.", "rail", (44, 42, 40), (222, 154, 76), (232, 228, 222)),
        ("Cool slate", "The current blue, pulled back 30 percent.", "topbar", (36, 44, 58), (96, 150, 220), (226, 230, 236)),
        ("Near black", "Highest contrast; stripes carried by a hairline.", "tiles", (18, 18, 20), (110, 190, 140), (222, 224, 224)),
    ]),
    "weekly-digest-card-1-layout": ("weekly-digest-card", "Weekly digest card: layout", "Where the three numbers sit on the card.", [
        ("Three tiles", "Spend, hours and tasks as equal tiles with one sentence under.", "tiles", (40, 52, 70), (92, 148, 200), (240, 242, 244)),
        ("Sentence first", "A written summary leads; the numbers trail as chips.", "topbar", (60, 48, 40), (206, 128, 70), (244, 240, 234)),
        ("Side rail", "Numbers down a rail, a short note beside it.", "rail", (30, 60, 52), (88, 176, 140), (238, 244, 240)),
    ]),
    "shift-swap-board-1-board": ("shift-swap-board", "Shift swap board: board shape", "Three shapes for the swap board.", [
        ("Week grid", "Seven columns, offered swaps pinned to the day.", "topbar", (52, 40, 70), (150, 110, 210), (240, 236, 246)),
        ("Plain list", "Newest offer first, a take button on each row.", "tiles", (46, 46, 46), (200, 160, 70), (242, 240, 236)),
    ]),
}

MARKS = {  # session folder name -> marks
    f"{day(-1)}-143012-Sam-Desktop": [
        dict(n=1, url="/tasks/", title="Done column crowds the date", comment="The date runs into the checkbox on a narrow window.", kind="bug", status="fixed", fix_note="Added a 12px gap and let the date wrap under the title below 520px."),
        dict(n=2, url="/trips/", title="Packing list has no empty state", comment="A new trip shows a blank card with no hint.", kind="idea", status="open"),
    ],
}


def spec_text(key):
    title, _, goal, sections = SPECS[key]
    out = [f"# {title}\n", f"{goal}\n"]
    for h, b in sections:
        out.append(f"## {h}\n\n{b}\n")
    return "\n".join(out)


def plan_text(key):
    title, _, goal, tasks = PLANS[key]
    out = [f"# {title} Implementation Plan\n", f"**Goal:** {goal}\n", "**Architecture:** One small change per file, tested before the next.\n",
           "**Runs as:** inline\n"]
    for i, (name, k, files, how, steps) in enumerate(tasks, 1):
        out.append(f"### Task {i}: {name} ~{k}k\n")
        out.append(f"Summary: {how}\n")
        out.append("**Files:**\n" + "\n".join(f"- {'Create' if j == 0 and i == 1 else 'Edit'}: `{f}`" for j, f in enumerate(files)) + "\n")
        out.append("\n".join(f"- [ ] **Step {j}: {s}** Do it and confirm it by running the test for this task." for j, s in enumerate(steps, 1)) + "\n")
    return "\n".join(out)


def option_files(slug):
    """{relative path inside the set folder: bytes}"""
    build, title, intro, cards = OPTION_SETS[slug]
    files = {"build.txt": build.encode() + b"\n"}
    files["head.html"] = f"<h1>{title}</h1>\n<p>{intro}</p>\n".encode()
    files["styles.css"] = b".opt .spec p{margin:6px 16px 12px}.opt .stage{padding:0 16px 8px}.opt .stage img{max-width:100%;border:1px solid #ccc}\n"
    arts = []
    for i, (t, blurb, layout, ink, accent, paper) in enumerate(cards):
        name = f"{chr(97 + i)}.png"
        files["assets/" + name] = wireframe(layout, ink, accent, paper)
        arts.append(f'<article class="opt"><h2>{t}</h2><div class="spec"><p>{blurb}</p></div>'
                    f'<div class="stage"><img alt="{t}" src="/workbench/api/option/asset?set={slug}&amp;path={name}"></div></article>')
    files["options.html"] = ("\n".join(arts) + "\n").encode()
    return files


def manifest(files):
    return {k: _sha(v) for k, v in sorted(files.items()) if k != "build.txt"}


def design_hash(files):
    return _sha(json.dumps(manifest(files), sort_keys=True).encode())


def mark_session_files(session):
    """marks.json plus a crop and after picture for each mark."""
    marks = []
    for m in MARKS[session]:
        marks.append({**m, "created": f"{day(-1)}T14:30:12"})
    head = {"started": f"{day(-1)}T14:30:12", "machine": "Sam-Desktop", "next_n": len(marks) + 1, "code_commit": "a41c9e2", "dirty": False, "marks": marks}
    out = {"marks.json": json.dumps(head, indent=2).encode()}
    for m in MARKS[session]:
        out[f"{m['n']:02d}-crop.png"] = png(240, 120, [(10, 10, 220, 24, (60, 60, 70)), (10, 46, 140, 12, (200, 120, 70)), (10, 70, 200, 10, (200, 200, 196))])
        if m["status"] == "fixed":
            out[f"{m['n']:02d}-after.png"] = png(240, 120, [(10, 10, 220, 24, (60, 60, 70)), (10, 46, 140, 12, (90, 170, 120)), (10, 70, 200, 10, (200, 200, 196)), (210, 100, 20, 10, (90, 170, 120))])
    return out

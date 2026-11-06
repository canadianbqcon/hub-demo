"""System pages for the demo: workbench, vault map, automations, music (databases),
plus the files behind workbench, marks, capabilities, inventory, artifacts and viewer.

AI-written rows are flagged as sample output: gmail_item.run_id = "demo-sample-run" and
decision.reason/rule text are model-style prose under that run; burn_run.status
"merged" with report_json.sample = true; music has none. Files cannot carry date
tokens (the reset only rewrites database cells), see sysdata_wb.ANCHOR.
"""
import datetime
import hashlib
import json
import string
import uuid

import s_mail
import sysdata_files as sf
import sysdata_wb as wb

DB = ("workbench", "vault_map", "automations", "music")
EXPECT = {
    "workbench.decisions": 9,
    "vault_map.map_node": 60, "vault_map.node_description": 3,
    "automations.gmail_item": 10, "automations.lane_run": 2, "automations.burn_run": 2,
    "automations.rule": 5, "automations.decision": 5, "automations.gmail_note": 1,
    "music.tracks": 30, "music.playlists": 6, "music.playlist_tracks": 40,
    "music.refreshes": 2, "music.changes": 4, "music.readings": 3,
}
SAMPLE_RUN = "demo-sample-run"


# ---------------------------------------------------------------- workbench decisions

def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _uid(rnd):
    return str(uuid.UUID(int=rnd.getrandbits(128), version=4))


def _stamp(hours):
    # decisions is append-only (a trigger refuses UPDATE), so the reset cannot rewrite @t tokens here
    return (datetime.datetime.combine(wb.ANCHOR, datetime.time(12)) + datetime.timedelta(hours=hours)).isoformat(sep=" ")


def _workbench(con, rnd, P):
    seqs = {}

    def add(slug, kind, path, verdict, hours, sha=None, choice=None, comment=None, snapshot=None):
        seqs[slug] = seqs.get(slug, 0) + 1
        con.execute("INSERT INTO decisions (id,seq,build_slug,kind,doc_path,doc_sha256,verdict,choice,comment,snapshot,decided_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (_uid(rnd), seqs[slug], slug, kind, path, sha, verdict, choice, comment, snapshot, _stamp(hours)))

    for key in ("dark-theme-tune", "weekly-digest-card", "shift-swap-board"):
        title, off, goal, _ = wb.SPECS[key]
        text = wb.spec_text(key)
        path = f"{wb.VAULT}/docs/specs/{wb.day(off)}-{key}.md"
        if key == "shift-swap-board":
            add(key, "spec", path, "sent_back", off * 24 + 34, _sha(text.encode()), comment="Say who can post a swap, not only who can take one.", snapshot=text)
        else:
            add(key, "spec", path, "approved", off * 24 + 30, _sha(text.encode()), snapshot=text)
    for key in ("dark-theme-tune", "weekly-digest-card"):
        title, off, goal, _ = wb.PLANS[key]
        text = wb.plan_text(key)
        add(key, "plan", f"{wb.VAULT}/docs/plans/{wb.day(off)}-{key}.md", "approved", off * 24 + 20, _sha(text.encode()), snapshot=text)
    for slug, choice in (("dark-theme-tune-1-surfaces", "A"), ("weekly-digest-card-1-layout", "A")):
        build = wb.OPTION_SETS[slug][0]
        files = wb.option_files(slug)
        man = wb.manifest(files)
        add(build, "design", f"{wb.VAULT}/data/workbench/options/{slug}", "approved", -24 * 12 if build.startswith("dark") else -24 * 6,
            wb.design_hash(files), choice=choice, snapshot=json.dumps(man, sort_keys=True, indent=2))
    # closed marks: only the ledger row stays once a mark is closed
    old = f"{wb.day(-4)}-091500-Sam-Desktop"
    add(old, "mark", None, "approved", -24 * 4 + 2, choice="1", snapshot=json.dumps(
        {"v": 1, "n": 1, "url": "/home/", "comment": "Weather chip wraps onto two lines.", "kind": "bug", "fix_note": "Chip no longer wraps below 480px.", "status_before": "fixed", "after_sha256": None}))
    add(old, "mark", None, "sent_back", -24 * 4 + 3, choice="2", comment="Still clipped on the phone width.", snapshot=json.dumps(
        {"v": 1, "n": 2, "url": "/finances/", "comment": "Amount column clipped.", "kind": "bug", "fix_note": "Widened the column.", "status_before": "fixed", "after_sha256": None}))


# ---------------------------------------------------------------- vault map

def _wiki_type(path):
    parts = path.split("/")
    if parts[0] == "wiki" and len(parts) == 3 and parts[1] in ("concepts", "decisions", "facts", "sources", "tasks", "maps"):
        return {"concepts": "concept", "decisions": "decision", "facts": "fact", "sources": "source", "tasks": "task", "maps": "map"}[parts[1]]
    return None


def _fn(path, name, top):
    ext = "." + name.rsplit(".", 1)[1] if "." in name else None
    if name in ("CLAUDE.md", "AGENTS.md") or top == ".claude":
        return "governance"
    if top in sf.FN_BY_TOP and ext in (None, ".md"):
        return sf.FN_BY_TOP[top]
    return sf.EXT_FN.get(ext, "unclassified")


def _vault_map(con, rnd, P):
    rows = []

    def walk(prefix, name_top, tree, files, parent, depth, top_fn):
        count = size = 0
        for fname, fsize, lines, purpose in files:
            path = f"{prefix}{fname}" if prefix else fname
            ext = "." + fname.rsplit(".", 1)[1] if "." in fname else None
            vpath = path
            fn = _fn(vpath, fname, vpath.split("/")[0] if not vpath.startswith("vault-code/") else vpath.split("/")[1])
            slug = path[:-3] if path.startswith("wiki/") and fname.endswith(".md") else None
            purpose = purpose or sf.EXT_LABEL.get(ext)
            rows.append(dict(path=vpath, parent_path=parent, name=fname, node_kind="file", wiki_type=_wiki_type(path), node_function=fn,
                             purpose=purpose, file_count=0, depth=depth, wiki_slug=slug, size=fsize, mtime=P.d(-rnd.randint(0, 40)),
                             lines=lines, ext=ext, generated=0))
            count += 1
            size += fsize
        for dname, (dpurpose, sub, sfiles) in tree.items():
            path = f"{prefix}{dname}"
            c, s = walk(path + "/", dname, sub, sfiles, path, depth + 1, top_fn)
            top = path.split("/")[0] if not path.startswith("vault-code/") else path.split("/")[1]
            rows.append(dict(path=path, parent_path=parent, name=dname, node_kind="folder", wiki_type=None,
                             node_function=sf.FN_BY_TOP.get(top, top_fn), purpose=dpurpose, file_count=c, depth=depth, wiki_slug=None,
                             size=s, mtime=P.d(-rnd.randint(0, 12)), lines=None, ext=None, generated=0))
            count += c
            size += s
        return count, size

    vc, vs = walk("", "", sf.VAULT_TREE, sf.VAULT_ROOT_FILES, ".", 2, "knowledge")
    cc, cs = walk("vault-code/", "", sf.CODE_TREE, sf.CODE_ROOT_FILES, "vault-code", 2, "code")
    rows.append(dict(path=".", parent_path="@", name="Sam's Vault", node_kind="folder", wiki_type=None, node_function="knowledge",
                     purpose="Sam's second-brain vault: wiki knowledge, raw inputs, SQLite data and the rules that govern them.",
                     file_count=vc, depth=1, wiki_slug=None, size=vs, mtime=P.d(0), lines=None, ext=None, generated=0))
    rows.append(dict(path="vault-code", parent_path="@", name="vault-code", node_kind="folder", wiki_type=None, node_function="code",
                     purpose="Sibling repo with the Flask app and database framework that read the vault.",
                     file_count=cc, depth=1, wiki_slug=None, size=cs, mtime=P.d(0), lines=None, ext=None, generated=0))
    rows.append(dict(path="@", parent_path=None, name="second brain", node_kind="folder", wiki_type=None, node_function="knowledge",
                     purpose="The whole system: the vault (knowledge and data) and the code repo that reads it.",
                     file_count=vc + cc, depth=0, wiki_slug=None, size=vs + cs, mtime=None, lines=None, ext=None, generated=0))
    for r in rows:
        r["generated_at"] = P.t(-1)
    cols = ["path", "parent_path", "name", "node_kind", "wiki_type", "node_function", "purpose", "file_count", "depth", "wiki_slug", "size", "mtime", "lines", "ext", "generated", "generated_at"]
    con.executemany(f"INSERT INTO map_node ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [tuple(r[c] for c in cols) for r in rows])
    for path, desc in (("wiki/concepts/budget-envelopes.md", "How Sam splits each paycheck into monthly envelopes and tops them up."),
                       ("data/tasks.db", "The planner's tasks, sections and daily briefing rows."),
                       ("vault-code/dashboard/hub/app.py", "Registers every Hub module and starts the scheduler.")):
        con.execute("INSERT INTO node_description (path, description, source, content_sig, generated_at) VALUES (?,?,?,?,?)",
                    (path, desc, "sample-sweep", "0:0", P.t(-48)))


# ---------------------------------------------------------------- automations

def _automations(con, rnd, P):
    tids = s_mail.thread_ids()
    first = {t["key"]: t["msgs"][0] for t, _ in s_mail.build()}
    subj = {t["key"]: t["subject"] for t, _ in s_mail.build()}

    def item(key, state, action, label, kind, summary, details, conf, hours, unsub=None, one=0, note=None, reason="", mi=-1):
        tid, mids = tids[key]
        name, addr = first[key][3], first[key][4]
        cur = con.execute(
            "INSERT INTO gmail_item (msg_id,thread_id,received_at,sender,domain,subject,summary,action,label,confidence,reason,unsub_url,"
            "unsub_one_click,state,run_id,cost_usd,updated_at,note,kind,judged_at,details) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mids[mi], tid, P.t(hours - 1), name, addr.split("@")[1], subj[key], summary, action, label, conf, reason, unsub, one, state,
             SAMPLE_RUN, 0.0021, P.t(hours), note, kind, P.t(hours), details))
        return cur.lastrowid

    ids = {}
    ids["promo"] = item("promo", "proposed", "DELETE", None, "promo", "Store promotion offering 40 percent off for 48 hours.",
                        "A clothing retailer is running a 48 hour sale with the code FLASH40. Nothing in it needs a reply.", "high", -2,
                        unsub="https://styledash.example/unsub?u=demo", one=1, reason="Sam has deleted this sender's promotions three times.")
    ids["electric"] = item("electric", "proposed", "MOVE", "Receipts", "bill", "October electric bill of $61.18 is ready, due November 21.",
                           "Prairie Power says the October bill is $61.18 and is due on November 21. Automatic payments can be set up online.", "medium", -3,
                           note="trash this once I have paid it", reason="Bills are filed under Receipts.", mi=0)
    ids["nl-data"] = item("nl-data", "unconfirmed", "MOVE", "Newsletters", "newsletter", "Weekly data newsletter issue 212.",
                          "Issue 212 covers forecasting with small samples, a dashboard checklist and three misleading charts.", "medium", -4,
                          reason="Sender matches a pending rule; waiting for Sam to confirm it.")
    ids["nl-cook"] = item("nl-cook", "moved", "MOVE", "Newsletters", "newsletter", "Cooking newsletter about braise season.",
                          "Five braise recipes and a shopping list.", "high", -20, reason="Confirmed rule for this sender.")
    ids["statement"] = item("statement", "moved", "MOVE", "Banking", "statement", "Credit union statement for October is ready.",
                            "The statement for the account ending 4471 is in online banking.", "high", -50, reason="Statements are filed under Banking.")
    ids["hr"] = item("hr", "done", "KEEP", None, "hr", "Benefits open enrollment closes November 15.",
                     "Elections roll over unless changed in the benefits portal before November 15.", "high", -100, reason="HR mail stays in the inbox.")
    ids["spam"] = item("spam", "moved", "DELETE", None, "spam", "Unsolicited reward claim.", "", "high", -30, reason="Looks like a scam: unknown sender, urgency.")
    ids["trash"] = item("trash", "undone", "DELETE", None, "receipt", "Old parking permit receipt.", "Permit renewal receipt.", "medium", -60,
                        reason="Old receipt; Sam moved it back and kept it.")
    ids["copper"] = item("copper", "stale", "KEEP", "Jobs", "recruiter", "Recruiter asking for an intro call.", "Copper Ridge supply planning opening.", "high", -90,
                         reason="Sam answered it in Mail before the lane did.")
    ids["transfer"] = item("transfer", "rejected", "KEEP", None, "quote", "Airport transfer quote.", "Two prices for the Lisbon airport pickup.", "medium", -70,
                           reason="Sam rejected the proposed label and kept it in the inbox.")
    ids["schedule"] = item("schedule", "failed", "MOVE", "Work", "schedule", "Weekly shift schedule from the manager.", "Thu, Fri and Sat shifts.", "high", -5,
                           reason="Gmail was busy; it will retry on the next run.")

    con.execute("INSERT INTO gmail_note (id,domain,kind,text,op,created_at,active,item_id,scope,judged_at,tries,button,rule_id) VALUES (1,?,?,?,?,?,1,?,?,?,1,NULL,4)",
                ("prairiepower.example", "bill", "trash this once I have paid it", "ack_then_trash", P.t(-3), ids["electric"], "both", P.t(-3)))

    def rule(rid, key, state, kind, source, ref, action=None, target=None, note=None, op=None, ev=None, hours=-200, decided=None):
        con.execute("INSERT INTO rule (id,lane,rule_key,state,rev,kind_of_rule,action,target,note,op,source,source_ref,evidence_json,reason,created_at,decided_at,updated_at)"
                    " VALUES (?,?,?,?,1,?,?,?,?,?,?,?,?,NULL,?,?,?)",
                    (rid, "gmail", key, state, kind, action, target, note, op, source, ref, json.dumps(ev) if ev else None,
                     P.t(hours), P.t(decided) if decided else None, P.t(decided or hours)))

    streak = lambda act, hs: [{"ts": P.t(h), "confirmed": act} for h in hs]
    rule(1, "datanotes.example|newsletter", "confirmed", "fixed_action", "streak", "datanotes.example|newsletter:3", "MOVE", "Newsletters", ev=streak("move", (-400, -300, -200)), decided=-190)
    rule(2, "styledash.example|promo", "proposed", "fixed_action", "streak", "styledash.example|promo:3", "DELETE", ev=streak("delete", (-300, -200, -100)))
    rule(3, "lakeshorecu.example|*", "confirmed", "files_without_asking", "approved_sender", "lakeshorecu.example", "MOVE", "Banking", hours=-500, decided=-500)
    rule(4, "prairiepower.example|bill", "confirmed", "instruction", "note", "note:1", note="trash this once I have paid it", op="ack_then_trash", hours=-3, decided=-3)
    rule(5, "parcelexpress.example|security", "rejected", "fixed_action", "streak", "parcelexpress.example|security:3", "DELETE", ev=streak("delete", (-600, -500, -400)), decided=-380)
    rule(6, "cooksalmanac.example|newsletter", "off", "fixed_action", "streak", "cooksalmanac.example|newsletter:3", "MOVE", "Newsletters", ev=streak("move", (-700, -650, -600)), decided=-300)

    def dec(item_key, hours, by, action, state, undo, labels, rule_id=None, reason=""):
        iid = ids[item_key]
        tid, mids = tids[item_key]
        con.execute("INSERT INTO decision (lane,ref,item_id,rule_key,made_at,made_by,action,changed_json,state,undo,reason,rule_id,rule_rev)"
                    " VALUES ('gmail',?,?,?,?,?,?,?,?,?,?,?,?)",
                    (mids[-1], iid, None, P.t(hours), by, action, json.dumps({"labels": labels}), state, undo, reason, rule_id, 1 if rule_id else None))

    dec("nl-cook", -20, "auto", "move", "applied", "reversible", [["INBOX", "UNREAD"], ["Label_5", "UNREAD"]], 1, "Matches the confirmed newsletter rule.")
    dec("statement", -50, "auto", "move", "applied", "reversible", [["INBOX"], ["Label_4"]], 3, "File-without-asking sender.")
    dec("spam", -30, "auto", "delete", "applied", "reversible", [["SPAM", "UNREAD"], ["TRASH"]], None, "Model's own call, no rule.")
    dec("trash", -60, "auto", "delete", "undone", "reversible", [["INBOX"], ["TRASH"]], None, "Undone by Sam.")
    dec("hr", -100, "sam", "keep", "applied", "none", [["INBOX"], ["INBOX"]], None, "Sam answered in the Mail page.")
    dec("schedule", -5, "auto", "move", "failed", "none", [["INBOX", "UNREAD"], ["Label_6", "UNREAD"]], None, "Gmail was busy.")

    con.execute("INSERT INTO lane_run VALUES (?,?,?,?,?,?,?)", (SAMPLE_RUN, "gmail-lane", P.t(-2), P.t(-2), "ok",
                json.dumps({"considered": 14, "moved": 3, "proposed": 3, "errors": 0}), 0.0412))
    con.execute("INSERT INTO lane_run VALUES (?,?,?,?,?,?,?)", ("demo-sample-run-2", "gmail-lane", P.t(-26), P.t(-26), "ok",
                json.dumps({"considered": 9, "moved": 2, "proposed": 1, "errors": 0}), 0.0287))

    def job(i, chain, status, h0, h1, summary, reason=None):
        return {"id": f"job-{i}", "source": "planner", "chain": chain, "status": status, "started": P.t(h0), "ended": P.t(h1),
                "summary": summary, "reason": reason, "worker_status": "done" if status.startswith("merged") else "stopped",
                "files": ["dashboard/hub/home/digest.py"] if i % 2 else ["tests/test_digest.py"], "undeclared": [], "db_writes": 0,
                "copy_verify": "ok", "live_verify": "ok" if status == "merged" else "skipped", "tests": "12 passed"}

    def burn(run, h0, h1, f0, f1, w0, w1, jobs, merged, failed):
        rep = {"sample": True, "jobs": jobs, "budget": "5h window, 3 jobs", "budget_end": "1 left"}
        con.execute("INSERT INTO burn_run (run,started_at,ended_at,status,five_allow,week_allow,five_start,five_end,week_start,week_end,merged,failed,report_json,recorded_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (run, P.t(h0), P.t(h1), "finished", 60.0, 55.0, f0, f1, w0, w1, merged, failed, json.dumps(rep), P.t(h1)))

    burn("demo-burn-1", -30, -27, 12.5, 41.0, 38.0, 42.5,
         [job(1, "A", "merged", -30, -29, "Weekly digest numbers function added with tests."), job(2, "A", "merged", -29, -28, "Digest card mounted on Home."),
          job(3, "B", "failed", -28, -27, "Shift swap board route did not pass its test.", "test_swaps failed: second take was accepted")], 2, 1)
    burn("demo-burn-2", -78, -75, 8.0, 33.5, 31.0, 36.0,
         [job(4, "A", "merged", -78, -77, "Dusk palette tokens added."), job(5, "A", "merged", -77, -76, "Theme switch points at the dusk file.")], 2, 0)


# ---------------------------------------------------------------- music

_ARTISTS = ["Low Tide Parade", "Mira Okonkwo-Lang", "Halcyon Static", "Neon Orchard", "Paper Lanterns Club", "Dusty Kerrigan",
            "The Velvet Harbor", "Juno Vasquez", "Cold Brew Collective", "Oskar Lindqvist", "Sundial Parade", "Tamsin Reed"]
_ADJ = ["Slow", "Midnight", "Paper", "Glass", "Northern", "Quiet", "Velvet", "Burnt", "Distant", "Golden", "Hollow", "Rooftop", "Salt", "Static"]
_NOUN = ["Harbor", "Garden", "Signals", "Weather", "Engines", "Summer", "Circles", "Lanterns", "Morning", "Radio", "Rivers", "Avenue", "Echo", "Orchard"]
_ALB = ["Small Hours", "Field Notes", "Second Sunrise", "Open Windows", "Bright Static", "Long Way Home", "Pocket Atlas"]
_B62 = string.digits + string.ascii_lowercase + string.ascii_uppercase


def _music(con, rnd, P):
    uris, seen = [], set()
    while len(uris) < 36:
        nm = f"{rnd.choice(_ADJ)} {rnd.choice(_NOUN)}"
        if nm in seen:
            continue
        seen.add(nm)
        uri = "spotify:track:" + "".join(rnd.choice(_B62) for _ in range(22))
        uris.append(uri)
        con.execute("INSERT INTO tracks (uri,isrc,name,album,artists,release_date,duration_ms,explicit,is_local,first_seen,updated) VALUES (?,?,?,?,?,?,?,?,0,?,?)",
                    (uri, "QZ" + "".join(rnd.choice("0123456789") for _ in range(10)), nm, rnd.choice(_ALB),
                     ";".join(rnd.sample(_ARTISTS, rnd.choice((1, 1, 2)))), f"{rnd.randint(2009, 2026)}-0{rnd.randint(1, 9)}-1{rnd.randint(0, 9)}",
                     rnd.randint(150, 330) * 1000, rnd.choice((0, 0, 0, 1)), P.d(-rnd.randint(30, 300)), P.d(-rnd.randint(0, 20))))
    lists = [("Liked Songs", "liked", None, 20), ("Morning Run", "demo0001", "playlists", 10), ("Deep Focus", "demo0002", "New Genres", 12),
             ("Sunday Kitchen", "demo0003", "playlists", 9), ("Late Shift Wind Down", "demo0004", "Old Genres", 8), ("Road Trip 2026", "demo0005", "Temp Genres", 7),
             ("Drum and Bass Warmup", "demo0006", "root", 9)]
    pids, members = [], {}
    for name, sid, grp, n in lists:
        cur = con.execute("INSERT INTO playlists (name,file_name,grp,spotify_id,status,first_seen,last_seen,updated,snapshot_id) VALUES (?,?,?,?,'active',?,?,?,?)",
                          (name, f"{name}.csv", grp, sid, P.d(-200), P.d(-3), P.d(-3), "snap" + sid[-2:]))
        pids.append(cur.lastrowid)
        pick = rnd.sample(uris, n)
        members[cur.lastrowid] = pick
        con.executemany("INSERT INTO playlist_tracks VALUES (?,?)", [(cur.lastrowid, u) for u in pick])
    r1 = con.execute("INSERT INTO refreshes (taken_at,source,summary) VALUES (?,?,?)", (P.t(-24 * 20), "export", "7 playlists, 36 songs")).lastrowid
    r2 = con.execute("INSERT INTO refreshes (taken_at,source,summary) VALUES (?,?,?)", (P.t(-3), "pull", "2 added, 2 removed")).lastrowid
    for rid, pl, kind in ((r2, pids[1], "added"), (r2, pids[1], "added"), (r2, pids[3], "removed"), (r2, pids[5], "removed"), (r1, pids[0], "added")):
        u = rnd.choice(members[pl]) if kind == "removed" else rnd.choice(uris)
        con.execute("INSERT INTO changes VALUES (?,?,?,?)", (rid, pl, u, kind))
    for i, u in enumerate(uris[:6]):
        bpm = rnd.choice((84, 92, 120, 128, 140, 170))
        con.execute("INSERT INTO readings (uri,pipeline_id,measured_at,status,main_bpm,consensus_bpm,agreement,tempo_change) VALUES (?,?,?,?,?,?,?,0)",
                    (u, "demo-v1", P.t(-48 - i), "ok", bpm, bpm, "agree"))


def seed(cons, rnd, P):
    _workbench(cons["workbench"], rnd, P)
    _vault_map(cons["vault_map"], rnd, P)
    _automations(cons["automations"], rnd, P)
    _music(cons["music"], rnd, P)


def check(cons):
    a, v = cons["automations"], cons["vault_map"]
    assert a.execute("SELECT count(DISTINCT state) FROM gmail_item").fetchone()[0] >= 6
    assert v.execute("SELECT count(*) FROM map_node WHERE parent_path IS NULL").fetchone()[0] == 1
    orphans = v.execute("SELECT count(*) FROM map_node n WHERE parent_path IS NOT NULL AND NOT EXISTS (SELECT 1 FROM map_node p WHERE p.path = n.parent_path)").fetchone()[0]
    assert orphans == 0, "every vault-map node has a parent"
    assert cons["workbench"].execute("SELECT count(*) FROM decisions WHERE verdict='sent_back' AND comment IS NULL").fetchone()[0] == 0


# ---------------------------------------------------------------- files

def files(root, rnd, P):
    out = {}
    for key, (title, off, *_r) in wb.SPECS.items():
        out[f"docs/specs/{wb.day(off)}-{key}.md"] = wb.spec_text(key).encode()
    for key, (title, off, *_r) in wb.PLANS.items():
        out[f"docs/plans/{wb.day(off)}-{key}.md"] = wb.plan_text(key).encode()
    short = {}
    for slug in wb.OPTION_SETS:
        for rel, data in wb.option_files(slug).items():
            out[f"data/workbench/options/{slug}/{rel}"] = data
    for t, *_ in list(wb.SPECS.values()) + list(wb.PLANS.values()):
        short[t] = t if len(t) <= 22 else t[:22].rsplit(" ", 1)[0]
    for _b, t, *_ in wb.OPTION_SETS.values():
        short[t] = t.replace(":", "")[:22].rsplit(" ", 1)[0]
    out["data/workbench/short-titles.json"] = (json.dumps(short, indent=1, sort_keys=True) + "\n").encode()
    for session in wb.MARKS:
        for name, data in wb.mark_session_files(session).items():
            out[f"data/marks/{session}/{name}"] = data
    out.update(sf.skill_files())
    out.update(sf.inventory_files())
    out.update(sf.artifacts_file())
    out.update(sf.viewer_files())
    for rel, data in out.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

"""
Hub-hosted headless skill scheduler.

Fires vault skills via `claude -p "/skill"` on a schedule, run from the vault
root so the vault CLAUDE.md + skills load, as non-blocking background children,
guarded by an atomic flock so a scheduled run never races a live local session.
No auto-retry: a failed run logs its outcome and exits.

The schedule is data-driven from scheduler-config.json (ships empty — the user
decides which skills run, at which times, and which machine owns the schedule).

Safety boundary (load-bearing):
  /gmail and /finance perform their external writes via Bash-run Python (the Google
  API client and the book module), NOT via Claude Code tools. So Claude Code's
  --disallowedTools cannot deny "the Gmail modify scope" or "the book write
  endpoint" — there is no such tool to deny, and denying Bash outright also
  breaks reading. The only enforceable draft-only boundary is read-only
  CREDENTIALS. Until a read-only credential profile is configured for an
  irreversible skill, this scheduler REFUSES to launch it (code-enforced, not a
  prompt instruction). Read-only skills (e.g. a briefing build that only writes
  reversible vault files) run to completion unattended.

Cross-machine overlap (PC Hub firing while a live Mac session exists) is not
solvable by a vault lock — the machines sync manually and rarely, and the race
is on the shared auth token, not vault state. It is handled by single-writer
discipline: only the machine named in config `active_machine` runs the schedule.
"""

import fcntl
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

import demo_views
import window_chain
from finances import shift_calendar
from vault_path import vault_root

logger = logging.getLogger(__name__)

HUB_DIR = Path(__file__).resolve().parent
CODE_DIR = HUB_DIR.parents[1]  # the vault-code repo root
CONFIG_PATH = HUB_DIR / "scheduler-config.json"

VAULT = Path(vault_root())
LOCK_PATH = VAULT / ".pending" / "scheduler.lock"
RUN_LOG = VAULT / "log" / "scheduler-runs.jsonl"

# Absolute path to the claude binary. The systemd unit's minimal PATH may not
# include ~/.local/bin, so resolve it explicitly rather than relying on PATH.
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", str(Path.home() / ".local" / "bin" / "claude"))

# Skills whose only side effects are reversible vault-file writes are safe to run
# to completion unattended. Irreversible skills take external actions (a Gmail
# modify, a book write) and are gated — see _enforce_boundary.
#
# Note the asymmetry: /gmail CAN be made credential-read-only (a gmail.readonly
# token; services.gmail() returns it under VAULT_HEADLESS_READONLY=1, so writes
# 403). /finance CANNOT — it writes book.db directly, so there is no read-only
# credential to hand it. Until a read-only profile exists, /finance has no
# satisfiable readonly_cred_profile and stays blocked.
IRREVERSIBLE_SKILLS = {"/gmail", "/finance"}

POLL_SECONDS = 30  # check twice a minute so an HH:MM slot is never missed


def _now():
    # Wall-clock read isolated here so tests can monkeypatch it.
    return datetime.now()


def load_config():
    """Read scheduler-config.json. Missing file -> an empty, inert schedule."""
    if not CONFIG_PATH.exists():
        return {"active_machine": None, "jobs": []}
    with open(CONFIG_PATH) as fh:
        cfg = json.load(fh)
    cfg.setdefault("active_machine", None)
    cfg.setdefault("jobs", [])
    return cfg


def is_active_machine(cfg):
    """Single-writer discipline: only the named machine runs the schedule.

    A null active_machine means "no machine owns the schedule yet" -> nothing
    fires anywhere (safe default), so an un-configured Hub never races.
    """
    active = cfg.get("active_machine")
    if not active:
        return False
    return active == socket.gethostname()


def _enforce_boundary(job):
    """Return (allowed: bool, reason: str) for an irreversible skill.

    The draft-only guarantee is a credential boundary, not a flag. An
    irreversible skill may run only if the job declares a read-only credential
    profile that actually exists on disk. Absent that, refuse — this is the
    code-level enforcement of "no irreversible action unattended."
    """
    skill = job.get("skill")
    if skill not in IRREVERSIBLE_SKILLS:
        return True, "read-only skill"
    profile = job.get("readonly_cred_profile")
    if not profile:
        return False, (
            f"{skill} is irreversible and no readonly_cred_profile is configured; "
            "refusing to run it unattended (would risk an external write with no "
            "human in the loop)"
        )
    if not Path(profile).exists():
        return False, f"{skill} readonly_cred_profile {profile!r} does not exist on disk"
    return True, f"{skill} gated to read-only credentials at {profile}"


def _write_run_record(record):
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RUN_LOG, "a") as fh:
        fh.write(json.dumps(record) + "\n")


def _gmail_drafts_dir():
    # Computed from the module global VAULT at call time so tests that reassign
    # scheduler.VAULT are honored (same pattern as LOCK_PATH/RUN_LOG).
    return VAULT / "log" / "gmail-drafts"


def _backfill_gmail_draft_if_missing(started):
    """Guarantee a successful draft-only /gmail run ALWAYS leaves a surfaceable
    artifact, so Sam is always notified the run happened.

    The SessionStart hook (vault-gmail-draft-surface.py) nudges Sam only when
    a *.json draft sits in log/gmail-drafts/. A headless run is *supposed* to
    write that draft — but that depended on the model taking the draft-only
    branch. If it instead ran the interactive flow and stopped at the unmanned
    confirm gate (which is exactly what happened 2026-06-29), no draft was written
    and the run was silent. A notification guarantee must not hinge on LLM
    compliance. So: if this run produced no fresh draft, the scheduler writes a
    fallback stub itself — deterministic Python, runs regardless of what the model
    did. The interactive review flow recognizes the fallback schema and runs a
    fresh triage rather than trying to act on empty decisions.

    Returns the stub Path if one was written, else None.
    """
    ddir = _gmail_drafts_dir()
    ddir.mkdir(parents=True, exist_ok=True)
    cutoff = started.timestamp() - 2  # small clock-skew epsilon
    produced = any(
        p.stat().st_mtime >= cutoff for p in ddir.glob("*.json")
    )
    if produced:
        return None
    stamp = started.strftime("%Y-%m-%dT%H-%M-%S")
    stub = ddir / f"{stamp}.json"
    if stub.exists():  # same-second collision guard
        stub = ddir / f"{stamp}-fallback.json"
    stub.write_text(json.dumps({
        "schema": "gmail-draft-fallback",
        "generated_by": "scheduler-backfill",
        "run_started": started.isoformat(),
        "note": (
            "Headless /gmail run completed but emitted no structured draft (it did "
            "not take the draft-only branch). The inbox was NOT pre-classified into "
            "this file. Running /gmail will surface this, archive the empty stub, "
            "and run a fresh interactive triage."
        ),
        "decisions": [],
    }, indent=2))
    return stub


def _already_ran(skill_or_job, scheduled_time, day, *, _record_key="skill"):
    """Dedupe across service restarts: was this skill/job+slot already logged today?

    _record_key selects which JSON field in the run log to match against
    skill_or_job. Defaults to "skill" so existing callers are unchanged.
    Python jobs pass _record_key="job" because their records carry "job":
    "<name>" rather than a "skill" field.
    """
    if not RUN_LOG.exists():
        return False
    with open(RUN_LOG) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                r.get(_record_key) == skill_or_job
                and r.get("scheduled_time") == scheduled_time
                and (r.get("date") or "").startswith(day)
            ):
                return True
    return False


def _locked_run(name, job, work, lock_path=None):
    """Run an LLM-free Python job under the same flock as run_skill, and log it.

    `work` returns the job-specific fields to merge into the run record. It is
    never handed the lock, and it must never shell out to `claude` — the whole
    point of these jobs is removing the LLM from the unattended path.
    `lock_path` gives a job its own lock, so book-sync or /job-sweep holding
    the shared one never skips it (the API lanes).
    """
    started = _now()
    lock_path = Path(lock_path or LOCK_PATH)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        base = {"job": name, "scheduled_time": job.get("time", ""), "date": started.isoformat()}
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            rec = {
                **base,
                "status": "skipped",
                "mode": "locked",
                "outcome": "another run or live session holds the lock",
            }
            _write_run_record(rec)
            return rec
        try:
            rec = {**base, **work()}
        except Exception as exc:
            # A failing job must still leave a record; no auto-retry, same as run_skill.
            logger.exception("scheduled job %s failed", name)
            rec = {**base, "status": "failed", "outcome": f"{type(exc).__name__}: {exc}"}
        _write_run_record(rec)
        return rec
    finally:
        os.close(lock_fd)


def run_shift_sync_job(job):
    """Resync scheduled work shifts from Google Calendar, then double-check them.

    Reads the calendar (read-only) and replaces the future rows of
    earnings_scheduled_shifts, which is what the earnings forecast prices
    against. The only write is to a local SQLite table this pipeline owns, so
    there is no irreversible external action.

    The sync itself stays LLM-free: pattern matching decides every row that gets
    written. The `audit` call after it is a separate read-only claude subprocess
    that writes nothing but its own report file, and its result is deliberately
    ignored here beyond being logged -- it exists because the matcher can go
    blind silently, as it did for ten days in Aug 2026. Its exceptions are
    swallowed inside `audit`, so a check that fails cannot take the sync down.
    """
    def work():
        mirror = shift_calendar.mirror_spoton()  # SpotOn calendar -> Personal, first
        events = shift_calendar.list_events()
        shifts = shift_calendar.fetch_shifts(events=events)
        shift_calendar.replace_scheduled(shifts)
        a = shift_calendar.audit(events, shifts)
        return {"status": "ok", "shifts": len(shifts), "mirror": mirror,
                "missed": len(a.get("missed") or []), "audit_error": a.get("error")}

    return _locked_run("shift-sync", job, work)


def run_owed_payments_job(job):
    """Read Venmo and Zelle notification emails into the owed tab.

    Read-only against Gmail (no label change, no send) and the only write is to
    data/owed.db, which this pipeline owns. No claude subprocess: the parsers are
    deterministic and a debt is auto-settled only when the payment note carries
    the request tag and the amount matches to the cent, so the unattended path
    can never guess a settlement.
    """
    def work():
        from finances import payments_scan
        out = payments_scan.scan(days=60)
        return {"status": "ok", **out}

    return _locked_run("owed-payments", job, work)


def run_book_sync_job(job):
    """Pull new bank transactions from SimpleFIN into data/book.db.

    The config is static JSON, so the credential check lives here: with no
    SIMPLEFIN_ACCESS_URL in dashboard/.env the run is a logged skip, not a
    failure. The only write is to book.db; the access URL never reaches the log.
    After the sync, finances.autocat asks Haiku 5.5 (Anthropic API) to categorize
    new rows and approves the sure ones; it can take a minute or two and never
    fails the sync (its result or error lands in the record's `autocat`). Then
    finances.memo_lane fills blank memos from matching Gmail receipts (record's `memo`).
    """
    def work():
        from finances import autocat, memo_lane, simplefin
        if not simplefin.access_url_or_none():
            return {"status": "skipped", "outcome": f"{simplefin.ENV_KEY} is not set in dashboard/.env"}
        try:
            out = simplefin.sync()
        except simplefin.Busy as e:
            return {"status": "skipped", "outcome": str(e)}
        try:
            ac = autocat.run()
        except Exception as e:
            logger.exception("autocat failed")
            ac = {"status": "error", "reason": str(e)}
        try:
            memo = memo_lane.run()
        except Exception as e:
            logger.exception("memo lane failed")
            memo = {"status": "error", "reason": str(e)}
        # error = the pull itself failed (nothing fetched); partial = a bank-side warning
        status = "error" if out.get("status") == "error" else "partial" if out["errors"] else "ok"
        rec = {"status": status, "added": out["added"],
               "updated": out["updated"], "superseded": out["superseded"],
               "errors": len(out["errors"]), "autocat": ac, "memo": memo}
        if out["errors"]:  # the Automations page shows outcome as the run's reason
            rec["outcome"] = "; ".join(out["errors"])
        return rec

    return _locked_run("book-sync", job, work)


def run_orders_scan_job(job):
    """Fold order and shipping email into the `orders` table, unattended.

    Same read-only shape as owed-payments: Gmail is only searched and read (no
    label, no move, no send) and the only write is to data/purchases.db, which
    this pipeline owns. No claude subprocess -- orders_mail's parsers are
    deterministic regexes, and its merge only ever fills a BLANK field, so an
    unattended run can never overwrite a tracking number Sam typed himself.

    This is what makes tracking numbers arrive on their own. The scan already
    existed behind the "scan email" button, which meant a parcel's tracking
    number only appeared if he happened to press it after the shipping email
    landed -- and a shipping email arrives while you are not looking at the tab.
    """
    def work():
        from purchases import db as purchases_db
        from purchases import orders_mail

        report = orders_mail.scan(purchases_db, days=int(job.get("days", 45)))
        if report.get("error"):
            return {"status": "failed", "outcome": report["error"]}
        created, updated = report.get("created", []), report.get("updated", [])
        blank = sum(1 for c in created if c.get("needs_tracking"))
        return {"status": "ok", "scanned": report.get("scanned", 0),
                "created": len(created), "updated": len(updated),
                "outcome": f"{len(created)} new, {len(updated)} updated"
                           + (f", {blank} still without a tracking number" if blank else "")}

    return _locked_run("orders-scan", job, work)


FORGE_DIR = HUB_DIR / "forge"
DDRAGON_VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"

# The bakes to re-run when a patch lands, in dependency order. The item catalog
# is deliberately not here: its builder lives outside this repo, and the shop
# only moves when Riot adds or removes an item. The job reports catalog drift
# rather than silently leaving it unsaid.
# Order is a dependency chain, not a preference: bake_catalog.py writes the item
# shop bake_passives.py resolves against and build_diff.py filters by, and
# build_runes.py writes the keystone->tree map bake_stats.py reads.
# Each entry is a script or a script plus its args. The Draft bakes come after
# the catalog, which they read. The matchup bake is ~1,200 page loads, so it gets
# MATCHUP_TIMEOUT; cut off, it resumes from its work file on the next milestone
# that runs the bakes (the milestone is spent once any bake succeeds), and drops
# that work file if the patch moved on in between.
FORGE_BAKES = ("bake_catalog.py", "build_runes.py", "bake_patchnotes.py",
               "build_diff.py", "bake_passives.py", "bake_stats.py",
               "bake_lolalytics.py", "bake_mino.py",
               ("bake_traits.py", "--items"),
               ("bake_lolalytics.py", "--matchups"),
               # teammate rows go into the store --matchups just rewrote; ~265 pages
               ("bake_lolalytics.py", "--synergy"),
               ("bake_lolalytics.py", "--archetypes"),
               ("bake_lolalytics.py", "--archetypes", "--mode", "aram"),
               ("bake_stats.py", "--roster"), "bake_identity.py",
               ("bake_traits.py", "--archetypes"),
               # champion pages read the published archetypes and calculator; ~25 min
               "bake_champions.py")
MATCHUP_TIMEOUT = 4 * 3600
LONG_BAKE_FLAGS = {"--matchups", "--synergy", "--archetypes", "--roster"}


def _live_ddragon():
    """Riot's newest Data Dragon version, e.g. "16.17.1"."""
    req = urllib.request.Request(DDRAGON_VERSIONS, headers={"User-Agent": "vault-hub"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())[0]


# A patch lands, and then it settles. The first day's win rates are a few thousand
# games of people first-timing the changes; a week in they are the numbers you
# would actually build against. So each patch gets three bakes, not one, and the
# cycle repeats on Riot's own two-week cadence because it is anchored to the drop.
FORGE_MILESTONES = (("drop", 0), ("day1", 1), ("week1", 7))


def _forge_state_path():
    return VAULT / "data" / "forge-rebake-state.json"


def _forge_due(state, live, today):
    """Which milestones this run owes, and the state to write after they run.

    A new patch resets the cycle and owes `drop` immediately. Otherwise a
    milestone is owed once its offset from the drop date has elapsed and it has
    not already run -- so a Hub that was off for a week still fires day1 and
    week1 on its next tick rather than skipping them, which is the whole reason
    the milestones are recorded by name instead of by a timer.
    """
    if state.get("patch") != live:
        return ["drop"], {"patch": live, "landed": today.isoformat(), "done": []}
    landed = datetime.fromisoformat(state["landed"]).date()
    done = list(state.get("done") or [])
    due = [name for name, offset in FORGE_MILESTONES
           if name not in done and (today - landed).days >= offset]
    return due, dict(state)


def run_forge_rebake_job(job):
    """Re-bake the Item Set Forge's numbers on the patch cycle, three times a patch.

    Rebaking on page open was the other candidate and it is worse twice over:
    `bake_lolalytics.py` drives a headless Chrome for ~5 minutes, so the Forge
    would block on it every visit, and it would re-scrape to re-derive numbers
    that cannot have changed since the last visit. The staleness that matters is
    patch-shaped, so the trigger is patch-shaped.

    The cadence is anchored to the patch Riot actually shipped, not to a fixed
    fortnightly timer. Patches slip, and a timer that started aligned drifts into
    baking halfway through a patch and then missing the next drop by days. The
    check is one version fetch and costs nothing on a day when nothing moved.

    The baked patch is read off forge-patch-notes.json rather than the catalog,
    because that file is written by a script in this list -- keying the check on
    something the job cannot advance would make it fire forever.
    """
    def work():
        live = _live_ddragon()
        today = _now().date()
        path = _forge_state_path()
        state = json.loads(path.read_text("utf-8")) if path.exists() else {}
        # A first run against an already-current vault must not re-bake: seed the
        # cycle from what is on disk instead of treating it as a fresh drop.
        if not state:
            notes = json.loads((VAULT / "data" / "forge-patch-notes.json").read_text("utf-8"))
            if notes.get("ddragon") == live:
                state = {"patch": live, "landed": today.isoformat(), "done": ["drop"]}
        due, state = _forge_due(state, live, today)
        catalog = json.loads(
            (FORGE_DIR / "frontend" / "static" / "catalog.json").read_text("utf-8")).get("ver")
        if not due:
            return {"status": "ok", "outcome": f"nothing due on {live}", "patch": live,
                    "milestones": [], "baked": [], "catalog_stale": catalog != live}
        ran, failed = [], []
        for entry in FORGE_BAKES:
            script, *args = (entry,) if isinstance(entry, str) else entry
            name = " ".join([script, *args])
            try:
                done = subprocess.run(
                    [sys.executable, str(FORGE_DIR / script), *args], cwd=str(HUB_DIR),
                    capture_output=True, text=True,
                    # the plain lolalytics bake covers every champion-role since
                    # 2026-11-04: 292 roles measured 3032 s, too near the 3600 s default
                    timeout=MATCHUP_TIMEOUT if LONG_BAKE_FLAGS & set(args)
                    or script == "bake_lolalytics.py" else 3600)
                ok = done.returncode == 0
            except subprocess.TimeoutExpired:
                ok = False
            # One bake failing must not cost the others: they read different
            # sources and a 403 on one says nothing about the next.
            (ran if ok else failed).append(name)
        # A milestone is only spent if something actually baked, so a run that
        # failed outright retries on the next tick instead of being marked done.
        if ran:
            state["done"] = sorted(set((state.get("done") or []) + due))
            path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        return {
            "status": "ok" if not failed else "failed",
            "outcome": f"{'+'.join(due)} on {live}"
                       + (f"; failed: {', '.join(failed)}" if failed else ""),
            "patch": live, "milestones": due, "baked": ran,
            # Now that bake_catalog.py is in the list this can only mean its bake
            # failed, which is worth saying out loud rather than inferring.
            "catalog_stale": catalog != live,
        }

    return _locked_run("forge-rebake", job, work)


def run_vault_map_refresh_job(job):
    """Rewalk the vault and vault-code into the Vault Map cache.

    Nothing else rebuilds that cache (the page only reads it), so without this
    the map froze at whenever someone last POSTed /vault-map/api/refresh.
    """
    def work():
        from vault_map import api as vault_map_api

        count = vault_map_api.rebuild()
        return {"status": "ok", "nodes": count, "outcome": f"{count} nodes"}

    return _locked_run("vault-map-refresh", job, work)


RELOGIN_TASK = "Log in to Spotify again for the music pull"


def run_music_pull_job(job):
    """Read Sam's Spotify playlists into data/music.db and log what changed.

    Read-only against Spotify; the only write is to data/music.db, which this
    pipeline owns. A night with any failed read writes nothing. A lapsed login
    parks one planner item to log in again, never a second while one is open.
    """
    def work():
        from music import library, spotify
        try:
            return {"status": "ok", **library.pull()}
        except spotify.AuthError:
            import tasks
            if not any(t.get("name") == RELOGIN_TASK.lower() for t in tasks.list_active()):
                tasks.add(RELOGIN_TASK, section="loose ends",
                          description="Run: cd vault-code/dashboard/hub && python3 -m music.library login")
            raise

    return _locked_run("music-pull", job, work)


def _lane_record(res):
    """A lane's result dict as run-record fields: status from its outcome, cost_usd kept."""
    status = {"failed": "failed", "citation_failed": "failed", "skipped": "skipped"}.get(res.get("outcome"), "ok")
    return {"status": status, **res}


def run_gmail_lane_job(job):
    """Hourly Haiku sort of new inbox mail (automations/gmail_lane.py), on its own lock."""
    def work():
        from automations import gmail_lane
        return _lane_record(gmail_lane.run(auto_move=bool(job.get("auto_move"))))

    return _locked_run("gmail-lane", job, work, VAULT / ".pending" / "gmail-lane.lock")


def run_voice_memo_job(job):
    """Acts on new voice memos with one Sonnet call each (automations/voice_memo_lane.py), on its own lock."""
    def work():
        from automations import voice_memo_lane
        return _lane_record(voice_memo_lane.run())

    return _locked_run("voice-memo", job, work, VAULT / ".pending" / "voice-memo.lock")


def _news_digest_due(now):
    """news.digest_api.due() against today's run records and today's digests row."""
    from news import db as news_db, digest_api
    today = now.date().isoformat()
    runs = [r for r in recent_runs(500) if str(r.get("date", "")).startswith(today)]
    return digest_api.due(now, runs, news_db.get_digest(today) is not None)


def run_news_digest_job(job):
    """The 06:00 digest as one Sonnet call (news/digest_api.py), on its own lock."""
    def work():
        from news import digest_api
        return _lane_record(digest_api.run())

    return _locked_run("news-digest", job, work, VAULT / ".pending" / "news-digest.lock")


SORT_TASK = "Sort the files the file sorter could not place"


def run_file_sort_job(job):
    """Restart iCloud (its sync stalls silently), then move new loose files from
    Downloads, Desktop and the capture folders into Demo Files.

    Rules only (automations/file_sort.py); a file no rule places stays put, and one
    planner item points at /file-sort to read and ask about them, never a second
    while one is open.
    """
    def work():
        from automations import file_sort
        from finances import icloud_ingest
        try:
            icloud_ok = icloud_ingest.restart_sync()
        except Exception:
            logger.exception("iCloud restart failed")
            icloud_ok = False
        res = file_sort.run()
        res["icloud_restarted"] = icloud_ok
        if res["unsure"]:
            import tasks
            if not any(t.get("name") == SORT_TASK.lower() for t in tasks.list_active()):
                tasks.add(SORT_TASK, section="loose ends",
                          description="Run /file-sort: Claude reads each one and asks where it goes")
        return res

    return _locked_run("file-sort", job, work, VAULT / ".pending" / "file-sort.lock")


TIDY_IDLE_DAYS = 3
_ANCHOR_RE = re.compile(r"(pending|handoff):\s*([^\s,]+\.md)", re.I)


def _process_folder_held(marker_text, active_keys):
    """True when a marker anchors to work still open: a live .pending/ or
    .handoff/ file, or a planner task key that is not done. Same anchor forms
    the Stop hook vault-downloads-autoclean.py reads."""
    import reconcile_gather as rg
    for kind, name in _ANCHOR_RE.findall(marker_text):
        if (VAULT / f".{kind.lower()}" / name).is_file():
            return True
    return any(k in active_keys for k in rg._HOLD_KEY_RE.findall(marker_text))


def run_downloads_tidy_job(job):
    """Move Claude process folders idle 3+ days from Downloads root into Claude Mockups.

    The CLAUDE-file-delivery.md stage -> move step, which had no runner. Moves
    only (the 14-day delete stays with /reconcile and the autoclean hook), never
    onto an existing folder, and skips any folder whose marker anchors to open work.
    """
    def work():
        import shutil
        import reconcile_gather as rg
        root = rg._downloads_root()
        dest_root = root / rg._DOWNLOADS_CONSOLIDATED
        cutoff = _now().timestamp() - TIDY_IDLE_DAYS * 86400
        active = rg._active_task_keys()
        moved, held, collided = [], [], []
        for entry in sorted(root.iterdir()):
            marker = entry / rg._DOWNLOADS_MARKER
            if not entry.is_dir() or entry.name == rg._DOWNLOADS_CONSOLIDATED or not marker.exists():
                continue
            if rg._newest_mtime(entry) >= cutoff:
                continue
            if _process_folder_held(marker.read_text("utf-8", errors="replace"), active):
                held.append(entry.name)
                continue
            dest = dest_root / entry.name
            if dest.exists():
                collided.append(entry.name)
                continue
            dest_root.mkdir(exist_ok=True)
            shutil.move(str(entry), str(dest))
            moved.append(entry.name)
        return {"status": "ok", "moved": moved, "held": held, "collided": collided,
                "outcome": f"{len(moved)} moved, {len(held)} held by open work"
                           + (f", {len(collided)} already in Claude Mockups" if collided else "")}

    return _locked_run("downloads-tidy", job, work, VAULT / ".pending" / "downloads-tidy.lock")


def _branch_task(repo, branch):
    return f"Merge or drop the stranded branch {branch} in {repo}"


def run_branch_check_job(job):
    """Park one planner item per local branch holding work that never reached main.

    Read-only against git (reconcile_gather._unmerged_branches); the only write is
    the planner item, never a second for a branch an open item already names.
    """
    def work():
        import reconcile_gather as rg
        import tasks
        open_names = {t.get("name") for t in tasks.list_active()}
        found = rg._unmerged_branches()
        parked = []
        for repo, branch in found:
            title = _branch_task(repo, branch)
            if title.lower() in open_names:
                continue
            tasks.add(title, section="loose ends",
                      description=f"`git -C <{repo}> log main..{branch}` shows what never landed; /reconcile walks it")
            parked.append(f"{repo}:{branch}")
        return {"status": "ok", "branches": len(found), "parked": parked,
                "outcome": f"{len(found)} unmerged, {len(parked)} new planner items"}

    return _locked_run("branch-check", job, work)


def _demo_refresh_job(cmd, job):
    """tools/demo_export/refresh.py prepare|publish; its own lock, since prepare runs minutes."""
    script = Path(__file__).resolve().parents[2] / "tools" / "demo_export" / "refresh.py"

    def work():
        r = subprocess.run([sys.executable, str(script), cmd], capture_output=True, text=True, timeout=1800)
        try:
            return json.loads(r.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            return {"status": "failed", "outcome": (r.stderr or r.stdout).strip()[-300:]}

    return _locked_run(job.get("job", f"demo-{cmd}"), job, work, lock_path=LOCK_PATH.parent / "demo-refresh.lock")


# Job name in scheduler-config.json -> the Python function that runs it. These are
# the jobs whose decisions are all Python; everything else goes through run_skill.
# shift-sync shells out to claude once for its report-only audit, but nothing that
# subprocess says can change a row it writes.
PYTHON_JOBS = {
    "shift-sync": run_shift_sync_job,
    "forge-rebake": run_forge_rebake_job,
    "owed-payments": run_owed_payments_job,
    "book-sync": run_book_sync_job,
    "orders-scan": run_orders_scan_job,
    "vault-map-refresh": run_vault_map_refresh_job,
    "music-pull": run_music_pull_job,
    "gmail-lane": run_gmail_lane_job,
    "voice-memo": run_voice_memo_job,
    "news-digest": run_news_digest_job,
    "file-sort": run_file_sort_job,
    "downloads-tidy": run_downloads_tidy_job,
    "branch-check": run_branch_check_job,
    "demo-views": lambda job: _locked_run("demo-views", job, lambda: {"status": "ok", **demo_views.check()}),
    "demo-refresh": lambda job: _demo_refresh_job("prepare", job),
    "demo-publish": lambda job: _demo_refresh_job("publish", job),
}

# Extra due checks on top of the clock slot. A "*:MM" time fires every hour at
# MM; the check then decides (the digest's catch-up window lives in digest_api).
DUE_CHECKS = {"news-digest": _news_digest_due}


def _build_env():
    """Explicit, known-good environment for the headless child.

    Inherits the current env but guarantees HOME and a PATH that includes the
    claude binary's directory, since transitive tools (node, etc.) may not be on
    the systemd service's minimal PATH.
    """
    env = dict(os.environ)
    env.setdefault("HOME", str(Path.home()))
    claude_dir = str(Path(CLAUDE_BIN).parent)
    path = env.get("PATH", "")
    if claude_dir not in path.split(":"):
        env["PATH"] = f"{claude_dir}:{path}" if path else claude_dir
    return env


def _skill_prompt(skill):
    """A skill's instructions (SKILL.md minus frontmatter), for a run that
    cannot resolve /skill-name because project settings are not loaded. Words
    after the name ("/trip-intake 7") ride along as the run's arguments."""
    name, _, args = skill.partition(" ")
    text = (VAULT / ".claude" / "skills" / name.lstrip("/") / "SKILL.md").read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    text = text.replace("<code>", str(CODE_DIR)).strip()
    return f"{text}\n\nArguments: {args}" if args else text


def run_skill(job):
    """Acquire the lock, launch the skill headless, log the outcome, release.

    Blocking by design when called directly (used in tests). The scheduler loop
    calls this inside a worker thread so the poll loop is never blocked.
    """
    skill = job["skill"]
    scheduled_time = job.get("time", "")
    started = _now()

    allowed, reason = _enforce_boundary(job)
    if not allowed:
        rec = {
            "skill": skill,
            "scheduled_time": scheduled_time,
            "date": started.isoformat(),
            "status": "refused",
            "exit_code": None,
            "mode": "blocked",
            "outcome": reason,
        }
        _write_run_record(rec)
        return rec

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Another run/session holds the lock. Atomic acquire, not a pgrep
            # check, so there is no check-then-act (TOCTOU) window.
            rec = {
                "skill": skill,
                "scheduled_time": scheduled_time,
                "date": started.isoformat(),
                "status": "skipped",
                "exit_code": None,
                "mode": "locked",
                "outcome": "another run or live session holds the lock",
            }
            _write_run_record(rec)
            return rec

        mode = "draft-only" if skill in IRREVERSIBLE_SKILLS else "full"
        env = _build_env()
        if skill in IRREVERSIBLE_SKILLS:
            # Credential-layer draft-only: services.gmail() returns the read-only
            # service when this is set, so write API calls 403. Paired with the
            # _enforce_boundary check that a readonly_cred_profile exists.
            env["VAULT_HEADLESS_READONLY"] = "1"
        cmd = [CLAUDE_BIN, "-p", skill]
        allowed_tools = job.get("allowed_tools")
        if allowed_tools:
            # A per-job tool allow-list only means something if the session's
            # permission mode actually consults it. bypassPermissions (the
            # mode .claude/settings.json turns on for this vault) skips every
            # permission check, allow-list included, so untrusted content the
            # skill reads (a feed title, here) could reach Bash and
            # credentials regardless of --allowedTools. "dontAsk" is the mode
            # that still applies allow/deny rules while auto-denying anything
            # that would otherwise prompt (there's nobody headless to answer
            # it) -- so it's what makes --allowedTools an actual restriction
            # here rather than a no-op under bypass.
            #
            # --allowedTools only ADDS to the allow rules the settings files
            # already carry, and the vault's project settings allow
            # Bash(python3 *), Bash(curl *) and more, so a 2026-09-25 run still
            # ran `python3 -c`. Loading only user settings (no allow list)
            # makes the CLI list the whole list. Project skills load with the
            # project settings, so the skill's own text goes in as the prompt.
            # Rules name the exact script ({code} = this repo's root): a
            # leading `*` would also match `python3 -c '...' /news/cli.py`.
            cmd = [CLAUDE_BIN, "-p", _skill_prompt(skill), "--setting-sources", "user",
                   "--permission-mode", "dontAsk", "--allowedTools",
                   ",".join(t.replace("{code}", str(CODE_DIR)) for t in allowed_tools)]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(VAULT),
                env=env,
                stdin=subprocess.DEVNULL,  # never inherit a TTY; matches headless rule
                capture_output=True,
                text=True,
                timeout=job.get("timeout_seconds", 1800),
            )
            exit_code = proc.returncode
            status = "ok" if exit_code == 0 else "failed"
            outcome = (proc.stdout or "").strip()[-500:] or (proc.stderr or "").strip()[-500:]
        except subprocess.TimeoutExpired:
            exit_code = None
            status = "failed"
            outcome = "timed out"
        except Exception as exc:  # launch failure (binary missing, env, etc.)
            exit_code = None
            status = "failed"
            outcome = f"launch error: {exc}"

        ended = _now()
        rec = {
            "skill": skill,
            "scheduled_time": scheduled_time,
            "date": started.isoformat(),
            "ended": ended.isoformat(),
            "status": status,  # ok | failed (no auto-retry on failed)
            "exit_code": exit_code,
            "mode": mode,
            "outcome": outcome,
        }
        _write_run_record(rec)
        # Notification guarantee: a successful draft-only /gmail run must always
        # leave a surfaceable draft, even if the model never wrote one. Never let
        # a backfill failure mask the run record.
        if skill == "/gmail" and status == "ok":
            try:
                _backfill_gmail_draft_if_missing(started)
            except Exception:
                logger.exception("gmail draft backfill failed for run started %s", started)
        return rec
    finally:
        # Releasing the fd releases the flock; do it only after the child exits.
        os.close(lock_fd)


def _run_window_chain(job):
    """Trigger-based job: keep the Claude usage window chained.

    Unlike every other job here this one is not tied to a clock time — the
    five-hour boundary moves about an hour earlier each day — so it is evaluated
    on every tick and decides for itself. Ticks that do not fire return None and
    are deliberately not logged; recording 2,880 no-ops a day would bury the
    firings that matter.

    It shells out to claude, so it is not a PYTHON_JOB (that category is
    LLM-free by contract). It takes the same flock inside window_chain.tick, so
    it still cannot race a live session or another scheduled run.
    """
    try:
        rec = window_chain.tick(job, CLAUDE_BIN, LOCK_PATH, env=_build_env())
    except Exception as exc:
        logger.exception("window-chain tick failed")
        rec = {
            "job": "window-chain",
            "scheduled_time": "",
            "date": _now().isoformat(),
            "status": "failed",
            "outcome": f"{type(exc).__name__}: {exc}",
        }
    if rec:
        _write_run_record(rec)
    return rec


def _run_news_poll(job):
    """Trigger-based job: the news poll's own cadence check (poll_state._run
    vs job["interval_minutes"]) and cross-tick lock live in news/poll.py
    itself, same shape as window-chain's flock. This wrapper's only job is
    importing news.poll lazily, so a bug or a missing dependency in that
    module (feedparser, trafilatura) can never take the scheduler process
    down with it -- caught here rather than left to crash `_tick`.
    """
    try:
        from news import poll as news_poll
    except Exception:
        logger.exception("news-poll import failed")
        return
    try:
        news_poll.run(job)
    except Exception:
        logger.exception("news-poll run failed")


def _run_mail_sync(job):
    """Trigger-based job: cadence (account.synced_at) and the overlap lock live
    in mail/gmail_sync.py; lazy import and catch-all keep the scheduler alive."""
    try:
        from mail import gmail_sync
        gmail_sync.run(min_age_minutes=job.get("interval_minutes", 5))
    except Exception:
        logger.exception("mail-sync run failed")
    try:  # list titles after the sync, outside its lock; a failure leaves the full subjects showing
        from mail import claude_actions, db as mail_db
        conn = mail_db.connect()
        try:
            claude_actions.short_titles(conn)
            claude_actions.list_previews(conn)
        finally:
            conn.close()
    except Exception:
        logger.exception("mail short titles failed")


def _run_sitesearch_alerts(job):
    """Trigger-based job: cadence, quiet hours and the overlap lock live in
    sitesearch/alerts.py. Lazy import and catch-all so a headless-browser or
    network failure can never take the scheduler process down."""
    try:
        from sitesearch import alerts
        alerts.run(job)
    except Exception:
        logger.exception("sitesearch-alerts run failed")


# Jobs that fire on their own cadence rather than a clock slot: evaluated on
# every tick, deciding for themselves whether they're due, so they carry no
# "time" in config. Kept separate from PYTHON_JOBS because a python job's
# cadence IS the clock slot it's configured with -- window-chain is also an
# LLM job (it shells out to claude) while news-poll is LLM-free, so "not
# LLM-free" is no longer what distinguishes this category. A registry rather
# than a name test in _tick so the config/runner pairing stays checkable from
# one place.
TRIGGER_JOBS = {"window-chain": _run_window_chain, "news-poll": _run_news_poll,
                "sitesearch-alerts": _run_sitesearch_alerts, "mail-sync": _run_mail_sync}


def _dispatch_job(job: dict, hhmm: str, day: str) -> tuple[str, dict] | None:
    """One job's dispatch for this tick. A due python or skill job is returned
    as (name, job) so the caller can chain it with any siblings sharing the
    slot; a trigger job fires its own thread here and returns None."""
    if not job.get("enabled"):
        return None
    # Trigger-based jobs fire on a moving boundary rather than a clock
    # slot, so they are evaluated every tick and must be branched before
    # the HH:MM match below. Threaded so a slow or hung ping can never
    # stall the poll loop past an HH:MM slot; the flock inside makes
    # overlapping ticks harmless.
    trigger = job.get("job")
    if trigger in TRIGGER_JOBS:
        threading.Thread(
            target=TRIGGER_JOBS[trigger], args=(job,),
            name=f"skill-run:{trigger}", daemon=True,
        ).start()
        return None
    slot = job.get("time", "")
    if ((slot.startswith("*:") and slot[1:] == hhmm[2:])
            or (slot.startswith("*/") and int(hhmm[3:]) % int(slot[2:]) == 0)):
        job = {**job, "time": hhmm}  # hourly or every N minutes: the record and dedupe carry this slot
    elif slot != hhmm:
        return None
    # Optional "days": ["mon", ...] narrows a slot to those weekdays (the weekly jobs).
    if job.get("days") and _now().strftime("%a").lower() not in job["days"]:
        return None
    # Python jobs: no "skill" key; must be branched before the
    # job["skill"] accesses below to avoid KeyError.
    name = job.get("job")
    if name in PYTHON_JOBS:
        if _already_ran(name, job.get("time", ""), day, _record_key="job"):
            return None
        if name in DUE_CHECKS and not DUE_CHECKS[name](_now()):
            return None
        return (name, job)
    # Normal skill job: returned for the chain, which runs it after the python jobs.
    if _already_ran(job["skill"], job.get("time", ""), day):
        return None
    return (job["skill"], job)


class SkillScheduler:
    """Background daemon thread that fires due jobs from scheduler-config.json."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None
        # (name, time, day) already handed to a worker. _already_ran only sees a
        # job once its run record lands, so the second 30s tick inside the same
        # minute would otherwise dispatch it again.
        self._fired = set()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="skill-scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                # A scheduler tick must never kill the thread; the next tick retries.
                logger.exception("scheduler tick failed")
            self._stop.wait(POLL_SECONDS)

    def _tick(self):
        cfg = load_config()
        if not is_active_machine(cfg):
            return  # not the schedule owner, or no owner set -> nothing fires
        now = _now()
        hhmm = now.strftime("%H:%M")
        day = now.date().isoformat()
        due = []
        for job in cfg.get("jobs", []):
            d = _dispatch_job(job, hhmm, day)
            if d and (d[0], d[1].get("time", ""), day) not in self._fired:
                self._fired.add((d[0], d[1].get("time", ""), day))
                due.append(d)

        # Jobs sharing a slot run in SEQUENCE, in one worker, not in parallel.
        # They all take the same exclusive flock, so firing them together means
        # one wins and the rest record "skipped: locked" -- and since a slot only
        # matches for its own minute and a skipped run is still a logged run, the
        # losers never get another attempt that day. 06:00 hit this: /job-sweep
        # won the lock and all six python jobs skipped. Python jobs go first
        # (seconds each), then skill jobs (minutes each).
        if due:
            due.sort(key=lambda d: d[0] not in PYTHON_JOBS)

            def _run_due(batch=tuple(due)):
                for name, job in batch:
                    try:
                        (PYTHON_JOBS[name] if name in PYTHON_JOBS else run_skill)(job)
                    except Exception:
                        # _locked_run / run_skill record their own failures; this
                        # is the belt for anything that escapes, and it must not
                        # cost the jobs queued behind it.
                        logger.exception("scheduled job %s raised", name)

            threading.Thread(target=_run_due, name="skill-run:python-jobs",
                             daemon=True).start()


def recent_runs(limit=20):
    """Most-recent run records for the Hub status panel (newest first)."""
    if not RUN_LOG.exists():
        return []
    out = []
    with open(RUN_LOG) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:][::-1]

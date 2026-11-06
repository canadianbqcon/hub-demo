"""Drains `approved` applications through a headless browser and submits them.

One small seam separates the two halves this module needs to stay testable:
    - the browser layer (`PlaywrightATSPage`, `_default_page_factory`) is the
      only thing that ever touches a real page. Every caller reaches it
      through a `page_factory(url, host) -> page` parameter, so a test hands
      in a stub with the same method names and the state machine below never
      knows the difference.
    - the state machine (`_process_claimed`, `_submit`, `_worker_loop`) is
      plain Python: claim the row, route it, fill it, record the outcome.

ABSOLUTE RULE: this module must never click submit on a real application
during development or testing. `--dry-run` and `JOB_SUBMIT_DRY_RUN=1` both
stop before the click; every live run in this build uses one of them.

CLI:
    python3 submitter.py --dry-run APP_ID    # fill + screenshot, no DB writes

Worker:
    submitter.start_worker()   # one daemon thread; idempotent; call once at
                                # app startup, same as skill_scheduler's start()
"""

from __future__ import annotations

import os
import random
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

_JOBS_DIR = Path(__file__).resolve().parent
_HUB = _JOBS_DIR.parent
_DASHBOARD = _HUB.parent
for _p in (str(_DASHBOARD), str(_HUB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from jobs import db  # noqa: E402
from jobs import form_schema  # noqa: E402
from jobs import resume_files  # noqa: E402
from vault_path import vault_root  # noqa: E402

_HOST_APPLY_URL = {
    "greenhouse": "https://job-boards.greenhouse.io/{slug}/jobs/{pid}",
    "lever": "https://jobs.lever.co/{slug}/{pid}/apply",
    "ashby": "https://jobs.ashbyhq.com/{slug}/{pid}/application",
}
_SUPPORTED_HOSTS = set(_HOST_APPLY_URL)

_CONFIRMATION_RE = re.compile(
    r"thank you for applying|application submitted|application has been received",
    re.IGNORECASE,
)
# Same decline wording list the design spec calls out; matched against every
# demographic field's option labels so the submitter always picks a decline
# option over guessing at real data.
# "<form uuid>_" in front of an Ashby field path; the uuid differs on every load
_ASHBY_FORM_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_(?=.)")
_DECLINE_RE = re.compile(
    r"decline|prefer not|don.?t wish|do not want|not to disclose|not to answer",
    re.IGNORECASE,
)
# Greenhouse loads invisible reCAPTCHA Enterprise on every board: a corner badge
# (iframe src size=invisible, .grecaptcha-* nodes) that scores the visit and only
# shows a challenge if it doubts it. That is not a captcha to stop for; a visible
# challenge after the submit click is caught by has_captcha() in _submit.
_CAPTCHA_SELECTORS = (
    "iframe[src*='captcha']:not([src*='size=invisible'])",
    "[class*='captcha' i]:not([class*='grecaptcha' i]):not([class*='g-recaptcha-response' i])",
    "#captcha",
)


# ── outcome helpers (pure) ───────────────────────────────────────────────────


def _decline_value(field: dict) -> str | None:
    for opt in field.get("options") or []:
        if _DECLINE_RE.search(opt.get("label", "")):
            return opt.get("value") or opt.get("label")  # Ashby EEOC radios have no values
    return None


def _apply_url(app: dict) -> str | None:
    host = app.get("ats_host") or ""
    fmt = _HOST_APPLY_URL.get(host)
    if not fmt:
        return None
    canonical = app.get("canonical_url") or app.get("job_url") or ""
    slug = form_schema._slug_from_canonical(canonical)
    pid = app.get("ats_posting_id") or ""
    if not slug or not pid:
        return None
    return fmt.format(slug=slug, pid=pid)


def _resume_path_for(app_id: int) -> Path | None:
    """The application's resume PDF, resolved and confirmed on disk. None if
    it has no resume row, or the stored path doesn't resolve safely."""
    for r in db.list_app_resumes(app_id):
        file_path = r.get("file_path") or ""
        if not file_path.lower().endswith(".pdf"):
            continue
        resolved = resume_files.resolve_resume_path(file_path)
        if resolved and resolved.exists():
            return resolved
    return None


def _cover_path_for(app_id: int) -> Path | None:
    """The newest cover letter PDF (resumes row, variant 'cover-letter'), on disk."""
    row = db.get_cover_pdf(app_id)
    if not row:
        return None
    resolved = resume_files.resolve_resume_path(row.get("file_path") or "")
    return resolved if resolved and resolved.exists() else None


def _is_cover_field(field: dict) -> bool:
    return "cover" in f"{field.get('name', '')} {field.get('label', '')}".lower()


def _screenshot_dir(app_id: int, resume_path: Path | None) -> Path:
    if resume_path is not None:
        return resume_path.parent
    d = vault_root() / "data" / "resumes" / "applications" / str(app_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _screenshot_path(app_id: int, resume_path: Path | None, tag: str) -> Path:
    d = _screenshot_dir(app_id, resume_path)
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S%f")
    return d / f"{app_id}-{tag}-{ts}.png"


def _to_vault_relative(path: Path) -> str:
    return str(path.resolve().relative_to(vault_root())).replace("\\", "/")


def _is_dry_run_env() -> bool:
    return os.environ.get("JOB_SUBMIT_DRY_RUN", "") == "1"


# ── filling (uses only the page_factory seam) ────────────────────────────────


def _fill_form(page, form: list[dict], resume_path: Path | None,
               page_required: frozenset = frozenset(),
               cover_path: Path | None = None) -> list[str]:
    """Fill every recorded field through `page`. Returns the labels of any
    required field that could not be filled (missing resume, missing answer,
    or the adapter itself failing on that control)."""
    failures: list[str] = []
    for field in form:
        label = field.get("label") or field.get("name") or ""
        if field.get("field_type") == "input_file":
            # the cover letter slot gets the cover PDF, never a second copy of the resume
            path = cover_path if _is_cover_field(field) else resume_path
            if path is None:
                if _is_cover_field(field) and not field.get("required"):
                    continue
                failures.append(label)
                continue
            try:
                page.upload_resume(field, path)
            except Exception as exc:  # noqa: BLE001 -- one bad field must not sink the row
                print(f"resume upload failed for {label!r}: {exc}")
                failures.append(label)
            continue

        # the page can mark required what the API calls optional (Greenhouse phone)
        required = field.get("required") or field.get("name") in page_required
        # demographics: the stored answer is already the standing one (sweep_prep); decline if none
        value = (field.get("answer") or _decline_value(field)) if field.get("is_demographic") else field.get("answer")
        if not value:
            if required:
                failures.append(label)
            continue
        # An optional control the page never rendered (Greenhouse lists compliance
        # questions some postings do not mount) is skipped, not a blocker.
        if not page.fill_field(field, value) and required:
            failures.append(label)
    return failures


# ── the state machine (plain Python) ─────────────────────────────────────────


def _submit(app_id: int, app: dict, page_factory) -> str:
    """Route + fill + record one already-claimed (status='submitting') row.

    Every branch calls `db.set_submit_result`, which is the only thing that
    can move the row off `submitting` -- so whatever path this takes, the row
    always lands on a terminal status.
    """
    host = app.get("ats_host") or ""
    if host not in _SUPPORTED_HOSTS:
        db.set_submit_result(app_id, "manual", f"unsupported host: {host or 'none'}")
        return "manual"

    form = db.get_form(app_id)
    if not form:
        # ponytail: "manual_only" has no persisted flag on the row by the time
        # it reaches the worker (it's a prep-time status, and approve() only
        # ever moves 'ready' rows). An approved row with nothing recorded to
        # fill is the same situation in practice, so an empty form is read as
        # manual-only and routed the same way: no browser opens.
        db.set_submit_result(app_id, "manual", "no form recorded (manual only)")
        return "manual"

    url = _apply_url(app)
    if not url:
        db.set_submit_result(app_id, "manual", "could not build an apply URL")
        return "manual"

    resume_path = _resume_path_for(app_id)
    if resume_path is None and any(
        f.get("field_type") == "input_file" and not _is_cover_field(f) for f in form
    ):
        db.set_submit_result(app_id, "manual", "no resume")
        return "manual"

    page = page_factory(url, host)
    try:
        recorded_names = {f.get("name", "") for f in form}
        page_required = frozenset(page.visible_required_names())
        # Greenhouse's phone country picker is filled along with the phone number
        extra = sorted(n for n in page_required if n and n not in recorded_names
                       and not (n == "country" and "phone" in recorded_names))
        if extra:
            db.set_submit_result(app_id, "manual", f"form changed: unrecorded field(s) {extra}")
            return "manual"

        if page.has_captcha():
            db.set_submit_result(app_id, "manual", "captcha detected")
            return "manual"

        failures = _fill_form(page, form, resume_path, page_required, _cover_path_for(app_id))
        pre_shot = _screenshot_path(app_id, resume_path, "prefill" if failures else "filled")
        page.screenshot(pre_shot)
        pre_rel = _to_vault_relative(pre_shot)

        if failures:
            db.set_submit_result(
                app_id, "manual", f"unfilled required field(s): {', '.join(failures)}",
                screenshot=pre_rel,
            )
            return "manual"

        if _is_dry_run_env():
            db.set_submit_result(app_id, "manual", "dry-run", screenshot=pre_rel)
            return "manual"

        page.click_submit()
        post_shot = _screenshot_path(app_id, resume_path, "postsubmit")
        page.screenshot(post_shot)
        post_rel = _to_vault_relative(post_shot)

        if page.wait_for_confirmation():
            db.set_submit_result(app_id, "applied", "confirmed", screenshot=post_rel)
            return "applied"
        if page.has_captcha():
            db.set_submit_result(app_id, "manual", "captcha challenge after submit", screenshot=post_rel)
            return "manual"
        db.set_submit_result(app_id, "unconfirmed", "clicked submit, no confirmation seen", screenshot=post_rel)
        return "unconfirmed"
    finally:
        page.close()


def _process_claimed(app_id: int, page_factory) -> str | None:
    """Claim `app_id` (approved -> submitting) and run it through `_submit`.

    None if the row didn't exist or lost the claim race (already handled by
    another caller) -- there should never be one with a single worker, but
    the conditional UPDATE is what actually guarantees it.
    """
    app = db.get_application(app_id)
    if app is None or not db.claim_for_submit(app_id):
        return None
    try:
        return _submit(app_id, app, page_factory)
    except Exception as exc:  # noqa: BLE001 -- an exception here must never kill the worker
        db.set_submit_result(app_id, "manual", f"worker error: {exc}")
        return "manual"


# ── worker thread ─────────────────────────────────────────────────────────────

_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None


def _worker_loop(gap_range=(30, 90), poll_interval=60, page_factory=None, stop_event=None):
    page_factory = page_factory or _default_page_factory
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        row = db.next_approved()
        if row is None:
            if stop_event is not None:
                if stop_event.wait(poll_interval):
                    return
            else:
                time.sleep(poll_interval)
            continue
        _process_claimed(row["id"], page_factory)
        gap = random.uniform(*gap_range)  # noqa: S311  human-like pacing jitter, not security
        if stop_event is not None:
            if stop_event.wait(gap):
                return
        else:
            time.sleep(gap)


def start_worker(*, gap_range=(30, 90), poll_interval=60, page_factory=None,
                  stop_event=None) -> threading.Thread:
    """Start the single submit-worker daemon thread. Idempotent: a second call
    while the first thread is still alive returns that same thread and starts
    nothing new -- this is what keeps approve-all from ever opening two
    browsers at once."""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return _worker_thread
        _worker_thread = threading.Thread(
            target=_worker_loop,
            kwargs={
                "gap_range": gap_range, "poll_interval": poll_interval,
                "page_factory": page_factory, "stop_event": stop_event,
            },
            daemon=True,
        )
        _worker_thread.start()
    return _worker_thread


# ── real browser adapter ──────────────────────────────────────────────────────


class PlaywrightATSPage:
    """The one seam that touches a real page. Field addressing differs by
    host: Greenhouse's rendered form keys every control by DOM `id` (its
    react-select comboboxes carry no `name` at all), Lever and Ashby key by
    the HTML `name` attribute -- both `name` values happen to come out of
    their respective Task 3 parsers already, so `field["name"]` is read as an
    id here and a name attribute there."""

    def __init__(self, page, host: str, pw=None, browser=None):
        self._page = page
        self._host = host
        self._pw = pw
        self._browser = browser

    def _locator(self, field: dict):
        name = field.get("name", "")
        if self._host == "greenhouse":
            return self._page.locator(f"#{name}")
        if self._host == "ashby":
            # resume has an id but no name; every other control sits in its entry
            return self._ashby_entry(field).locator("input, textarea, select").first
        return self._page.locator(f'[name="{name}"]')

    def _ashby_entry(self, field: dict):
        """Ashby prefixes radio names with a form id that changes on every page
        load, so a recorded name never matches twice. The field entry's
        data-field-path is the stable part. Unnamed means the location picker."""
        path = _ASHBY_FORM_ID_RE.sub("", field.get("name", "")) or "_systemfield_location"
        return self._page.locator(f'[data-field-path="{path}"]')

    def _fill_ashby_choice(self, field: dict, value: str) -> None:
        ftype = field.get("field_type", "")
        name = field.get("name", "")
        truthy = value.strip().lower() in ("true", "yes", "1", "on")
        if ftype == "radio":
            # the page's radios carry no value attribute: pick by the option's visible label
            label = next((o["label"] for o in field.get("options") or []
                          if str(o.get("value")) == str(value) and o.get("label")), value)
            self._ashby_entry(field).get_by_label(label, exact=True).check()
            return
        yesno = self._ashby_entry(field).locator("button[data-option]")
        if yesno.count():  # yes/no question: the checkbox is hidden behind two buttons
            yesno.and_(self._page.locator(f'[data-option="{"yes" if truthy else "no"}"]')).click()
            return
        if truthy:  # one box of a checkbox group, recorded under the option's own name
            self._page.locator(f'input[type="checkbox"][name="{name}"]').check()

    def _fill_ashby_location(self, value: str) -> None:
        combo = self._page.locator('[data-field-path="_systemfield_location"] [role="combobox"]')
        combo.click()
        combo.fill(value)
        self._page.get_by_role("option").first.click(timeout=10000)

    def visible_required_names(self) -> set[str]:
        names: set[str] = set()
        try:
            elements = self._page.locator(
                "input[required], textarea[required], select[required], [aria-required='true']"
            ).all()
        except Exception as e:
            print(f"required-field scan failed: {e}", file=sys.stderr)
            return names
        for el in elements:
            try:
                if not el.is_visible():
                    continue
            except Exception as e:
                print(f"visibility check failed: {e}", file=sys.stderr)
                continue
            ident = el.get_attribute("name") or el.get_attribute("id") or ""
            if ident:
                names.add(ident)
        return names

    def has_captcha(self) -> bool:
        for sel in _CAPTCHA_SELECTORS:
            try:
                if self._page.locator(sel).count() > 0:
                    return True
            except Exception as e:
                print(f"captcha probe {sel!r} failed: {e}", file=sys.stderr)
                continue
        return False

    def fill_field(self, field: dict, value: str) -> bool:
        ftype = field.get("field_type", "")
        try:
            if self._host == "ashby" and ftype in ("radio", "input_checkbox", "checkbox_group"):
                self._fill_ashby_choice(field, value)
            elif self._host == "ashby" and not field.get("name") and ftype == "input_text":
                self._fill_ashby_location(value)
            elif ftype in ("input_text", "input_email", "input_tel", "textarea"):
                loc = self._locator(field)
                loc.wait_for(state="visible", timeout=5000)
                loc.fill(value)
                if field.get("name") == "phone":
                    self._fill_phone_country()
            elif ftype in ("multi_value_single_select", "multi_value_multi_select"):
                self._select_greenhouse(field, value)
            elif ftype == "select":
                self._locator(field).select_option(value)
            elif ftype in ("radio", "input_checkbox", "checkbox_group"):
                self._page.locator(f'[name="{field.get("name", "")}"][value="{value}"]').check()
            else:
                return False
            return True
        except Exception as exc:  # noqa: BLE001 -- caller records this as an unfilled field
            print(f"fill failed for {field.get('label')!r} ({field.get('name')}): {exc}")
            return False

    def _fill_phone_country(self) -> None:
        # ponytail: the candidate is US-based; read it from the profile if that changes
        combo = self._page.locator("#country")
        if not combo.count() or not combo.is_visible():
            return
        combo.click()
        combo.fill("United States")
        self._page.get_by_role("option", name=re.compile(r"^United States")).first.click()

    def _select_greenhouse(self, field: dict, value: str) -> None:
        # Greenhouse's `multi_value_*_select` fields render as react-select
        # comboboxes: no native <select>, no value on the DOM node. The only
        # thing to click is the option whose visible text matches the
        # answer's label, so the value -> label lookup happens here. Compared
        # as strings: Greenhouse's own option values are JSON integers, but
        # an answer read back from the `answers` table is always TEXT.
        label = next(
            (o["label"] for o in field.get("options") or [] if str(o.get("value")) == str(value)),
            value,
        )
        combo = self._page.locator(f"#{field.get('name', '')}")
        gate = self._page.locator("#hispanic_ethnicity")
        if field.get("name") == "race" and not combo.is_visible() and gate.count():
            # Greenhouse mounts race only after the Hispanic/Latino question, which
            # the boards API never lists. Declining that gate keeps race unmounted.
            gate.click()
            self._page.get_by_role("option", name=_DECLINE_RE).first.click()
            return
        combo.wait_for(state="visible", timeout=5000)
        combo.click()
        self._page.get_by_role("option", name=label, exact=True).click()

    def upload_resume(self, field: dict, resume_path: Path) -> None:
        self._locator(field).set_input_files(str(resume_path))
        # Greenhouse uploads in the background; submitting before the file name
        # shows can send the form without it. Raising routes the row to manual.
        self._page.get_by_text(resume_path.name, exact=True).first.wait_for(timeout=30000)

    def screenshot(self, dest: Path) -> None:
        self._page.screenshot(path=str(dest), full_page=True)

    def click_submit(self) -> None:
        self._page.locator('button[type="submit"]').first.click()

    def wait_for_confirmation(self, timeout_ms: int = 20000) -> bool:
        try:
            self._page.wait_for_function(
                "() => document.body && "
                f"/{_CONFIRMATION_RE.pattern}/i.test(document.body.innerText)",
                timeout=timeout_ms,
            )
            return True
        except Exception as e:  # timeout means no confirmation seen
            print(f"confirmation wait ended: {e}", file=sys.stderr)
            return False

    def close(self) -> None:
        try:
            if self._browser is not None:
                self._browser.close()
        finally:
            if self._pw is not None:
                self._pw.stop()


def _default_page_factory(url: str, host: str) -> PlaywrightATSPage:
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    page.goto(url, wait_until="networkidle", timeout=30000)
    return PlaywrightATSPage(page, host, pw=pw, browser=browser)


# ── --dry-run CLI: fill + screenshot, never touches the DB status ───────────


def fill_and_screenshot(app_id: int, page_factory=None) -> Path:
    """`submitter.py --dry-run APP_ID`. Reads the application and its recorded
    form, fills every field on the live page and screenshots -- never claims
    the row, never calls set_submit_result, never clicks submit."""
    app = db.get_application(app_id)
    if app is None:
        raise SystemExit(f"no application {app_id}")
    form = db.get_form(app_id)
    url = _apply_url(app)
    if not url:
        raise SystemExit(
            f"cannot build an apply URL for application {app_id} "
            f"(ats_host={app.get('ats_host')!r})"
        )
    resume_path = _resume_path_for(app_id)
    page_factory = page_factory or _default_page_factory
    page = page_factory(url, app.get("ats_host", ""))
    try:
        failures = _fill_form(page, form, resume_path, frozenset(page.visible_required_names()),
                              _cover_path_for(app_id))
        if failures:
            print(f"unfilled (missing answer or fill failed): {', '.join(failures)}")
        shot = _screenshot_path(app_id, resume_path, "dryrun")
        page.screenshot(shot)
        print(f"screenshot: {shot}")
        return shot
    finally:
        page.close()


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    ids = [a for a in argv if a != "--dry-run"]
    if "--dry-run" not in argv or len(ids) != 1:
        print("usage: submitter.py --dry-run APP_ID", file=sys.stderr)
        sys.exit(1)
    db.init(vault_root() / "data" / "jobs.db")
    fill_and_screenshot(int(ids[0]))


if __name__ == "__main__":
    main()

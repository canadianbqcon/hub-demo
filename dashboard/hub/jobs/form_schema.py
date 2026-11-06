"""Reads an application's form and fills form_fields for it.

Two pure parsers do the actual field extraction, so they're testable off a
saved fixture with no network call:
    parse_greenhouse_questions(json) -> list[field]   # boards-api ?questions=true
    parse_apply_page(html)           -> list[field]   # rendered Lever/Ashby/company-hosted apply page

A field dict: {label, name, field_type, required, options, is_demographic}.
options is a list of {"label", "value"} dicts (empty for free-text fields).

CLI:
    python3 form_schema.py [--dry-run] URL   # read one posting, print its fields
    python3 form_schema.py read-sourced [--limit N]  # fill form_fields for unread `sourced` rows
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

_JOBS_DIR = Path(__file__).resolve().parent
_HUB = _JOBS_DIR.parent
_DASHBOARD = _HUB.parent
for _p in (str(_DASHBOARD), str(_HUB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from jobs import db  # noqa: E402
from jobs import sweep_sources  # noqa: E402
from vault_path import vault_root  # noqa: E402

_HTTP_TIMEOUT = 15

# read_url's answer for a posting that no longer exists: greenhouse boards-api
# 404s, Lever serves a 404 page, Ashby serves a 200 page saying "Job not found".
CLOSED = "closed"
_CLOSED_PAGE_TEXT = ("Job not found", "The job posting you're looking for might have closed")


class _PostingClosed(Exception):
    pass


# ── Greenhouse questions parser (pure) ──────────────────────────────────────

# A question can carry more than one field (Resume/CV ships input_file AND a
# pasted-text textarea for the same upload); the file input is the one that
# actually needs a value at submit time, so it wins and the question becomes
# one form field, not two.
def _pick_field(fields: list[dict]) -> dict | None:
    for f in fields:
        if f.get("type") == "input_file":
            return f
    return fields[0] if fields else None


def _question_to_field(q: dict, is_demographic: bool) -> dict | None:
    f = _pick_field(q.get("fields") or [])
    if f is None:
        return None
    options = [
        {"label": v.get("label", ""), "value": v.get("value", "")}
        for v in (f.get("values") or [])
    ]
    return {
        "label": q.get("label", ""),
        "name": f.get("name", ""),
        "field_type": f.get("type", ""),
        "required": bool(q.get("required")),
        "options": options,
        "is_demographic": is_demographic,
    }


def parse_greenhouse_questions(data: dict) -> list[dict]:
    """boards-api ?questions=true payload -> list[field].

    `questions` are the ordinary application fields; `compliance` entries
    carry the EEOC-style voluntary demographic questions (disability,
    veteran status, race, gender) -- flagged is_demographic so the submitter
    always picks the decline option and never guesses at real data.
    location_questions is skipped: its Longitude/Latitude fields are hidden,
    JS-filled by an autocomplete widget rather than typed, so there is
    nothing here for a form filler to answer.
    """
    out = []
    for q in data.get("questions") or []:
        field = _question_to_field(q, is_demographic=False)
        if field:
            out.append(field)
    for c in data.get("compliance") or []:
        for q in c.get("questions") or []:
            field = _question_to_field(q, is_demographic=True)
            if field:
                out.append(field)
    return out


def fetch_greenhouse_questions(slug: str, posting_id: str) -> dict:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{posting_id}?questions=true"
    req = urllib.request.Request(url, headers={"User-Agent": "job-autopilot/1.0"})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── apply-page parser (pure) ────────────────────────────────────────────────


def _label_for(soup, el) -> str:
    el_id = el.get("id")
    if el_id:
        lbl = soup.find("label", attrs={"for": el_id})
        if lbl:
            text = lbl.get_text(" ", strip=True)
            if text:
                return text
    parent_label = el.find_parent("label")
    if parent_label:
        text = parent_label.get_text(" ", strip=True)
        if text:
            return text
    return el.get("aria-label") or el.get("placeholder") or ""


def _group_label(el) -> str:
    """The question a radio or checkbox group answers.

    Ashby wraps a group in a fieldset with a legend. Lever puts the question in
    an `application-label` div beside the `application-field` holding the inputs.
    """
    fieldset = el.find_parent("fieldset")
    if fieldset:
        legend = fieldset.find("legend")
        if legend:
            text = legend.get_text(" ", strip=True)
            if text:
                return text
    field = el.find_parent(class_="application-field")
    if field:
        lbl = field.find_previous_sibling(class_="application-label")
        if lbl:
            return lbl.get_text(" ", strip=True)
    return ""


# Voluntary self-identification: Lever's diversity survey and EEO block, plus any
# question whose wording is about identity. The submitter always takes the decline
# option on these.
_DEMOGRAPHIC_NAME_RE = re.compile(r"^(surveysResponses|eeo)\[")
_DEMOGRAPHIC_LABEL_RE = re.compile(
    r"gender|race|ethnic|veteran|disabilit|sexual orientation|transgender|pronoun",
    re.IGNORECASE,
)


def _is_demographic(name: str, label: str) -> bool:
    return bool(_DEMOGRAPHIC_NAME_RE.match(name or "") or _DEMOGRAPHIC_LABEL_RE.search(label or ""))


def _clean_label(text: str) -> str:
    return text.replace("\u2731", "").strip()


def parse_apply_page(html: str) -> list[dict]:
    """A rendered Lever/Ashby apply-page HTML -> list[field].

    Radio inputs sharing a `name` collapse into one field (one option per
    button); every other control is a field on its own. Hidden and submit
    inputs are skipped -- nothing for a submitter to fill in.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form") or soup

    fields: list[dict] = []
    seen_radio_names: set[str] = set()
    for el in form.find_all(["input", "textarea", "select"]):
        el_type = str(el.get("type") or "text").lower() if el.name == "input" else el.name
        if el.name == "input" and el_type in ("hidden", "submit", "button"):
            continue
        if str(el.get("name") or "").endswith("captcha-response"):
            continue  # captcha token textarea: the widget fills it, not us

        name = str(el.get("name") or "")
        group = []
        if el.name == "input" and el_type in ("radio", "checkbox") and name:
            group = form.find_all("input", attrs={"type": el_type, "name": name})
        if el_type == "radio" or len(group) > 1:
            if name in seen_radio_names:
                continue
            seen_radio_names.add(name)
            options = [
                {"label": _label_for(soup, g) or g.get("value", ""), "value": g.get("value", "")}
                for g in group
            ]
            label = _clean_label(_group_label(el)) or name
            fields.append({
                "label": label,
                "name": name,
                "field_type": "radio" if el_type == "radio" else "checkbox_group",
                "required": any(g.has_attr("required") for g in group),
                "options": options,
                "is_demographic": _is_demographic(name, label),
            })
            continue

        name = name or str(el.get("id") or "")
        label = _clean_label(_label_for(soup, el)) or name
        required = el.has_attr("required") or el.get("aria-required") == "true"
        if el.name == "select":
            field_type = "select"
            options = [
                {"label": o.get_text(strip=True), "value": o.get("value", o.get_text(strip=True))}
                for o in el.find_all("option")
                if (o.get("value") or o.get_text(strip=True))
            ]
        elif el.name == "textarea":
            field_type = "textarea"
            options = []
        else:
            field_type = f"input_{el_type}"
            options = []
        fields.append({
            "label": label, "name": name, "field_type": field_type,
            "required": required, "options": options,
            "is_demographic": _is_demographic(name, label),
        })
    return fields


_ASHBY_FORM_QUERY = (
    "query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {"
    " jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName,"
    " jobPostingId: $jobPostingId) { applicationForm { sections { fieldEntries {"
    " ... on FormFieldEntry { field isRequired } } } } } }"
)


def fetch_ashby_form(slug: str, posting_id: str) -> dict:
    body = json.dumps({
        "operationName": "ApiJobPosting",
        "variables": {"organizationHostedJobsPageName": slug, "jobPostingId": posting_id},
        "query": _ASHBY_FORM_QUERY,
    }).encode()
    req = urllib.request.Request(
        "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting", data=body,
        headers={"Content-Type": "application/json", "User-Agent": "job-autopilot/1.0"},
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def merge_ashby_form(fields: list[dict], data: dict) -> list[dict]:
    """Ashby's rendered page loses the question text of radio groups, yes/no boxes
    and the location picker, and marks nothing required. Its form API has both, so
    label and required come from the API, matched by field path. The page's names
    stay: they are what the submitter fills by. Radios are named <formId>_<path>;
    the location picker renders with no name at all."""
    sections = ((data.get("data") or {}).get("jobPosting") or {}).get("applicationForm", {}).get("sections") or []
    entries = [e for s in sections for e in (s.get("fieldEntries") or []) if e.get("field")]
    by_path = {e["field"].get("path"): e for e in entries}
    location = next((e for e in entries if e["field"].get("type") == "Location"), None)
    out = []
    for f in fields:
        name = f.get("name") or ""
        e = by_path.get(name) or by_path.get(name.rsplit("_", 1)[-1])
        if e is None and not name:
            if f.get("field_type") != "input_text" or location is None:
                continue  # the unnamed "autofill from resume" upload: not a question
            e = location
        if e is not None:
            label = e["field"].get("title") or f.get("label", "")
            f = {**f, "label": label, "required": bool(e.get("isRequired")),
                 "is_demographic": _is_demographic(name, label)}
            api_opts = e["field"].get("selectableValues") or []
            if api_opts and not any(o.get("value") for o in f.get("options") or []):
                # the page's radios carry no value attribute, so nothing could be picked
                f["options"] = [{"label": o.get("label", ""), "value": o.get("value", "")} for o in api_opts]
        if f.get("options") and not any(o.get("value") for o in f["options"]):
            # still valueless (the EEOC survey is not in the form API): the submitter picks by label
            f = {**f, "options": [{**o, "value": o.get("label", "")} for o in f["options"]]}
        out.append(f)
    return out


def _fetch_rendered_html(url: str, wait_selector: str = "form", reveal: bool = False) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page()
            resp = page.goto(url, wait_until="networkidle", timeout=30000)
            if resp is not None and resp.status == 404:
                raise _PostingClosed(url)
            if reveal:
                # company career pages (shopify.com) render the form only after "Apply"
                link = page.get_by_role("link", name=re.compile(r"^\s*apply", re.I))
                if not link.count():
                    link = page.get_by_role("button", name=re.compile(r"^\s*apply", re.I))
                if link.count():
                    try:
                        link.first.click(timeout=5000)
                    except Exception as e:
                        print(f"apply click failed for {url}: {e}", file=sys.stderr)
            try:
                page.wait_for_selector(wait_selector, timeout=15000)
            except Exception as e:  # best-effort; parse whatever rendered
                print(f"form wait failed for {url}: {e}", file=sys.stderr)
            html = page.content()
            if any(t in html for t in _CLOSED_PAGE_TEXT) and "<form" not in html:
                raise _PostingClosed(url)
        finally:
            browser.close()
    return html


# ── dispatch by host ─────────────────────────────────────────────────────────


def _slug_from_canonical(canonical_url: str) -> str:
    path = urlsplit(canonical_url).path.strip("/")
    return path.split("/")[0] if path else ""


def _looks_like_application(fields: list[dict]) -> bool:
    return any(f.get("field_type") in ("input_email", "input_file") for f in fields)


def read_url(url: str) -> list[dict] | str | None:
    """Read one posting's form. CLOSED when the posting is gone, None on an
    unsupported host or a read failure."""
    canonical_url, ats_host, posting_id = sweep_sources.canonicalize(url)
    slug = _slug_from_canonical(canonical_url)
    try:
        if ats_host == "greenhouse":
            return parse_greenhouse_questions(fetch_greenhouse_questions(slug, posting_id))
        if ats_host == "lever":
            html = _fetch_rendered_html(f"https://jobs.lever.co/{slug}/{posting_id}/apply")
            return parse_apply_page(html)
        if ats_host == "ashby":
            html = _fetch_rendered_html(f"https://jobs.ashbyhq.com/{slug}/{posting_id}/application")
            # no API answer -> read failure, not the page alone: its required flags are all off
            return merge_ashby_form(parse_apply_page(html), fetch_ashby_form(slug, posting_id))
        if url.startswith("http"):
            # company-hosted page (e.g. shopify.com/careers, Ashby form embedded):
            # read the rendered form; a page with no email/resume field is not one
            fields = parse_apply_page(_fetch_rendered_html(url, "textarea, input[type=file]", reveal=True))
            return fields if _looks_like_application(fields) else None
    except _PostingClosed:
        return CLOSED
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return CLOSED
        print(f"read failed for {url}: {exc}")
        return None
    except Exception as exc:  # network/host down, page shape changed, etc.
        print(f"read failed for {url}: {exc}")
        return None
    return None  # unsupported host


_UNREAD_SQL = (
    "FROM applications a WHERE a.status = 'sourced' AND NOT EXISTS "
    "(SELECT 1 FROM form_fields f WHERE f.application_id = a.id)"
)


def _unread_rows(limit: int | None) -> list[dict]:
    sql = f"SELECT a.* {_UNREAD_SQL} ORDER BY a.id"
    params: tuple = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    with db._conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [db._row(r) for r in rows]


def unread_count() -> int:
    with db._conn() as conn:
        return conn.execute(f"SELECT COUNT(*) {_UNREAD_SQL}").fetchone()[0]


def _mark_closed(app_id: int) -> bool:
    """sourced -> cut, closed_reason 'posting closed'. Nothing to hand him."""
    with db._conn() as conn:
        cur = conn.execute(
            "UPDATE applications SET status = 'cut', closed_reason = 'posting closed', "
            "closed_date = date('now', 'localtime'), updated = date('now', 'localtime') WHERE id = ? AND status = 'sourced'",
            (app_id,),
        )
    return cur.rowcount == 1


def _mark_manual_only(app_id: int) -> bool:
    """sourced -> manual_only. Conditional so a row that moved on since the
    read started (approved from a prior sweep, e.g.) is left alone."""
    with db._conn() as conn:
        cur = conn.execute(
            "UPDATE applications SET status = 'manual_only', updated = date('now', 'localtime') "
            "WHERE id = ? AND status = 'sourced'",
            (app_id,),
        )
    return cur.rowcount == 1


def read_sourced(limit: int | None = None) -> tuple[int, int, int]:
    """Fill form_fields for up to `limit` unread `sourced` rows. A closed
    posting is cut; any other unreadable row goes manual_only.

    Returns (read, manual_only, closed) counts. Every row it touches leaves the
    unread set, so repeated calls always make progress.
    """
    read = manual = closed = 0
    for row in _unread_rows(limit):
        url = row.get("canonical_url") or row.get("job_url") or ""
        fields = read_url(url) if url else None
        if isinstance(fields, str):  # CLOSED
            closed += _mark_closed(row["id"])
        elif fields:
            db.save_form_fields(row["id"], fields)
            read += 1
        elif _mark_manual_only(row["id"]):
            manual += 1
    return read, manual, closed


# ── CLI ───────────────────────────────────────────────────────────────────────


def _print_fields(fields: list[dict]) -> None:
    for f in fields:
        opts = "; ".join(f"{o.get('label')}={o.get('value')}" for o in f.get("options") or [])
        line = f"{f['label']} [{f['field_type']}] required={bool(f['required'])}"
        if opts:
            line += f" options: {opts}"
        print(line)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]

    if not argv:
        print("usage: form_schema.py [--dry-run] URL | read-sourced [--limit N]", file=sys.stderr)
        sys.exit(1)

    if argv[0] == "read-sourced":
        limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
        db.init(vault_root() / "data" / "jobs.db")
        read, manual, closed = read_sourced(limit)
        print(f"read-sourced: {read} read, {manual} manual_only, {closed} closed, {unread_count()} remaining")
        return

    # ponytail: URL mode is always read-only. There is no reliable app_id to
    # attach a bare URL's fields to, so nothing is written whether or not
    # --dry-run is passed -- add DB linking here if a caller ever needs it.
    fields = read_url(argv[0])
    if isinstance(fields, str):  # CLOSED
        print("posting closed")
        return
    if fields is None:
        print("no fields read (unsupported host or read failed)")
        return
    _print_fields(fields)
    _ = dry_run  # accepted for CLI-contract compatibility; both paths are read-only


if __name__ == "__main__":
    main()

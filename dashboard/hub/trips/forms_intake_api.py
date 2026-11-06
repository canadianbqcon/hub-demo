"""The Google Forms API side of forms_intake: fetching, signing, prefilling.

Section of `trips.forms_intake` (the facade). See that module's docstring for
the REF-signing rationale; this file is the code that talks to Google and
turns a signed ref into a trusted member key.
"""

from __future__ import annotations

import hmac
import urllib.parse
from hashlib import sha256
from pathlib import Path

from . import forms_intake as _fi


def spec(kind: str) -> dict:
    if kind not in _fi._SPEC:
        raise ValueError(f"unknown form kind: {kind!r}")
    return _fi._SPEC[kind]


def entry_id(question_id: str) -> int:
    """The prefill `entry.N` for a Forms API questionId. It is the hex, in base 10."""
    return int(question_id, 16)


def _ref_secret() -> str:
    """The HMAC key, shared by Hub and the public mirror.

    Its own file, not either process's session secret: both processes mint and
    verify these refs, so a per-process key would make links minted on one fail
    on the other. 0600 beside the code, gitignored, created on first use.
    """
    if _fi._secret is None:
        import config  # deferred: forms_intake must import without the app config

        _fi._secret = config.load_or_create_secret_key(
            Path(config.__file__).parent / ".form_ref_secret", "TRIPS_FORM_REF_SECRET"
        )
    return _fi._secret


def sign_ref(key: str) -> str:
    """`<member key>~<hmac>` — what actually rides in the form's REF question."""
    if not key:
        return ""
    mac = hmac.new(_ref_secret().encode(), key.encode(), sha256).hexdigest()
    return f"{key}{_fi._SEP}{mac[:_fi._SIG_LEN]}"


def verify_ref(signed: str) -> str:
    """The member key back out of a signed ref, or "" if it was not ours.

    "" is the unmatched path, never a guess at who meant to submit: attaching one
    person's allergies to another is not a mistake anyone catches by reading the
    board. rsplit, because a `name:` key may hold anything a person typed.
    """
    signed = (signed or "").strip()
    if _fi._SEP not in signed:
        return ""
    key, _, sig = signed.rpartition(_fi._SEP)
    if not key or not hmac.compare_digest(sig, sign_ref(key).rpartition(_fi._SEP)[2]):
        return ""
    return key


def prefill_url(kind: str, ref: str, name: str = "", ref_qid: str = "") -> str:
    """The link a guest opens: the real form, with who they are already filled in.

    `ref` is db.member_key output and is what a submitted response is matched on.
    It goes in signed, so editing it on the form yields an unmatched submission
    rather than someone else's identity.
    `name` is a courtesy so nobody types their own name again; it is display only.
    """
    s = spec(kind)
    fields = {}
    if name:
        fields[f"entry.{entry_id(s['name_qid'])}"] = name
    qid = ref_qid or _fi._ref_qid.get(kind) or s.get("ref_qid", "")
    if ref and qid:
        fields[f"entry.{entry_id(qid)}"] = sign_ref(ref)
    if not fields:
        return s["responder"]
    return s["responder"] + "?usp=pp_url&" + urllib.parse.urlencode(fields)


# ── Forms API ─────────────────────────────────────────────────────────────────


def _service():
    """A Forms API client on the shared Drive credentials.

    Imported lazily: googleapiclient is heavy, the credentials file is machine
    state, and the trips module has to keep importing on a box with neither.
    """
    import sys

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    cfg = "/home/demo/.config/vault-api"
    if cfg not in sys.path:
        sys.path.append(cfg)
    import services  # type: ignore[import-not-found]

    creds = Credentials.from_authorized_user_file(str(services.DRIVE_TOKEN))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("forms", "v1", credentials=creds, cache_discovery=False)


def ref_question_id(kind: str, svc=None) -> str:
    """The attribution question's id, located on the live form by its title.

    Returns "" when the question is not there yet, which is the signal to run
    ensure_ref_question. Cached per process: the form does not change under us.
    """
    if kind in _fi._ref_qid:
        return _fi._ref_qid[kind]
    svc = svc or _service()
    form = svc.forms().get(formId=spec(kind)["form_id"]).execute()
    for item in form.get("items", []):
        if item.get("title") == _fi.REF_TITLE:
            qid = item.get("questionItem", {}).get("question", {}).get("questionId", "")
            if qid:
                _fi._ref_qid[kind] = qid
                return qid
    return ""


def ensure_ref_question(kind: str, svc=None) -> str:
    """Add the attribution question to the live form if it is not already there.

    Idempotent, and additive only — it never edits or removes anything Sam
    wrote. Placed at index 1, immediately under Name, because a question at the
    bottom of a five-section form is one people scroll past.
    """
    svc = svc or _service()
    existing = ref_question_id(kind, svc)
    if existing:
        return existing
    svc.forms().batchUpdate(
        formId=spec(kind)["form_id"],
        body={"requests": [{"createItem": {
            "item": {
                "title": _fi.REF_TITLE,
                "description": "Filled in from your invite link. It tells the "
                               "trip board whose answers these are.",
                "questionItem": {"question": {
                    "required": False, "textQuestion": {"paragraph": False},
                }},
            },
            "location": {"index": 1},
        }}]},
    ).execute()
    _fi._ref_qid.pop(kind, None)
    return ref_question_id(kind, svc)


def _answer_values(answers: dict, qid: str) -> list[str]:
    got = answers.get(qid) or {}
    return [a.get("value", "") for a in got.get("textAnswers", {}).get("answers", [])]


def _first(answers: dict, qid: str) -> str:
    vals = _answer_values(answers, qid)
    return vals[0] if vals else ""


def _parse_grid(kind: str, s: dict, answers: dict) -> dict:
    grid: dict[str, str] = {}
    for qid, label in s["grid"].items():
        raw = _first(answers, qid)
        if not raw:
            continue
        mapped = _fi._INTEREST.get(raw)
        if mapped:
            grid[label] = mapped
        else:
            _fi.logger.warning("%s form: unmapped grid value %r for %s", kind, raw, label)
    return grid


def _parse_choices(s: dict, answers: dict) -> dict:
    out: dict = {}
    for qid, (key, vocab) in s["choices"].items():
        raw = _first(answers, qid)
        if not raw:
            continue
        mapped = vocab.get(raw) or _fi._LEGACY_TRAVEL.get(key, {}).get(raw)
        if mapped:
            out[key] = mapped
        else:
            # "Other" on a Forms radio arrives as the typed text, so it is a real
            # answer, just not a scale position. It rides along in <key>_other,
            # the same companion-field convention the contact template uses.
            out[key] = "other"
            out[f"{key}_other"] = raw
    return out


def parse_response(kind: str, response: dict) -> dict:
    """One Forms response → {ref, name, response_id, submitted_at, prefs}.

    Unmapped option text does NOT become the enum. It is dropped and logged,
    because a stray value flows straight into preferences.py's rank maps, where
    an unknown key reads as "this member has no opinion" rather than as an error.
    """
    s = spec(kind)
    answers = response.get("answers", {}) or {}
    prefs: dict = {}

    grid = _parse_grid(kind, s, answers)
    if grid:
        prefs[s["grid_key"]] = grid

    prefs.update(_parse_choices(s, answers))

    for qid, key in s["checkbox"].items():
        vals = _answer_values(answers, qid)
        if vals:
            prefs[key] = vals

    for qid, key in s["text"].items():
        val = _first(answers, qid).strip()
        if val:
            prefs[key] = val

    ref_qid = _fi._ref_qid.get(kind) or s.get("ref_qid", "")
    return {
        # Verified, not trusted: the REF question is editable on the live form.
        "ref": (verify_ref(_first(answers, ref_qid)) if ref_qid else ""),
        "name": _first(answers, s["name_qid"]).strip(),
        "response_id": response.get("responseId", ""),
        "submitted_at": response.get("lastSubmittedTime", "") or response.get("createTime", ""),
        "prefs": prefs,
    }


def fetch_responses(kind: str, svc=None) -> list[dict]:
    """Every response on one form, parsed, oldest first.

    Oldest first so a caller that upserts in order ends up holding the newest
    submission per person — which is what "fill it in again to change your
    answers" has to mean, since a Google Form has no update-in-place.
    """
    svc = svc or _service()
    ref_question_id(kind, svc)  # populate the cache so parse_response can read ref
    out: list[dict] = []
    token = None
    while True:
        page = svc.forms().responses().list(
            formId=spec(kind)["form_id"], pageToken=token
        ).execute()
        out.extend(parse_response(kind, r) for r in page.get("responses", []))
        token = page.get("nextPageToken")
        if not token:
            break
    out.sort(key=lambda r: r["submitted_at"])
    return out

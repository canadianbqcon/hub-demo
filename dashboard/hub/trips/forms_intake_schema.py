"""The in-dashboard render of the two forms: schema, gaps, and a clean submit.

Section of `trips.forms_intake` (the facade). See that module's docstring and
its "Render schema" comment block for why only titles and section order live
as data here, with every option label read straight out of the parse-side
vocabularies.
"""

from __future__ import annotations

from . import forms_intake as _fi
from . import preferences as prefs


def _options_for(key: str, values) -> list[str]:
    """The question's options: the whole scale, low end first. Nothing else.

    The SCALE is the source of the list, not the Google Form's vocabulary. That
    matters twice over. The form's order is not the scale — `adventure` is
    authored high-first, `spice` low-first, `raw` neither — which was invisible
    while every option was a sentence and stopped being invisible the moment the
    form grew an axis, because the axis prints low → high and half the questions
    ran the other way. And a stop that belongs on the scale but that the Google
    Form never offered (`funk` has no middle there) can be added to SCALES alone
    and appear here, instead of needing a fake entry in a map whose only job is
    to read real responses.

    Values with no position on the scale are no longer offered at all (2026-08-29).
    "Depends" and "mix of all of it" were ways to not answer: they rode along in
    per_member, `_spread` skipped them, and the rail had nothing to draw — so the
    one person who picked one dropped silently out of every read the question
    feeds. The Google Form still offers them and the parse maps above still read
    them, so an old response is understood; it just cannot be chosen again here.

    A question with no scale keeps its own list, in form order.
    """
    scale = prefs.SCALES.get(key)
    return list(scale["order"]) if scale else list(values)


def _schema_choices(s: dict) -> dict:
    by_qid: dict[str, dict] = {}
    for qid, (key, vocab) in s["choices"].items():
        # `vocab` maps the Google Form's prose onto the enum and stays the PARSE
        # path; what a person reads comes from preferences.LABELS. They used to be
        # the same string, which is how the form ended up asking people to pick
        # "Always local and authentic, the more unusual the better" off a list of
        # five sentences while the crew card called the same answer "very
        # adventurous". Order is the vocab's (the form's own), so a reworded label
        # cannot silently reshuffle the options.
        by_qid[qid] = {
            "key": key, "type": "radio", "title": _fi._TITLES.get(qid, key),
            "options": [{"value": v, "label": prefs.label(key, v)}
                        for v in _options_for(key, vocab.values())],
        }
    for qid, key in s["text"].items():
        by_qid[qid] = {
            "key": key, "title": _fi._TITLES.get(qid, key),
            "type": "paragraph" if qid in _fi._PARAGRAPH else "text",
        }
    for qid, key in s["checkbox"].items():
        by_qid[qid] = {
            "key": key, "type": "checkbox", "title": _fi._TITLES.get(qid, key),
            "options": [{"value": o, "label": o}
                        for o in _fi._CHECKBOX_OPTIONS.get(key, [])],
        }
    return by_qid


def schema(kind: str) -> dict:
    """The whole form as data: sections, questions, options, in form order.

    Every option's `value` is the stored enum and its `label` is the exact text
    the Google form shows, both read from the maps above. A renderer needs
    nothing else, and a validator needs nothing else either — api checks a
    submission against this, so an answer that is not on the form cannot be
    stored by posting it.
    """
    s = _fi.spec(kind)
    grid_key, cols = s["grid_key"], _fi._GRID_COLS[kind]
    by_qid = _schema_choices(s)

    grid = {
        "key": grid_key, "type": "grid",
        # Two grids, two questions. Interests asks what you want to DO, cuisines
        # asks what you LIKE — and asking "how interested are you" about Korean
        # food was the framing Sam called out: it reads as committing to a
        # meal when the honest answer is just that you like it.
        "title": ("How interested are you in each?" if kind == _fi.TRAVEL
                  else "How do you feel about each?"),
        "options": [
            {"value": v, "label": prefs.label(grid_key, v)}
            for v in _options_for(grid_key, (_fi._INTEREST[c] for c in cols))
        ],
        "rows": [
            {"key": label, "label": _fi._GRID_ROW_TITLES.get(label, label)}
            for label in s["grid"].values()
        ],
    }

    sections = []
    for title, qids in _fi._SECTIONS[kind]:
        qs = [grid if q == "grid" else by_qid[q] for q in qids if q == "grid" or q in by_qid]
        if qs:
            sections.append({"title": title, "questions": qs})
    return {"kind": kind, "label": s["label"], "sections": sections}


def unanswered(kind: str, answers: dict) -> list[dict]:
    """The questions this person still owes an answer to, on the CURRENT form.

    The mirror of `clean_submission`: that says what a payload may hold, this
    says what it is missing. Both read the live schema, so a question added,
    reworded or retired changes what is asked for without a second list to keep
    in step.

    A question counts as unanswered when its stored value is not one of the
    options the form offers **now** — which folds two different states into one,
    on purpose. Never answered, and answered with an option since retired, are
    the same problem from the reader's side: the group read cannot place the
    value, so that person is simply absent from it. Retiring the escape hatches
    on 2026-08-29 turned seven live answers into the second kind, and nothing
    would have said so — the form row existed, so every completeness check in
    the app read them as done.

    Free text and checkboxes are exempt. Blank is a real answer on both ("no
    allergies", "no diet"), so nagging about them would nag forever. So is
    `other` with its companion filled in: Akshay answered walking with "For sure
    get them steps in (10-20k minimum a day)", which is an answer the scale
    cannot rank and a person definitely gave.
    """
    answers = answers if isinstance(answers, dict) else {}
    owed = []
    for section in schema(kind)["sections"]:
        for q in section["questions"]:
            allowed = {o["value"] for o in q.get("options", [])}
            if q["type"] == "radio":
                got = answers.get(q["key"])
                if got == "other" and str(answers.get(f"{q['key']}_other") or "").strip():
                    continue
                if got not in allowed:
                    owed.append({"key": q["key"], "title": q["title"], "rows": 0,
                                 "row_keys": []})
            elif q["type"] == "grid":
                got = answers.get(q["key"])
                got = got if isinstance(got, dict) else {}
                # WHICH rows, not just how many. A count tells the nag how loud to
                # be; the keys are what lets the form itself put the marker on the
                # nine cuisines that need re-rating and leave the other twenty
                # alone. "3 to re-answer" with no pointer is a scavenger hunt.
                missing = [r["key"] for r in q["rows"] if got.get(r["key"]) not in allowed]
                if missing:
                    owed.append({"key": q["key"], "title": q["title"],
                                 "rows": len(missing), "row_keys": missing})
    return owed


def _clean_grid(q: dict, got) -> dict | None:
    if not isinstance(got, dict):
        return None
    allowed = {o["value"] for o in q["options"]}
    rows = {r["key"] for r in q["rows"]}
    picked = {
        k: v for k, v in got.items()
        if k in rows and isinstance(v, str) and v in allowed
    }
    return picked or None


def _clean_checkbox(q: dict, got) -> list | None:
    if not isinstance(got, list):
        return None
    allowed = {o["value"] for o in q["options"]}
    picked = [v for v in got if isinstance(v, str) and v in allowed]
    return picked or None


def clean_submission(kind: str, answers: dict) -> dict:
    """A posted answer set, reduced to what this form can actually hold.

    Anything not on the schema is dropped rather than stored: the payload feeds
    preferences.py's rank maps, where an unrecognised value reads as "no opinion"
    instead of as an error, so a stray key is invisible once it is in. Free text
    is length-capped for the same reason the gate caps its fields — the point is
    to keep a megabyte out of the row, not to argue about wording.
    """
    answers = answers if isinstance(answers, dict) else {}
    out: dict = {}
    for section in schema(kind)["sections"]:
        for q in section["questions"]:
            got = answers.get(q["key"])
            if q["type"] == "grid":
                picked = _clean_grid(q, got)
                if picked:
                    out[q["key"]] = picked
            elif q["type"] == "radio":
                allowed = {o["value"] for o in q["options"]}
                if isinstance(got, str) and got in allowed:
                    out[q["key"]] = got
            elif q["type"] == "checkbox":
                picked = _clean_checkbox(q, got)
                if picked:
                    out[q["key"]] = picked
            else:
                if isinstance(got, str) and got.strip():
                    out[q["key"]] = got.strip()[:1000]
    return out

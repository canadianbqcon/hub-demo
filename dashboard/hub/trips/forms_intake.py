"""The two Google Forms behind crew preferences, read through the Forms API.

Sam's Travel Preferences and Food Preferences forms stay where they are.
This module is the bridge: it hands a guest a prefilled link to fill one in, and
it reads the submitted responses back out as the same kebab-case vocabulary the
crew tab already aggregates on (see preferences.py and the contact-node template
in the vault's .claude/skills/ingest/contact-template.md).

Why the Forms API and not a downloaded PDF: responses used to leave the form only
as PDFs, which is why intake was a manual /ingest. forms.responses.list returns
them directly, and the existing Drive token already carries the scope — verified
2026-08-25 against both live forms.

Attribution is the one thing a Google Form does not give for free. Each form
carries a REF short-answer question that the prefilled link fills in with the
guest's member key (db.member_key — a contact slug, or `name:<lowered>` for
someone with no wiki node). The Name field is prefilled too, but it is a display
value people legitimately edit ("Leo pt 2" is a real answer in this data), so it
is never the join key.

A Google Form cannot make a prefilled field read-only, so the REF question is
editable by whoever opens it — and a bare member key is a kebab-cased name,
i.e. guessable. On its own that means anyone holding any link can type someone
else's key and overwrite their allergies, since a submission is latest-wins per
ref. So the value carried is `<key>~<hmac>`, signed with a machine-local key
(sign_ref/verify_ref below). A tampered or hand-typed ref fails verification and
lands in the unmatched queue for Sam, which is the same place an
unattributable submission has always gone. The signature is authenticity only,
not secrecy: the key is still readable in the link, which is fine — it is the
guest's own.

Prefill entry ids are not a second thing to maintain: a Forms API questionId is
the prefill `entry.N` in hex. int(qid, 16) is the whole conversion, verified
against both forms' public HTML.

This module is the facade: it owns every constant and piece of module state
(Rule 1 of docs/archive/specs/2026-09-24-trips-split-complexity-design.md).
The actual functions live in two sections it imports at the bottom and
re-exports by name: `forms_intake_api.py` (signing, prefilling, the Forms API
fetch/parse) and `forms_intake_schema.py` (the in-dashboard render schema,
gap-check, and clean-submit). A section reaches this module's state at call
time via `from . import forms_intake as _fi`, never by binding a name to a
local import, so a test that patches `forms_intake._secret` or `._ref_qid`
still reaches the code the sections run.
"""

from __future__ import annotations

import hmac  # noqa: F401 -- unused here; kept so the name still resolves on the facade (Rule 4 manifest)
import logging
import urllib.parse  # noqa: F401 -- same as hmac above
from hashlib import sha256  # noqa: F401 -- same as hmac above
from pathlib import Path  # noqa: F401 -- same as hmac above
from typing import Any

from . import preferences as prefs  # noqa: F401 -- same as hmac above; used by forms_intake_schema

logger = logging.getLogger(__name__)

TRAVEL, FOOD = "travel", "food"
KINDS = (TRAVEL, FOOD)

# Both forms live in Sam's Drive. Ids are stable; the responder uri is the
# public /viewform link, which is what a guest actually opens.
_TRAVEL_ID = "DEMO_FORM_ID_1"
_FOOD_ID = "DEMO_FORM_ID_2"
_RESPONDER = "https://docs.google.com/forms/d/e/{}/viewform"
_TRAVEL_RESPONDER = _RESPONDER.format(
    "DEMO_FORM_ID_3"
)
_FOOD_RESPONDER = _RESPONDER.format(
    "DEMO_FORM_ID_4"
)

# The title of the attribution question, matched when locating it on the live
# form so the id below can be discovered rather than typed twice.
REF_TITLE = "Reference (prefilled — please leave this as it is)"

# ── Option vocabularies ───────────────────────────────────────────────────────
#
# Every mapping below turns the form's prose option into the kebab enum the
# dashboard aggregates on. Keep these values stable: preferences.py ranks them,
# and a value missing from a rank map silently drops that member out of a spread.

_INTEREST = {
    "Must do": "must", "Want to do": "want", "Neutral": "neutral",
    "Rather not": "rather-not", "Hate": "hate",
    # the food form's grid asks the same five-point question in its own words
    "Must have": "must", "Want to try": "want",
}

_TRAVEL_CHOICES: dict[str, tuple[str, dict[str, str]]] = {
    "5c8a45e9": ("active_hours", {
        "About 4 hours, then I'm done for the day": "4-hrs",
        "About 6 hours, a full morning or a full afternoon": "6-hrs",
        "About 9 hours, most of the day with breaks": "9-hrs",
        "12 hours or more, morning to night": "12-hrs",
    }),
    "473316d6": ("downtime", {
        "A break after every activity": "after-each",
        "One real midday rest": "midday-rest",
        "Short breaks here and there": "short-breaks",
        "None until the night, keep moving": "none-till-night",
    }),
    "13883349": ("start_time", {
        "Up and out by 8, I want a full morning": "by-8",
        "Out by 9 or 10": "by-10",
        "Out by noon, no earlier": "by-noon",
        "Afternoon or later, evenings are my best hours": "after-noon",
    }),
    "31509aae": ("chill_days", {
        "0 — I'm here to do things": "0", "1": "1", "2 or more": "2",
        # Retired options, kept so an old Google response still parses.
        "Depends on how tired I am": "depends",
    }),
    "6ec5233f": ("meals_coordinated", {
        "Every meal": "every", "Lunch and dinner": "lunch-dinner",
        "Just dinner": "dinner",
        "Totally flexible — figure it out as we go": "flexible",
    }),
    "7e87e43e": ("walking", {
        "Under 1 mile": "under-1-mi", "1 to 2 miles": "1-2-mi",
        "2 to 4 miles": "2-4-mi", "4 to 7 miles": "4-7-mi",
        "Any distance, walking is not a factor": "any",
    }),
    "263da1fe": ("distance_willing", {
        "Within about 15 minutes": "15-min", "Up to about 30 minutes": "30-min",
        "Up to about an hour": "60-min",
        "Any distance, wherever the activity is": "any",
    }),
    "7121566e": ("long_travel_days", {
        "No issue, travel is part of it": "welcome",
        "Fine once or twice in a trip": "once-or-twice",
        "Would rather keep them short": "prefer-short",
        "Prefer none at all": "prefer-none",
        "Hard no": "hard-no",
    }),
}

# The travel form was reworded on 2026-08-10 (see the "Old vocabulary,
# superseded" note in the vault's contact-template). The seven responses from
# May carry the ORIGINAL option text, so every one of them lands in `other`
# without these. Only labels actually observed in the response set are listed —
# the live form no longer offers any of them, so this map is closed, not a guess
# at what Google might send next.
_LEGACY_TRAVEL: dict[str, dict[str, str]] = {
    "active_hours": {
        "A solid chunk — active most of the morning or afternoon": "6-hrs",
        "Most of the day with breaks": "9-hrs",
        "Morning to night, maximize everything": "12-hrs",
    },
    "downtime": {
        "Like a mid-day rest or buffer": "midday-rest",
        "An hour here and there is enough": "short-breaks",
    },
    "start_time": {
        "Mid-morning — out by 9 or 10 is fine": "by-10",
        "Relaxed — noon starts don't bother me": "by-noon",
    },
    # "Happy to walk most places" is the legacy `most-places`, and 4-7-mi is the
    # value the hand ingest already gave it on the existing contact nodes. Kept
    # identical so a re-pull does not silently move anyone on the scale.
    "walking": {
        "Happy to walk most places": "4-7-mi",
        "Distance doesn't matter to me": "any",
    },
    "distance_willing": {
        "Up to 20–30 minutes away is fine": "30-min",
        "An hour out is no big deal": "60-min",
        "Willing to go wherever the activity is": "any",
    },
    "long_travel_days": {
        "Would rather keep them short if possible": "prefer-short",
    },
}

_TRAVEL_TEXT = {
    "4e43efd1": "absolute_nos",
    "310691da": "physical_limits",
    "386e85ce": "extra_notes",
}

_TRAVEL_GRID = {
    "459f3585": "Nature", "3d652ca1": "City", "42774f98": "Food",
    "79ad860a": "Nightlife", "2d3dadb0": "Arts", "61736345": "Music",
}

_FOOD_CHOICES: dict[str, tuple[str, dict[str, str]]] = {
    "663e6600": ("spice", {
        "None, keep it mild": "none", "A little kick is fine": "mild",
        "Comfortably medium": "medium", "I like it genuinely hot": "hot",
        "The hotter the better": "very-hot",
    }),
    "24ca5e36": ("adventure", {
        "Always local and authentic, the more unusual the better": "very-adventurous",
        "Lean adventurous, but not every meal": "adventurous",
        "Mix it evenly, some new and some familiar": "balanced",
        "Lean familiar, occasional adventure is fine": "mostly-familiar",
        "Prefer to stick to what I know": "familiar-only",
    }),
    "75b99775": ("funk", {
        "Actively seek them out": "seek", "Happy to try": "willing",
        "Depends on the dish": "depends", "Rather not": "rather-not",
        "Hard no": "hard-no",
    }),
    "2f9b5905": ("offal", {
        "Love them": "love", "Will eat them": "willing",
        "Will try a bite": "a-bite", "Rather not": "rather-not",
        "Hard no": "hard-no",
    }),
    "14f94c10": ("raw", {
        "Love them": "love", "Fine with them": "willing",
        "Cooked fish yes, raw no": "cooked-only",
        "Only if I know the place": "if-trusted", "Hard no": "hard-no",
    }),
    "344e78d8": ("sharing", {
        "Family style, share everything": "family-style",
        "Mostly share, one dish I want to myself": "mostly-share",
        "Own dish, happy to trade bites": "own-with-bites",
        "Own dish, no sharing": "own-only",
    }),
    "4e29b8af": ("spend", {
        "Under $15": "under-15", "$15 to $25": "15-25", "$25 to $40": "25-40",
        "$40 to $70": "40-70", "$70 and up": "70-plus",
        "Depends entirely on the occasion": "depends",
    }),
    "0a0dbece": ("venue", {
        "Street food and hole in the wall": "street-food",
        "Casual and cheap": "casual", "Solid mid-range sit-down": "mid-range",
        "Nicer restaurants worth dressing for": "upscale",
        "Mix of all of it": "mixed",
    }),
    "7c7c12e9": ("reservations", {
        "Will plan around a hard-to-get reservation": "will-chase",
        "Happy to book, will not chase": "will-book",
        "Short wait is fine, no reservations needed": "short-wait",
        "Prefer to walk in and be seated": "walk-in",
    }),
    "35ad19cc": ("alcohol", {
        "I do not drink": "none", "Rarely, maybe one": "rarely",
        "Socially, a couple with dinner": "social",
        "Enthusiastically, drinks are part of the night": "enthusiastic",
    }),
}

_FOOD_TEXT = {
    "29919da4": "allergies",
    "2a31d48f": "wont_eat",
    "0bb8f240": "textures",
    "3ac4bb91": "extra_notes",
}

# Multi-select. Kept as a list because "vegetarian + gluten-free" is two facts,
# and collapsing it to a string is how one of them gets lost.
#
# `_DRINKS_QID` is not a Google question. The old coffee/tea radio (52b17222) was
# two questions wearing one — "coffee, and I care about it" and "both" were not
# mutually exclusive, so a serious coffee drinker who also drinks tea had two
# right answers. It is retired, and what replaced it is a multi-select the Google
# Form does not have. The qid is a synthetic hex id so the schema stays keyed the
# same way; `parse_response` looks for it in a Google payload, never finds it, and
# stores nothing, which is correct — nobody is asked this on Google.
_DRINKS_QID = "dbd21f0c"
_FOOD_CHECKBOX = {"5b4e3f02": "diets", _DRINKS_QID: "drinks"}

_FOOD_GRID = {
    "4a3ef41f": "Chinese", "4ee527b8": "Japanese", "61a8e8a2": "Korean",
    "463fee73": "Thai & SE Asian", "494f5219": "Indian & South Asian",
    "2f0fa4ec": "Middle Eastern", "3d1b8dd9": "Mexican & Latin American",
    "54107243": "Italian", "2209f1f2": "French & European",
    "3d46ff67": "American & BBQ", "11a8e161": "Caribbean & African",
    "11030463": "Seafood", "7b200bd2": "Vegetarian & plant-forward",
}

_SPEC: dict[str, dict[str, Any]] = {
    TRAVEL: {
        "form_id": _TRAVEL_ID,
        "responder": _TRAVEL_RESPONDER,
        "label": "Travel Preferences",
        "name_qid": "1b4800c0",
        # Created by ensure_ref_question on 2026-08-25 and pinned here so a
        # prefill link costs zero Google round trips — this is read on every
        # crew-tab render. ref_question_id re-discovers it live during a sync,
        # which is what repairs this if the question is ever deleted and remade.
        "ref_qid": "5a7f3d3e",
        "grid": _TRAVEL_GRID,
        "grid_key": "interests",
        "choices": _TRAVEL_CHOICES,
        "text": _TRAVEL_TEXT,
        "checkbox": {},
    },
    FOOD: {
        "form_id": _FOOD_ID,
        "responder": _FOOD_RESPONDER,
        "label": "Food Preferences",
        "name_qid": "7269cb68",
        "ref_qid": "6a283d24",
        "grid": _FOOD_GRID,
        "grid_key": "cuisines",
        "choices": _FOOD_CHOICES,
        "text": _FOOD_TEXT,
        "checkbox": _FOOD_CHECKBOX,
    },
}

# Discovered from the live form on first use and cached here, rather than typed
# in as a constant that has to be re-typed if the question is ever recreated.
_ref_qid: dict[str, str] = {}

_SEP = "~"
_SIG_LEN = 16
_secret: str | None = None

# ── Render schema (the in-dashboard form) ─────────────────────────────────────
#
# The same two forms, rendered by the trips board so a guest never has to leave
# it — and, more to the point, so the answer is attributed by the session rather
# than by anything the browser sends. See api.api_submit_prefs.
#
# Only the question TITLES and the section order live here. Every option label
# is read straight out of the maps above, in the order they are written, which
# is form order — so an option cannot drift between what the form shows and what
# the board stores, because there is only one copy of it.
#
# Titles verified against both live forms 2026-08-25.

_GRID_COLS = {
    TRAVEL: ["Must do", "Want to do", "Neutral", "Rather not", "Hate"],
    FOOD: ["Must have", "Want to try", "Neutral", "Rather not", "Hate"],
}

# The grid's row wording on the live form. The maps above key on the SHORT label
# the dashboard aggregates on ("Nature"), which is not what a person should be
# asked to rate ("Nature & Outdoors").
_GRID_ROW_TITLES = {
    "Nature": "Nature & Outdoors", "City": "City Exploration",
    "Food": "Food & Eating Out", "Nightlife": "Nightlife & Bars",
    "Arts": "Arts & Culture", "Music": "Music & Live",
    "Thai & SE Asian": "Thai & Southeast Asian",
    "Indian & South Asian": "Indian & South Asian",
    "American & BBQ": "American, BBQ & diner",
    "Seafood": "Seafood-forward",
}

# No "No restrictions" option: an unchecked list already says that, and a button
# for it was a second way to say the same thing that three separate surfaces then
# had to filter back out. Dropping it here does not erase it — five member_prefs
# rows and the live Google Form still carry the value, api._denoise strips it on
# the way to every surface, and clean_submission drops it the next time that
# person saves the form. Nobody is asked the question again.
_DIET_OPTIONS = [
    "Vegetarian", "Vegan", "Pescatarian", "Halal", "Kosher",
    "Gluten-free", "Dairy-free", "Low carb or keto",
]

# What you enjoy drinking, tick as many as apply. A checkbox rather than a radio
# because the honest answer is usually more than one, which is exactly what the
# coffee/tea radio could not hold. Not locked to five the way the single-pick
# scales are — a list you tick is not an answer range, and `diets` runs to eight.
_DRINK_OPTIONS = ["Water only", "Coffee", "Tea", "Boba", "Smoothies"]

_CHECKBOX_OPTIONS = {"diets": _DIET_OPTIONS, "drinks": _DRINK_OPTIONS}

_TITLES = {
    # travel
    "5c8a45e9": "How many hours of active time do you prefer per day?",
    "473316d6": "How important is downtime between activities?",
    "13883349": "What time do you like to start the day?",
    "31509aae": "In a typical 5-day trip, how many fully low-key days do you want?",
    "6ec5233f": "How many meals per day do you want planned as a group?",
    "7e87e43e": "How much walking are you comfortable with per day?",
    "263da1fe": "How far from home base will you go for an activity?",
    "7121566e": "How do you feel about long travel days within the trip?",
    "4e43efd1": "Absolute no's — things you won't do regardless of the group.",
    "310691da": "Any physical limitations? (injuries, mobility, heat sensitivity)",
    "386e85ce": "Anything else?",
    # food
    "29919da4": "Any food allergies or intolerances?",
    "5b4e3f02": "Do you follow any of these?",
    "2a31d48f": "Foods you will not eat, regardless of the group",
    "0bb8f240": "Any textures you cannot deal with?",
    "663e6600": "How much spice can you handle?",
    "24ca5e36": "How adventurous are you with food?",
    "75b99775": "Strong or funky flavors (fermented, aged, pungent)?",
    "2f9b5905": "Organ meats and offal?",
    "14f94c10": "Raw dishes (sushi, tartare, oysters, ceviche)?",
    "344e78d8": "How do you prefer to order in a group?",
    "4e29b8af": "A comfortable spend per person for a normal dinner out?",
    "0a0dbece": "What kind of place do you gravitate to?",
    "7c7c12e9": "How do you feel about waiting for a table or booking ahead?",
    "35ad19cc": "How do you drink alcohol?",
    "dbd21f0c": "What do you enjoy drinking?",
    "3ac4bb91": "Anything else worth knowing about how you eat?",
}

# Section title -> the qids under it, in form order. "grid" is the interests /
# cuisines matrix, which has no single qid.
_SECTIONS = {
    TRAVEL: [
        ("Activity interests", ["grid"]),
        # "How many meals get planned as a group" is trip scheduling, so it sits
        # with the rest of the day's shape. The old "Food & drink" section that
        # held it also asked how adventurous you are with food and whether you
        # have dietary restrictions — both of which the FOOD form asks properly
        # (adventure; and allergies / diets / wont_eat as three questions rather
        # than one free-text line). Asking them twice produced two answers per
        # person that could disagree, which they did.
        ("Energy & pace", ["5c8a45e9", "473316d6", "13883349", "31509aae", "6ec5233f"]),
        ("Logistics & range", ["7e87e43e", "263da1fe", "7121566e"]),
        ("Hard limits", ["4e43efd1", "310691da", "386e85ce"]),
    ],
    FOOD: [
        ("Cuisines", ["grid"]),
        ("Restrictions & hard no's", ["29919da4", "5b4e3f02", "2a31d48f", "0bb8f240"]),
        ("Heat & adventurousness", ["663e6600", "24ca5e36", "75b99775", "2f9b5905", "14f94c10"]),
        ("Dining style & budget", ["344e78d8", "4e29b8af", "0a0dbece", "7c7c12e9"]),
        ("Drinks", ["35ad19cc", _DRINKS_QID]),
    ],
}

# Which payload keys are free text, so a submission can be checked against the
# schema rather than against a second hand-kept list. Built once, at import.
_PARAGRAPH = {"310691da", "386e85ce", "29919da4", "2a31d48f", "3ac4bb91"}

# How long a fix-up actually takes, in minutes. One number, one place, and it is
# in the copy on both surfaces — a nag that does not say how long reads as a
# project, and people put a project off. A handful of single-pick questions is a
# genuine two minutes; the estimate is deliberately not scaled per person,
# because "about 2 minutes" is what makes somebody do it now.
FIX_MINUTES = 2


# ── Sections (Rule 3: imported last, after every name above is defined) ───────

from . import forms_intake_api as _forms_intake_api  # noqa: E402
from . import forms_intake_schema as _forms_intake_schema  # noqa: E402

# Explicit re-exports (Rule 4: never `import *`, which drops underscore names).
spec = _forms_intake_api.spec
entry_id = _forms_intake_api.entry_id
_ref_secret = _forms_intake_api._ref_secret
sign_ref = _forms_intake_api.sign_ref
verify_ref = _forms_intake_api.verify_ref
prefill_url = _forms_intake_api.prefill_url
_service = _forms_intake_api._service
ref_question_id = _forms_intake_api.ref_question_id
ensure_ref_question = _forms_intake_api.ensure_ref_question
_answer_values = _forms_intake_api._answer_values
_first = _forms_intake_api._first
_parse_grid = _forms_intake_api._parse_grid
_parse_choices = _forms_intake_api._parse_choices
parse_response = _forms_intake_api.parse_response
fetch_responses = _forms_intake_api.fetch_responses

_options_for = _forms_intake_schema._options_for
_schema_choices = _forms_intake_schema._schema_choices
schema = _forms_intake_schema.schema
unanswered = _forms_intake_schema.unanswered
_clean_grid = _forms_intake_schema._clean_grid
_clean_checkbox = _forms_intake_schema._clean_checkbox
clean_submission = _forms_intake_schema.clean_submission

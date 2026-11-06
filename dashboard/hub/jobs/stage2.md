# dashboard/hub/jobs/stage2.md — Stage 2: Research sweep

For routing and overview, see `dashboard/hub/jobs/CLAUDE.md`. For cross-module rules, see `dashboard/CLAUDE.md`.

**Canonical behavior spec:** `.claude/skills/job-research/SKILL.md`. This file is a field reference — the skill is the authoritative source for what Stage 2 does.

## Stage 2: Research sweep

**Trigger:** Invoked automatically by `/job` after Stage 1, or directly via `/job-research [company | app id | all]`.

**What Claude does:**

At more than ~3 target listings, per-company research fans out to read-only sub-agents (one per company) that return gap-fill, research-row, and process-step payloads while all DB writes stay in the main thread — see the "Sub-agent fan-out" section in the `job-research` skill for the dispatch contract.

1. For each target listing, call `GET http://localhost:5002/jobs/api/applications/{id}` and build a **gap list** — null or empty intake fields from Stage 1.
2. Fill gaps: Glassdoor culture data (always), re-read JD if scoring/requirements incomplete, any other null fields resolvable via search.
3. `PATCH http://localhost:5002/jobs/api/applications/{id}` with updated intake fields.
4. Fill every research-row subcategory (single 8-category schema, 39 subs) via `POST http://localhost:5002/jobs/api/applications/{id}/research` — one POST per subcategory.
5. Create process steps via `POST http://localhost:5002/jobs/api/applications/{id}/process-steps/bulk`.

## Gap fill fields (Stage 2 responsibility)

| Field | Source |
|---|---|
| `culture_rating` | Glassdoor overall rating |
| `culture_recommend` | % employees who recommend |
| `culture_work_life` | Glassdoor work-life balance rating |
| `score_role` | Re-read JD if null from Stage 1 |
| `requirements` | Re-read JD if incomplete |
| `nice_to_haves` | Re-read JD if incomplete |
| Any other null intake field | Additional web research |

Glassdoor search format: `"<Company name>" Glassdoor rating "recommend to a friend" "work-life balance" 2025 OR 2026`

## Research-row categories

`POST http://localhost:5002/jobs/api/applications/{id}/research` with `category` + `subcategory` + `content`. One unified schema — **8 categories, 39 subcategories** — fills both the research surface and the intake research snapshot. Write **one POST per subcategory (39 total per listing)**; this matches `job-research/SKILL.md` Step 3 and the frontend `RESEARCH_CATEGORIES` exactly.

| category | subcategories | Primary sources |
|---|---|---|
| `role` | `summary`, `day_to_day`, `travel`, `success`, `customers`, `schedule`, `tools`, `environment` | JD, company blog, LinkedIn job posts, Glassdoor reviews |
| `company` | `stage`, `size`, `funding`, `sites` | Crunchbase, LinkedIn company page, press coverage |
| `culture` | `vibe`, `looking_for`, `not_looking_for`, `green_flags`, `red_flags`, `values` | Glassdoor reviews, Blind, Reddit |
| `compensation` | `base`, `equity`, `bonus`, `comparison` | Glassdoor, Levels.fyi, LinkedIn salary insights |
| `progression` | `internal_path`, `lateral`, `tenure` | LinkedIn profiles of current/former employees, Glassdoor |
| `benefits` | `health`, `retirement`, `time_off`, `perks` | Company careers page benefits section, Glassdoor |
| `process` | `steps`, `rounds`, `gating`, `timeline`, `referral` | Glassdoor interviews section, Reddit, LinkedIn posts |
| `intel` | `insider`, `hypothesis`, `tactical`, `sample_questions`, `unionization` | Reddit, Glassdoor reviews/interviews, news, NLRB filings, LinkedIn activity |

If a subcategory has no available data, write `"No public data found."` — blank looks identical to not-yet-researched.

**Intake-visible subs** (surface in the intake tab research snapshot — write with the same quality): `role.summary`, `role.day_to_day`, `role.travel`, `company.stage`, `company.size`, `culture.vibe`, `culture.looking_for`, `culture.not_looking_for`, `culture.green_flags`, `culture.red_flags`, `compensation.base`.

**Removed keys (do not write):** `locations`, `role_mechanics`, and `progression.for_me` were removed in commit `f477b1e` (`schedule`/`tools`/`environment` folded into `role`, `sites` folded into `company`). `benefits.eligibility` is likewise gone. Any existing DB rows under these keys are orphaned and will not render — never write to them.

## Process steps

After filling the `process` category research rows, call:

```
POST http://localhost:5002/jobs/api/applications/{id}/process-steps/bulk
{
  "steps": [
    { "step_order": 0, "label": "Applied",        "step_type": "submitted",   "status": "complete", "notes": "" },
    { "step_order": 1, "label": "Phone Screen",   "step_type": "screen",      "status": "pending",  "notes": "30 min with recruiter" },
    ...
  ]
}
```

This replaces all existing steps. If process unknown: `submitted` (complete) + one generic `interview` (pending).

**Step types:** `submitted`, `screen`, `assessment`, `interview`, `panel`, `reference`, `offer`, `other`.

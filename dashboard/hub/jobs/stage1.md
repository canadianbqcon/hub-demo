# dashboard/hub/jobs/stage1.md — Stage 1: Batch intake

For routing and overview, see `dashboard/hub/jobs/CLAUDE.md`. For cross-module rules, see `dashboard/CLAUDE.md`. For per-ATS URL resolution and JD-fetch detail, see `dashboard/hub/jobs/ats-reference.md` — load on demand.

**Canonical behavior spec:** `.claude/skills/job-intake/SKILL.md`. This file is a field reference — the skill is the authoritative source for what Stage 1 does.

## Stage 1: Batch intake

**Trigger:** Sam pastes job listings (URLs, pasted text, or mix). Invoked via `/job-intake` or automatically as part of `/job`.

**What Claude does:**

1. Read `candidate_profile.md`.
2. Evaluate each listing against hard-cut rules (location, salary, domain, experience, scam signals). Full rule list in the `job-intake` skill.
3. For each passing listing, run in parallel: resolve `job_url`, fetch the full JD (Playwright for SPAs), extract intake fields. At more than ~8 surviving listings, this fans out to read-only sub-agents (one per ~5–8 listings) that return intake payloads while all DB writes stay in the main thread — see the "Sub-agent fan-out" section in the `job-intake` skill for the dispatch contract.
4. `POST http://localhost:5002/jobs/api/applications` with all fields extractable from the listing text and JD.
5. Report results.

**Glassdoor culture data is Stage 2.** Do not search Glassdoor at intake. `culture_rating`, `culture_recommend`, and `culture_work_life` are written as `null` at Stage 1 and filled by Stage 2.

## Fields written at Stage 1

From listing text:

| Field | Value |
|---|---|
| `company` | Company name |
| `role` | Exact job title from the listing |
| `status` | `"researching"` |
| `work_arrangement` | `"Remote"`, `"Hybrid"`, or `"Onsite"` |
| `employment_type` | `"Full-time"`, `"Part-time"`, `"Contract"`, or `"Temp"` — default `"Full-time"` if unlabeled |
| `location` | City/state only, e.g. `"New York, NY"` |
| `source` | `"LinkedIn"`, `"Indeed"`, `"company direct"`, `"referral"`, `"other"` |
| `salary_min` / `salary_max` | Numeric annual dollar values — see salary extraction rule below |
| `listing_posted_date` | Date the listing was posted, ISO `YYYY-MM-DD`. Use the posting/"posted" date shown on the listing or ATS; leave `null` if none is shown (do not guess from the scrape date) |

From JD:

| Field | Value |
|---|---|
| `job_url` | Direct listing URL (resolved via URL resolution rule) |
| `score_role` | 1–10 AI assessment of role fit vs. candidate profile |
| `priority` | `"high"` / `"medium"` / `"low"` |
| `priority_reason` | 1–3 sentences: what fits, what doesn't, domain gap |
| `red_flags` | Signals from listing or JD — unmet requirements, vague JD, scam signals |
| `red_flags_risk` | `"low"` / `"medium"` / `"high"` |
| `requirements` | Hard requirements from JD, one per line |
| `nice_to_haves` | Preferred qualifications, one per line |
| `years_required` | Minimum years of experience required, as an integer. `0` for entry-level / "no experience required" roles; `null` if the JD states none. This is the structured field — still also lead `notes` with the human-readable `Requirements: X years` line |
| `notes` | Leads with `Requirements: X years, [quals].` |
| `company_summary` | **Best-effort.** 1–2 plain sentences: what the company is + what their product/service is. Surfaced in the "the company & the role" section atop the intake tab. Fill from the JD / company page when stated; leave `""` if the listing doesn't say. Not gated — no extra fetch, no hold-for-input. |
| `role_summary` | **Best-effort.** 1–2 plain sentences: what you'd do in the role + what it provides the company. Fill from the JD when clear; leave `""` if the JD is too thin. Not gated. |

Fields left `null` at Stage 1 (filled by Stage 2):

| Field | Filled in Stage 2 via |
|---|---|
| `culture_rating` | Glassdoor search |
| `culture_recommend` | Glassdoor search |
| `culture_work_life` | Glassdoor search |

### Salary extraction rule (mandatory)

Salary must go into `salary_min` and `salary_max` as numeric annual dollar values — never as text in `notes`:

- `$50–70k` → `salary_min: 50000, salary_max: 70000`
- `$65k` single value → both fields: 65000
- `$22/hr` → 45760 (×2,080 hrs)
- `$22–28/hr` → `salary_min: 45760, salary_max: 58240`
- Not listed → leave both `null`. Null salary fields cause `compScore()` to return neutral (5/10).

### JD fetch rule (mandatory)

Do not add a listing to the DB without having read the JD. See the `job-intake` skill for the full fetch path (WebFetch → Playwright → WebSearch snippets → hold for user input).

### URL resolution rule (mandatory)

No stubs on `job_url`. See the `job-intake` skill for full resolution order (company site → ATS → brand-domain fallback). For per-ATS specifics see `ats-reference.md`.

### Intake report format

```
Stage 1 complete.

Added (X):
  - Company — Role | score_role: N | priority: high/medium/low

Cut (Y):
  - Company — Role | reason

Flagged (Z):
  - Company — Role | reason
```

# dashboard/hub/jobs/stage3.md — Stage 3: Application prep

For routing and overview, see `dashboard/hub/jobs/CLAUDE.md`. For cross-module rules, see `dashboard/CLAUDE.md`. For candidate profile and position IDs, read `dashboard/hub/jobs/candidate_profile.md` before any tailoring.

## Stage 3: Application prep

**Trigger:** "tailor resume for [company]", "write cover letter for [company]", "application prep for [company]", or "prep for [company]".

**What Claude does:**

1. Read the job via `GET /jobs/api/applications/{id}` — pay attention to `research` entries, especially `role/summary`, `role/day_to_day`, `process/steps`, `role/success`, `role_mechanics/tools`.
2. Read `dashboard/hub/jobs/candidate_profile.md` for canonical work history.
3. **Run the mapping analysis** (mandatory pre-generation step — see below). Surface gaps to the user before writing any tailored output.

### Mapping analysis (mandatory pre-generation step)

The pipeline runs **candidate-first**, not JD-first. Before any tailored output is written, produce an explicit mapping table:

| JD requirement (verbatim or close paraphrase) | Candidate match | Source |
|---|---|---|
| (each major JD requirement from role/day_to_day, role/success, role_mechanics/tools) | verbatim source bullet OR "no match — gap" | position ID + bullet, or candidate_profile.md section, or vault node path |

Extract requirements from: `company_research` rows for the application (categories `role/day_to_day`, `role/success`, `role_mechanics/tools`, `process/steps`), plus the application's `notes` field, plus the JD URL if newer information is in scope.

**Rule on gaps:** Requirements with no candidate match are *gaps*. Gaps are NOT filled. They remain visible to the user. The user may explicitly approve framing for a borderline gap; Claude does not paper over silently. If a JD requirement names a tool, language, system, or skill the candidate has no source evidence for (e.g. "Acumatica ERP," "Gemini," "data entry"), it is a gap — do NOT add it to skills, summary, or bullets to "match" the JD. The whole point of this step is to make gaps visible *before* the temptation to fill them.

**Why this exists:** The opposite pipeline — JD-first, "what would the JD want to see" — produces JD-keyword injection: skills and claims pulled from the requirements list and dropped into the resume even when the candidate has no source evidence. See [[wiki/problems/resume-jd-injection]] for the triggering case.

Surface the mapping table (or at minimum, the gap list) to the user in chat before writing resume_notes. Wait for acknowledgement before generating output.

### Resume tailoring

Write via `POST /jobs/api/applications/{id}/resume-notes`:

| section | note |
|---|---|
| `"summary"` | 2–3 sentence tailored professional summary. Every claim (verb, tool name, adjective applied to the candidate) must trace to specific source evidence. Marketing-style language without an underlying source claim is removed. |
| `"skills"` | Comma-separated. Every skill must trace to specific source evidence (position ID + bullet, OR named project in candidate_profile.md, OR a vault node confirmed to apply to the candidate). A skill that does not trace is removed, not flagged. JD-listed tools the candidate does not use are gaps — do not add them. |
| `"exp:{position_id}"` | 3–5 bullet points starting with `•`, rewritten to emphasize skills relevant to THIS job — see source-trace rule below |
| `"projects"` | Optional. Side projects, portfolio work, AI-directed builds, etc. — surface only what the role rewards. Format: project name + year on one line, then `•` bullets. Same source-trace rule as bullets: every claim must trace to a vault node or candidate_profile.md entry. |
| `"__sort__"` | **Default: reverse-chronological by start date.** JD-relevance ordering is an explicit override only — Claude must surface "I'd reorder positions to put X before Y for relevance" and wait for user approval before writing a non-chronological sort. ATS systems and most recruiters expect reverse-chrono first. |
| `"__hide__"` | Comma-separated position IDs to exclude (for clearly irrelevant roles) |

**Stage 3 UI render order** (matches the downloaded PDF layout): Professional Summary → Skills Highlight → Experience cards → Projects → Application Responses → Cover Letter (collapsible, default closed since not every job requests one). When writing resume_notes, populate sections in any order — the UI orders them by this convention regardless of write order.

Tailored bullets rewrite and emphasize real experience — they do **not** invent credentials. Reframe real experience to match job language; if a skill is not in the work history, do not claim it.

**Rewriting boundary (mandatory):** You may change verb choice, industry framing, word order, and level of specificity. You may NOT change the underlying action — what the person actually did. "Trained on SOPs" and "maintained documentation for SOPs" are different actions; the latter is fabrication even though it sounds adjacent. When in doubt, ask: could someone ask a follow-up interview question that would expose this as false? If yes, do not write it.

**Post-generation source-trace check (mandatory — applies to bullets, skills, AND summary):** After generating each tailored bullet, each skill in the skills list, and each clause in the summary, identify the specific source it derives from — a position ID + verbatim source bullet, OR a named project in `candidate_profile.md`, OR a vault node path. If no source maps, it is removed — not flagged, removed. The user can add it back if they choose to own the claim. State this trace inline when writing bullets, e.g.: `• [derived from isshiki_lead_barista: "Trained all new hires on SOPs..."] Standardized onboarding for all new hires...` For skills and summary, surface the trace mapping to the user in chat alongside the generated text. The skills/summary trace is the same rule and the same enforcement as bullets — there is no "soft" version for those sections.

**Cross-position contamination check (mandatory):** Do not borrow bullets from one position and attribute them to another. Each position's tailored bullets must derive exclusively from that position's source lines. The AOM "Built location-specific SOPs" bullet must never appear under Lead Barista, even in paraphrased form.

**Cover letter** — write via `POST /jobs/api/applications/{id}/cover-letter` with `tone`, `angle`, and `draft` fields.

**Prep tab** (stories, skills, application Q&A):

- Stories: `POST /jobs/api/applications/{id}/stories` — behavioral interview stories (STAR format) selected and framed for this role's likely interview style
- Skills: `POST /jobs/api/applications/{id}/skills` — skills assessment and gap analysis vs. job description
- Application-specific questions: write answers into `notes` or a dedicated research block (`category: "prep"`, `subcategory: "{question_slug}"`) when the listing has specific screening questions

**Position IDs** (from `GET /jobs/api/candidate-profile`):
- `isshiki_area_operations` — AOM at Isshiki
- `isshiki_lead_barista` — Lead Barista at Isshiki
- `juniper_barback` — Barback at Juniper & Co
- `advanced_scrub_technician` — Scrub Tech at Advanced Vascular Care
- `harbs_food_server` — Food Server at HARBS UES
- `columbia_assistant_lab` — Lab Tech at Columbia
- `tiertime_accounting_assistant` — Accounting intern at Tiertime

### Interview Q&A population

After completing the mapping analysis and resume tailoring:

1. Call `POST /jobs/api/applications/{id}/interview-qa/from-template` to clone the standard 20-question bank into this application. Idempotent — safe to call again if some questions are already present.
2. For each cloned question, fill the `answer` field via `PATCH /jobs/api/interview-qa/{qa_id}` using the candidate profile (`candidate_profile.md`) and application research. Source-trace rule applies: every claim in an answer must trace to a source bullet in `candidate_profile.md` or a company research row.
3. Generate role-specific questions (3–5): from `role/day_to_day` and `role/success` research rows, extract questions a thoughtful interviewer would ask about this specific role. Write via `POST /jobs/api/applications/{id}/interview-qa` with `question_type: "role_specific"` and `sort_order: 700+`.
4. Generate company-specific questions (3–5): from `culture` research, `intel` research, and the job posting, extract questions about the company's situation, priorities, or challenges. Write via `POST /jobs/api/applications/{id}/interview-qa` with `question_type: "company_specific"` and `sort_order: 750+`.

### Resume file management

When a tailored resume has been generated and saved as a file:

1. Place it at `data/resumes/applications/{app_id}/{label}-{YYYY-MM-DD}.docx` (relative to vault root).
2. Register it: `POST /jobs/api/applications/{id}/resumes` with `file_path`, `variant` (`hybrid`, `management`, `tailored`, or `other`), and `label`.

Base templates live at `data/resumes/base/` and are registered with `application_id = NULL`. Use `GET /jobs/api/resumes/base` to list them; use `GET /jobs/api/resumes/{id}/download` for a download link.

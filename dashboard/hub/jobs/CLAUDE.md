# CLAUDE.md — dashboard/hub/jobs/ (job-search 3-stage pipeline)

Router for the jobs module. For cross-module dashboard rules (wiki-implementation sync, naming), see `dashboard/CLAUDE.md`. When working in `dashboard/hub/jobs/`, load this file plus the scoped file for the stage you're working in.

This module lives under the Hub dashboard (port 5002). It was relocated 2026-05-25 from `dashboard/jobs/`; the legacy port-5001 mount has been removed.

## Stage routing

Each stage's rules live in a separate file. Load the file for the stage you're executing:

| Stage | File | Skill | Trigger |
|---|---|---|---|
| Stage 1: Batch intake | `stage1.md` | `/job-intake` | Sam pastes job listings |
| Stage 2: Research sweep | `stage2.md` | `/job-research` | "research [company / role / all]", auto-chained from `/job` |
| Stage 3: Application prep | `stage3.md` | *(none)* | "tailor resume for [company]", "prep for [company]" |

Invoke `/job` to run Stage 1 then Stage 2 in one turn. Invoke `/job-intake` or `/job-research` directly to run a single stage.

For per-ATS URL resolution and JD-fetch detail (Ashby, Greenhouse, Lever, gem.com, iCIMS, Breezy, Workday, LinkedIn fallback, WebSearch fallback), see `ats-reference.md` — read on demand when a URL or JD fetch is failing.

## Overview

Three distinct stages with defined triggers and field-fill obligations. Never skip ahead — a listing should only reach Stage 2 after surviving Stage 1 triage, and Stage 3 only when actively preparing to apply.

Claude Code is the intake processor — there is **no Anthropic API key** and no server-side AI. All AI-powered features run in an active Claude Code session only.

## Candidate profile

Lives at `dashboard/hub/jobs/candidate_profile.md`. Read it at the start of every intake batch and every Stage 3 prep session. If it's missing or incomplete, surface that before processing.

- **Cover letter PDFs** live in the `resumes` table with `variant = 'cover-letter'`. `db.list_app_resumes()` excludes them (the submitter uploads its first row as the resume); `db.get_cover_pdf()` returns the newest one, and the focus pane renders it in the cover letter box. The submitter uploads it into any file field whose name or label says "cover" (an optional cover slot with no letter is left empty), and waits for each file name to show on the page before submitting.

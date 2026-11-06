# dashboard/hub/jobs/ats-reference.md — per-ATS URL resolution and JD-fetch reference

Reference for the Stage 1 URL-resolution and JD-fetch rules in `dashboard/hub/jobs/CLAUDE.md`. Loaded **on demand** — only when a listing URL is missing or broken, or when a Playwright fetch is failing on a specific ATS. Not auto-loaded into context the way `CLAUDE.md` files are.

The goal: reach the specific listing URL on the company's own ATS — not an aggregator, not a board root.

**Starting point (always):** Try the company's own careers page first. Most companies surface links directly to the specific ATS listing — and the careers page is plain HTML, not a SPA. Search: `"<Company>" careers OR jobs site:<company>.com`

---

## Ashby

- **URL pattern:** `https://jobs.ashbyhq.com/<company-slug>/<job-uuid>`
- **Finding the URL:** Search `"<Company>" "<Role>" site:jobs.ashbyhq.com` — company slug is usually the company name, camel-case or lowercased. Each listing has a UUID.
- **Playwright:** Works reliably with `waitUntil: 'networkidle'`. Full JD renders including requirements.
- **Closed listing signal:** Playwright returns explicit "Job not found" / "This position is no longer available" text — distinct from blank page. Blank WebFetch is identical for open and closed; Playwright is not.
- **Example:** Campus → `jobs.ashbyhq.com/Campus/53bbe1eb-3140-4ca4-8997-ce3dd80a1896`

---

## Greenhouse

- **URL pattern:** `https://job-boards.greenhouse.io/<company-slug>/jobs/<numeric-id>`
- **Finding the URL:**
  1. Search `"<Company>" "<Role>" site:job-boards.greenhouse.io` — often surfaces direct listing URL.
  2. Or render the company's Greenhouse board with Playwright (`job-boards.greenhouse.io/<slug>`), then use `page.selectOption('select', {label:'<Department>'})` to filter by department, then click Submit to load listings. Get links from the rendered result.
- **Playwright:** Works for most Greenhouse boards. Some boards return "Uh oh, something went wrong..." for the company — if that happens, the board is broken or the company no longer uses it. Try the company site instead.
- **Department filter approach (confirmed working):**
  ```bash
  PWMOD=/home/demo/.npm-global/lib/node_modules/@playwright/cli/node_modules/playwright
  node -e "const {chromium}=require('$PWMOD');(async()=>{
    const b=await chromium.launch({headless:true,executablePath:'/usr/bin/google-chrome'});
    const p=await b.newPage();
    await p.goto('https://job-boards.greenhouse.io/<slug>',{waitUntil:'networkidle',timeout:30000});
    await p.selectOption('select',{label:'<Department Name>'});
    await p.click('[type=submit]');
    await p.waitForTimeout(3000);
    console.log(await p.innerText('body'));
    await b.close();
  })().catch(e=>{console.error(e.message);process.exit(1)});" 2>&1
  ```
- **Example:** Guidepoint → `job-boards.greenhouse.io/guidepoint/jobs/8536171002` (found via Insights dept filter)

---

## Lever

- **URL pattern:** `https://jobs.lever.co/<company-slug>/<uuid>`
- **Finding the URL:** Search `"<Company>" "<Role>" site:jobs.lever.co`
- **Playwright:** Works reliably with `waitUntil: 'networkidle'`. Full JD renders.

---

## gem.com (GEM ATS)

- **URL pattern:** `https://jobs.gem.com/<company-slug>/<base64-encoded-id>`
- **Finding the URL:** Company careers page → job listing → links to gem.com URL. Not searchable via `site:jobs.gem.com` — results are gated.
- **Playwright: fails** — gem.com is heavily JavaScript-rendered. Playwright fetches the page but `innerText('body')` returns empty or near-empty content. No JD text is surfaced.
- **Workaround:**
  1. Check if the company has a separate Greenhouse/Lever board (some companies dual-post). Search `site:job-boards.greenhouse.io/<slug>` or `site:jobs.lever.co/<slug>`.
  2. WebFetch the company's careers page directly — some surface the JD text in standard HTML alongside the gem.com apply link.
  3. If neither works: hold the listing, ask user to paste the JD.
- **Example:** Imagen Technologies → `jobs.gem.com/imagen-technologies/am9icG9zdDqHCtN4y58_4LBc3TZ8HfE6` — Playwright returns no content; Greenhouse board (`job-boards.greenhouse.io/imagentechnologies`) returns error page.

---

## iCIMS

- **URL pattern:** `https://careers.<company>.com/job/<id>/<slug>/` or `https://<company>.icims.com/jobs/<id>/...`
- **Finding the URL:** Company careers page → search by job title or ID.
- **Playwright: blocked by Cloudflare Turnstile.** iCIMS portals protected by Cloudflare bot challenge. The page returns HTTP 200 and loads the job title list, but the specific JD content is never served to headless browsers. Longer waits and `domcontentloaded` do not help — the Turnstile challenge runs before any JD content is injected.
- **What you get instead:** The page shell loads with an autocomplete dropdown showing all open job titles (confirming the listing exists), but clicking or navigating to the specific listing returns no body content.
- **Workaround:**
  1. Search aggregators for a cached copy: `"<Company>" "<Role>" site:linkedin.com OR site:indeed.com` — if the listing was syndicated, snippets may contain requirements.
  2. Search by iCIMS job code (extracted from WebFetch page source — look for `BUSIN` or similar codes in the HTML): `"<job code>" site:<company>.com`
  3. If all fail: flag in `red_flags` that the portal requires Cloudflare bypass, and tell the user to open the URL in a real browser. Do not add the listing without JD.
- **Example:** NFP → `careers.nfp.com/job/23315646/benefits-operations-associate-new-york-ny/` — Cloudflare Turnstile confirmed blocking. Job code: `BUSIN015226_2`.

---

## Breezy

- **URL pattern:** `https://<company>.breezy.hr/p/<slug>`
- **Finding the URL:** Search `"<Company>" site:breezy.hr`
- **Playwright:** Works. Full JD renders with `waitUntil: 'networkidle'`.
- **Closed listing signal:** Breezy returns a 404 or "Position closed" page when the listing is removed. Playwright confirms this cleanly.
- **Example:** Personified → `personified-tech.breezy.hr` (listing was removed — confirmed via Playwright returning closed-listing page)

---

## Workday

- **URL pattern:** `https://<company>.wd<N>.myworkdayjobs.com/en-US/<board>/job/<title>/<id>`
- **Playwright:** Works on most Workday implementations. Use `waitUntil: 'networkidle'` and a 5-second extra wait — Workday is slow to render.
- **Finding the URL:** Company careers page almost always links to their Workday board. Search `"<Company>" site:myworkdayjobs.com`.

---

## LinkedIn (aggregator — fallback only, never primary)

- LinkedIn job listing URLs expire after 2–3 months. The listing redirects to LinkedIn login or "this job is no longer available" once the employer removes it.
- Use **only** as a last resort when no direct ATS URL is findable.
- Always add `red_flags: "Job URL is LinkedIn company page — verify listing is still active on company site before applying."` with `red_flags_risk: "low"`.
- Never use the LinkedIn company `/jobs` page as the URL — that's the company's job board root, not a specific listing.

---

## WebSearch aggregator fallback (for iCIMS / gem.com / closed portals)

When Playwright and company site fail, search these in order:

1. `"<Company>" "<Role title>" site:linkedin.com` — LinkedIn job view pages often appear in search and show requirements snippets
2. `"<Company>" "<Role title>" site:indeed.com` — Indeed caches many listings even after expiry
3. `"<Company>" "<Role title>" requirements experience qualifications` — unfiltered search, may surface BuiltIn, Glassdoor job pages, or company press with requirement details
4. Job code search: if the page source revealed an internal code (e.g. iCIMS `BUSIN015226_2`), search that code directly

Requirements snippets in search results are sufficient to extract key qualifiers (years, pedigree, hard skills) even when the full JD page is unreachable.

---

## Per-company URL resolution notes (current tracker)

| Company | ATS | Direct URL | Notes |
|---|---|---|---|
| Imagen Technologies | gem.com | `jobs.gem.com/imagen-technologies/am9icG9zdDqHCtN4y58_4LBc3TZ8HfE6` | gem.com Playwright returns blank. Greenhouse board errors. JD confirmed via user paste. |
| Guidepoint | Greenhouse | `job-boards.greenhouse.io/guidepoint/jobs/8536171002` | Found via Playwright on board with Insights dept filter + Submit. |
| Campus | Ashby | `jobs.ashbyhq.com/Campus/53bbe1eb-3140-4ca4-8997-ce3dd80a1896` | Full JD via Playwright. Role is domain-disqualifying (higher ed required). |
| NFP | iCIMS | `careers.nfp.com/job/23315646/benefits-operations-associate-new-york-ny/` | Cloudflare Turnstile blocks Playwright. Job code BUSIN015226_2. Open in real browser. |
| Ned | Direct | `nedhelps.com` | Early-stage startup. JD confirmed via user paste. |
| Clipboard Health | Check site | — | Check `clipboardhealth.com/careers` — likely Greenhouse or Lever. |
| Verse Medical | Check site | — | Check `versemedical.com/careers` — small startup, may be Lever or Ashby. |

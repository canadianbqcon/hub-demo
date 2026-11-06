/* Jobs · 2 of 5 (React): the intake, research and application surface bodies. Ported from
   jobs-surfaces.js lines 1-540. Assigns into window.JobsUI and declares nothing at top level.
   renderIntake / renderResearch / renderApplication keep their plain names: each is the "draw this
   job again" call the shell makes when the open job or the active tab changes, and here it bumps an
   epoch (or takes a snapshot) that the component below draws from. */
(() => {
  const { useState, useEffect, useLayoutEffect, useRef } = React;
  const U = window.JobsUI;
  const S = U.S;
  const { ExTa, Card, InlineEdit, surfaceCls, linesOf } = U;


  // ── intake surface ─────────────────────────────────────────────────────────────

  function renderIntake() {
    if (!S.current) return;
    S.ep.intake += 1;
    S.snap.intakeResearch = researchByCatSub();
    U.bump();
  }

  // the autosave listener the plain page bound to each box: read the text when the timer fires
  function autosave(field, ms) {
    return (read) => U.debounce(`patch:${field}`, () => U.patchApp({ [field]: read() }), ms);
  }

  // Strip text that's redundant in the snapshot because it's already shown elsewhere on the card:
  // the company name and the role title (and the role's significant words). The role/company are in
  // the header and the "role" snap cell, so repeating them in a research preview is noise.
  function stripRedundant(s, app) {
    let t = s;
    const kill = [];
    if (app) {
      if (app.company) kill.push(app.company);
      if (app.role) {
        kill.push(app.role);
        (app.role).split(/[\s,/&–-]+/).forEach((w) => { if (w.length > 3) kill.push(w); });
      }
    }
    for (const k of kill) {
      const esc = k.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      if (esc) t = t.replace(new RegExp(`\\b${esc}\\b`, "gi"), "");
    }
    t = t.replace(/\s+/g, " ").trim();
    // drop a dangling leading connective left behind by the strip (e.g. "at  is an entry-level…")
    t = t.replace(/^(?:[\s,;:.·|–—-]*\b(?:at|is|are|a|an|the|this|that|role|position|job|like|for|in|with|of|as)\b)+[\s,]*/i, "");
    t = t.replace(/^[\s,;:.·|–—-]+/, "").trim();
    return t || s.replace(/\s+/g, " ").trim();   // never strip down to nothing
  }

  // Display-only de-word-salad for the intake snapshot. There's no runtime Anthropic key in this
  // module, so this is a heuristic, not a real summary: strip redundant naming, then take the first
  // whole sentence if substantial, else cap at a word boundary. True summaries would be written at
  // Stage-2 research time (Claude Code) into the research content itself.
  function previewText(s, app) {
    const t = stripRedundant((s || "").replace(/\s+/g, " ").trim(), app);
    if (!t) return "";
    const m = t.match(/^.*?[.!?](\s|$)/);
    if (m && m[0].trim().length >= 20 && m[0].trim().length <= 160) return m[0].trim();
    if (t.length <= 110) return t;
    const cut = t.slice(0, 110);
    const sp = cut.lastIndexOf(" ");
    return `${(sp > 40 ? cut.slice(0, sp) : cut).trim()}…`;
  }

  function IntakeResearch() {
    const map = S.snap.intakeResearch;
    if (!S.current || !map) return null;
    const out = [];
    let first = true;
    for (const cat of U.RESEARCH_CATEGORIES) {
      const intakeSubs = cat.subs.filter((s) => s.intake);
      if (!intakeSubs.length) continue;
      if (!first) out.push(<div className="intake-research-snap-sep" key={`sep-${cat.key}`}></div>);
      first = false;
      for (const sub of intakeSubs) {
        const entry = map[`${cat.key}::${sub.key}`];
        const content = (entry?.content?.trim()) || "";
        out.push(
          <div className="intake-research-snap-row" key={`${cat.key}-${sub.key}`}>
            <span className="intake-research-snap-label">{sub.label}</span>
            {content
              ? <span className="intake-research-snap-val">{previewText(content, S.current)}</span>
              : <span className="intake-research-snap-empty">—</span>}
          </div>
        );
      }
    }
    return <div className="intake-research-snap">{out}</div>;
  }

  // what a snap cell shows for the open job ("—" with none open)
  function cellText(field) {
    const a = S.current;
    if (!a) return "—";
    if (field === "salary") return U.formatSalary(a);
    if (field === "listing_age") return U.listingAge(a.listing_posted_date);
    if (field === "arrangement_location") return `${a.work_arrangement || "—"} | ${a.location || "—"}`;
    if (field.indexOf("culture_") === 0) { const v = a[field]; return v == null ? "—" : String(v); }
    let raw = a[field];
    if (raw === 0) raw = 0;   // normalize negative zero → "0" so it never renders as "-0"
    const display = raw == null ? "" : raw;
    return display === "" ? "—" : String(display);
  }

  // one editable cell of the snapshot: click, Enter or Space opens a one-line editor, blur saves
  function SnapCell({ field, cls }) {
    const [editing, setEditing] = useState(false);
    const a = S.current;
    function open() { if (!S.current || editing) return; setEditing(true); }
    let type = "text", init = "", placeholder;
    if (editing) {
      if (field === "salary") {
        init = `${a.salary_min || ""},${a.salary_max || ""}`;
        placeholder = "min,max in dollars";
      } else if (field === "arrangement_location") {
        init = a.work_arrangement == null ? "" : a.work_arrangement;
        placeholder = "e.g. remote, hybrid, on-site";
      } else if (field === "listing_age") {
        // the cell shows a computed age, but edits the underlying posted date
        type = "date";
        init = a.listing_posted_date || "";
      } else {
        init = a[field] == null ? "" : a[field];
        if (field === "years_required") type = "number";
      }
    }
    function save(value) {
      let patch = {};
      if (field === "salary") {
        const parts = value.split(",").map((s) => s.trim());
        patch = { salary_min: parts[0] ? +parts[0] : null, salary_max: parts[1] ? +parts[1] : null };
      } else if (field === "arrangement_location") {
        patch = { work_arrangement: value };
      } else if (field === "listing_age") {
        patch = { listing_posted_date: value || null };
      } else {
        let val = value;
        if (type === "number") val = val === "" ? null : +val;
        patch = { [field]: val };
      }
      return U.patchApp(patch).then(() => { setEditing(false); renderIntake(); });
    }
    return (
      <span className={cls} data-field={field} role="button" tabIndex={0} onClick={open}
            onKeyDown={(e) => {
              if (e.target !== e.currentTarget) return;
              if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
            }}>
        {editing
          ? <InlineEdit type={type} init={String(init)} placeholder={placeholder} label={field.replace(/_/g, " ")} onSave={save} />
          : cellText(field)}
      </span>
    );
  }

  const SNAP_ROWS = [
    ["role", "role"], ["years required", "years_required"], ["salary band", "salary"],
    ["arrangement", "arrangement_location"], ["employment", "employment_type"],
    ["listing age", "listing_age"], ["source", "source"],
  ];
  const CULTURE_STATS = [
    ["culture_rating", "overall", "/ 5 · glassdoor"],
    ["culture_recommend", "recommend", "to a friend %"],
    ["culture_work_life", "work-life", "/ 5"],
  ];

  // The requirements / nice-to-have box: its text reads as a clean list until the list is clicked,
  // which hides it and opens the textarea; blur draws the list again from what was typed.
  function ReqBlock({ listId, taId, field, label, placeholder, epoch }) {
    const a = S.current;
    const [text, setText] = useState(a ? (a[field] || "") : "");
    const textRef = useRef(text);
    const [listOn, setListOn] = useState(false);
    const [lines, setLines] = useState([]);
    const ta = useRef(null);
    function drawList(v) {
      const ls = linesOf(v);
      setLines(ls);
      setListOn(ls.length > 0);
    }
    const first = useRef(true);
    useLayoutEffect(() => {
      if (first.current) { first.current = false; return; }
      const v = S.current ? (S.current[field] || "") : "";
      textRef.current = v;
      setText(v);
      if (document.activeElement !== ta.current) drawList(v);   // never redraw under the caret
    }, [epoch]);
    useLayoutEffect(() => {
      if (ta.current) { ta.current.style.height = "auto"; ta.current.style.height = `${ta.current.scrollHeight}px`; }
    }, [text]);
    return (
      <React.Fragment>
        <div className="req-list-display" id={listId} style={{ display: listOn ? "" : "none" }}
             onClick={() => {
               ReactDOM.flushSync(() => setListOn(false));
               ta.current.focus();
             }}>
          {lines.map((line, i) => <div className="req-list-item" key={i}>{line}</div>)}
        </div>
        <textarea ref={ta} className={`field-textarea${listOn ? " req-list-collapsed" : ""}`} id={taId}
                  placeholder={placeholder} aria-label={label} data-reqlist="1" value={text}
                  onChange={(e) => {
                    textRef.current = e.target.value;
                    setText(e.target.value);
                    autosave(field, 400)(() => textRef.current);
                  }}
                  onBlur={() => { if (S.current) drawList(textRef.current); }} />
      </React.Fragment>
    );
  }

  function RiskToggle({ epoch }) {
    const [risk, setRisk] = useState(S.current ? S.current.red_flags_risk : undefined);
    const first = useRef(true);
    useLayoutEffect(() => {
      if (first.current) { first.current = false; return; }
      setRisk(S.current ? S.current.red_flags_risk : undefined);
    }, [epoch]);
    return (
      <div className="risk-toggle" id="redFlagsRisk">
        {["low", "medium", "high"].map((r) => (
          <button type="button" className={`risk-btn ${r}${risk === r ? " active" : ""}`} data-risk={r} key={r}
                  onClick={() => { setRisk(r); U.patchApp({ red_flags_risk: r }); }}>{r}</button>
        ))}
      </div>
    );
  }

  function IntakeSurface() {
    const a = S.current;
    const ep = S.ep.intake;
    const val = (f) => (a ? a[f] : "");
    return (
      <div className={surfaceCls("intake")} data-surface-body="intake">

        <Card title="the company & the role">
          <div className="rundown-block">
            <div>
              <div className="questions-subhead">
                <span className="questions-subhead-l">company</span>
              </div>
              <ExTa id="intakeCompanySummary" surface="intake" style={{ marginTop: "8px" }} value={val("company_summary")} epoch={ep}
                    placeholder="what is this company? what do they make or sell?" label="company summary"
                    onInput={autosave("company_summary", 400)} />
            </div>
            <div>
              <div className="questions-subhead">
                <span className="questions-subhead-l">role</span>
              </div>
              <ExTa id="intakeRoleSummary" surface="intake" style={{ marginTop: "8px" }} value={val("role_summary")} epoch={ep}
                    placeholder="what would you do in this role? what does it provide the company?" label="role summary"
                    onInput={autosave("role_summary", 400)} />
            </div>
          </div>
        </Card>

        <Card title="decide — keep or cut">
          <div className="intake-snapshot" id="intakeSnapshot">

            <div className="snap-card">
              {SNAP_ROWS.map(([label, field]) => (
                <div className="snap-row" key={field}>
                  <span className="snap-l">{label}</span>
                  <SnapCell field={field} cls="snap-v editable" />
                </div>
              ))}
            </div>

            <div className="snap-col">
              <div className="score-hero">
                <span className="score-hero-l">priority score</span>
                <span className="score-hero-num empty" id="intakeScoreNum"
                      onInput={(e) => {
                        const v = e.target.value;
                        U.debounce("scoreRole", () => U.patchApp({ score_role: +v || 0 }).then(() => U.renderRailScore()), 400);
                      }}>{a ? (a.score_role || 0) : "—"}</span>
                <span className="score-hero-meta" id="intakeScoreMeta">role fit · 0 to 10 · 8+ strong</span>
              </div>
              <div className="culture-stats-row">
                {CULTURE_STATS.map(([field, label, meta]) => (
                  <div className="culture-stat hub-stat" key={field}>
                    <SnapCell field={field} cls="culture-stat-v hub-stat-v empty editable" />
                    <span className="culture-stat-l">{label}</span>
                    <span className="culture-stat-meta">{meta}</span>
                  </div>
                ))}
              </div>
            </div>

            <Card style={{ gap: "var(--s-2)" }} title="requirements">
              <ReqBlock listId="intakeRequirementsList" taId="intakeRequirements" field="requirements" epoch={ep}
                        label="requirements" placeholder="one requirement per line — pasted from the jd" />
            </Card>

            <Card style={{ gap: "var(--s-2)" }} title="nice to have">
              <ReqBlock listId="intakeNiceToHavesList" taId="intakeNiceToHaves" field="nice_to_haves" epoch={ep}
                        label="nice to have" placeholder="one nice-to-have per line" />
            </Card>

            <div className="red-flag-block empty intake-full" id="redFlagBlock">
              <div className="red-flag-head">
                <span className="red-flag-l">red flags</span>
                <RiskToggle epoch={ep} />
              </div>
              <ExTa id="intakeRedFlags" surface="intake" value={val("red_flags")} epoch={ep}
                    placeholder="anything that gives you pause · vague jd, no salary, suspicious recruiter, signs of churn…"
                    label="red flags" onInput={autosave("red_flags", 400)} />
            </div>

            {/* misc notes. Small leftovers only: anything substantial belongs in requirements, red
                flags, or the rundown summaries above. */}
            <Card cls="intake-full" style={{ gap: "var(--s-2)" }} title="notes">
              <ExTa id="intakeNotes" surface="intake" value={val("notes")} epoch={ep}
                    placeholder="anything with nowhere else to live · referral name, a recruiter's aside, an odd application step"
                    label="notes" onInput={autosave("notes", 400)} />
            </Card>

          </div>
        </Card>

        <div className="section hub-plate-card">
          <div className="section-head hub-section-head">
            <span className="section-title hub-section-head-t">Research Snapshot</span>
          </div>
          <div id="intakeResearchBlocks"><IntakeResearch /></div>
        </div>

        <div className="section hub-plate-card">
          <div className="section-head hub-section-head">
            <span className="section-title hub-section-head-t">Decision</span>
          </div>
          <div className="hub-btn-row">
            <button type="button" className="hub-btn hub-btn--lg btn-primary" id="btnKeepResearch"
                    onClick={() => U.patchApp({ status: "researching" }).then(() => U.switchSurface("research", false))}>→ keep · move to research</button>
            <button type="button" className="hub-btn hub-btn--lg" id="btnFlagReview"
                    onClick={() => U.patchApp({ priority: "high" }).then(() => U.toast("flagged for review"))}>flag for review</button>
            <button type="button" className="hub-btn hub-btn--lg btn-alert" id="btnCutIgnore"
                    onClick={() => {
                      if (!confirm("cut this application?")) return;
                      return U.patchApp({ status: "ignored", closed_date: U.todayIso(), closed_reason: "no_reason_given" })
                        .then(() => U.switchSurface("closed", false));
                    }}>cut · ignore</button>
          </div>
        </div>
      </div>
    );
  }

  // ── research surface ───────────────────────────────────────────────────────────

  function researchByCatSub() {
    const map = {};
    for (const r of ((S.current?.research) || [])) {
      if (r.category === "prep") continue;
      const k = `${r.category}::${r.subcategory || ""}`;
      map[k] = r;
    }
    return map;
  }

  function renderResearch() {
    S.snap.research = researchByCatSub();
    S.ep.research += 1;
    U.bump();
  }

  function saveResearchBlock(category, subcategory, content, id) {
    if (!S.current) return Promise.resolve();
    let p;
    if (id) {
      p = U.apiPatch(`/jobs/api/applications/${S.current.id}/research/${id}`, { content }).then((updated) => {
        if (updated) {
          const i = S.current.research.findIndex((r) => r.id === id);
          if (i >= 0) S.current.research[i] = updated;
        }
      });
    } else if (content.trim()) {
      p = U.apiPost(`/jobs/api/applications/${S.current.id}/research`, { category, subcategory, content }).then((created) => {
        if (created) {
          S.current.research = S.current.research || [];
          S.current.research.push(created);
          renderResearch();  // re-render so subsequent edits use the new id
        }
      });
    } else {
      p = Promise.resolve();
    }
    return p.then(() => {
      U.bump();  // the category status pills draw from the record, so this is refreshResearchHead
      const gid = S.current.id;
      U.loadGlossary(gid).then((g) => { if (S.current && S.current.id === gid) { S.glossary = g; U.bump(); } });
    });
  }

  function ResearchSurface() {
    const a = S.current;
    const snap = S.snap.research || {};
    const live = researchByCatSub();
    return (
      <div className={surfaceCls("research")} data-surface-body="research">

        <div className="section hub-plate-card">
          <div className="section-head hub-section-head">
            <span className="section-title hub-section-head-t">Research — Context</span>
          </div>
          <p style={{ fontStyle: "italic", color: "var(--fg-dim)", fontSize: "var(--fs-subhead)", lineHeight: "1.5" }}>deeper context for being a better applicant — values, hiring patterns, financials, culture, locations, intel. jd info itself lives in intake.</p>
        </div>

        <div id="researchCategories" key={S.ep.research}>
          {a && U.RESEARCH_CATEGORIES.map((cat) => {
            const filled = cat.subs.filter((s) => (live[`${cat.key}::${s.key}`]?.content || "").trim()).length;
            const total = cat.subs.length;
            const status = filled === 0 ? "empty" : filled === total ? "complete" : "partial";
            return (
              <div className="research-category" key={cat.key}>
                <div className="research-cat-head">
                  <div className="research-cat-title">{cat.label}</div>
                  <div className={`research-cat-status ${status}`}>{`${filled}/${total}`}</div>
                </div>
                <div className="research-blocks">
                  {cat.subs.map((sub) => {
                    const existing = snap[`${cat.key}::${sub.key}`];
                    return (
                      <div className="research-block" key={sub.key}>
                        <div className="research-block-label">{sub.label}</div>
                        <ExTa direct dynamic surface="research" value={existing ? existing.content : ""}
                              placeholder={`notes on ${sub.label}…`} label={sub.label}
                              onInput={(read) => U.debounce(`research:${cat.key}:${sub.key}`,
                                () => saveResearchBlock(cat.key, sub.key, read(), existing?.id), 400)} />
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        <div className="section" style={{ paddingTop: "var(--s-3)" }}>
          <div className="hub-btn-row">
            <button type="button" className="hub-btn hub-btn--lg btn-primary" id="btnMoveToApplication"
                    onClick={() => U.patchApp({ status: "applying" }).then(() => U.switchSurface("application", false))}>→ move to application</button>
          </div>
        </div>
      </div>
    );
  }

  // ── application surface ────────────────────────────────────────────────────────

  function loadPositionToggles() {
    if (!S.current) return Promise.resolve();
    const row = (S.current.resume_notes || []).find((n) => n.section === "position_state");
    if (!row) { S.positionToggles = {}; return Promise.resolve(); }
    try { S.positionToggles = JSON.parse(row.note || "{}") || {}; }
    catch { S.positionToggles = {}; }
    return Promise.resolve();
  }

  // pdf.js draws into a div React leaves empty (no React children), page by page
  function renderPdf(url, pagesEl, emptyEl, live, scale = 1.5) {
    pagesEl.innerHTML = "";
    pagesEl.classList.remove("loaded");
    if (emptyEl) emptyEl.style.display = "";
    if (!url) return;
    Promise.resolve().then(() => pdfjsLib.getDocument(url).promise).then((pdf) => {
      let chain = Promise.resolve();
      const draw = (i) => pdf.getPage(i).then((page) => {
        if (!live.on) return;
        const viewport = page.getViewport({ scale });
        const canvas = document.createElement("canvas");
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.style.width = "100%";
        // a mark over this page records these in its elements, so /marks can find the file and page
        canvas.dataset.pdf = url;
        canvas.dataset.page = String(i);
        pagesEl.appendChild(canvas);
        return page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
      });
      for (let i = 1; i <= pdf.numPages; i++) chain = chain.then(() => draw(i));
      return chain.then(() => {
        if (!live.on) return;
        pagesEl.classList.add("loaded");
        if (emptyEl) emptyEl.style.display = "none";
      });
    }).catch((e) => { console.error("pdf render failed", e); });
  }

  function revealResume(id) {
    return U.apiPost(`/jobs/api/resumes/${id}/reveal`).then((res) => {
      if (res?.revealed) U.toast("opened in file explorer");
    }, () => {
      // api() already toasted the failure
    });
  }

  // the plain renderApplication: draw both viewers, the reveal button and the sent record again
  function renderApplication() {
    if (!S.current) return;
    const latest = (S.current.resumes || [])[0];
    const cover = S.current.cover_pdf;
    S.snap.app = {
      latest: latest || null,
      url: latest ? `/jobs/api/resumes/${latest.id}/view` : null,
      coverUrl: cover ? `/jobs/api/resumes/${cover.id}/view` : null,
      sent: S.current.sent_answers || [],
    };
    S.ep.application += 1;
    U.bump();
  }

  // full size: the pages drawn by renderPdf on a glass sheet over the Hub, so there is no
  // browser viewer chrome or thumbnail rail (mark 2026-11-03-180641:1, sent back)
  function openFull(url) {
    const d = document.createElement("dialog");
    d.className = "pdf-full";
    const x = document.createElement("button");
    x.type = "button"; x.className = "hub-btn pdf-full-x"; x.title = "close"; x.setAttribute("aria-label", "close");
    x.innerHTML = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
    x.onclick = () => d.close();
    const pages = document.createElement("div");
    pages.className = "pdf-full-pages sb-host";
    d.append(x, pages);
    const live = { on: true };
    d.addEventListener("close", () => { live.on = false; d.remove(); }); // Esc closes a modal dialog natively
    // a click on the dimmed page around the sheet lands on the dialog itself
    d.addEventListener("click", (e) => { if (e.target === d) d.close(); });
    document.body.appendChild(d);
    d.showModal();
    renderPdf(url, pages, null, live, 2.5);
  }

  // floats over the page by default; `head` puts it in a card's header row instead
  function FullBtn({ url, head }) {
    if (!url) return null;
    return <button type="button" className={`hub-btn sm ${head ? "pdf-head-btn" : "pdf-full-btn"}`} title="read full size" aria-label="read full size" onClick={() => openFull(url)}>
      <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" />
      </svg>
    </button>;
  }

  function PdfViewer({ viewerId, emptyId, pagesId, url, epoch, emptyLabel, headBtn }) {
    const pages = useRef(null);
    const empty = useRef(null);
    useEffect(() => {
      const live = { on: true };
      if (S.snap.app) renderPdf(url, pages.current, empty.current, live);
      return () => { live.on = false; };
    }, [epoch]);
    return (
      <div className="pdf-viewer" id={viewerId}>
        <div className="pdf-empty" id={emptyId} ref={empty}>
          <div className="pdf-empty-doc"></div>
          <div className="pdf-empty-label">{emptyLabel}</div>
          <div className="pdf-empty-sub">tell claude code which file to link</div>
        </div>
        <div className="pdf-pages" id={pagesId} ref={pages}></div>
        {headBtn ? null : <FullBtn url={url} />}
      </div>
    );
  }

  // the frozen record of what actually went: plain question/answer rows, no
  // draft, no edited tag (he only wants the final answer, not its history)
  function SentAnswers({ rows }) {
    const sentAt = ((rows[0]?.sent_at) || "").slice(0, 10);
    const copyAll = () => rows.map((r) => `${r.question}\n${r.answer || ""}`).join("\n\n");
    return (
      <div className="section hub-plate-card" id="rtsSentSection">
        <div className="section-head hub-section-head">
          <span className="section-title hub-section-head-t">What I Sent</span>
          {sentAt ? <span className="rts-sent-date">{sentAt}</span> : null}
        </div>
        <div className="rts-qa-list">
          {rows.map((r, i) => (
            <div className="rts-qa" key={i}>
              <div className="rts-q">{r.question}</div>
              <div className={`rts-a${r.answer ? "" : " is-muted"}`}>{r.answer || "left blank"}</div>
            </div>
          ))}
        </div>
        <div className="hub-btn-row">
          <button type="button" className="hub-btn"
                  onClick={() => navigator.clipboard.writeText(copyAll()).then(() => U.toast("answers copied"))}>copy all</button>
        </div>
      </div>
    );
  }

  function ApplicationSurface() {
    const snap = S.snap.app;
    const ep = S.ep.application;
    return (
      <div className={surfaceCls("application")} data-surface-body="application">

        <div className="section hub-plate-card">
          <div className="section-head hub-section-head">
            <span className="section-title hub-section-head-t">Resume</span>
            <span className="pdf-head-tools">
              {snap?.latest ? (
                <button className="hub-btn sm pdf-head-btn" id="resumeRevealBtn" type="button" title="open in folder"
                        aria-label="open in folder" onClick={() => revealResume(snap.latest.id)}>
                  <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true">
                    <path d="M1.5 3.5h4.5l1.5 1.5h7v7.5h-13z" />
                  </svg>
                </button>
              ) : null}
              <U.DocMarkBtn a={S.current} url={snap ? snap.url : null} label="resume" head />
              <FullBtn url={snap ? snap.url : null} head />
            </span>
          </div>
          <PdfViewer viewerId="resumeViewer" emptyId="resumeEmpty" pagesId="resumePages"
                     url={snap ? snap.url : null} epoch={ep} emptyLabel="add resume" headBtn />
        </div>

        {/* no cover letter on this application: no card at all (mark 2026-11-03-181041:4) */}
        {snap?.coverUrl ? (
          <div className="section hub-plate-card">
            <div className="section-head hub-section-head">
              <span className="section-title hub-section-head-t">Cover Letter</span>
              <span className="pdf-head-tools"><U.DocMarkBtn a={S.current} url={snap.coverUrl} label="cover letter" head /><FullBtn url={snap.coverUrl} head /></span>
            </div>
            <PdfViewer viewerId="coverViewer" emptyId="coverEmpty" pagesId="coverPages"
                       url={snap.coverUrl} epoch={ep} emptyLabel="add cover letter" headBtn />
          </div>
        ) : null}

        {S.current?.form?.length ? (
          <div className="section hub-plate-card">
            <div className="section-head hub-section-head">
              <span className="section-title hub-section-head-t">Application Questions</span>
              <span className="pdf-head-tools">
                <button type="button" className="hub-btn sm pdf-head-btn" title="copy all answers" aria-label="copy all answers"
                        onClick={() => navigator.clipboard.writeText(U.answerLines(S.current)).then(() => U.toast("answers copied"))}>
                  <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true">
                    <rect x="5.5" y="5.5" width="8" height="8.5" rx="1.5" /><path d="M10.5 5.5V3.5a1.5 1.5 0 0 0-1.5-1.5H4A1.5 1.5 0 0 0 2.5 3.5v6A1.5 1.5 0 0 0 4 11h1.5" />
                  </svg>
                </button>
              </span>
            </div>
            <div className="rts-qa-list"><U.QaBlock a={S.current} canEdit={!S.current.sent_answers?.length} /></div>
          </div>
        ) : null}

        <div className="section">
          <div className="hub-btn-row">
            <button type="button" className="hub-btn hub-btn--lg btn-primary" id="btnMarkSubmitted"
                    onClick={() => {
                      if (!S.current) return;
                      return U.patchApp({ status: "interviewing", date_applied: U.todayIso() }).then(() => {
                        U.switchSurface("prep", false);
                        U.toast("marked submitted");
                      });
                    }}>→ mark as submitted</button>
          </div>
        </div>

        {snap?.sent.length ? <SentAnswers rows={snap.sent} /> : null}
      </div>
    );
  }

  Object.assign(U, {
    IntakeSurface, ResearchSurface, ApplicationSurface,
    renderIntake, renderResearch, renderApplication, researchByCatSub, saveResearchBlock,
    loadPositionToggles, revealResume, FullBtn,
  });
})();

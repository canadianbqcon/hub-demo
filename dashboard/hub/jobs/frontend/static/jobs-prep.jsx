/* Jobs · 4 of 5 (React): the prep surface, the interview-stage subsystem: pipeline and process
   steps, interviewers, stories, resumes, and the q&a bank. Ported from jobs-prep.js. Assigns into
   window.JobsUI and declares nothing at top level. Each plain renderX() that cleared and rebuilt a
   list keeps its name and now bumps that list's epoch, which is part of the list's React key. */
(() => {
  const { useRef } = React;
  const U = window.JobsUI;
  const S = U.S;
  const { ExTa, Card, surfaceCls } = U;


  // ── data and controllers ───────────────────────────────────────────────────────

  function renderPrep() {
    if (!S.current) return;
    renderPipeline();
    renderActiveStep();
    renderInterviewers();
    renderStories();
    renderResumes();
    renderQa();
    // questions-to-ask textareas (stored as research with category=prep)
    S.ep.prepQ += 1;
    U.bump();
  }

  function prepRow(sub) {
    return ((S.current?.research) || []).find((r) => r.category === "prep" && r.subcategory === sub);
  }

  function savePrepResearch(subcategory, content) {
    if (!S.current) return Promise.resolve();
    const existing = (S.current.research || []).find((r) => r.category === "prep" && r.subcategory === subcategory);
    if (existing) {
      return U.apiPatch(`/jobs/api/applications/${S.current.id}/research/${existing.id}`, { content }).then((u) => {
        if (u) Object.assign(existing, u);
      });
    }
    if (content.trim()) {
      return U.apiPost(`/jobs/api/applications/${S.current.id}/research`, { category: "prep", subcategory, content }).then((c) => {
        if (c) { S.current.research = S.current.research || []; S.current.research.push(c); }
      });
    }
    return Promise.resolve();
  }

  function renderPipeline() {
    S.pipeDrawn = true;
    S.ep.pipe += 1;
    U.bump();
  }

  function activeStep() {
    const steps = (S.current?.process_steps) || [];
    if (S.activeStepId) {
      const found = steps.find((s) => s.id === S.activeStepId);
      if (found) return found;
    }
    return steps.find((s) => s.status !== "complete" && s.status !== "skipped") || steps[0] || null;
  }

  function renderActiveStep() {
    const s = activeStep();
    if (!s) {
      // the notes box of whichever step was drawn last stays, as it did on the plain page
      S.stepView = Object.assign({}, S.stepView, { title: "no active step", meta: "add a step to get started" });
      U.bump();
      return;
    }
    S.activeStepId = s.id;
    S.stepView = { title: s.label || "untitled step", meta: `${s.step_type || "step"} · ${s.status || "pending"}`, step: s };
    S.ep.step += 1;
    U.bump();
  }

  function addProcessStep() {
    if (!S.current) return Promise.resolve();
    const label = prompt("step label (e.g. 'recruiter screen', 'hiring manager round'):", "");
    if (!label) return Promise.resolve();
    const stepType = prompt("step type (phone | interview | take_home | onsite | offer):", "interview") || "interview";
    const order = (S.current.process_steps || []).length;
    return U.apiPost(`/jobs/api/applications/${S.current.id}/process-steps`, {
      label, step_type: stepType, step_order: order, status: "pending",
    }).then((created) => {
      if (created) {
        S.current.process_steps = S.current.process_steps || [];
        S.current.process_steps.push(created);
        S.activeStepId = created.id;
        renderPipeline();
        renderActiveStep();
        U.renderRailPipeline();
      }
    });
  }

  function editStep(s) {
    const newLabel = prompt("rename step:", s.label || "");
    if (newLabel == null) return Promise.resolve();
    return U.apiPatch(`/jobs/api/applications/${S.current.id}/process-steps/${s.id}`, { label: newLabel }).then((u) => {
      if (u) { Object.assign(s, u); renderPipeline(); renderActiveStep(); U.renderRailPipeline(); }
    });
  }

  function updateActiveStep(status) {
    const s = activeStep();
    if (!s) return Promise.resolve();
    return U.apiPatch(`/jobs/api/applications/${S.current.id}/process-steps/${s.id}`, { status }).then((u) => {
      if (u) Object.assign(s, u);
      renderPipeline();
      renderActiveStep();
      U.renderRailPipeline();
    });
  }

  function renderInterviewers() { S.ep.iv += 1; U.bump(); }

  function addInterviewer() {
    if (!S.current) return Promise.resolve();
    return U.apiPost(`/jobs/api/applications/${S.current.id}/interviewers`, { name: "", role: "" }).then((created) => {
      if (created) {
        S.current.interviewers = S.current.interviewers || [];
        S.current.interviewers.push(created);
        renderInterviewers();
      }
    });
  }

  function renderStories() { S.ep.stories += 1; U.bump(); }
  function renderResumes() { S.ep.resumes += 1; U.bump(); }
  function renderQa() { S.ep.qa += 1; U.bump(); }

  function openResumeDialog(isBase) {
    S.dialog = { kind: "resume", isBase };
    U.bump();
  }
  function addBaseResume() { openResumeDialog(true); }
  function addAppResume() {
    if (!S.current) return;
    openResumeDialog(false);
  }

  function cloneQaTemplate() {
    if (!S.current) return Promise.resolve();
    return U.apiPost(`/jobs/api/applications/${S.current.id}/interview-qa/from-template`).then((rows) => {
      if (rows) {
        S.current.interview_qa = rows;
        renderQa();
        U.toast(`cloned ${rows.length} questions`);
      }
    });
  }

  function addQa(data) {
    if (!S.current) return Promise.resolve();
    return U.apiPost(`/jobs/api/applications/${S.current.id}/interview-qa`, data).then((created) => {
      if (created) {
        S.current.interview_qa = S.current.interview_qa || [];
        S.current.interview_qa.push(created);
        renderQa();
      }
    });
  }

  // ── components ─────────────────────────────────────────────────────────────────

  // a one-line box the plain page filled once when it built the row; it saves what is in it when
  // the timer fires, so onInput hands over read()
  function LineField({ cls, placeholder, label, value, onInput }) {
    const ref = useRef(null);
    return (
      <input ref={ref} className={cls} type="text" defaultValue={value || ""} placeholder={placeholder} aria-label={label}
             onInput={() => onInput(() => ref.current.value)} />
    );
  }

  const keyActivate = (fn) => (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(e); } };

  function PipelineRow() {
    if (!S.pipeDrawn) return <div className="pipe-empty">no process steps yet — add a step via <em>+ step</em>.</div>;
    const steps = (S.current?.process_steps) || [];
    if (!steps.length) return <div className="pipe-empty">no steps · click add step</div>;
    return (
      <React.Fragment>
        {steps.map((s, i) => {
          const stat = s.status || "pending";
          const isCurrent = S.activeStepId === s.id;
          const prevStat = i > 0 ? (steps[i - 1].status || "pending") : null;
          const isFirst = i === 0;
          const isLast = i === steps.length - 1;

          let segL = "pipe-seg seg-l";
          if (isFirst) segL += " ghost";
          else if (prevStat === "complete") segL += " done";

          let segR = "pipe-seg seg-r";
          if (isLast) segR += " ghost";
          else if (stat === "complete") segR += " done";

          const selectStep = () => {
            S.activeStepId = s.id;
            renderPipeline();
            renderActiveStep();
          };
          const cycleStatus = (e) => {
            e.stopPropagation();
            const next = stat === "pending" ? "active" : stat === "active" ? "complete" : stat === "complete" ? "skipped" : "pending";
            s.status = next;
            renderPipeline();
            return U.apiPatch(`/jobs/api/applications/${S.current.id}/process-steps/${s.id}`, { status: next }).then((u) => {
              if (u) Object.assign(s, u);
              renderPipeline();
              renderActiveStep();
              U.renderRailPipeline();
            });
          };
          // the click rebuilds the row, so the double-click lands on a detached node that React's root
          // listener never sees; a native handler on the node itself fires like the plain page's did
          return (
            <div className={`pipe-step ${stat}${isCurrent ? " current" : ""}`} key={s.id} role="button" tabIndex={0}
                 aria-label={`${s.label || `step ${i + 1}`} · ${stat}`}
                 onClick={selectStep} onKeyDown={keyActivate(selectStep)}
                 ref={(n) => { if (n) n.ondblclick = () => editStep(s); }}>
              <div className="pipe-track">
                <div className={segL}></div>
                <div className="pipe-pip" role="button" tabIndex={0} aria-label="cycle step status"
                     onClick={cycleStatus} onKeyDown={keyActivate(cycleStatus)}></div>
                <div className={segR}></div>
              </div>
              <div className="pipe-label">{s.label || `step ${i + 1}`}</div>
              <div className="pipe-meta">{s.step_type || ""}</div>
            </div>
          );
        })}
      </React.Fragment>
    );
  }

  function StepFields() {
    const v = S.stepView;
    if (!v?.step) {
      return <div id="prepStepFields" className="hub-field-hint field-hint">prep fields appear here once a step is selected. field set varies by step type — screen / assessment / interview / panel / reference each have their own prompts.</div>;
    }
    const s = v.step;
    return (
      <div id="prepStepFields" className="hub-field-hint field-hint" key={S.ep.step}>
        <ExTa dynamic surface="prep" value={s.notes} placeholder="notes…" label="step notes"
              onInput={(read) => U.debounce(`step:${s.id}`, () => U.apiPatch(`/jobs/api/applications/${S.current.id}/process-steps/${s.id}`, { notes: read() }).then((u) => {
                if (u) Object.assign(s, u);
              }), 800)} />
      </div>
    );
  }

  function Interviewers() {
    const items = (S.current?.interviewers) || [];
    if (!items.length) return <div className="req-empty">no interviewers logged</div>;
    const patch = (iv, field, read) => U.debounce(`iv:${iv.id}:${field}`, () => U.apiPatch(`/jobs/api/applications/${S.current.id}/interviewers/${iv.id}`, { [field]: read() }).then((u) => {
      if (u) Object.assign(iv, u);
    }), 800);
    return (
      <React.Fragment>
        {items.map((iv) => (
          <div className="interviewer-card" key={iv.id}>
            <div className="grid-2">
              <LineField cls="field-input" value={iv.name} placeholder="name" label="interviewer name" onInput={(r) => patch(iv, "name", r)} />
              <LineField cls="field-input" value={iv.role} placeholder="role" label="interviewer role" onInput={(r) => patch(iv, "role", r)} />
            </div>
            <LineField cls="field-input" value={iv.linkedin_url} placeholder="linkedin url" label="interviewer linkedin url" onInput={(r) => patch(iv, "linkedin_url", r)} />
            <ExTa dynamic surface="prep" value={iv.notes} placeholder="notes…" label="interviewer notes" onInput={(r) => patch(iv, "notes", r)} />
            <div className="interviewer-foot">
              <button className="hub-btn hub-btn--lg alert sm" type="button"
                      onClick={() => {
                        if (!confirm("delete this interviewer?")) return;
                        return U.apiDelete(`/jobs/api/applications/${S.current.id}/interviewers/${iv.id}`).then(() => {
                          S.current.interviewers = (S.current.interviewers || []).filter((x) => x.id !== iv.id);
                          renderInterviewers();
                        });
                      }}>delete</button>
            </div>
          </div>
        ))}
      </React.Fragment>
    );
  }

  // stories — read-only render here; full edit lives in another module
  function Stories() {
    const items = (S.current?.stories) || [];
    if (!items.length) return <div className="req-empty">no stories linked</div>;
    return (
      <React.Fragment>
        {items.map((s, i) => (
          <div className="story-card" key={i}>
            <div className="story-title">{s.title}</div>
            <div className="story-link-notes">{s.link_notes || ""}</div>
          </div>
        ))}
      </React.Fragment>
    );
  }

  function ResumeRow({ r, isBase }) {
    return (
      <div className="resume-row">
        <div className="resume-row-main">
          <div className="resume-row-label">{r.label || r.file_path}</div>
          <div className="resume-row-meta">{`${r.variant || "—"} · ${r.file_path}`}</div>
        </div>
        <button className="hub-btn hub-btn--lg sm" type="button" onClick={() => U.revealResume(r.id)}>open in folder</button>
        <a className="hub-btn hub-btn--lg sm" href={`/jobs/api/resumes/${r.id}/download`}>download</a>
        <button className="hub-btn hub-btn--lg alert sm" type="button"
                onClick={() => {
                  if (!confirm(`delete record for ${r.file_path}? (file on disk is not removed)`)) return;
                  return U.apiDelete(`/jobs/api/resumes/${r.id}`).then(() => {
                    if (isBase) { S.baseResumes = S.baseResumes.filter((x) => x.id !== r.id); }
                    else S.current.resumes = S.current.resumes.filter((x) => x.id !== r.id);
                    renderResumes();
                  });
                }}>delete</button>
      </div>
    );
  }

  function ResumeList({ items, empty, isBase }) {
    return (
      <React.Fragment>
        {!items.length ? <div className="req-empty">{empty}</div> : null}
        {items.map((r) => <ResumeRow r={r} isBase={isBase} key={r.id} />)}
      </React.Fragment>
    );
  }

  // the register dialog: the plain page read its boxes when "register" was pressed
  function ResumeDialog({ isBase }) {
    const filePath = useRef(null), label = useRef(null), variant = useRef(null), notes = useRef(null);
    return (
      <U.Modal title={isBase ? "register base resume" : "register application resume"} primary="register"
               onPrimary={() => {
                 const body = { file_path: filePath.current.value, label: label.current.value, variant: variant.current.value, notes: notes.current.value };
                 if (!body.file_path) { U.toast("file path required", "alert"); return false; }
                 const url = isBase ? "/jobs/api/resumes/base" : `/jobs/api/applications/${S.current.id}/resumes`;
                 return U.apiPost(url, body).then((created) => {
                   if (created) {
                     if (isBase) S.baseResumes.push(created);
                     else { S.current.resumes = S.current.resumes || []; S.current.resumes.push(created); }
                     renderResumes();
                   }
                   return true;
                 });
               }}>
        <div className="hub-field field"><label htmlFor="rsf-path">file path</label>
          <input id="rsf-path" ref={filePath} className="field-input" type="text" placeholder="data/resumes/base/resume-hybrid.docx" aria-label="resume file path" /></div>
        <div className="hub-field field"><label htmlFor="rsf-label">label</label>
          <input id="rsf-label" ref={label} className="field-input" type="text" placeholder="label (e.g. 'hybrid')" aria-label="resume label" /></div>
        <div className="hub-field field"><label htmlFor="rsf-variant">variant</label>
          <input id="rsf-variant" ref={variant} className="field-input" type="text" placeholder="variant (e.g. 'management')" aria-label="resume variant" /></div>
        <div className="hub-field field"><label htmlFor="rsf-notes">notes</label>
          <textarea id="rsf-notes" ref={notes} className="field-textarea" placeholder="notes" aria-label="resume notes"
                    onInput={(e) => { e.target.style.height = "auto"; e.target.style.height = `${e.target.scrollHeight}px`; }} /></div>
      </U.Modal>
    );
  }

  const ORDERED_TYPES = ["intro", "motivation", "behavioral", "situational", "culture", "technical", "curveball", "ask_them"];

  function QaCard({ q }) {
    const patchQ = (field, read) => U.debounce(`qa:${q.id}:${field}`, () => U.apiPatch(`/jobs/api/interview-qa/${q.id}`, { [field]: read() }).then((u) => {
      if (u) {
        Object.assign(q, u);
        if (field === "question_type") renderQa();
      }
    }), 800);
    const sel = useRef(null);
    return (
      <div className={`qa-card ${q.question_type || ""}`}>
        <div className="qa-head">
          <span className={`qa-type-pill ${q.question_type || ""}`}>{U.QA_TYPE_LABELS[q.question_type] || q.question_type || "other"}</span>
          <select ref={sel} className="field-input qa-type" aria-label="question type" defaultValue={q.question_type}
                  onInput={() => patchQ("question_type", () => sel.current.value)}
                  onChange={() => U.debounce(`qa:${q.id}:question_type`, () => U.apiPatch(`/jobs/api/interview-qa/${q.id}`, { question_type: sel.current.value }).then((u) => {
                    if (u) { Object.assign(q, u); renderQa(); }
                  }), 0)}>
            {Object.entries(U.QA_TYPE_LABELS).map(([k, label]) => <option value={k} key={k}>{label}</option>)}
          </select>
          <button className="hub-btn hub-btn--lg alert sm" type="button"
                  onClick={() => {
                    if (!confirm("delete this question?")) return;
                    return U.apiDelete(`/jobs/api/interview-qa/${q.id}`).then(() => {
                      S.current.interview_qa = (S.current.interview_qa || []).filter((x) => x.id !== q.id);
                      renderQa();
                    });
                  }}>delete</button>
        </div>
        <LineField cls="field-input qa-question" value={q.question} placeholder="question…" label="interview question" onInput={(r) => patchQ("question", r)} />
        <ExTa dynamic surface="prep" cls="qa-answer" value={q.answer} placeholder="answer…" label="interview answer" onInput={(r) => patchQ("answer", r)} />
      </div>
    );
  }

  function Qa() {
    const items = (S.current?.interview_qa) || [];
    if (!items.length) return <div className="req-empty">no questions yet · clone the template or add a single question</div>;
    const groups = {};
    for (const q of items) {
      const k = q.question_type || "other";
      groups[k] = groups[k] || [];
      groups[k].push(q);
    }
    const types = ORDERED_TYPES.filter((t) => groups[t]).concat(Object.keys(groups).filter((t) => !ORDERED_TYPES.includes(t)));
    return (
      <React.Fragment>
        {types.map((t) => (
          <React.Fragment key={t}>
            <div className="qa-group-head">{U.QA_TYPE_LABELS[t] || t}</div>
            {groups[t].map((q) => <QaCard q={q} key={q.id} />)}
          </React.Fragment>
        ))}
      </React.Fragment>
    );
  }

  function PrepSurface() {
    const sv = S.stepView;
    const ready = S.pipeDrawn;   // the template's own idle text shows until the first draw
    const gap = prepRow("gap"), standout = prepRow("standout");
    return (
      <div className={surfaceCls("prep")} data-surface-body="prep">

        <div className="section hub-plate-card">
          <div className="section-head hub-section-head">
            <span className="section-title hub-section-head-t">Process Pipeline</span>
          </div>
          <div className="pipeline-row" id="pipelineRow" key={S.ep.pipe}><PipelineRow /></div>
          <div className="hub-btn-row">
            <button type="button" className="hub-btn hub-btn--lg" id="btnAddStep" onClick={addProcessStep}>+ step</button>
          </div>
        </div>

        <div className="section" id="prepActiveStepBlock">
          <div className="prep-block-head">
            <span className="prep-step-title placeholder" id="prepStepTitle">{sv ? sv.title : "no active step"}</span>
            <span className="prep-step-meta" id="prepStepMeta">{sv ? sv.meta : "select a step from the pipeline above"}</span>
          </div>
          <StepFields />
        </div>

        <Card title="questions to ask">
          <div className="questions-block">
            <div>
              <div className="questions-subhead">
                <span className="questions-subhead-l">gap-driven · from research</span>
              </div>
              <ExTa id="prepQuestionsGap" surface="prep" style={{ marginTop: "8px" }} value={gap ? gap.content : ""} epoch={S.ep.prepQ}
                    placeholder="questions about things research didn't tell you — comp specifics, progression, etc."
                    label="questions gap-driven from research"
                    onInput={(read) => U.debounce("prep:gap", () => savePrepResearch("gap", read()), 800)} />
            </div>
            <div>
              <div className="questions-subhead">
                <span className="questions-subhead-l">stand-out · depth + curiosity</span>
              </div>
              <ExTa id="prepQuestionsStandout" surface="prep" style={{ marginTop: "8px" }} value={standout ? standout.content : ""} epoch={S.ep.prepQ}
                    placeholder="questions that show deep understanding of the role and curiosity about the work"
                    label="questions stand-out depth and curiosity"
                    onInput={(read) => U.debounce("prep:standout", () => savePrepResearch("standout", read()), 800)} />
            </div>
          </div>
        </Card>

        <Card title="interviewers">
          <div id="interviewersList" key={S.ep.iv}>{ready ? <Interviewers /> : null}</div>
          <div className="hub-btn-row">
            <button type="button" className="hub-btn hub-btn--lg" id="btnAddInterviewer" onClick={addInterviewer}>+ interviewer</button>
          </div>
        </Card>

        <Card title="resumes">
          <div className="section" style={{ gap: "var(--s-2)" }}>
            <div className="section-head hub-section-head">
              <span className="section-title hub-section-head-t">Base Templates</span>
            </div>
            <div id="resumesBase" key={`b${S.ep.resumes}`}>
              {ready ? <ResumeList items={S.baseResumes || []} empty="no base resumes registered" isBase={true} /> : null}
            </div>
            <div className="hub-btn-row">
              <button type="button" className="hub-btn hub-btn--lg" id="btnAddResumeBase" onClick={addBaseResume}>+ register base resume</button>
            </div>
          </div>
          <div className="section" style={{ gap: "var(--s-2)", marginTop: "var(--s-3)" }}>
            <div className="section-head hub-section-head">
              <span className="section-title hub-section-head-t">Tailored for This App</span>
            </div>
            <div id="resumesApp" key={`a${S.ep.resumes}`}>
              {ready ? <ResumeList items={(S.current?.resumes) || []} empty="no application-specific resumes yet" isBase={false} /> : null}
            </div>
            <div className="hub-btn-row">
              <button type="button" className="hub-btn hub-btn--lg" id="btnAddResumeApp" onClick={addAppResume}>+ register tailored resume</button>
            </div>
          </div>
        </Card>

        <Card title="interview Q&A">
          <div id="qaList" key={S.ep.qa}>{ready ? <Qa /> : null}</div>
          <div className="hub-btn-row">
            <button type="button" className="hub-btn hub-btn--lg" id="btnCloneQaTemplate" onClick={cloneQaTemplate}>↻ clone from template</button>
            <button type="button" className="hub-btn hub-btn--lg" id="btnAddQa" onClick={() => addQa({ question_type: "behavioral", question: "" })}>+ add question</button>
          </div>
        </Card>

        <Card title="stories — primed for this step">
          <div id="storiesList" key={S.ep.stories}>{ready ? <Stories /> : null}</div>
        </Card>

        <div className="section">
          <div className="hub-btn-row">
            <button type="button" className="hub-btn hub-btn--lg btn-primary" id="btnMarkStepComplete" onClick={() => updateActiveStep("complete")}>→ mark step complete</button>
            <button type="button" className="hub-btn hub-btn--lg" id="btnSkipStep" onClick={() => updateActiveStep("skipped")}>skip this step</button>
          </div>
        </div>
      </div>
    );
  }

  Object.assign(U, { PrepSurface, ResumeDialog, renderPrep });
})();

/* Jobs · 3 of 5 (React): the closed surface and the ready-to-send page. Ported from
   jobs-surfaces.js lines 541-1083. Assigns into window.JobsUI and declares nothing at top level.

   Ready to send: a full page, one job at a time, with everything on the card. The deck and the full
   record share one list of rows and one decide(): approving from either side changes the same row,
   so they can never disagree. A row stays in the deck after it is decided (the left arrow steps back
   to it); only a `ready` row gets buttons. Approve only changes status; the submit worker sends, one
   row at a time. The deck redraws from S.review the way the plain renderReview() rebuilt its DOM. */
(() => {
  const { useState, useEffect, useLayoutEffect, useRef } = React;
  const U = window.JobsUI;
  const S = U.S;
  const { ExTa, Card, surfaceCls } = U;


  // ── closed surface ─────────────────────────────────────────────────────────────

  // the banner is only drawn when the record loads or the reason changes, so it draws from a snapshot
  function renderClosed() {
    if (!S.current) return;
    const a = S.current;
    S.snap.closed = {
      tone: a.status === "offer" ? "offer" : (a.status === "rejected" || a.status === "ignored") ? "alert" : "",
      status: U.STATUS_LABELS[a.status] || a.status,
      meta: a.closed_date ? `closed ${a.closed_date}` : "no close date yet",
    };
    S.ep.closed += 1;
    U.bump();
  }

  function ClosedSurface() {
    const a = S.current;
    const ep = S.ep.closed;
    const snap = S.snap.closed;
    const [reason, setReason] = useState("");
    const [date, setDate] = useState("");
    const dateEl = useRef(null);
    const first = useRef(true);
    useLayoutEffect(() => {
      if (first.current) { first.current = false; return; }
      setReason((S.current?.closed_reason) || "");
      setDate((S.current?.closed_date) || "");
    }, [ep]);
    // a date box saves on change, not on every keystroke of a half-typed date
    useEffect(() => {
      const el = dateEl.current;
      const on = (e) => { U.patchApp({ closed_date: e.target.value }); };
      el.addEventListener("change", on);
      return () => el.removeEventListener("change", on);
    }, []);
    const val = (f) => (a ? a[f] : "");
    return (
      <div className={surfaceCls("closed")} data-surface-body="closed">

        <div className={`closed-banner${snap?.tone ? ` ${snap.tone}` : ""}`} id="closedBanner">
          <span className="closed-banner-l">status</span>
          <span className="closed-banner-v placeholder" id="closedBannerStatus">{snap ? snap.status : "application still open"}</span>
          <span className="closed-banner-meta" id="closedBannerMeta">{snap ? snap.meta : "post-mortem becomes editable once status moves to offer / rejected / ignored"}</span>
        </div>

        <Card title="what went well">
          <ExTa id="closedWell" surface="closed" value={val("closed_well")} epoch={ep}
                placeholder="what worked? specific moments, not vague feelings." label="what went well"
                onInput={(read) => U.debounce("patch:closed_well", () => U.patchApp({ closed_well: read() }), 800)} />
        </Card>

        <Card title="what didn't">
          <ExTa id="closedDidnt" surface="closed" value={val("closed_didnt")} epoch={ep}
                placeholder="what didn't land? be specific about the failure mode." label="what didn't go well"
                onInput={(read) => U.debounce("patch:closed_didnt", () => U.patchApp({ closed_didnt: read() }), 800)} />
        </Card>

        <Card title="what I'd do differently">
          <ExTa id="closedDifferently" surface="closed" value={val("closed_differently")} epoch={ep}
                placeholder="what changes for next time?" label="what I'd do differently"
                onInput={(read) => U.debounce("patch:closed_differently", () => U.patchApp({ closed_differently: read() }), 800)} />
        </Card>

        <Card title="reason">
          <select className="field-input" id="closedReason" aria-label="closed reason" value={reason}
                  onChange={(e) => {
                    const v = e.target.value;
                    setReason(v);
                    U.patchApp({ closed_reason: v }).then(() => renderClosed());
                  }}>
            {U.CLOSED_REASONS.map(([v, label]) => <option value={v} key={v}>{label}</option>)}
          </select>
        </Card>

        <Card title="closed date">
          <input type="date" className="field-input" id="closedDate" aria-label="closed date" ref={dateEl}
                 value={date} onChange={(e) => setDate(e.target.value)} />
        </Card>

        <div className="section">
          <div className="hub-btn-row">
            <button type="button" className="hub-btn hub-btn--lg" id="btnReopenApp"
                    onClick={() => {
                      if (!confirm("reopen this application?")) return;
                      return U.patchApp({ status: "applying", closed_reason: "", closed_date: "" })
                        .then(() => U.switchSurface("application", false));
                    }}>re-open application</button>
            <button type="button" className="hub-btn hub-btn--lg btn-alert" id="btnDeleteRecord"
                    onClick={() => {
                      if (!S.current) return;
                      if (!confirm(`permanently delete ${S.current.company} · ${S.current.role}?`)) return;
                      return U.apiDelete(`/jobs/api/applications/${S.current.id}`).then(() => {
                        S.current = null;
                        location.hash = "";
                        return U.loadApplications();
                      }).then(() => U.renderFocusEmpty());
                    }}>delete record</button>
          </div>
        </div>
      </div>
    );
  }

  // ── ready to send: data ────────────────────────────────────────────────────────

  const SUBMIT_HOSTS = ["greenhouse", "lever", "ashby"];
  const DECIDED_LABEL = { approved: "approved · queued to send", cut: "skipped", applied: "sent", moved: "moved on elsewhere" };

  const waitingRows = () => S.review.ready.filter((a) => a.status === "ready");
  const firstWaiting = (after) => {
    const from = after == null ? -1 : after;
    return S.review.ready.find((a, i) => i > from && a.status === "ready") || waitingRows()[0];
  };
  const curIndex = () => S.review.ready.findIndex((a) => a.id === S.review.curId);

  function renderReview() {
    S.ep.review += 1;
    U.bump();
  }

  function loadReady() {
    return U.apiGet("/jobs/api/ready").then((data) => {
      const review = S.review;
      review.needs = data.needs_you || [];
      // keep rows decided this session (so the left arrow still reaches them); refresh the rest from the server
      const server = data.ready || [];
      const byId = new Map(server.map((a) => [a.id, a]));
      const list = review.ready.map((a) => byId.get(a.id) || (a.status === "ready" ? Object.assign({}, a, { status: "moved" }) : a));
      for (const a of server) if (!review.ready.some((x) => x.id === a.id)) list.push(a);
      review.ready = list;
      if (!review.ready.some((a) => a.id === review.curId)) {
        const pick = firstWaiting() || review.ready[0];
        review.curId = pick ? pick.id : null;
      }
      paintReadyCounts();
      if (S.reviewOpen) renderReview();
      U.bump();
    }, () => {});
  }

  function paintReadyCounts() {
    S.readyPainted = true;
    U.bump();
  }

  function setReviewOpen(open) {
    S.reviewOpen = open;
    if (open) renderReview();
    U.bump();
  }

  // any status change on a deck row, from anywhere on the page, lands on the shared row
  function syncReadyRow(app) {
    if (!app) return;
    const row = S.review.ready.find((x) => x.id === app.id);
    if (row) row.status = app.status;
    if (S.current && S.current.id === app.id) S.current.status = app.status;
    paintReadyCounts();
  }

  // ── reading a form field the way a person would ────────────────────────────────

  const RAW_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-/i;
  const CONTACT_RE = /^(first name|last name|preferred first name|name|legal name|full name|email|phone|linkedin|linkedin profile|please include the direct link to your linkedin profile\.?)$/i;

  function questionText(f) {
    const t = (f.label || "").trim();
    if (!t || RAW_ID.test(t)) return "(the form hid this question's text: open the posting to read it)";
    // communicationConsent -> Communication consent
    if (/^[A-Za-z]+$/.test(t) && /[a-z][A-Z]/.test(t)) return t.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase().replace(/^./, (c) => c.toUpperCase());
    return t;
  }

  // the stored answer is an option's value (an id, "given", "1"); show the option's words
  function answerText(f) {
    const v = f.answer;
    if (v == null || v === "") return null;
    const opts = f.options || [];
    if (opts.length) {
      let vals;
      try { vals = JSON.parse(v); } catch { vals = v; }
      return [].concat(vals).map((x) => {
        const o = opts.find((o2) => String(o2.value) === String(x));
        return (o?.label) || String(x);
      }).join(", ");
    }
    if (f.field_type === "input_checkbox") return v === "true" || v === "on" ? "Yes" : "No";
    return v;
  }

  const needsAnswer = (f) => f.required && f.field_type !== "input_file" && !f.is_demographic && !f.answer;
  const unanswered = (a) => (a.form || []).filter(needsAnswer);

  // statuses where he can still change an answer before it goes: waiting for his
  // ok, or a you-submit job he hasn't sent yet
  const EDITABLE_STATUSES = new Set(["ready", "manual_only", "manual"]);

  function cancelEdit(f) {
    S.editing.delete(f.id);
    renderReview();
  }

  function saveAnswer(a, f, value, onSaved) {
    return U.api("POST", `/jobs/api/applications/${a.id}/answers`, { [f.id]: value }).then((res) => {
      for (const r of [a, S.current, S.review.ready.find((x) => x.id === a.id)]) if (r && r.id === a.id) r.form = res.form;
      if (onSaved) onSaved();
      U.toast("answer saved");
      renderReview();
    }, () => {});
  }

  // { showCancel } is false for a still-blank required field: there's nothing to
  // restore, so a cancel button there would just reopen the same empty editor
  function AnswerControl({ a, f, showCancel }) {
    const done = () => S.editing.delete(f.id);
    const cancelBtn = showCancel ? <button type="button" className="hub-btn" onClick={() => cancelEdit(f)}>cancel</button> : null;
    const opts = f.options?.length ? f.options
      : f.field_type === "input_checkbox" ? [{ label: "Yes", value: "true" }, { label: "No", value: "false" }] : null;
    const multi = !!opts && (/multi/.test(f.field_type) || f.field_type === "checkbox_group");
    let current = [];
    if (multi) {
      try { current = [].concat(JSON.parse(f.answer || "[]")); } catch { current = f.answer ? [f.answer] : []; }
    }
    const [selected, setSelected] = useState(() => new Set(current.map(String)));
    const [text, setText] = useState(f.answer || "");
    if (opts) {
      if (multi) {
        return (
          <div className="rts-choices">
            {opts.map((o) => {
              const val = String(o.value);
              return (
                <button type="button" className={`hub-btn${selected.has(val) ? " active" : ""}`} key={val}
                        onClick={() => setSelected((prev) => { const n = new Set(prev); if (n.has(val)) n.delete(val); else n.add(val); return n; })}>{o.label}</button>
              );
            })}
            <button type="button" className="hub-btn hub-btn--accent"
                    onClick={() => saveAnswer(a, f, Array.from(selected), done)}>save</button>
            {cancelBtn}
          </div>
        );
      }
      return (
        <div className="rts-choices">
          {opts.map((o) => (
            <button type="button" className="hub-btn" key={String(o.value)}
                    onClick={() => saveAnswer(a, f, String(o.value), done)}>{o.label}</button>
          ))}
          {cancelBtn}
        </div>
      );
    }
    return (
      <div className="rts-choices">
        <textarea className="field-textarea" rows={Math.min(14, Math.max(2, Math.ceil(text.length / 90)))} placeholder="type your answer" aria-label={questionText(f)}
                  value={text} onChange={(e) => setText(e.target.value)} />
        <button type="button" className="hub-btn hub-btn--accent"
                onClick={() => {
                  const v = text.trim();
                  if (v || !f.required) saveAnswer(a, f, v, done);
                }}>save</button>
        {cancelBtn}
      </div>
    );
  }

  // ── essay marks: pop a written answer out, highlight a passage, say what to fix ──
  // Each comment is saved as a mark (kind "essay", no screenshot) in the same store as mark mode,
  // so a running /marks watch wakes on it and fixes the stored answer. One session per pop-out,
  // so its comments share one Workbench walk-through.

  // character offset of (node, off) inside root, counting text only (highlight <mark>s included)
  function textOffset(root, node, off) {
    const r = document.createRange();
    r.setStart(root, 0);
    r.setEnd(node, off);
    return r.toString().length;
  }

  // the shared pop: select a passage in the body, say what to fix, send it as a mark.
  // render(sent, ask) draws the body; meta(ask) gives the mark's kind and where it points.
  function PassagePop({ title, wide, render, meta: metaFor, onClose }) {
    const body = useRef(null);
    const session = useRef(null);
    const [sent, setSent] = useState([]); // [{start, end, n, range, page}]
    const [ask, setAsk] = useState(null); // {start, end, quote, x, y, range, page}
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);

    // once per pop: re-asking on every [ask] change handed each mark a fresh session (2026-11-06, 8 marks in 8 walk-throughs)
    useEffect(() => {
      fetch("/marks/api/session").then((r) => r.json()).then((j) => { if (!session.current) session.current = j.session; }, () => {});
    }, []);
    useEffect(() => {
      const esc = (e) => { if (e.key === "Escape") { if (ask) setAsk(null); else onClose(); } };
      document.addEventListener("keydown", esc);
      return () => document.removeEventListener("keydown", esc);
    }, [ask]);

    const pick = () => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || !body.current.contains(sel.anchorNode) || !body.current.contains(sel.focusNode)) return;
      const rg = sel.getRangeAt(0);
      const start = textOffset(body.current, rg.startContainer, rg.startOffset);
      const end = textOffset(body.current, rg.endContainer, rg.endOffset);
      if (end - start < 1) return;
      const box = rg.getBoundingClientRect();
      // under the passage, kept on screen
      const x = Math.max(12, Math.min(box.left, window.innerWidth - 340));
      const y = box.bottom + 230 < window.innerHeight ? box.bottom + 8 : Math.max(12, box.top - 222);
      const pg = (rg.startContainer.nodeType === 1 ? rg.startContainer : rg.startContainer.parentElement)?.closest("[data-page]");
      setAsk({ start, end, quote: rg.toString(), x, y, range: rg.cloneRange(), page: pg ? Number(pg.dataset.page) : null });
      setNote("");
    };

    const send = () => {
      const comment = note.trim();
      if (!comment || busy) return;
      setBusy(true);
      const meta = {
        cid: Date.now().toString(36) + Math.random().toString(36).slice(2, 8),
        comment, quote: ask.quote, capture: "none", ...metaFor(ask),
      };
      if (session.current) meta.session = session.current;
      const fd = new FormData();
      fd.append("meta", JSON.stringify(meta));
      fetch("/marks/api/mark", { method: "POST", body: fd })
        .then((r) => r.json().then((j) => { if (!r.ok) throw new Error(j.error || r.status); return j; }))
        .then((j) => {
          session.current = j.session;
          setSent((s) => s.concat({ ...ask, n: j.n }).sort((p, q) => p.start - q.start));
          setAsk(null);
          window.getSelection()?.removeAllRanges();
          U.toast(`mark ${j.n} sent for fixing`);
        }, (e) => U.toast(`could not send: ${e.message}`, "alert"))
        .finally(() => setBusy(false));
    };

    return ReactDOM.createPortal(
      <div className="hub-modal-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
        <div className={`hub-modal hub-modal--wide essay-pop${wide ? " doc-pop" : ""}`} role="dialog" aria-label={title}>
          <div className="hub-modal-title">{title}</div>
          <div className="essay-hint">Highlight a passage, then say what to fix. Each one goes to /marks.{sent.length ? ` ${sent.length} sent.` : ""}</div>
          <div ref={body} onMouseUp={pick}>{render(sent, ask)}</div>
          <div className="hub-modal-actions"><button type="button" className="hub-modal-btn" onClick={onClose}>done</button></div>
          {/* on the page, not in the modal: the modal scrolls and clipped a box that hung past its edge (2026-11-06) */}
          {ask ? ReactDOM.createPortal(
            <div className="essay-ask" style={{ left: ask.x, top: ask.y }}>
              <div className="essay-ask-q">“{ask.quote.length > 120 ? `${ask.quote.slice(0, 117)}…` : ask.quote}”</div>
              <textarea className="field-textarea" rows={3} autoFocus placeholder="what should change here…" value={note}
                        onChange={(e) => setNote(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send(); }} />
              <div className="hub-modal-actions">
                <button type="button" className="hub-modal-btn" onClick={() => setAsk(null)}>cancel</button>
                <button type="button" className="hub-btn hub-btn--accent" disabled={busy || !note.trim()} onClick={send}>send</button>
              </div>
            </div>,
            document.body,
          ) : null}
        </div>
      </div>,
      document.body,
    );
  }

  function EssayPop({ a, f, onClose }) {
    const text = f.answer || "";
    // every sent passage highlighted, and the one being commented on (overlaps draw from the earlier one's end)
    const render = (sent, ask) => {
      const parts = [];
      let at = 0;
      const all = ask ? sent.concat({ ...ask, n: "ask" }).sort((p, q) => p.start - q.start) : sent;
      for (const m of all) {
        const s = Math.max(m.start, at);
        if (s >= m.end) continue;
        if (s > at) parts.push(text.slice(at, s));
        parts.push(<mark key={m.n} className={m.n === "ask" ? "is-ask" : ""} title={m.n === "ask" ? "this passage" : `mark ${m.n}`}>{text.slice(s, m.end)}</mark>);
        at = m.end;
      }
      parts.push(text.slice(at));
      return <div className="essay-text">{parts}</div>;
    };
    return <PassagePop title={questionText(f)} render={render} onClose={onClose}
      meta={(ask) => ({
        kind: "essay", url: `/jobs#app/${a.id}`, title: `${a.company || "Jobs"} essay`,
        essay: { app_id: a.id, field_id: f.id, question: questionText(f), start: ask.start, end: ask.end },
      })} />;
  }

  // a resume or cover letter: pdf.js pages with a text layer so a passage can be selected.
  // Highlights use the CSS Highlight API, since the text layer is pdf.js's DOM, not React's.
  function DocPages({ url, sent, ask }) {
    const host = useRef(null);
    useEffect(() => {
      const el = host.current;
      el.innerHTML = "";
      let on = true;
      pdfjsLib.getDocument(url).promise.then(async (pdf) => {
        for (let i = 1; i <= pdf.numPages && on; i++) {
          const page = await pdf.getPage(i);
          const scale = el.clientWidth / page.getViewport({ scale: 1 }).width;
          const vp = page.getViewport({ scale });
          const dpr = window.devicePixelRatio || 1;
          const wrap = document.createElement("div");
          wrap.className = "doc-page";
          wrap.dataset.page = String(i);
          wrap.style.height = `${vp.height}px`;
          const canvas = document.createElement("canvas");
          canvas.width = vp.width * dpr;
          canvas.height = vp.height * dpr;
          const tl = document.createElement("div");
          tl.className = "textLayer";
          tl.style.setProperty("--scale-factor", String(scale));
          wrap.append(canvas, tl);
          el.appendChild(wrap);
          await page.render({ canvasContext: canvas.getContext("2d"), viewport: page.getViewport({ scale: scale * dpr }) }).promise;
          await pdfjsLib.renderTextLayer({ textContentSource: page.streamTextContent(), container: tl, viewport: vp, textDivs: [] }).promise;
        }
      }).catch((e) => console.error("pdf render failed", e));
      return () => { on = false; };
    }, [url]);
    useEffect(() => {
      if (!window.CSS?.highlights) return;
      CSS.highlights.set("mark-sent", new Highlight(...sent.map((m) => m.range)));
      CSS.highlights.set("mark-ask", new Highlight(...(ask ? [ask.range] : [])));
      return () => { CSS.highlights.delete("mark-sent"); CSS.highlights.delete("mark-ask"); };
    }, [sent, ask]);
    return <div className="doc-pages" ref={host}></div>;
  }

  function DocPop({ a, url, label, onClose }) {
    return <PassagePop title={`${a.company || "Jobs"} ${label}`} wide onClose={onClose}
      render={(sent, ask) => <DocPages url={url} sent={sent} ask={ask} />}
      meta={(ask) => ({
        kind: "doc", url: `/jobs#app/${a.id}`, title: `${a.company || "Jobs"} ${label}`,
        doc: { app_id: a.id, pdf: url, page: ask.page, label },
      })} />;
  }

  // the header button that pops a resume or cover letter out to mark
  function DocMarkBtn({ a, url, label, head }) {
    const [open, setOpen] = useState(false);
    if (!url || !a) return null;
    return <React.Fragment>
      <button type="button" className={`hub-btn sm ${head ? "pdf-head-btn" : "pdf-full-btn pdf-mark-btn"}`} title="pop out to mark" aria-label="pop out to mark"
              onClick={() => setOpen(true)}>
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M9 2h5v5M14 2L7.5 8.5M12 9.5V14H2V4h4.5" />
        </svg>
      </button>
      {open ? <DocPop a={a} url={url} label={label} onClose={() => setOpen(false)} /> : null}
    </React.Fragment>;
  }

  // canEdit: the full record's application tab decides for itself (editable until the application went)
  function QaBlock({ a, canEdit }) {
    const [popped, setPopped] = useState(null); // the field whose essay is popped out
    const editable = canEdit ?? EDITABLE_STATUSES.has(a.status);
    const form = a.form || [];
    const contact = [], demo = [], questions = [];
    for (const f of form) {
      if (f.field_type === "input_file") continue;
      if (f.is_demographic) demo.push(f);
      else if (CONTACT_RE.test((f.label || "").trim())) contact.push(f);
      else questions.push(f);
    }
    questions.sort((x, y) => needsAnswer(y) - needsAnswer(x)); // what needs him goes first
    const rows = [];
    if (contact.length) {
      rows.push(
        <div className="rts-qa is-compact" key="contact">
          <div className="rts-q">Contact details</div>
          <div className="rts-a">{contact.map((f) => answerText(f)).filter(Boolean).join(" · ") || "none filled"}</div>
        </div>
      );
    }
    for (const f of questions) {
      const ans = answerText(f);
      const missing = needsAnswer(f);
      let body;
      if (missing) {
        body = editable
          ? <div className="rts-a"><div className="rts-missing">No answer yet. Required, so this can't be sent until you pick one:</div><AnswerControl a={a} f={f} showCancel={false} /></div>
          : <div className="rts-a is-muted">no answer</div>;
      } else if (editable && S.editing.has(f.id)) {
        body = <div className="rts-a"><AnswerControl a={a} f={f} showCancel={true} /></div>;
      } else {
        body = (
          <div className={`rts-a${ans ? "" : " is-muted"}`}>{ans || "left blank (optional)"}</div>
        );
      }
      rows.push(
        <div className={`rts-qa${missing ? " is-missing" : ""}`} key={f.id}>
          <div className="rts-q">
            <span className="rts-q-t">{questionText(f)}{f.required ? null : <span className="rts-opt">optional</span>}</span>
            {f.field_type === "textarea" && ans ? (
              <button type="button" className="hub-btn sm rts-edit" title="pop out to mark" aria-label="pop out to mark"
                      onClick={() => setPopped(f)}>
                <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M9 2h5v5M14 2L7.5 8.5M12 9.5V14H2V4h4.5" />
                </svg>
              </button>
            ) : null}
            {/* edit sits at the question's right end, so the answer flows as plain text (mark 2026-11-03-181041:5) */}
            {editable && !missing && !S.editing.has(f.id) ? (
              <button type="button" className="hub-btn sm rts-edit" title="edit answer" aria-label="edit answer"
                      onClick={() => { S.editing.add(f.id); renderReview(); }}>
                <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M10.5 2.5l3 3L5 14H2v-3z" />
                </svg>
              </button>
            ) : null}
          </div>
          {body}
        </div>
      );
    }
    if (demo.length) {
      rows.push(
        <div className="rts-qa is-compact" key="demo">
          <div className="rts-q">Voluntary self-ID</div>
          <div className="rts-a is-muted">{`declined to answer: ${demo.map((f) => questionText(f).replace(/status$/i, " status").toLowerCase()).join(", ")}`}</div>
        </div>
      );
    }
    return <React.Fragment>{rows}{popped ? <EssayPop a={a} f={popped} onClose={() => setPopped(null)} /> : null}</React.Fragment>;
  }

  // ── ready to send: the page ────────────────────────────────────────────────────

  function hostLabel(a) {
    const host = a.ats_host || "other site";
    return SUBMIT_HOSTS.includes(host) ? `${host} · sent for you after approval` : `${host} · you submit by hand`;
  }

  function answerLines(a) {
    return (a.form || []).filter((f) => f.field_type !== "input_file")
      .map((f) => `${questionText(f)}\n${answerText(f) == null ? "" : answerText(f)}`).join("\n\n");
  }

  function Sec({ title, children }) {
    return <div className="rts-sec"><div className="rts-sec-t">{title}</div>{children}</div>;
  }

  function TextList({ s }) {
    const items = (s || "").split("\n").map((x) => x.replace(/^[-•*]\s*/, "").trim()).filter(Boolean);
    return items.length
      ? <ul className="rts-list">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
      : <p className="rts-p is-muted">none logged</p>;
  }

  function QueueItem({ a }) {
    const done = a.status !== "ready";
    const gaps = unanswered(a).length;
    const tag = done ? (DECIDED_LABEL[a.status] || a.status) : gaps ? `${gaps} to answer` : "ready";
    return (
      <button type="button"
              className={`rts-qi${a.id === S.review.curId ? " active" : ""}${done ? " is-done" : ""}${!done && gaps ? " is-gap" : ""}`}
              onClick={() => { S.review.curId = a.id; renderReview(); }}>
        <span className="rts-qi-t">{a.company || "(no company)"}</span>
        <span className="rts-qi-s">{a.role || ""}</span>
        <span className="rts-qi-tag">{tag}</span>
      </button>
    );
  }

  function reviewAct(url, body) {
    return U.api("POST", url, body).then(() => {}, () => { /* api() already toasted */ }).then(() => loadReady());
  }

  function NeedsCard({ a }) {
    const manual = a.status === "manual_only" || a.status === "manual";
    let pill, note, acts;
    if (a.status === "unconfirmed") {
      // no finish-by-hand action here: a second submit could double-apply
      pill = <span className="hub-pill is-alert">may be sent</span>;
      note = <div className="hub-callout-warn">Submit was clicked but no confirmation showed. Check your email before doing anything.</div>;
      acts = (
        <div className="hub-btn-row">
          {[["mark applied", "applied"], ["mark closed", "closed"]].map(([label, outcome]) => (
            <button type="button" className="hub-btn" key={outcome}
                    onClick={() => reviewAct(`/jobs/api/applications/${a.id}/resolve`, { outcome })}>{label}</button>
          ))}
        </div>
      );
    } else {
      pill = <span className="hub-pill is-warn">{a.status === "manual_only" ? "you submit" : "finish by hand"}</span>;
      const why = SUBMIT_HOSTS.includes(a.ats_host) && a.status === "manual_only"
        ? "The sweep could not answer every required question. Nothing sent."
        : `${a.ats_host || "This site"}: prep only. Resume and answers ready to paste.`;
      note = <div className="review-need-d">{a.reason || why}</div>;
      acts = (
        <div className="hub-btn-row">
          {a.job_url ? <a className="hub-btn" href={a.job_url} target="_blank" rel="noopener">open posting</a> : null}
          {a.resume_url ? <a className="hub-btn" href={a.resume_url} target="_blank" rel="noopener">resume</a> : null}
          {a.screenshot_url ? <a className="hub-btn" href={a.screenshot_url} target="_blank" rel="noopener">screenshot</a> : null}
          <button type="button" className="hub-btn"
                  onClick={() => navigator.clipboard.writeText(answerLines(a)).then(() => U.toast("answers copied"))}>copy answers</button>
          {manual ? (
            <button type="button" className="hub-btn hub-btn--accent"
                    onClick={() => {
                      if (!confirm("mark this application as sent?")) return;
                      reviewAct(`/jobs/api/applications/${a.id}/mark-sent`);
                    }}>mark sent</button>
          ) : null}
        </div>
      );
    }
    return (
      <div className="review-need">
        <div className="review-need-t">
          <a href={`#app/${a.id}`}>{a.company || "(no company)"}</a>
          <span className="review-card-sub">{a.role || ""}</span>
          {pill}
        </div>
        {note}
        {acts}
        {manual ? <div className="rts-qa-list"><QaBlock a={a} /></div> : null}
      </div>
    );
  }

  function JobCard({ a }) {
    const money = U.formatSalary(a);
    const facts = [a.location, a.work_arrangement, a.employment_type,
      money !== "—" ? money.split(" · ").filter((v, i, all) => all.indexOf(v) === i).join(" to ") : null].filter(Boolean).join(" · ");
    const gaps = unanswered(a).length;
    return (
      <div className="rts-card">
        <div className="rts-head">
          <div className="rts-title">
            <span className="rts-co">{a.company || "(no company)"}</span>
            <span className="rts-role">{a.role || ""}</span>
          </div>
          <div className="rts-facts">{facts}<span className="rts-host">{hostLabel(a)}</span></div>
          <div className="hub-btn-row">
            {a.job_url ? <a className="hub-btn" href={a.job_url} target="_blank" rel="noopener">↗ posting</a> : null}
            <a className="hub-btn" href={`#app/${a.id}`}>full record</a>
          </div>
        </div>
        <div className="rts-grid">
          <div className="rts-col">
            <div className="rts-fit">
              <span className="rts-score">{a.fit_score != null ? `${Math.round(a.fit_score)}` : "—"}</span>
              <span className="rts-fit-t">{a.fit_reason || "no fit note"}</span>
            </div>
            {a.red_flags ? <div className="hub-callout-warn">{`Watch out: ${a.red_flags}`}</div> : null}
            <Sec title="the company"><p className="rts-p">{a.company_summary || "no summary"}</p></Sec>
            <Sec title="the role"><p className="rts-p">{a.role_summary || "no summary"}</p></Sec>
            <Sec title="requirements"><TextList s={a.requirements} /></Sec>
            <Sec title="nice to have"><TextList s={a.nice_to_haves} /></Sec>
          </div>
          <div className="rts-col">
            <Sec title={`the application${gaps ? ` · ${gaps} question${gaps > 1 ? "s need" : " needs"} you` : " · every required question answered"}`}>
              <div className="rts-qa-list"><QaBlock a={a} /></div>
            </Sec>
          </div>
          <div className="rts-col rts-resume">
            <Sec title="resume sent with it">
              {a.resume_url
                ? <div className="pdf-wrap"><iframe className="rts-pdf" src={`${a.resume_url}#view=FitH&toolbar=0`} title="resume"></iframe><U.FullBtn url={a.resume_url} /><DocMarkBtn a={a} url={a.resume_url} label="resume" /></div>
                : <div className="hub-callout-warn">No resume attached. This can't be sent.</div>}
            </Sec>
          </div>
        </div>
      </div>
    );
  }

  function DecideButtons({ a, where }) {
    if (a.status !== "ready") return <span className="hub-pill">{DECIDED_LABEL[a.status] || a.status}</span>;
    const gaps = unanswered(a).length;
    return (
      <React.Fragment>
        <button type="button" className="hub-btn hub-btn--lg" onClick={() => decide(a.id, "skip", where)}>skip</button>
        <button type="button" className="hub-btn hub-btn--lg hub-btn--accent" disabled={gaps > 0}
                title={gaps ? "answer the flagged questions first" : undefined}
                onClick={() => decide(a.id, "approve", where)}>{gaps ? `answer ${gaps} first` : "approve & next"}</button>
      </React.Fragment>
    );
  }

  function Deck() {
    const review = S.review;
    const n = review.ready.length;
    const approved = review.ready.filter((a) => a.status === "approved").length;
    const i = curIndex();
    const a = review.ready[i];
    return (
      <React.Fragment>
        <div className="rts-top">
          <nav className="jobs-modes" id="rtsModes" aria-label="view"></nav>
          <span className="rts-top-s">{n ? `${i + 1} of ${n} · ${waitingRows().length} waiting · ${approved} approved` : "nothing waiting"}</span>
        </div>
        <div className="rts-body">
          <div className="rts-queue">{review.ready.map((r) => <QueueItem a={r} key={r.id} />)}</div>
          <div className="rts-main">
            {a ? (
              <React.Fragment>
                <JobCard a={a} />
                <div className="rts-foot">
                  <button type="button" className="hub-btn" disabled={i <= 0} onClick={() => step(-1)}>‹ prev</button>
                  <button type="button" className="hub-btn" disabled={i >= n - 1} onClick={() => step(1)}>next ›</button>
                  <span className="rts-spacer"></span>
                  <DecideButtons a={a} where="deck" />
                  <span className="review-keys">A approve · S skip · ← → move</span>
                </div>
              </React.Fragment>
            ) : <p className="review-done">Nothing waiting. New jobs land here after the 6am sweep.</p>}
          </div>
          {/* its own grid cell: under the queue on desktop, after the job on a phone */}
          <div className="rts-needs">
            {review.needs.length ? (
              <React.Fragment>
                <div className="rts-sec-t rts-needs-t">{`needs you · ${review.needs.length}`}</div>
                {review.needs.map((r) => <NeedsCard a={r} key={r.id} />)}
              </React.Fragment>
            ) : null}
          </div>
        </div>
      </React.Fragment>
    );
  }

  // the deck is only drawn while the page is open; closed, it stays as it was last drawn
  function ReviewView() {
    const last = useRef(null);
    if (S.reviewOpen && S.ep.review > 0) last.current = <Deck key={S.ep.review} />;
    return (
      <div className="review-view" id="reviewView" hidden={!S.reviewOpen}>
        <div className="review-needs" id="reviewNeeds"></div>
        <div className="review-deck" id="reviewDeck">{last.current}</div>
      </div>
    );
  }

  function step(d) {
    const i = curIndex() + d;
    if (i < 0 || i >= S.review.ready.length) return;
    S.review.curId = S.review.ready[i].id;
    renderReview();
  }

  // the one approve / skip path, used by the deck and by the full record's bar
  function decide(id, action, where) {
    const a = S.review.ready.find((x) => x.id === id);
    if (a?.status !== "ready") return Promise.resolve();
    return U.api("POST", `/jobs/api/applications/${id}/${action}`).then((res) => {
      syncReadyRow(res);
      const nx = firstWaiting(S.review.ready.indexOf(a));
      S.review.curId = nx ? nx.id : id;
      paintReadyCounts();
      if (where === "record") {
        // back to the deck on the next job, so the two views never drift apart
        history.pushState(null, "", "#ready");
        U.hashSelect();
      } else {
        renderReview();
      }
    }, () => {
      return loadReady(); // 409: it moved elsewhere (another tab); show the server's view
    });
  }

  // the full record of a deck job carries the same approve / skip as its card
  function ReviewBar() {
    const a = S.current && S.review.ready.find((x) => x.id === S.current.id);
    const i = a ? S.review.ready.indexOf(a) : -1;
    return (
      <div className="rts-bar" id="reviewBar" hidden={!a}>
        {a ? (
          <React.Fragment>
            {/* biome-ignore lint/a11y/useValidAnchor: real hash navigation to #ready; onClick only records which review card to return to */}
            <a className="hub-btn" href="#ready" onClick={() => { S.review.curId = a.id; }}>‹ back to ready to send</a>
            <span className="rts-bar-t">{`ready to send · ${i + 1} of ${S.review.ready.length}`}</span>
            <span className="rts-spacer"></span>
            <DecideButtons a={a} where="record" />
          </React.Fragment>
        ) : null}
      </div>
    );
  }

  // the keys the page answers while it is open: A approve, S skip, arrows move
  function reviewKey(e) {
    if (!S.reviewOpen || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target.closest?.("input, textarea, select, [contenteditable]")) return;
    const k = e.key.toLowerCase();
    const a = S.review.ready[curIndex()];
    if (k === "a" && a && !unanswered(a).length) decide(a.id, "approve", "deck");
    else if (k === "s" && a) decide(a.id, "skip", "deck");
    else if (e.key === "ArrowLeft") step(-1);
    else if (e.key === "ArrowRight") step(1);
    else return;
    e.preventDefault();
  }

  Object.assign(U, {
    ClosedSurface, ReviewView, ReviewBar,
    renderClosed, renderReview, loadReady, setReviewOpen, syncReadyRow, reviewKey,
    waitingRows, firstWaiting, QaBlock, answerLines, DocMarkBtn,
  });
})();

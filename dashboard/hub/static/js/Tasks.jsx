/* tasks panel — reads/writes wiki/notes/claude-work-planner*.md via hub API */

const { useState: tasksUseState, useEffect: tasksUseEffect, useRef: tasksUseRef } = React;

const GROUPS = [
  { label: "life",    sections: ["general", "personal", "work"] },
  { label: "systems", sections: ["setup & workflow", "vault", "sorting"] },
  { label: "build",   sections: ["dashboard", "claude code & skills"] },
  { label: "horizon", sections: ["travel", "explore"] },
];

const ALL_SECTIONS = GROUPS.flatMap((g) => g.sections);

const SCHEDULED = "scheduled"; // synthetic top section holding every timed task

// Urgency triage chip: a single field with two states. `critical` = must-do,
// `quickwin` = high value-to-effort. Anything else = no chip.
const URGENCY_LABEL = { critical: "critical", quickwin: "quick win" };
const URGENCY_OPTIONS = [
  { v: "", label: "none" },
  { v: "critical", label: "critical" },
  { v: "quickwin", label: "quick win" },
];

// Input pip: how much of Sam a task needs before Claude can finish it.
// green = zero questions (the /tasks auto-queue), yellow = up to 3, red = full
// back-and-forth. Untriaged rows render a hollow pip so a miss stays visible.
const INPUT_LABEL = {
  none: "no input needed — Claude can finish this alone",
  low: "low input — up to 3 questions",
  high: "hands-on — needs full back-and-forth",
};
const INPUT_OPTIONS = [
  { v: "none", label: "none" },
  { v: "low", label: "low" },
  { v: "high", label: "high" },
  { v: "", label: "untriaged" },
];

// A long-stale overdue item reads identically loud as one that just slipped —
// same red, same weight — which trains the eye to tune out the color entirely.
// Past this many days overdue, the chip drops to a muted "stale" treatment
// instead of full alarm red (home critique P2: overdue triage).
const STALE_OVERDUE_DAYS = 30;

// Live time-remaining for a countdown target (ISO local datetime from the API).
// Granularity is days + hours per the chip spec; under an hour collapses to
// "<1h", a passed target reads "overdue" (with elapsed days once it's been a
// day or more, so a 2-day slip and a 4-month one don't look the same).
function countdownParts(target, now) {
  const ms = new Date(target).getTime();
  if (Number.isNaN(ms)) return null;
  const diff = ms - now;
  if (diff <= 0) {
    const overdueDays = Math.floor(-diff / 86400000);
    const stale = overdueDays >= STALE_OVERDUE_DAYS;
    const text = overdueDays >= 1 ? `${overdueDays}d overdue` : "overdue";
    return { text, overdue: true, stale };
  }
  const totalHours = diff / 3600000;
  const days = Math.floor(totalHours / 24);
  const hours = Math.floor(totalHours % 24);
  let text;
  if (days >= 1) text = `${days}d ${hours}h`;
  else if (totalHours >= 1) text = `${hours}h`;
  else {
    // inside the final hour, a real ticking m:ss countdown
    const mins = Math.floor(diff / 60000);
    const secs = Math.floor((diff % 60000) / 1000);
    text = `${mins}:${String(secs).padStart(2, "0")}`;
  }
  return { text, overdue: false };
}

function taskPost(url, body) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function TaskEditModal({ task, source, onSave, onClose }) {
  const [name, setName] = tasksUseState(task.name);
  const [urgency, setUrgency] = tasksUseState(task.urgency || "");
  const [inputLevel, setInputLevel] = tasksUseState(task.input_level || "");
  const [group, setGroup] = tasksUseState(task.group_label || "");
  const [desc, setDesc] = tasksUseState(task.description || "");

  async function save() {
    const trimmed = name.trim();
    if (!trimmed) return;
    const res = await taskPost("/api/tasks/update", {
      id: task.id,
      name: trimmed,
      description: desc.trim(),
      urgency,
      input_level: inputLevel,
      group_label: group.trim(),
      source,
    });
    if (res.ok) onSave();
  }

  const dref = useDialogA11y(onClose);

  return (
    <div className="task-modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="task-modal" ref={dref} tabIndex={-1} role="dialog" aria-modal="true" aria-label="edit task">
        <div className="task-modal-label">edit task</div>
        {/* no autoFocus here — it's the first focusable control in the dialog,
            so useDialogA11y's own mount effect (dref, above) already focuses it */}
        <input
          className="task-edit-input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()}
        />
        <textarea
          className="task-edit-textarea"
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          placeholder="description (optional)"
        />
        <input
          className="task-edit-input task-edit-group"
          value={group}
          onChange={(e) => setGroup(e.target.value)}
          placeholder="group (optional) — tasks sharing a group cluster together"
        />
        <div className="task-modal-sub">input needed from you</div>
        <div className="task-urgency-row">
          {INPUT_OPTIONS.map((o) => (
            <button type="button"
              key={o.v || "untriaged"}
              className={`task-urgency-opt${inputLevel === o.v ? " on" : ""}`}
              onClick={() => setInputLevel(o.v)}
              title={INPUT_LABEL[o.v] || "not triaged yet"}
            >
              <span className={`task-input-pip ${o.v || "untriaged"}`} />
              {o.label}
            </button>
          ))}
        </div>
        <div className="task-modal-sub">urgency</div>
        <div className="task-urgency-row">
          {URGENCY_OPTIONS.map((o) => (
            <button type="button"
              key={o.v}
              className={`task-urgency-opt${urgency === o.v ? " on" : ""}${o.v ? ` ${o.v}` : ""}`}
              onClick={() => setUrgency(o.v)}
            >
              {o.label}
            </button>
          ))}
        </div>
        <div className="task-edit-actions">
          <button type="button" className="task-edit-save" onClick={save}>save</button>
          <button type="button" className="task-edit-cancel" onClick={onClose}>cancel</button>
        </div>
      </div>
    </div>
  );
}

// done/total counts keyed by a row->key function, over the combined active+completed
// pool, so a section/group header can show progress even on the active tab (where
// completed rows aren't rendered).
function countBy(rows, keyFn) {
  const m = {};
  for (const t of rows) {
    const k = keyFn(t);
    if (!k) continue;
    if (!m[k]) m[k] = { done: 0, total: 0 };
    m[k].total++;
    if (t.done) m[k].done++;
  }
  return m;
}

function Tasks({ initial, initialCompleted, hideDueThrough, hideHead, title }) {
  const [tasks, setTasks] = tasksUseState(initial || []);
  const [completed, setCompleted] = tasksUseState(initialCompleted || []);

  // Adopt the parent's data when it arrives. With progressive load the panel
  // mounts with empty arrays and App fills them once /api/home returns. The props
  // are referentially stable after that (App holds them in one `home` object), so
  // these fire once on arrival and never clobber local optimistic edits from
  // complete/reopen on later re-renders.
  tasksUseEffect(() => { if (initial) setTasks(initial); }, [initial]);
  tasksUseEffect(() => { if (initialCompleted) setCompleted(initialCompleted); }, [initialCompleted]);

  // Today's due/scheduled tasks live in the today zone (right column cap), so the
  // backlog panel hides active tasks due today or earlier — otherwise they'd
  // double-list. Completed tasks are unaffected (the completed tab stays a full
  // historical record). Falls back to the full list when no hideDueThrough is set.
  const BL = window.BriefingLogic;
  const activeTasks = (hideDueThrough && BL)
    ? tasks.filter((t) => !(t.due_target && BL.localDayString(t.due_target) <= hideDueThrough))
    : tasks;

  const [tab, setTab] = tasksUseState("active");
  const [selected, setSelected] = tasksUseState(new Set());
  const [ddOpen, setDdOpen] = tasksUseState(false);
  const [expanded, setExpanded] = tasksUseState(new Set());
  const [collapsedSecs, setCollapsedSecs] = tasksUseState(new Set());
  const [collapsedGroups, setCollapsedGroups] = tasksUseState(new Set());
  const [modalTask, setModalTask] = tasksUseState(null);
  const [now, setNow] = tasksUseState(() => Date.now());
  const ddRef = tasksUseRef(null);

  // Tick the countdown chips. A self-scheduling timer picks its own cadence: 1s
  // while any active task is inside its final hour (so the m:ss countdown moves
  // in real time), 30s otherwise (days/hours barely change — no reason to churn
  // re-renders all day in an always-open tab).
  tasksUseEffect(() => {
    let timer;
    const tick = () => {
      const t = Date.now();
      setNow(t);
      const subHour = activeTasks.some((task) => {
        if (task.done || !task.due_target) return false;
        const diff = new Date(task.due_target).getTime() - t;
        return diff > 0 && diff < 3600000;
      });
      timer = setTimeout(tick, subHour ? 1000 : 30000);
    };
    tick();
    return () => clearTimeout(timer);
  }, [tasks, hideDueThrough]);

  function toggleExpanded(id) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleCollapsed(setFn, key) {
    setFn((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  tasksUseEffect(() => {
    if (!ddOpen) return;
    const handler = (e) => {
      if (ddRef.current && !ddRef.current.contains(e.target)) setDdOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [ddOpen]);

  const sectionCount = (sec) =>
    [...activeTasks, ...completed].filter((t) => t.section === sec).length;

  const visibleTasks = (tab === "active" ? activeTasks : completed).filter(
    (t) => selected.size === 0 || selected.has(t.section)
  );

  // progress totals span active + completed regardless of the section filter, so
  // a header reads "1/3 done" even when the done ones live on the other tab.
  const allRows = [...activeTasks, ...completed];
  const secProgress = countBy(allRows, (t) => t.section);
  const groupProgress = countBy(allRows, (t) =>
    t.group_label ? `${t.section}::${t.group_label}` : null
  );

  const ddLabel =
    selected.size === 0
      ? "all sections"
      : selected.size === 1
      ? [...selected][0]
      : `${selected.size} sections`;

  function toggleSection(sec) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(sec) ? next.delete(sec) : next.add(sec);
      return next;
    });
  }

  async function refresh() {
    const data = await fetch("/api/home").then((r) => r.json());
    setTasks(data.TASKS || []);
    setCompleted(data.TASKS_COMPLETED || []);
  }

  async function handleComplete(task) {
    const res = await taskPost("/api/tasks/complete", { id: task.id });
    if (!res.ok) return;
    setTasks((xs) => xs.filter((t) => t.id !== task.id));
    const data = await fetch("/api/home").then((r) => r.json());
    setCompleted(data.TASKS_COMPLETED || []);
  }

  async function handleReopen(task) {
    const res = await taskPost("/api/tasks/reopen", { id: task.id });
    if (!res.ok) return;
    setCompleted((xs) => xs.filter((t) => t.id !== task.id));
    const data = await fetch("/api/home").then((r) => r.json());
    setTasks(data.TASKS || []);
  }

  const activeCount = activeTasks.length;
  const doneCount = completed.length;
  const source = tab === "completed" ? "completed" : "active";

  // Section blocks to render, top-down. On the active tab every task with a due
  // date (anything carrying a countdown chip — timed events and all-day
  // deadlines alike) is pulled into a synthetic "scheduled" section at the top,
  // sorted soonest-due first, and removed from its normal section. The completed
  // tab keeps the plain section grouping (a countdown on a done task is moot).
  const groupTimed = tab === "active";
  const timedItems = groupTimed
    ? visibleTasks
        .filter((t) => t.due_target)
        .slice()
        .sort((a, b) => new Date(a.due_target).getTime() - new Date(b.due_target).getTime())
    : [];
  const sectionPool = groupTimed ? visibleTasks.filter((t) => !t.due_target) : visibleTasks;
  const blocks = [
    ...(timedItems.length ? [{ sec: SCHEDULED, items: timedItems }] : []),
    ...ALL_SECTIONS
      .map((sec) => ({ sec, items: sectionPool.filter((t) => t.section === sec) }))
      .filter(({ items }) => items.length > 0),
  ];

  // One task row. Shared by grouped and ungrouped rendering.
  function renderTask(t) {
    const isExpanded = expanded.has(t.id);
    const cd = (!t.done && t.due_target) ? countdownParts(t.due_target, now) : null;
    const uLabel = URGENCY_LABEL[t.urgency];
    return (
      <div key={t.id} className="task-item">
        <div className={`task-row${t.done ? " done" : ""}${isExpanded ? " open" : ""}`}>
          <button type="button"
            className="task-check"
            onClick={() => t.done ? handleReopen(t) : handleComplete(t)}
            title={t.done ? "reopen" : "complete"}
          >
            {t.done ? "✓" : ""}
          </button>
          {t.done
            ? <span className="task-input-slot" />
            : <span
                className={`task-input-pip ${t.input_level || "untriaged"}`}
                role="img"
                title={INPUT_LABEL[t.input_level] || "not triaged yet"}
                aria-label={INPUT_LABEL[t.input_level] || "not triaged yet"}
              />}
          <span
            className="task-name"
            onClick={() => toggleExpanded(t.id)}
            role="button"
            tabIndex={0}
            aria-expanded={isExpanded}
            onKeyDown={(e) => {
              if (e.key === "Enter") toggleExpanded(t.id);
              else if (e.key === " ") { e.preventDefault(); toggleExpanded(t.id); }
            }}
          >
            {t.name}
          </span>
          {uLabel && !t.done
            ? <span className={`task-urgency-chip ${t.urgency}`} title={`${uLabel} priority`}>{uLabel}</span>
            : <span className="task-urgency-slot" />}
          {cd
            ? <span
                className={`task-time-chip${cd.overdue ? " overdue" : ""}${cd.stale ? " stale" : ""}`}
                title={cd.stale ? "overdue for a long time — consider archiving" : "time remaining"}
              >{cd.text}</span>
            : <span className="task-time-slot" />}
        </div>
        <HubCollapse open={isExpanded}>
          <div className="task-detail">
            <div className="task-detail-head">
              <span>
                {t.description
                  ? t.description
                  : <span className="task-detail-empty">no details yet</span>}
              </span>
              <button type="button" className="task-edit-btn" onClick={() => setModalTask(t)}>
                edit
              </button>
            </div>
          </div>
        </HubCollapse>
      </div>
    );
  }

  // Render a section's items, clustering by group_label. The API already sorts
  // items so ungrouped come first and each group's tasks are contiguous.
  function renderSectionBody(sec, items) {
    const out = [];
    let run = [];   // current contiguous run of ungrouped tasks
    let curGroup = null;
    let groupRun = [];

    const flushUngrouped = () => {
      run.forEach((t) => { out.push(renderTask(t)); });
      run = [];
    };
    const flushGroup = () => {
      if (curGroup == null) return;
      const key = `${sec}::${curGroup}`;
      const collapsed = collapsedGroups.has(key);
      const p = groupProgress[key];
      const items = groupRun;
      out.push(
        <div key={`g:${key}`} className="task-group">
          <button
            type="button"
            className="task-group-head"
            onClick={() => toggleCollapsed(setCollapsedGroups, key)}
            aria-expanded={!collapsed}
          >
            <span className="task-group-caret">{collapsed ? "▸" : "▾"}</span>
            <span className="task-group-name">{curGroup}</span>
            {p && <span className="task-group-count">{p.done}/{p.total}</span>}
          </button>
          <HubCollapse open={!collapsed}>{items.map((t) => renderTask(t))}</HubCollapse>
        </div>
      );
      curGroup = null;
      groupRun = [];
    };

    for (const t of items) {
      const g = t.group_label || "";
      if (!g) { flushGroup(); run.push(t); continue; }
      // grouped task
      flushUngrouped();
      if (g !== curGroup) { flushGroup(); curGroup = g; }
      groupRun.push(t);
    }
    flushUngrouped();
    flushGroup();
    return out;
  }

  return (
    <div className="panel flex">
      {modalTask && (
        <TaskEditModal
          task={modalTask}
          source={source}
          onSave={async () => { setModalTask(null); await refresh(); }}
          onClose={() => setModalTask(null)}
        />
      )}

      {!hideHead && (
        <div className="panel-head">
          <h2 className="panel-title">{title || "tasks"}</h2>
          {!title ? <span className="panel-meta">planner.md</span> : null}
        </div>
      )}

      <div className="task-tabs">
        <button type="button"
          className={`task-tab${tab === "active" ? " active" : ""}`}
          onClick={() => setTab("active")}
        >
          active <span className="task-tab-count">{activeCount}</span>
        </button>
        <button type="button"
          className={`task-tab${tab === "completed" ? " active" : ""}`}
          onClick={() => setTab("completed")}
        >
          completed <span className="task-tab-count">{doneCount}</span>
        </button>
      </div>

      <div className="task-dd-wrap" ref={ddRef}>
        <button type="button" className="task-dd-trigger" onClick={() => setDdOpen((v) => !v)}>
          <span className="task-dd-label">{ddLabel}</span>
          <span className="task-dd-arrow" aria-hidden="true">
            <svg viewBox="0 0 10 14" width="8" height="12"><path d="M2 5l3-3 3 3M2 9l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </span>
        </button>

        <HubCollapse open={ddOpen} float>
          <div className="task-dd-menu">
            {GROUPS.map((g) => (
              <div key={g.label} className="task-dd-group">
                <div className="task-dd-group-head">{g.label}</div>
                {g.sections.map((sec) => {
                  const checked = selected.has(sec);
                  return (
                    <label key={sec} className={`task-dd-row${checked ? " checked" : ""}`}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleSection(sec)}
                      />
                      <span className="task-dd-sec">{sec}</span>
                      <span className="task-dd-n">{sectionCount(sec)}</span>
                    </label>
                  );
                })}
              </div>
            ))}
          </div>
        </HubCollapse>
      </div>

      <div className="panel-body scroll">
        <div className="task-list">
          {visibleTasks.length === 0 && (
            <div className="task-empty">no tasks</div>
          )}
          {blocks.map(({ sec, items }) => {
            const isScheduled = sec === SCHEDULED;
            const secCollapsed = collapsedSecs.has(sec);
            const p = isScheduled ? null : secProgress[sec];
            return (
              <div key={sec} className="task-section">
                <button
                  type="button"
                  className="task-section-head"
                  onClick={() => toggleCollapsed(setCollapsedSecs, sec)}
                  aria-expanded={!secCollapsed}
                >
                  <span className="task-section-caret">{secCollapsed ? "▸" : "▾"}</span>
                  <span className="task-section-name">{sec}</span>
                  {p
                    ? <span className="task-section-count">{p.done}/{p.total}</span>
                    : <span className="task-section-count">{items.length}</span>}
                </button>
                <HubCollapse open={!secCollapsed}>
                  {isScheduled
                    ? items.map((t) => renderTask(t))
                    : renderSectionBody(sec, items)}
                </HubCollapse>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Tasks });

/* schedule panel — left column. 8-day window (yesterday → today → next 6),
   today-anchored: yesterday collapses into a thin clickable strip at the top
   (expand to reveal its events) so today is the first full block. today/tomorrow
   keep the primary visual weight. */

const { useState: scheduleUseState, useEffect: scheduleUseEffect, useRef: scheduleUseRef } = React;

// Fixed 15-minute time grid for the start/end dropdowns. A <select> is inherently
// a scroll list with hard top/bottom stops (no carousel wrap like the native
// time spinner). Values are 24h "HH:MM" (what buildEventBody expects); labels
// are the hub's 12-hour a/p shape for reading — never the value itself, which
// Google's API wants in 24h.
const TIME_OPTIONS = (() => {
  const out = [];
  for (let h = 0; h < 24; h++) {
    for (let m = 0; m < 60; m += 15) {
      const value = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
      const h12 = h % 12 || 12;
      const label = `${h12}:${String(m).padStart(2, '0')}${h < 12 ? 'a' : 'p'}`;
      out.push({ value, label });
    }
  }
  return out;
})();

// Build the full options list for a given value — splices in off-grid times.
function buildTimeOpts(value) {
  if (value && !TIME_OPTIONS.some(o => o.value === value)) {
    const [h, m] = value.split(':').map(Number);
    const h12 = h % 12 || 12;
    const label = `${h12}:${String(m).padStart(2, '0')}${h < 12 ? 'a' : 'p'}`;
    return [...TIME_OPTIONS, { value, label }].sort((a, b) => a.value.localeCompare(b.value));
  }
  return TIME_OPTIONS;
}

// Custom time picker. Opens a scrollable list positioned so the current value
// is at the TOP of the visible area — scroll down for later times, scroll up
// for earlier times. Falls back to "— time —" placeholder when empty.
function TimeDropdown({ value, onChange, placeholder }) {
  const [open, setOpen] = scheduleUseState(false);
  const containerRef = scheduleUseRef(null);
  const listRef = scheduleUseRef(null);
  const ITEM_H = 34;
  const VISIBLE = 7;

  const opts = buildTimeOpts(value);
  const displayLabel = value
    ? (opts.find(o => o.value === value)?.label || value)
    : (placeholder || '— time —');

  // Close on outside click
  scheduleUseEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  // Escape key closes
  scheduleUseEffect(() => {
    if (!open) return;
    const handler = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open]);

  // Scroll so the current time is the first visible item
  scheduleUseEffect(() => {
    if (!open || !listRef.current) return;
    const i = value ? opts.findIndex(o => o.value === value) : 0;
    listRef.current.scrollTop = Math.max(0, i) * ITEM_H;
  }, [open]);

  return (
    <div ref={containerRef} className="time-dropdown-wrap">
      <div
        className={`ep-select time-dropdown-trigger${open ? ' open' : ''}${!value ? ' placeholder' : ''}`}
        role="button" tabIndex={0} aria-haspopup="listbox" aria-expanded={open}
        onClick={() => setOpen(o => !o)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(o => !o); } }}
      >
        {displayLabel}
      </div>
      <HubCollapse open={open} float>
        <div
          ref={listRef}
          className="time-dropdown-list"
          role="listbox"
          style={{ height: `${ITEM_H * VISIBLE}px` }}
        >
          {opts.map(o => (
            <div
              key={o.value}
              className={`time-dropdown-item${o.value === value ? ' active' : ''}`}
              style={{ height: `${ITEM_H}px`, lineHeight: `${ITEM_H}px` }}
              role="option" aria-selected={o.value === value} tabIndex={-1}
              onMouseDown={(e) => { e.preventDefault(); onChange(o.value); setOpen(false); }}
              onKeyDown={(e) => { if (e.key === "Enter") { onChange(o.value); setOpen(false); } }}
            >
              {o.label}
            </div>
          ))}
        </div>
      </HubCollapse>
    </div>
  );
}

function Schedule({ schedule, selectedIso, onSelectDay, view }) {
  // Optimistic done-state overrides keyed by task_key; the server `done` on each
  // event is the base truth. Completing/reopening writes through to the canonical
  // task store, which also updates the planner mirror and any linked calendar
  // event or wiki node. (Replaces the old localStorage-only schedule done-state.)
  const [overrides, setOverrides] = scheduleUseState({});

  const toggle = async (taskId, currentlyDone) => {
    if (!taskId) return;
    setOverrides((prev) => ({ ...prev, [taskId]: !currentlyDone }));
    const url = currentlyDone ? "/api/tasks/reopen" : "/api/tasks/complete";
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: taskId }),
      });
      if (!res.ok) throw new Error("toggle failed");
    } catch {
      setOverrides((prev) => ({ ...prev, [taskId]: currentlyDone }));  // revert on failure
    }
  };

  const [modal, setModal] = scheduleUseState(null);

  const openModal = (event, date) => {
    if (event) {
      setModal({ mode: 'edit', event });
    } else {
      setModal({ mode: 'create', date: date || new Date().toISOString().slice(0, 10) });
    }
  };
  const closeModal = () => setModal(null);

  // The backend sends a -7..+7 window for the today zone. On home the today zone
  // owns today's calendar, so this panel runs FORWARD-only (tomorrow → +7) and the
  // panel's day blocks never include today. Without view="forward" it keeps the
  // original yesterday → +6 band (standalone-safe default).
  const forward = view === "forward";
  const todayIdx = schedule.findIndex((d) => d.isToday);
  const band = todayIdx >= 0
    ? (forward
        ? schedule.slice(todayIdx + 1, todayIdx + 8)
        : schedule.slice(Math.max(0, todayIdx - 1), todayIdx + 7))
    : schedule.slice(forward ? 1 : 0, 8);
  const metaLabel = forward ? "next 7 days" : "8 days";

  return (
    <>
      <div className={forward ? "panel fixed" : "panel flex"}>
        {forward ? (
          // Home view: the today zone above already owns today's calendar, so this
          // forward panel is just tomorrow → +7 flowing under it as one continuous
          // schedule column. It renders NO "schedule" panel-head — a header wedged
          // between today and the following days reads as a disconnect. No standalone
          // add affordance either — creating an event happens via the per-day "add
          // event" ghost row below.
          null
        ) : (
          <div className="panel-head">
            <div className="panel-head-l">
              <h2 className="panel-title">schedule</h2>
              <span className="panel-meta">{metaLabel}</span>
            </div>
            <button type="button" className="add-btn" onClick={() => openModal(null, null)} title="new event">+</button>
          </div>
        )}
        <div className={forward ? "panel-body" : "panel-body scroll"}>
          {band.map((d, di) => (
            <DayBlock key={d.isoDate || di} day={d} dayIdx={di} overrides={overrides} toggle={toggle} openModal={openModal} selectedIso={selectedIso} onSelectDay={onSelectDay} />
          ))}
        </div>
      </div>

      {modal && (
        <EventModal modalState={modal} onClose={closeModal} onSaved={() => window.location.reload()} />
      )}
    </>
  );
}

function DayBlock({ day, overrides, toggle, openModal, selectedIso, onSelectDay }) {
  // Yesterday is the one past day: it renders as a collapsed strip (header only)
  // and expands on click. Today stays the first full block.
  const isPast = day.label === "yesterday";
  const [expanded, setExpanded] = scheduleUseState(false);
  const collapsed = isPast && !expanded;
  const n = day.events.length;
  const isSelected = !!onSelectDay && day.isoDate === selectedIso;

  const dayClass = `day${day.isToday ? " is-today" : ""}${isPast ? " is-past" : ""}${isSelected ? " is-selected" : ""}`;
  const labelClass =
    isPast ? "past" :
    day.label === "today" ? "today" :
    day.label === "tomorrow" ? "tomorrow" : "future";
  // Clicking a day-head focuses the daily briefing on that day; a past day also
  // toggles its inline expansion.
  const headClickable = !!onSelectDay || isPast;
  const onHeadClick = () => {
    if (onSelectDay) onSelectDay(day.isoDate);
    if (isPast) setExpanded(e => !e);
  };
  return (
    <div className={dayClass}>
      {/* biome-ignore lint/a11y/useAriaPropsSupportedByRole: aria-expanded is only set when isPast, and headClickable is `!!onSelectDay || isPast` — so isPast true implies headClickable true implies role="button". Two ternaries biome can't correlate, but the condition below is a strict subset. */}
      <div
        className={`day-head${isPast ? " day-head-toggle" : ""}${headClickable ? " day-head-clickable" : ""}`}
        onClick={headClickable ? onHeadClick : undefined}
        role={headClickable ? "button" : undefined}
        tabIndex={headClickable ? 0 : undefined}
        aria-expanded={isPast ? expanded : undefined}
        onKeyDown={headClickable ? (e) => {
          if (e.key === "Enter") onHeadClick();
          else if (e.key === " ") { e.preventDefault(); onHeadClick(); }
        } : undefined}
        title={onSelectDay ? "show this day in the briefing" : undefined}
      >
        <span className={`day-label ${labelClass}`}>
          {isPast && <span className="day-caret">{expanded ? "▾" : "▸"}</span>}
          {day.label}
        </span>
        <span className="day-date">
          {collapsed ? (n ? `${n} event${n === 1 ? "" : "s"}` : "no events") : day.date}
        </span>
      </div>
      <HubCollapse open={!collapsed}>
      {day.events.map((e, ei) => {
        const done = e.taskId && (e.taskId in overrides) ? overrides[e.taskId] : !!e.done;
        return (
          <EventRow
            key={ei}
            event={e}
            done={done}
            completable={!!e.taskId}
            onToggle={() => toggle(e.taskId, done)}
            onEdit={() => e.sub === 'cal' && openModal(e)}
          />
        );
      })}
      <button
        type="button"
        className="event-row-ghost"
        onClick={() => openModal(null, day.isoDate)}
      >
        <span className="ghost-time">—</span>
        <span className="ghost-pip"></span>
        <span className="ghost-label">add event</span>
      </button>
      </HubCollapse>
    </div>
  );
}

// Text on a box in the event's Google colour: black wherever black holds 3.5:1,
// white only on the dark ones (Blueberry, Grape, Graphite). 2026-10-20: white on
// Banana, Sage, Flamingo, Peacock, Tangerine, Lavender fell under 4.5:1 and he asked
// for black; then he picked black on Tomato too (3.8:1) so every box matches.
// WCAG relative luminance of a #rrggbb colour, null when it is not one
function hexLuminance(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return null;
  return [0, 2, 4].map(i => parseInt(m[1].slice(i, i + 2), 16) / 255)
    .map(c => c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
    .reduce((s, c, i) => s + c * [0.2126, 0.7152, 0.0722][i], 0);
}
function eventInk(hex) {
  const L = hexLuminance(hex);
  if (L == null) return '#fff';
  return (L + 0.05) / 0.05 >= 3.5 ? '#000' : '#fff';
}

function EventRow({ event, done, completable, onToggle, onEdit }) {
  const tint = event.color ? ' tinted' : '';
  const tintStyle = event.color ? { '--ev-c': event.color, '--ev-ink': eventInk(event.color) } : {};
  if (event.task) {
    // Every Tomato event is completable — all-day and timed alike get a taskId
    // from sync_event, so the pip is interactive in both cases (a timed task
    // sits in its own time slot). The static-pip branch below is defensive only,
    // for the rare task event that somehow lacks a linked row.
    return (
      <div
        className={`event-row task cal-editable${done ? ' done' : ''}${tint}`}
        style={{ cursor: 'pointer', ...tintStyle }}
        onClick={onEdit}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter") onEdit();
          else if (e.key === " ") { e.preventDefault(); onEdit(); }
        }}
      >
        <span className="event-time">{event.time}</span>
        {/* biome-ignore lint/a11y/useAriaPropsSupportedByRole: role and aria-checked below both key off the same `completable` condition, so aria-checked is only set when role="checkbox" — biome can't correlate the two ternaries even though the conditions match. */}
        <span
          className={`event-pip${completable ? '' : ' event-pip-static'}`}
          title={completable ? (done ? 'mark undone' : 'mark done') : 'scheduled task'}
          onClick={completable ? (ev) => { ev.stopPropagation(); onToggle(); } : undefined}
          role={completable ? "checkbox" : undefined}
          aria-checked={completable ? done : undefined}
          tabIndex={completable ? 0 : undefined}
          onKeyDown={completable ? (ev) => {
            if (ev.key === "Enter") { ev.stopPropagation(); onToggle(); }
            else if (ev.key === " ") { ev.preventDefault(); ev.stopPropagation(); onToggle(); }
          } : undefined}
        ></span>
        <span className="event-name">{event.name}{event.rolled && <sup className="event-rolled" title="after midnight — counts to this night">+1</sup>}</span>
        <span className="task-flag">task</span>
      </div>
    );
  }
  const isEditable = event.sub === 'cal';
  // "cal" is just "this is a calendar event, not a task" — wasted space, so drop
  // it. Any other sub (e.g. "trip") still renders under the name.
  const sub = event.sub && event.sub !== 'cal' ? event.sub : '';
  // Show the end time only when it's real and different from the start. It stacks
  // under the start time as a transit-style timeline: a dot at each time joined
  // by a vertical line, like a train route to the next station.
  const hasEnd = event.timeEnd && event.timeEnd !== event.time;
  return (
    <div
      className={`event-row${hasEnd ? ' has-end' : ''}${isEditable ? ' cal-editable' : ''}${tint}`}
      onClick={isEditable ? onEdit : undefined}
      style={{ cursor: isEditable ? 'pointer' : 'default', ...tintStyle }}
      role={isEditable ? "button" : undefined}
      tabIndex={isEditable ? 0 : undefined}
      onKeyDown={isEditable ? (e) => {
        if (e.key === "Enter") onEdit();
        else if (e.key === " ") { e.preventDefault(); onEdit(); }
      } : undefined}
    >
      <span className="event-time">{event.time}</span>
      {hasEnd
        ? <span className="event-pipline">
            <span className="event-pip"></span>
            <span className="event-line"></span>
            <span className="event-pip event-pip-end"></span>
          </span>
        : <span className="event-pip"></span>}
      <span className="event-name-cell">
        <div className="event-name">{event.name}{event.rolled && <sup className="event-rolled" title="after midnight — counts to this night">+1</sup>}</div>
        {sub && <div className="event-sub">{sub}</div>}
      </span>
      {hasEnd && <span className="event-time event-time-end">{event.timeEnd}</span>}
    </div>
  );
}

function EventModal({ modalState, onClose, onSaved }) {
  const isEdit = modalState.mode === 'edit';
  const ev = modalState.event || {};

  const parseDate = (dtStr) => dtStr ? dtStr.slice(0, 10) : '';
  const parseTime = (dtStr) => {
    if (!dtStr || dtStr.length < 16) return '';
    return dtStr.slice(11, 16);
  };
  const addOneHour = (t) => {
    if (!t) return '';
    try {
      const [h, m] = t.split(':').map(Number);
      return `${String((h + 1) % 24).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
    } catch { return ''; }
  };
  const addOneDay = (d) => {
    if (!d) return '';
    try {
      const dt = new Date(`${d}T00:00:00`);
      dt.setDate(dt.getDate() + 1);
      return dt.toISOString().slice(0, 10);
    } catch { return d; }
  };

  const initStartDate = isEdit ? (parseDate(ev.startDt) || ev.date || '') : (modalState.date || new Date().toISOString().slice(0, 10));
  const initStartTime = isEdit ? parseTime(ev.startDt) : '';
  const initEndDate   = isEdit ? (parseDate(ev.endDt) || ev.date || '') : (modalState.date || new Date().toISOString().slice(0, 10));
  const initEndTime   = isEdit ? parseTime(ev.endDt) : '';

  const [title, setTitle]             = scheduleUseState(isEdit ? (ev.name || '') : '');
  const [allDay, setAllDay]           = scheduleUseState(isEdit ? (ev.allDay || false) : false);
  const [startDate, setStartDate]     = scheduleUseState(initStartDate);
  const [startTime, setStartTime]     = scheduleUseState(initStartTime);
  const [endDate, setEndDate]         = scheduleUseState(initEndDate);
  const [endTime, setEndTime]         = scheduleUseState(initEndTime);
  const [description, setDescription] = scheduleUseState(isEdit ? (ev.description || '') : '');
  const [calendarId, setCalendarId]   = scheduleUseState(isEdit ? (ev.calendarId || 'primary') : 'primary');
  const [calendars, setCalendars]     = scheduleUseState([]);
  const [saving, setSaving]           = scheduleUseState(false);
  const [saved, setSaved]             = scheduleUseState(false);
  const [error, setError]             = scheduleUseState('');

  // ── date/time helpers: auto-fill so the end never lags the start ──
  // setting the start date pulls a stale/empty end forward to match
  const applyStartDate = (d) => {
    setStartDate(d);
    setEndDate(prev => (!prev || prev < d) ? d : prev);
  };
  // setting the start time seeds an empty end time with start + 1h, and on the
  // same day pulls a now-too-early end up to at least the start ("HH:MM" 24h
  // strings sort lexicographically, so a string compare is the time compare)
  const applyStartTime = (t) => {
    setStartTime(t);
    setEndTime(prev => {
      if (!prev) return addOneHour(t);
      const sameDay = !endDate || endDate === startDate;
      return (sameDay && t && prev < t) ? t : prev;
    });
  };

  scheduleUseEffect(() => {
    fetch('/api/calendar/calendars')
      .then(r => r.json())
      .then(data => { if (Array.isArray(data)) setCalendars(data); })
      .catch(() => {});
  }, []);

  const dref = useDialogA11y(onClose);

  const buildEventBody = () => {
    if (allDay) {
      return {
        summary: title.trim(),
        start: { date: startDate },
        end: { date: addOneDay(endDate || startDate) },
        description,
      };
    }
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return {
      summary: title.trim(),
      start: { dateTime: `${startDate}T${startTime || '09:00'}:00`, timeZone: tz },
      end:   { dateTime: `${endDate || startDate}T${endTime || addOneHour(startTime) || '10:00'}:00`, timeZone: tz },
      description,
    };
  };

  // pull a human message out of a failed response; fall back to the status
  const errorFrom = async (res, fallback) => {
    try {
      const d = await res.json();
      if (d?.error) return d.error;
    } catch { /* non-JSON body */ }
    return `${fallback} (HTTP ${res.status})`;
  };

  const handleSave = async () => {
    if (!title.trim()) return;
    setSaving(true);
    setError('');
    try {
      const eventBody = buildEventBody();
      const res = isEdit
        ? await fetch(`/api/calendar/events/${ev.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ calendar_id: calendarId, event: eventBody }),
          })
        : await fetch('/api/calendar/events', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ calendar_id: calendarId, event: eventBody }),
          });
      if (!res.ok) {
        setError(await errorFrom(res, 'could not save event'));
        setSaving(false);
        return;
      }
      // flip to the faded "✓ saved" confirmation, then reload so the new/edited
      // event shows up in the schedule
      setSaved(true);
      setTimeout(onSaved, 900);
    } catch {
      setError('network error — could not reach the calendar');
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setSaving(true);
    setError('');
    try {
      const res = await fetch(`/api/calendar/events/${ev.id}`, { method: 'DELETE' });
      if (!res.ok) {
        setError(await errorFrom(res, 'could not delete event'));
        setSaving(false);
        return;
      }
      onSaved();
    } catch {
      setError('network error — could not reach the calendar');
      setSaving(false);
    }
  };

  const calName = calendars.find(c => c.id === calendarId)?.summary || '';

  return (
    <div className="hub-modal-scrim event-scrim" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="event-panel" ref={dref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={isEdit ? 'edit event' : 'new event'}>
        <div className="ep-head">
          <span className="ep-title">{isEdit ? 'edit event' : 'new event'}</span>
          {isEdit && calName && <span className="ep-cal-name">{calName}</span>}
        </div>
        <div className="ep-body">
          <div className="ep-field">
            <label className="ep-label" htmlFor="ep-title-input">title</label>
            {/* no autoFocus here — it's the first focusable control in the dialog,
                so useDialogA11y's own mount effect (dref, above) already focuses it */}
            <input
              id="ep-title-input"
              className="ep-input"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="event title"
            />
          </div>

          <div
            className="ep-allday-row"
            role="checkbox"
            aria-checked={allDay}
            tabIndex={0}
            onClick={() => setAllDay(a => !a)}
            onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setAllDay(a => !a); } }}
          >
            <div className={`ep-toggle${allDay ? ' on' : ''}`}></div>
            <span className="ep-allday-label">all day</span>
          </div>

          <div className="ep-field">
            {/* not a control label — "date & time" groups four separate inputs below,
                so it's a section heading, not associable with one field */}
            <span className="ep-label">date &amp; time</span>
            <div className="ep-sublabel">start</div>
            <div className="ep-row-2">
              <input className="ep-input ep-dt" type="date" value={startDate} onChange={e => applyStartDate(e.target.value)} />
              {!allDay
                ? <TimeDropdown value={startTime} onChange={applyStartTime} />
                : <div />}
            </div>
            <div className="ep-dt-sep" />
            <div className="ep-sublabel">end</div>
            <div className="ep-row-2">
              <input className="ep-input ep-dt" type="date" value={endDate} min={startDate || undefined} onChange={e => setEndDate(e.target.value)} />
              {!allDay
                ? <TimeDropdown value={endTime} onChange={setEndTime} />
                : <div />}
            </div>
          </div>

          <div className="ep-divider" />

          <div className="ep-field">
            <label className="ep-label" htmlFor="ep-description-input">description</label>
            <textarea id="ep-description-input" className="ep-textarea" value={description} onChange={e => setDescription(e.target.value)} placeholder="optional notes" />
          </div>

          <div className="ep-field">
            <label className="ep-label" htmlFor="ep-calendar-select">calendar</label>
            <select id="ep-calendar-select" className="ep-select" value={calendarId} onChange={e => setCalendarId(e.target.value)}>
              {calendars.length === 0
                ? <option value="primary">primary</option>
                : calendars.map(c => <option key={c.id} value={c.id}>{c.summary}</option>)}
            </select>
          </div>
        </div>

        {error && <div className="ep-error">{error}</div>}

        <div className="ep-foot">
          <div>
            {isEdit && (
              <button type="button" className="ep-btn-delete" onClick={handleDelete} disabled={saving}>delete</button>
            )}
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button type="button" className="ep-btn-cancel" onClick={onClose} disabled={saving || saved}>cancel</button>
            <button type="button"
              className={`ep-btn-save${saved ? ' is-saved' : ''}`}
              onClick={handleSave}
              disabled={saving || saved || !title.trim()}
            >{saved ? '✓ saved' : 'save'}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Schedule, EventModal, eventInk, hexLuminance });

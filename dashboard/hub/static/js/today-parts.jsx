/* Home today-briefing · 3 of 4: bring-list merging, the briefing summary, and the small presentational pieces the caps are built from.

   Split from today.jsx 2026-07-29 (1065 lines), which was itself split out of
   chrome.jsx the same day. index.html loads the four in this order and each is
   its own Babel script with its own scope, so every name another file needs is
   handed over explicitly through the Object.assign at the bottom, the same
   pattern chrome.jsx uses. React hooks are re-destructured per file for the
   same reason.
*/

function mergedBring(aggBring, wx) {
  const BL = window.BriefingLogic;
  const seen = new Set(aggBring.map((s) => s.toLowerCase()));
  const out = aggBring.map((label) => ({ label, weather: false }));
  for (const s of BL.weatherBring(wx)) {
    if (seen.has(s.toLowerCase())) continue;
    seen.add(s.toLowerCase());
    out.push({ label: s, weather: true });
  }
  return out;
}

// Case-insensitive union of two label arrays, first-seen casing wins. Used to
// fold a day's frozen snapshot bring/prep into the live-computed lists.
function unionLabels(a, b) {
  const out = [];
  const seen = new Set();
  for (const v of [...(a || []), ...(b || [])]) {
    const k = String(v).toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(v);
  }
  return out;
}

// bring list for a day: live event + weather bring (mergedBring, where weather is
// re-derived from `wx` — the frozen forecast on a past day), plus any extra items
// frozen in that day's snapshot (situation-derived, or preserved if the source
// event was edited away later). Snapshot extras carry no weather tag.
function mergedBringWithSnapshot(aggBring, wx, snap) {
  const live = mergedBring(aggBring, wx);
  if (!snap || !Array.isArray(snap.bring) || !snap.bring.length) return live;
  const seen = new Set(live.map((b) => b.label.toLowerCase()));
  const out = live.slice();
  for (const label of snap.bring) {
    const k = String(label).toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push({ label, weather: false });
  }
  return out;
}

function todayBriefingSummary({ now, schedule, tasks, cards, wx, snapshots, selectedIso }) {
  const BL = window.BriefingLogic;
  if (!BL) return "";
  const tIso = BL.localDayString(now);
  const selIso = selectedIso || tIso;
  const events = eventsForDay(schedule, selIso);
  const agg = BL.aggregateLabels(events);
  const due = BL.selectDueItemsForDay(tasks, cards, selIso, tIso);
  // live forecast if present, else the day's frozen snapshot (past days).
  const snap = (snapshots?.[selIso]) || null;
  const dayWx = ((wx?.byDate?.[selIso]) || snap) || null;
  return BL.buildSummary({
    eventCount: events.length,
    bringCount: mergedBringWithSnapshot(agg.bring, dayWx, snap).length,
    earliestLeave: agg.leave.length ? agg.leave[0].text : null,
    dueCount: due.tasks.length + due.cards.length,
  });
}

/* A tickable checklist row (bring/prep). Top-level so its identity is stable
   across the once-a-second TodayBriefing re-render. Completion is a client-side
   day-scoped flag (see TodayBriefing) — checking it strikes the row through; it
   does NOT write to any task/calendar store. `tag` carries an optional marker
   (e.g. "weather" for forecast-derived items). */
function CheckItem({ itemKey, label, tag, done, onToggle }) {
  return (
    <button
      type="button"
      className={`tb-li tb-check-li${done ? " is-done" : ""}`}
      aria-pressed={done}
      onClick={() => onToggle(itemKey)}
    >
      <span className="tb-check" aria-hidden="true">{done ? "✓" : ""}</span>
      <span className="tb-check-text">{label}</span>
      {tag ? <span className="tb-li-tag">{tag}</span> : null}
    </button>
  );
}

/* A tickable "due" row. Unlike CheckItem (bring/prep, client-side day flag), a
   due TASK completes for real: ticking it POSTs /api/tasks/complete and the
   parent re-hydrates so it drops off. Due CARDS (credit-card payments) have no
   complete endpoint, so they strike through client-side day-scoped like bring.
   `pill` is the optional overdue/today badge. Top-level for stable identity. */
function DueRow({ label, done, pill, onToggle }) {
  return (
    <button
      type="button"
      className={`tb-li tb-check-li${done ? " is-done" : ""}`}
      aria-pressed={done}
      onClick={onToggle}
    >
      <span className="tb-check" aria-hidden="true">{done ? "✓" : ""}</span>
      <span className="tb-check-text">{label}</span>
      {pill}
    </button>
  );
}

/* One packed card (due/bring/leave/prep/note). Top-level so its identity is
   stable across TodayBriefing re-renders; a nested definition would remount
   every tick. Renders nothing when its list is empty, unless it has a `placeholder`:
   then the card stays and says so. The `alert` flag flips the accent bar + badge to
   the alert color (used by `due` when overdue). */
function Card({ name, count, badge = count, alert, placeholder, after, children }) {
  if (!count && !placeholder) return null;
  return (
    <div className={`tb-card${alert ? " tb-card-alert" : ""}`}>
      <div className="tb-card-h">
        <span className="tb-card-name">{name}</span>
        {badge ? <span className="tb-card-badge">{badge}</span> : null}
      </div>
      <div className="tb-card-b">{count ? children : <div className="gt-none">{placeholder}</div>}{after}</div>
    </div>
  );
}

/* ---------------- Today zone (permanent) ----------------
   The today-briefing, promoted from the old collapsible AlwaysSeeTab drawer to a
   permanent zone: a full-width header (TodayHeader) plus a soft-accent cap atop
   each of the 3 body columns (TodayCalendarCap / the glance box / TodayPrepCap) that
   flows continuously into the column content below. computeTodayView derives
   everything once (pure, cheap); App calls it each tick and hands slices to the
   four pieces, so no state is shared across them. Reuses briefing.logic.js
   (selectDueItems / aggregateLabels / dayOffset / addDays) unchanged. */

Object.assign(window, { mergedBring, unionLabels, mergedBringWithSnapshot, todayBriefingSummary,
                        CheckItem, DueRow, Card });

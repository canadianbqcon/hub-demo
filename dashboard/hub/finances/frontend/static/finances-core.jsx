/* Finances · 1 of 5 (React): formatters, API helpers, the payee flip, the earnings tab (totals strip,
   expected forecast, grouped periods table) and the tab shell. Ported from finances.js lines 1-600
   and the template's body markup. Creates window.FinancesUI; the other four files assign into it and
   declare nothing else at top level. The plain page painted by hand with innerHTML; here each panel
   keeps its data in state and draws the same DOM and classes. The footer is the shared
   StatusStrip (topbar.jsx), which keeps its own clock. Every read
   keeps the plain page's failure behaviour (a failed totals read stays "loading...", a failed
   period list says so); a response that arrives after the table was rebuilt is dropped. */
window.FinancesUI = window.FinancesUI || {};
(() => {
  const { useState, useEffect, useRef } = React;
  const U = window.FinancesUI;

  const money = (v) => v == null ? "--" : `$${Number(v).toFixed(2)}`;
  // Exact cents, always (never rounded, see the money-shows-exact-cents rule), but
  // with thousands separators: "$8,250.40" reads at a glance where "$8250.40" does not.
  const moneyC = (v) => v == null ? "--" : (v < 0 ? "-$" : "$") +
    Math.abs(Number(v)).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const hrs   = (v) => v == null ? "--" : Number(v).toFixed(2);

  const MONTH_FULL = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];
  const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const DOW_NAME = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  // dates drop the year (it's the enclosing group) but keep month, since a period/shift can fall in another month.
  function fmtShortDate(iso) {
    const [, m, d] = iso.split("-");
    return `${MONTH_ABBR[Number(m) - 1]} ${Number(d)}`;
  }
  function fmtPeriod(start, end) {
    return `${fmtShortDate(start)} – ${fmtShortDate(end)}`;
  }

  // source is stored as a slug (data); display wants a proper name.
  // known exceptions (real names that aren't a plain title-case of their slug) go here,
  // everything else falls back to the generic hyphen->title-case conversion.
  const SOURCE_DISPLAY = {
    "juniper-and-co": "Juniper & Co",
    "isshiki-loulou": "Isshiki \u2014 LOULOU",
    "isshiki-salud-soho": "Isshiki \u2014 Salud SoHo",
    "nys-unemployment": "NYS Unemployment",
  };
  const TITLE_CASE_MINOR = new Set(["and", "of", "the", "or", "a", "an", "in"]);
  function sourceLabel(slug) {
    if (SOURCE_DISPLAY[slug]) return SOURCE_DISPLAY[slug];
    return slug.split("-")
      .map((w, i) => (i > 0 && TITLE_CASE_MINOR.has(w)) ? w : w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  }

  // "16:00" -> "4:00p". The hub's one clock shape (lowercase a/p, no space).
  // Anything that is not HH:MM passes through untouched, so a blank or free-text
  // window still prints itself instead of "NaN:NaNa".
  function fmtHM(hm) {
    const m = /^(\d{1,2}):(\d{2})/.exec(String(hm || "").trim());
    if (!m) return String(hm || "");
    const h = Number(m[1]);
    if (h > 23 || Number(m[2]) > 59) return String(hm);
    return `${h % 12 || 12}:${m[2]}${h < 12 ? "a" : "p"}`;
  }

  // "2026-12" -> "December 2026", the full name, for section headers (fmtMonth
  // is the abbreviated one used everywhere else).
  function fmtMonthFull(ym) {
    const [y, m] = ym.split("-");
    return `${MONTH_FULL[Number(m) - 1]} ${y}`;
  }
  // "2026-12-01" -> "Dec 2026". Projection months are always the 1st, so the day is noise.
  function fmtMonth(iso) {
    if (!iso) return "--";
    const [y, m] = iso.split("-");
    return `${MONTH_ABBR[Number(m) - 1]} ${y}`;
  }
  const money0 = (v) => v == null ? "--" : (v < 0 ? "-$" : "$") + Math.abs(Math.round(Number(v))).toLocaleString("en-US");
  // 1st 2nd 3rd 4th ... 11th 12th 13th ... 21st 22nd 23rd
  const ordinal = (n) => n + (["th", "st", "nd", "rd"][(n % 100 - 20) % 10] || ["th", "st", "nd", "rd"][n % 100] || "th");
  const pct = (v) => v == null ? "--" : `${Number(v).toFixed(2)}%`;
  const pct0 = (v) => v == null ? "--" : `${Number.isInteger(Number(v)) ? String(v) : Number(v).toFixed(2)}%`;
  function daysUntil(iso) {
    return Math.ceil((new Date(`${iso}T00:00:00`) - Date.now()) / 86400000);
  }
  // Fractions come off the API as 0..1; the page shows whole-ish percents.
  const share = (v) => v == null ? "--" : `${(v * 100).toFixed(1)}%`;
  // `many` covers the irregulars (person/people); everything else takes the "s".
  const plural = (n, word, many) => `${n} ${n === 1 ? word : (many || `${word}s`)}`;
  const dateRange = (a, b) => a === b ? fmtShortDate(a)
                                      : `${fmtShortDate(a)} – ${fmtShortDate(b)}`;
  function owedDate(iso) {
    if (!iso) return "";
    const [y, m, d] = iso.split("-");
    return `${MONTH_ABBR[Number(m) - 1]} ${Number(d)} ${y.slice(2)}`;
  }

  function postJSON(url, body, method) {
    return fetch(url, {
      method: method || "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then(res => res.json().catch(() => ({ error: "server said nothing" })));
  }
  const getJSON = (url) => fetch(url).then(r => r.json());

  Object.assign(U, { money, moneyC, hrs, MONTH_FULL, MONTH_ABBR, DOW_NAME, fmtShortDate, fmtPeriod, sourceLabel,
    fmtHM, fmtMonthFull, fmtMonth, money0, ordinal, pct, pct0, daysUntil, share, plural, dateRange, owedDate,
    postJSON, getJSON });


  // ── Payee ───────────────────────────────────────────────────────────────────
  // A payee shows its human title (PAYEE_SHORT, set in the template from book.db);
  // a click flips to the bank's own name and back.

  function Payee({ name }) {
    const [flipped, setFlipped] = useState(false);
    const short = PAYEE_SHORT[name];
    if (!short) return name || "--";
    return (
      <span className="payee-flip" data-alt={flipped ? short : name} title={name}
            onClick={e => { e.preventDefault(); setFlipped(f => !f); }}>{flipped ? name : short}</span>
    );   // preventDefault: a payee inside a <summary> flips without opening the row
  }
  U.Payee = Payee;

  // ── Totals ──────────────────────────────────────────────────────────────────

  function Totals({ state }) {
    const t = state.data;
    return (
      <section className="totals" id="totals">
        {[["week", "past week"], ["month", "past month"], ["ytd", "year to date"]].map(([scope, title]) => {
          const s = !state.loading && t ? t[scope] : null;
          let figs = <span className="figs-loading">loading...</span>;
          if (s) {
            const hrsLine = s.hours != null ? `${hrs(s.hours)} hrs` : null;
            const effLine = s.effective_hourly != null ? `${money(s.effective_hourly)}/hr` : null;
            const midParts = [hrsLine, effLine].filter(Boolean);
            figs = (
              <React.Fragment>
                <span className="net">{money(s.net)}</span>
                {midParts.length ? <span className="sub">{midParts.join(" · ")}</span> : null}
                {s.withheld != null ? <span className="sub">{`withheld ${money(s.withheld)}`}</span> : null}
              </React.Fragment>
            );
          }
          return (
            <div className="total-card" data-scope={scope} key={scope}>
              <h3>{title}</h3>
              <div className="figs">{figs}</div>
            </div>
          );
        })}
      </section>
    );
  }

  function BySource({ data }) {
    return (
      <section className="by-source" id="by-source">
        <h3>by source</h3>
        {/* the earnings table's figure columns (mark 2026-11-03); a figure a source has none of reads as a dash */}
        {!data ? null : data.by_source?.length ? (
          <table id="by-source-table">
            <thead><tr><th>source</th><th>hrs</th><th>eff $/hr</th><th>tax</th><th>gross</th><th>net</th></tr></thead>
            <tbody>{data.by_source.map(s => (
              <tr key={s.source}>
                <td>{sourceLabel(s.source)}</td>
                <td>{s.hours ? hrs(s.hours) : "—"}</td>
                <td>{s.hours ? `$${(s.gross / s.hours).toFixed(2)}` : "—"}</td>
                <td>{s.tax ? money(s.tax) : "—"}</td>
                <td>{money(s.gross)}</td>
                <td className="col-net">{money(s.net)}</td>
              </tr>))}</tbody>
          </table>
        ) : <p className="by-source-empty">no earnings recorded yet</p>}
      </section>
    );
  }

  // ── Expected (scheduled shifts × historical day-of-week average) ────────────
  // The forecast is one payload rendered at a chosen buyout multiple. A buyout tips
  // out on actual sales, so its pool is the one input nobody can measure ahead of
  // time, the slider rescales it client-side rather than asking the server, since
  // tips move linearly with it and every other input is fixed.

  // Only the buyout shift moves. Everything downstream is re-derived from the
  // shift list so the month cards and the paychecks can never disagree.
  function shiftsAt(week, mult, base) {
    const k = base ? mult / base : 1;
    return week.shifts.map(s => {
      if (s.shift_kind !== "buyout" || k === 1) return s;
      const tips = s.expected_tips * k;
      return Object.assign({}, s, { expected_tips: tips, expected_total: s.expected_wages + tips });
    });
  }

  function crewLabel(s) {
    const m = /(\d+) tipped coworker/.exec(s.pricing_note || "");
    if (s.shift_kind === "buyout") return "buyout";
    if (!m) return "--";
    const n = Number(m[1]);
    return n === 0 ? "alone" : `${n} on`;
  }

  // Same `assumed` vocabulary as the pricing-inputs table: a shift Sam
  // projected from a recurring pattern must not read like one J&Co actually posted.
  // roster_source is null on a row synced before migration 006, no chip, as before.
  function ShiftRows({ shifts }) {
    return shifts.map((s, i) => (
      <tr className={s.roster_source === "assumed" ? "assumed" : ""} key={i}>
        <td>{fmtShortDate(s.shift_date)}<span className="sr-dow"> {DOW_NAME[s.dow].slice(0, 3)}</span>
          {s.roster_source === "assumed"
            ? <React.Fragment>{" "}<span className="tag-assumed" title="projected from a recurring pattern &mdash; no posted roster covers this date">assumed</span></React.Fragment>
            : null}</td>
        <td className="win">{fmtHM(s.start_at)}&ndash;{fmtHM(s.end_at)}</td>
        <td className="num">{hrs(s.expected_hours)}</td>
        <td><span className={`crew${s.shift_kind === "buyout" ? " crew-buyout" : ""}`}
                  title={s.pricing_note || ""}>{crewLabel(s)}</span></td>
        <td className="num">{`${(s.model_share * 100).toFixed(1)}%`}</td>
        <td className="num dim">{moneyC(s.expected_wages)}</td>
        <td className="num dim">{moneyC(s.expected_tips)}</td>
        <td className="num strong">{moneyC(s.expected_total)}</td>
      </tr>));
  }

  // A week can be entirely projection, the per-row chips say which shifts, this says how much of the money it is.
  function AssumedNote({ w }) {
    const a = w.shifts.filter(s => s.roster_source === "assumed");
    if (!a.length) return null;
    const gross = a.reduce((t, s) => t + s.expected_total, 0);
    const all = a.length === w.shifts.length;
    return <p className="pw-assumed">{`${all ? "This whole paycheck is" : `${moneyC(gross)} of this paycheck is`}` +
      ` projected: ${a.length} ${a.length === 1 ? "shift is" : "shifts are"}` +
      ` a recurring-pattern guess, not a posted roster.`}</p>;
  }

  function Paychecks({ d, mult, base, openWeeks }) {
    const pay = d?.pay;
    if (!pay?.weeks?.length) {
      return (
        <div className="paychecks" hidden>
          <div className="paychecks-head">
            <h4>paychecks</h4>
            <span className="expected-note">Mon–Sun week, paid the Thursday after</span>
          </div>
          <ol className="pay-weeks"></ol>
        </div>
      );
    }
    const weeks = pay.weeks.map(w => {
      const shifts     = shiftsAt(w, mult, base);
      const shiftGross = shifts.reduce((a, s) => a + s.expected_total, 0);
      const shiftNet   = shiftGross * pay.withholding_ratio;
      // UI benefit tracks hours, not money, so it rides through the rescale untouched.
      const uiGross    = w.total_gross - w.shift_gross;
      const uiNet      = w.total_net   - w.shift_net;
      return Object.assign({}, w, { shifts, shiftGross, shiftNet, uiGross, uiNet,
               totalNet: shiftNet + uiNet, totalGross: shiftGross + uiGross });
    });
    const peak = Math.max(...weeks.map(w => w.totalNet), 1);
    return (
      <div className="paychecks">
        <div className="paychecks-head">
          <h4>paychecks</h4>
          <span className="expected-note">Mon–Sun week, paid the Thursday after</span>
        </div>
        <ol className="pay-weeks">
          {weeks.map(w => {
            const hours = w.shifts.reduce((a, s) => a + s.expected_hours, 0);
            const bits  = [`${w.shifts.length} ${w.shifts.length === 1 ? "shift" : "shifts"}`, `${hrs(hours)}h`];
            if (w.ui_effective_days) {
              bits.push(`${w.ui_effective_days} benefit ${w.ui_effective_days === 1 ? "day" : "days"}`);
            }
            return (
              <li className="pay-week" key={w.pay_date}>
                <details data-week={w.pay_date} open={openWeeks.has(w.pay_date)}
                         onToggle={e => { e.currentTarget.open ? openWeeks.add(w.pay_date) : openWeeks.delete(w.pay_date); }}>
                  <summary>
                    <span className="pw-caret" aria-hidden="true"></span>
                    <span className="pw-date">{fmtShortDate(w.pay_date)}</span>
                    <span className="hub-track pw-track" aria-hidden="true">
                      <span className="hub-bar pw-bar" style={{ "--pct": (w.totalNet / peak).toFixed(3) }}></span>
                    </span>
                    <span className="pw-net">{moneyC(w.totalNet)}</span>
                    <span className="pw-sub">{`${fmtPeriod(w.week_start, w.week_end)} · ${bits.join(" · ")}`}</span>
                  </summary>
                  <table className="dow-table shift-table">
                    <thead><tr><th>shift</th><th>window</th><th className="num">hrs</th><th>crew</th>
                      <th className="num">share</th><th className="num">wages</th><th className="num">tips</th>
                      <th className="num">total</th></tr></thead>
                    <tbody><ShiftRows shifts={w.shifts} /></tbody>
                  </table>
                  <p className="pw-split">{`shifts ${moneyC(w.shiftGross)} gross → ${moneyC(w.shiftNet)} net` +
                    (w.uiGross ? ` · unemployment ${moneyC(w.uiGross)} → ${moneyC(w.uiNet)} net` : "")}</p>
                  <AssumedNote w={w} />
                </details>
              </li>
            );
          })}
        </ol>
      </div>
    );
  }

  // Month cards are summed from the same rescaled shift list, not from the
  // server's month totals, so the slider can never leave the two disagreeing.
  function monthTotals(d, mult, base) {
    const out = {};
    for (const w of d.pay?.weeks || []) {
      for (const s of shiftsAt(w, mult, base)) {
        const k = `${s.month}|${s.source}`;
        out[k] = (out[k] || 0) + s.expected_total;
      }
    }
    return out;
  }

  function ExpMonths({ d, mult, base }) {
    const sums = monthTotals(d, mult, base);
    return d.months.map(m0 => {
      const sources = m0.sources.map(s => Object.assign({}, s, {
        expected_total: sums[`${m0.month}|${s.source}`] ?? s.expected_total }));
      const shiftTotal = sources.reduce((a, s) => a + s.expected_total, 0);
      const m = Object.assign({}, m0, { sources, shift_total: shiftTotal,
                  expected_total: shiftTotal + (m0.ui ? m0.ui.gross : 0) });
      // Shift income splits per job; UI is its own line. With one job and no UI the
      // breakdown just restates the total, so it only renders when there's a split.
      const parts = m.sources.map(s => [sourceLabel(s.source),
        `${s.scheduled_shifts} ${s.scheduled_shifts === 1 ? "shift" : "shifts"} · ${moneyC(s.expected_total)}`]);
      if (m.ui) {
        parts.push(["Unemployment",
          `${m.ui.effective_days} eff ${m.ui.effective_days === 1 ? "day" : "days"} · ${moneyC(m.ui.gross)}`]);
      }
      const missed = (d.sync_audit?.missed || []).filter(x => x.date.startsWith(m.month));
      return (
        <div className="exp-month" key={m.month}>
          <div className="exp-month-head"><h4>{fmtMonthFull(m.month)}</h4>
            {missed.length
              ? <span className="exp-flag exp-flag-warn" title={`on the calendar but not counted here \u2014 ` +
                  `${missed.map(x => `${x.date} ${x.summary}`).join(", ")}`}>{`${missed.length} missed?`}</span>
              : null}
            {m.shifts_assumed
              ? <span className="exp-flag" title="projected from a recurring pattern &mdash; no posted roster covers those dates">{`${m.shifts_assumed} projected`}</span>
              : null}
            {m.shifts_priced_by_fallback
              ? <span className="exp-flag" title="no history for that day of week &mdash; priced at the job's overall average">{`${m.shifts_priced_by_fallback} estimated`}</span>
              : null}</div>
          <div className="exp-total">{moneyC(m.expected_total)}</div>
          <div className="exp-sub">{`${m.scheduled_shifts} scheduled ${m.scheduled_shifts === 1 ? "shift" : "shifts"}` +
            (m.jobs > 1 ? ` · ${m.jobs} jobs` : "") +
            (m.ui ? ` · ${m.ui.weeks} benefit ${m.ui.weeks === 1 ? "week" : "weeks"}` : "")}</div>
          <div className="exp-srcs">{parts.length < 2 ? null : parts.map(([name, figs]) => (
            <span className="exp-src" key={name}>
              <span className="exp-src-name">{name}</span>
              <span className="exp-src-figs">{figs}</span>
            </span>))}</div>
        </div>
      );
    });
  }

  function Expected({ data }) {
    const d = data?.d;
    const pricing = data?.pricing;
    const base = data ? data.base : null;
    // the slider rests at the stored multiple until he moves it
    const [dragged, setMult] = useState(null);
    const mult = dragged != null ? dragged : (base || 1);
    const openWeeks = useRef(new Set()).current;

    const buyout = d ? (d.pay?.weeks || []).flatMap(w => shiftsAt(w, mult, base)).find(s => s.shift_kind === "buyout") : null;

    // Assumed inputs ship with verified=0 specifically so they can be labelled here;
    // a back-solved density must never read with the same authority as a paid rate.
    const pRows = d ? [
      ...(pricing?.points || []).map(p => [`${p.role.replace(/_/g, " ")} points`,
        String(p.points), p.verified, p.note]),
      // buyout_multiple is deliberately absent: it has its own labelled slider
      // right above, and listing a stored 2.5× beside a slider the user has
      // dragged to 3.5× reads as the page contradicting itself.
      ...(pricing?.params || []).filter(p => p.key !== "buyout_multiple")
        .map(p => [p.key.replace(/_/g, " "), `${moneyC(p.value)}/h`, p.verified, p.note]),
    ] : [];
    // avg / hr is the figure the fallback actually multiplies by (migration 007);
    // avg / shift stays visible beside it because it is what the sample really is.
    const perHr = r => (r.avg_hours ? moneyC(r.avg_shift_total / r.avg_hours) : "--");
    const uiShown = !!(d?.ui_claim && d.ui_weeks?.length);
    const c = uiShown ? d.ui_claim : null;

    return (
      <section className="expected" id="expected" hidden={!d}>
        <div className="expected-head">
          <h3>expected</h3>
          <span className="expected-note">shifts + unemployment</span>
        </div>
        <div className="expected-months">{d ? <ExpMonths d={d} mult={mult} base={base} /> : null}</div>

        <Paychecks d={d} mult={mult} base={base} openWeeks={openWeeks} />

        <div className="buyout-knob" hidden={!buyout}>
          <div className="knob-line">
            <label htmlFor="buyout-mult">buyout sales</label>
            {base
              ? <input type="range" id="buyout-mult" min="1.5" max="3.5" step="0.1"
                       aria-describedby="buyout-readout" value={mult}
                       onChange={e => setMult(Number(e.target.value))} />
              : <input type="range" id="buyout-mult" min="1.5" max="3.5" step="0.1"
                       aria-describedby="buyout-readout" />}
            <output id="buyout-readout" htmlFor="buyout-mult">{buyout ? `${fmtShortDate(buyout.shift_date)} pays ${moneyC(buyout.expected_total)}` : ""}</output>
          </div>
          <p className="knob-note">{buyout ? `${mult.toFixed(1)}× Sunday pool · ${moneyC(buyout.expected_tips)} tips · ${moneyC(buyout.expected_wages)} wages` : ""}</p>
        </div>

        <details className="expected-basis expected-inputs" hidden={!pRows.length}>
          <summary>inputs</summary>
          <table className="dow-table">
            <thead><tr><th>input</th><th className="hub-num">value</th><th>basis</th></tr></thead>
            <tbody>{pRows.map(([name, val, ok, note], i) => (
              <tr className={ok ? "" : "assumed"} key={i}>
                <td>{name}{ok ? null : <React.Fragment>{" "}<span className="tag-assumed">assumed</span></React.Fragment>}</td>
                <td className="hub-num">{val}</td>
                <td className="win">{note || ""}</td>
              </tr>))}</tbody>
          </table>
        </details>
        <details className="expected-basis expected-dow">
          <summary>day-of-week averages</summary>
          <p className="expected-note">unmodelled shift: hours × day avg / hr</p>
          <table className="dow-table">
            <thead><tr><th>job</th><th>day</th><th>avg / shift</th><th>avg / hr</th><th>shifts</th><th>sample window</th></tr></thead>
            <tbody>{d ? [
              ...d.dow_avg.map((r, i) => (
                <tr key={`d${i}`}>
                  <td>{sourceLabel(r.source)}</td>
                  <td>{DOW_NAME[r.dow]}</td>
                  <td className="hub-num">{moneyC(r.avg_shift_total)}</td>
                  <td className="hub-num strong">{perHr(r)}</td>
                  <td className="hub-num">{r.sample_shifts}</td>
                  <td className="win">{`${fmtShortDate(r.first_shift)} – ${fmtShortDate(r.last_shift)}`}</td>
                </tr>)),
              ...d.fallback_avg.map((r, i) => (
                <tr className="fb-row" key={`f${i}`}>
                  <td>{sourceLabel(r.source)}</td>
                  <td>any day</td>
                  <td className="hub-num">{moneyC(r.avg_shift_total)}</td>
                  <td className="hub-num strong">{perHr(r)}</td>
                  <td className="hub-num">{r.sample_shifts}</td>
                  <td className="win">used when that day has no history</td>
                </tr>)),
            ] : null}</tbody>
          </table>
        </details>
        <details className="expected-basis expected-ui" hidden={!uiShown}>
          <summary>unemployment, week by week</summary>
          <p className="ui-note">{c ? `${c.days_remaining} of ${Math.round(c.max_payable / c.day_rate)} effective days left` +
            ` · ${moneyC(c.day_rate)} each · claim ends ${c.benefit_year_end}` +
            ` · forecast stops at the last rostered shift (${c.horizon}), since an empty` +
            ` calendar past that means not-yet-scheduled, not a week off` : ""}</p>
          <table className="dow-table">
            <thead><tr><th>week ending</th><th className="hub-num">shifts</th><th className="hub-num">hours</th><th className="hub-num">eff. days</th><th className="hub-num">benefit</th><th></th></tr></thead>
            <tbody>{uiShown ? d.ui_weeks.map((w, i) => (
              <tr key={i}>
                <td>{fmtShortDate(w.week_end)}</td>
                <td className="hub-num">{w.shifts}</td>
                <td className="hub-num">{w.hours.toFixed(2)}</td>
                <td className="hub-num">{w.effective_days}</td>
                <td className="hub-num">{moneyC(w.gross)}</td>
                <td className="win">{w.capped_by_claim ? "claim exhausted mid-week" : ""}</td>
              </tr>)) : null}</tbody>
          </table>
        </details>
      </section>
    );
  }

  // ── Earnings table (grouped: year > month > period) ─────────────────────────

  // earnings arrive sorted desc (period_end DESC), grouping just buckets them, insertion order stays desc.
  function groupByYearMonth(earnings) {
    const years = new Map();
    for (const e of earnings) {
      const y = e.period_start.slice(0, 4);
      const m = e.period_start.slice(5, 7);
      if (!years.has(y)) years.set(y, new Map());
      const months = years.get(y);
      if (!months.has(m)) months.set(m, []);
      months.get(m).push(e);
    }
    return years;
  }

  // clock_in/out are ISO timestamps with an embedded local offset (e.g. "2026-07-12T15:49:00-04:00") ,
  // slice the wall-clock HH:MM straight out rather than going through Date/timezone conversion.
  function fmtTime(iso) {
    return fmtHM(iso.slice(11, 16));
  }

  // total tips = what actually lands in pocket: cash + cc net of processing fee.
  // null only when neither tip figure exists (untipped/salaried shift), so it reads "--" not "$0.00".
  function shiftTips(s) {
    if (s.cash_tips == null && s.cc_tips_net == null) return null;
    return (s.cash_tips || 0) + (s.cc_tips_net || 0);
  }

  // shift breakdown mirrors the period columns (hrs, eff $/hr, total) plus per-shift wage + total tips.
  // effective $/hr = shift_total / hours, the same gross/hours meaning the period's "eff $/hr" column uses.
  function ShiftsTable({ shifts }) {
    return (
      <table className="shift-table"><thead><tr>
        <th>date</th><th>hrs</th><th>$/hr</th><th>wage</th><th>tips</th><th>total</th>
      </tr></thead><tbody>{shifts.map((s, i) => {
        const day   = s.shift_date ? fmtShortDate(s.shift_date) : "";
        const times = (s.clock_in && s.clock_out) ? `${fmtTime(s.clock_in)}–${fmtTime(s.clock_out)}` : "";
        const eff   = (s.hours && s.hours > 0 && s.shift_total != null)
          ? `$${(s.shift_total / s.hours).toFixed(2)}` : "--";
        return (
          <tr title={s.note || undefined} key={i}>
            <td className="st-date">{day}{times ? <span className="st-times">{times}</span> : null}</td>
            <td>{hrs(s.hours)}</td>
            <td>{eff}</td>
            <td>{money(s.wage_pay)}</td>
            <td>{money(shiftTips(s))}</td>
            <td className="st-total">{money(s.shift_total)}</td>
          </tr>);
      })}</tbody></table>
    );
  }

  function DetailRow({ row }) {
    const shifts     = row.shifts     || [];
    const deductions = row.deductions || [];
    const parts = [];
    if (row.notes) {
      parts.push(<div className="shift-row-line detail-label" key="nl">note</div>);
      parts.push(<div className="shift-row-line" key="nt">{row.notes}</div>);
      parts.push(<div className="shift-row-line detail-sep" key="ns"></div>);
    }
    if (shifts.length > 0) parts.push(<ShiftsTable shifts={shifts} key="st" />);
    if (deductions.length > 0) {
      if (parts.length) parts.push(<div className="shift-row-line detail-sep" key="ds"></div>);
      parts.push(<div className="shift-row-line detail-label" key="dl">withholding</div>);
      deductions.forEach((d, i) => { parts.push(<div className="shift-row-line" key={`d${i}`}>{`${d.label}: ${money(d.amount)}`}</div>); });
    }
    if (!parts.length) parts.push(<div className="shift-row-line" style={{ fontStyle: "italic" }} key="nd">no detail available</div>);
    return <tr className="shift-detail"><td colSpan="7">{parts}</td></tr>;
  }

  // month/year header rows carry the same figure columns as their periods, so a
  // month reads at a glance without expanding it. eff $/hr = gross / hours, the
  // period column's meaning. Sums skip nulls the way the totals strip does.
  function GroupCells({ entries }) {
    let hours = 0, tax = 0, gross = 0, net = 0;
    for (const e of entries) {
      hours += e.hours || 0; tax += e.tax_withheld || 0;
      gross += e.gross || 0; net += e.net || 0;
    }
    const eff = hours > 0 ? `$${(gross / hours).toFixed(2)}` : "--";
    return (
      <React.Fragment>
        <td></td><td>{hrs(hours)}</td><td>{eff}</td><td>{money(tax)}</td>
        <td>{money(gross)}</td><td className="col-net">{money(net)}</td>
      </React.Fragment>
    );
  }

  // year/month/period rows are all click <tr>s with no native keyboard
  // activation, Enter/Space does the click.
  const rowKeys = (go) => (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault(); // Space otherwise scrolls the page
    go();
  };

  // Keyed by load: every (re)load of the list is a fresh table, as the plain page's innerHTML was.
  function PeriodsTable({ pstate, onAdd }) {
    // earnings arrive sorted desc, auto-expand every year/month group touched by the most recent 12 entries.
    const [expandedYears, setYears] = useState(() => new Set(pstate.list.slice(0, 12).map(e => e.period_start.slice(0, 4))));
    const [expandedMonths, setMonths] = useState(() => new Set(pstate.list.slice(0, 12).map(e => e.period_start.slice(0, 7)))); // keyed "YYYY-MM"
    const [details, setDetails] = useState({});               // eid -> detail row payload
    const gen = useRef(0);                                     // bumps whenever the table is rebuilt
    const busy = useRef(new Set());

    // a rebuilt table closes every open shift detail, as the plain page's re-render did
    const rebuilt = () => { gen.current++; setDetails({}); };
    const toggleYear = (y) => {
      const n = new Set(expandedYears);
      n.has(y) ? n.delete(y) : n.add(y);
      setYears(n);
      rebuilt();
    };
    const toggleMonth = (k) => {
      const n = new Set(expandedMonths);
      n.has(k) ? n.delete(k) : n.add(k);
      setMonths(n);
      rebuilt();
    };
    const toggleShifts = (eid) => {
      if (details[eid]) {
        setDetails(prev => { const n = Object.assign({}, prev); delete n[eid]; return n; });
        return;
      }
      if (busy.current.has(eid)) return;
      busy.current.add(eid);
      const g = gen.current;
      fetch(`/finances/api/earnings/${eid}`).then(r => r.json()).then(row => {
        busy.current.delete(eid);
        if (g !== gen.current) return;   // the table was rebuilt while this was loading
        setDetails(prev => Object.assign({}, prev, { [eid]: row }));
      }).catch(err => { busy.current.delete(eid); console.error("toggleShifts failed:", err); });
    };

    let body;
    if (pstate.status === "loading") {
      body = <tr><td colSpan="7" className="table-empty">loading...</td></tr>;
    } else if (pstate.status === "failed") {
      body = <tr><td colSpan="7" className="table-empty">failed to load earnings</td></tr>;
    } else if (!pstate.list.length) {
      body = <tr><td colSpan="7" className="table-empty">no earnings recorded yet &mdash; <button type="button" id="empty-add-cta" className="table-empty-cta" onClick={onAdd}>add your first entry</button></td></tr>;
    } else {
      body = [];
      for (const [year, months] of groupByYearMonth(pstate.list)) {
        const yOpen = expandedYears.has(year);
        body.push(
          <tr className="group-row year-row" data-year={year} tabIndex={0} aria-expanded={yOpen} key={`y${year}`}
              onClick={() => toggleYear(year)} onKeyDown={rowKeys(() => toggleYear(year))}>
            <td><span className="caret">{yOpen ? "▾" : "▸"}</span> {year}</td>
            <GroupCells entries={[...months.values()].flat()} />
          </tr>);
        if (!yOpen) continue;
        for (const [month, entries] of months) {
          const mKey = `${year}-${month}`;
          const mOpen = expandedMonths.has(mKey);
          body.push(
            <tr className="group-row month-row" data-month-key={mKey} tabIndex={0} aria-expanded={mOpen} key={`m${mKey}`}
                onClick={() => toggleMonth(mKey)} onKeyDown={rowKeys(() => toggleMonth(mKey))}>
              <td><span className="caret">{mOpen ? "▾" : "▸"}</span> {MONTH_FULL[Number(month) - 1]}</td>
              <GroupCells entries={entries} />
            </tr>);
          if (!mOpen) continue;
          for (const e of entries) {
            // effective hourly: gross / hours (works for all source types, fixes $0.00/hr on venture/investment)
            let eff = "--";
            if (e.hours && e.hours > 0 && e.gross != null) eff = `$${(e.gross / e.hours).toFixed(2)}`;
            const open = !!details[e.id];
            body.push(
              <tr className="period-row" data-eid={e.id} data-source-type={e.source_type || ""} tabIndex={0}
                  aria-expanded={open} key={`p${e.id}`}
                  onClick={() => toggleShifts(e.id)} onKeyDown={rowKeys(() => toggleShifts(e.id))}>
                <td><span className="caret">{open ? "▾" : "▸"}</span> {fmtPeriod(e.period_start, e.period_end)}</td>
                <td><span className="source-dot"></span>{sourceLabel(e.source)}</td>
                <td>{hrs(e.hours)}</td>
                <td>{eff}</td>
                <td>{money(e.tax_withheld)}</td>
                <td>{money(e.gross)}</td>
                <td className="col-net">{money(e.net)}</td>
              </tr>);
            if (open) body.push(<DetailRow row={details[e.id]} key={`d${e.id}`} />);
          }
        }
      }
    }
    return (
      <table id="periods-table">
        <thead><tr>
          <th>period</th>
          <th>source</th>
          <th>hrs</th>
          <th>eff $/hr</th>
          <th>tax</th>
          <th>gross</th>
          <th>net</th>
        </tr></thead>
        <tbody>{body}</tbody>
      </table>
    );
  }

  // ── Earnings panel ──────────────────────────────────────────────────────────

  function EarningsPanel({ active }) {
    const [totals, setTotals] = useState({ data: null, loading: true });
    const [expected, setExpected] = useState(null);
    const [pstate, setPstate] = useState({ id: 0, status: "loading", list: [] });
    const loads = useRef(0);
    const [manualOpen, setManualOpen] = useState(false);

    function loadTotals() {
      // Scoped to #totals: the spending panel reuses the same .total-card markup.
      setTotals(prev => ({ data: prev.data, loading: true }));
      return fetch("/finances/api/totals").then(r => r.json()).then(t => {
        setTotals({ data: t, loading: false });
      }).catch(err => { console.error("loadTotals failed:", err); });
    }

    function loadExpected() {
      return Promise.all([
        fetch("/finances/api/expected").then(r => r.json()),
        fetch("/finances/api/pricing").then(r => r.json()).catch(() => null),
      ]).then(([d, pricing]) => {
        if (!d.months?.length) return;   // no shifts on the calendar: stay hidden
        const param = (pricing?.params || []).find(p => p.key === "buyout_multiple");
        setExpected({ d, pricing, base: param ? param.value : null });
      }).catch(err => { console.error("loadExpected failed:", err); });
    }

    function loadPeriods() {
      setPstate({ id: ++loads.current, status: "loading", list: [] });
      return fetch("/finances/api/earnings").then(r => r.json()).then(({ earnings }) => {
        setPstate({ id: ++loads.current, status: "ready", list: earnings || [] });
      }).catch(err => {
        console.error("loadPeriods failed:", err);
        setPstate({ id: ++loads.current, status: "failed", list: [] });
      });
    }

    useEffect(() => { loadTotals(); loadExpected(); loadPeriods(); }, []);

    return (
      <div className="finances-main fin-panel" role="tabpanel" id="panel-earnings" aria-labelledby="tab-earnings" tabIndex={0} hidden={!active}>

        {/* ─── TOTALS STRIP ─── */}
        <Totals state={totals} />

        {/* ─── EXPECTED (scheduled shifts priced by the tip-pool model) ─── */}
        <Expected data={expected} />

        {/* ─── BY SOURCE ─── */}
        <BySource data={totals.data} />

        {/* ─── PERIODS TABLE ─── */}
        <section className="periods">
          <div className="periods-head">
            <h3>earnings</h3>
            <button id="add-toggle" type="button" aria-expanded={manualOpen} aria-controls="manual-wrap"
                    onClick={() => setManualOpen(o => !o)}>{`${manualOpen ? "− " : "+ "}manual entry`}</button>
          </div>

          {/* source-type dot legend, the dots on each period row otherwise carry meaning by color alone */}
          <div className="type-legend">
            <span className="hub-dot" style={{ "--dot-color": "var(--accent)" }}>venture</span>
            <span className="hub-dot" style={{ "--dot-color": "var(--good)" }}>salaried</span>
            <span className="hub-dot" style={{ "--dot-color": "var(--warn)" }}>tipped hourly</span>
            <span className="hub-dot" style={{ "--dot-color": "var(--violet-label)" }}>investment</span>
            <span className="hub-dot" style={{ "--dot-color": "var(--series-2)" }}>benefits</span>
          </div>

          <U.ManualForm open={manualOpen}
                        onSaved={() => { setManualOpen(false); return Promise.all([loadTotals(), loadPeriods()]); }} />

          <PeriodsTable key={pstate.id} pstate={pstate} onAdd={() => setManualOpen(o => !o)} />
        </section>

      </div>
    );
  }
  U.EarningsPanel = EarningsPanel;

  // ── Section tabs ────────────────────────────────────────────────────────────
  // Accessible tablist: click + arrow-key nav, deep-linkable via #earnings / #stocks.
  // Earnings loads on boot; each other tab loads the first time it is shown.

  const TABS = ["earnings", "spending", "debt", "owed", "stocks", "transactions"];
  U.TABS = TABS;

  function Tabs({ tab, select }) {
    return (
      <div className="hub-tabs fin-tabs" role="tablist" aria-label="finances sections"
           onKeyDown={e => {
             if (e.key === "Home") { e.preventDefault(); select(TABS[0], true); return; }
             if (e.key === "End") { e.preventDefault(); select(TABS[TABS.length - 1], true); return; }
             if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
             e.preventDefault();
             const i = TABS.indexOf(tab);
             select(TABS[(i + (e.key === "ArrowRight" ? 1 : -1) + TABS.length) % TABS.length], true);
           }}>
        {TABS.map(t => (
          <button className="hub-tab fin-tab" type="button" role="tab" id={`tab-${t}`} aria-controls={`panel-${t}`}
                  aria-selected={t === tab} tabIndex={t === tab ? 0 : -1} key={t}
                  onClick={() => select(t, false)}>{t}</button>))}
      </div>
    );
  }
  U.Tabs = Tabs;
})();

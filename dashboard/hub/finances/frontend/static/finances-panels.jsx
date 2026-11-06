/* Finances · 3 of 5 (React): the read-only panels, spending, debt (with its SVG payoff chart) and
   stocks. Ported from finances.js (stocks 731-872, debt 915-1374, spending 1376-1647). Each panel
   loads once, the first time its tab is shown (the `active` prop), and keeps the plain page's
   failure behaviour: spending retries when the tab is reopened after a failed read, debt and
   stocks do not. A response that answers a request no longer current (an older debt payment, an
   older stock) is dropped. Assigns into window.FinancesUI; declares nothing else at top level. */
(() => {
  const { useState, useEffect, useRef, useLayoutEffect } = React;
  const U = window.FinancesUI;
  const { moneyC, money0, fmtShortDate, fmtMonth, ordinal, pct, pct0, daysUntil, share, plural, dateRange,
          Payee } = U;

  const catTag = (t) => <React.Fragment>{" "}<span className="cat-tag">{t}</span></React.Fragment>;

  // ── Spending ────────────────────────────────────────────────────────────────
  // consumes: /finances/api/spending
  // Sister to earnings. YNAB is the ledger, so there is no local store to read ,
  // one fetch carries the whole tab and nothing here refetches on interaction.

  const SCOPE_LABEL = { week: "past week", month: "past month", ytd: "this year" };

  // The charges behind one row. Every band, and every category, opens to this.
  function SpendTxns({ txns }) {
    return (
      <table className="dow-table sp-txns"><tbody>{txns.map((t, i) => (
        <tr key={i}><td className="sp-t-date">{fmtShortDate(t.date)}</td>
          <td><Payee name={t.payee} /></td>
          <td className="sp-t-cat">{t.category || "(uncategorized)"}</td>
          <td className="num">{moneyC(t.amount)}</td></tr>
      ))}</tbody></table>
    );
  }

  // One expandable row: name + headline figure + the line of context under it.
  // `<details>` rather than a click handler and an open-set, the browser already
  // owns this widget, keyboard and all, and every band on the page needs it.
  function SpendRow({ r }) {
    return (
      <details className={`sp-row${r.dim ? " sp-dim" : ""}`}><summary>
        <span className="pw-caret"></span>
        <span className="sp-name"><Payee name={r.name} />{r.tag}</span>
        <span className="sp-fig">{r.fig}</span>
        <span className="sp-sub">{r.sub}</span>
      </summary><SpendTxns txns={r.txns} /></details>
    );
  }

  // Rows carrying `group` + `amt` are shown under one head per group, biggest group
  // first, its subtotal beside it (mark 2026-11-03 "group by category").
  function groupRows(rows, unitText) {
    const by = new Map();
    rows.forEach(r => { if (!by.has(r.group)) by.set(r.group, []); by.get(r.group).push(r); });
    const sum = rs => rs.reduce((a, r) => a + r.amt, 0);
    return [...by.entries()].sort((a, b) => sum(b[1]) - sum(a[1])).map(([g, rs]) => (
      <div className="sp-group" key={g}>
        <div className="sp-group-head"><span>{g}</span>
          <span className="sp-group-fig">{moneyC(sum(rs))}{unitText ? unit(unitText) : null}</span></div>
        {rs.map((r, i) => <SpendRow r={r} key={i} />)}
      </div>));
  }

  function Band({ id, title, note, fig, rows, empty, rest, groupUnit }) {
    return (
      <section className="by-source sp-band" id={id}>
        <div className="cat-head">
          <h3>{title}</h3>
          <span className="sp-band-fig">{fig}</span>
        </div>
        <p className="sp-band-note">{note}</p>
        <div className="sp-rows">{!rows ? null : rows.length
          ? (rows[0].group !== undefined ? groupRows(rows, groupUnit) : rows.map((r, i) => <SpendRow r={r} key={i} />))
          : <p className="by-source-empty">{empty}</p>}</div>
        {rest !== undefined ? <p className="sp-rest">{rest}</p> : null}
      </section>
    );
  }

  const unit = (v) => <span className="sp-band-unit">{v}</span>;

  function SpendTotals({ d }) {
    return (
      <section className="totals" id="spend-totals">
        {[["week", "past week"], ["month", "past month"], ["ytd", "year to date"]].map(([scope, title]) => {
          const s = d ? d.scopes[scope] : null;
          let figs = null;
          if (s) {
            // Spent is the headline because this is the spending tab, but it is useless
            // alone, the earned/left pair underneath is the whole reason the tab is a
            // sister to earnings rather than a standalone ledger view.
            const negative = s.net < 0;
            // A window with neither side in it yet is empty, not balanced. Printing a
            // green "left $0.00" on the 1st of a month reads as a month going well.
            const empty = !s.spent && !s.earned;
            figs = (
              <React.Fragment>
                <span className="net">{moneyC(s.spent)}</span>
                {empty
                  ? <span className="sub sp-excl">nothing recorded yet</span>
                  : <React.Fragment>
                      <span className="sub">{`earned ${moneyC(s.earned)}`}</span>
                      <span className={`sub ${negative ? "sp-under" : "sp-net"}`}>
                        {`${negative ? "over by " : "left "}${moneyC(Math.abs(s.net))}`}</span>
                    </React.Fragment>}
                {s.excluded ? <span className="sub sp-excl">{`+ ${moneyC(s.excluded)} not spending`}</span> : null}
                {s.card_payments ? <span className="sub sp-excl">{`card payments not counted: ${moneyC(s.card_payments)}`}</span> : null}
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

  function SpendTrend({ d }) {
    const t = d ? d.trend : null;
    return (
      <section className="periods" id="spend-trend">
        <div className="periods-head">
          <h3>trend</h3>
          <span className="pay-note" id="spend-trend-note">{t ? (t.latest_closed
            ? `${fmtMonth(t.latest_closed)} against the months before it` +
              (t.vs_peak != null ? ` · ${share(Math.abs(t.vs_peak))} ${t.vs_peak < 0 ? "below" : "above"} the ${fmtMonth(t.peak_month)} peak` : "")
            : "not enough closed months to compare yet") : ""}</span>
        </div>
        {/* Movers compare the latest CLOSED month against the months before it, the
            current month is excluded from both sides, or every category reads as a
            collapse for the first week of a month. */}
        <div className="sp-movers">{t ? t.movers.map((m, i) => (
          <span className={`sp-mover ${m.delta > 0 ? "sp-up" : "sp-down"}`} key={i}>
            {`${m.group} ${m.delta > 0 ? "+" : "−"}${moneyC(Math.abs(m.delta))}`}
            <span className="sp-mover-sub">{`${moneyC(m.now)} vs ${moneyC(m.baseline)} usual`}</span>
          </span>)) : null}</div>
        <div className="sp-trend-scroll">
          <table className="dow-table" id="spend-trend-table">
            <thead><tr>{t ? <React.Fragment><th>group</th>
              {t.months.map(m => <th className="hub-num" key={m}>{fmtMonth(m)}</th>)}</React.Fragment> : null}</tr></thead>
            <tbody>{t ? t.rows.map((r, i) => (
              <tr key={i}><td>{r.group}</td>
                {t.months.map(m => <td className="hub-num" key={m}>{r.by_month[m] ? moneyC(r.by_month[m]) : "--"}</td>)}
              </tr>)) : null}</tbody>
            <tfoot><tr>{t ? <React.Fragment><td>total</td>
              {t.months.map(m => <td className="hub-num" key={m}>{moneyC(t.totals[m])}</td>)}</React.Fragment> : null}</tr></tfoot>
          </table>
        </div>
      </section>
    );
  }

  function SpendingPanel({ active }) {
    const [d, setD] = useState(null);
    const [err, setErr] = useState(null);
    const [scope, setScope] = useState("month");
    const started = useRef(false);

    useEffect(() => {
      if (!active || started.current) return;
      started.current = true;
      fetch("/finances/api/spending").then(r => r.json()).then(data => {
        if (!data.configured) {
          setErr(data.error
            ? "could not read the book \u2014 see the server log."
            : "The book is not set up, so spending is unavailable. Sync the book and reload.");
          return;
        }
        setErr(null);
        setD(data);
      }).catch(e => {
        console.error("[spending] fetch failed", e);
        started.current = false;   // a network blip should not brick the tab until reload
        setErr("could not load spending \u2014 reopen the tab to retry.");
      });
    }, [active]);

    const cats = d ? (d.by_category[scope] || []) : null;
    return (
      <div className="spending-main fin-panel" role="tabpanel" id="panel-spending" aria-labelledby="tab-spending" tabIndex={0} hidden={!active}>

        <div className="hub-error" id="spend-error" aria-live="polite" hidden={!err}>{err}</div>

        {/* ─── TOTALS STRIP: mirrors earnings, but each card carries the pair: out, in, left ─── */}
        <SpendTotals d={d} />

        {/* ─── COMMITTED: what a month costs before he decides anything ─── */}
        <section className="sp-committed" id="spend-committed" hidden={!d}>{d ? <React.Fragment>
          <h3>committed</h3>
          <div className="sp-committed-fig">{moneyC(d.committed_monthly)}<span>/mo</span></div>
          <p className="sp-committed-note">{`what a month costs before any decision: ` +
            `${moneyC(d.subscriptions.monthly)} of subscriptions + ` +
            `${moneyC(d.recurring.monthly)} of recurring charges across ` +
            `${plural(d.recurring.rows.length, "payee")}.`}</p>
        </React.Fragment> : null}</section>

        {/* ─── THE THREE BANDS: descending order of how little say he has ───
            Each row opens to the charges behind it: no figure on this page is one
            he has to take on faith. */}
        <Band id="spend-subs" title="subscriptions"
              note={<React.Fragment>the YNAB <em>Subscriptions</em> group, priced at the most recent charge of each</React.Fragment>}
              fig={d ? <React.Fragment>{moneyC(d.subscriptions.monthly)}{unit("/mo")}</React.Fragment> : null}
              empty={d ? `nothing in the ${d.floor_group} group yet` : ""}
              rows={d ? d.subscriptions.lines.map(r => ({
                name: r.name,
                // A plan the ledger thinks stopped stays on the page, what he stopped
                // paying for is part of how he spends, but it stops counting toward the
                // monthly figure. A plan he has CONFIRMED cancelled never gets here.
                tag: <React.Fragment>{r.live ? null : catTag("stopped")}{r.cadence === "yearly" ? catTag("yearly") : null}</React.Fragment>,
                dim: !r.live,
                fig: <React.Fragment>{moneyC(r.monthly)}{unit("/mo")}</React.Fragment>,
                // A yearly plan's real charge is the number he recognizes on the card;
                // the /mo figure beside it is the twelfth that lets the floor add up.
                sub: `${r.cadence === "yearly" ? `${moneyC(r.charge)}/yr · ` : ""}` +
                     `${plural(r.count, "charge")} · ${moneyC(r.total)} so far · last ${fmtShortDate(r.last)}`,
                txns: r.txns,
              })) : null} />

        <Band id="spend-recurring" title="recurring"
              note="a payee seen in three or more months that is still charging; no single charge is a decision, the total is"
              fig={d ? <React.Fragment>{moneyC(d.recurring.monthly)}{unit("/mo")}</React.Fragment> : null}
              empty="no payee has charged in three separate months yet"
              groupUnit="/mo"
              rows={d ? d.recurring.rows.map(r => ({
                name: r.name,
                group: r.category, amt: r.monthly,
                fig: <React.Fragment>{moneyC(r.monthly)}{unit("/mo")}</React.Fragment>,
                sub: `${plural(r.count, "charge")} over ${plural(r.months, "month")} · ` +
                     `${moneyC(r.total)} total` +
                     (r.categories.length > 1 ? ` · also ${r.categories.filter(c => c !== r.category).join(", ")}` : ""),
                txns: r.txns,
              })) : null} />

        <Band id="spend-episodes" title="episodes" note="the one-off decisions, grouped by payee"
              fig={d ? <React.Fragment>{moneyC(d.episodes.total)}
                {d.episodes.share != null ? unit(` · ${share(d.episodes.share)} of everything chosen`) : null}</React.Fragment> : null}
              empty="no single decision big enough to name yet"
              rows={d ? d.episodes.rows.map(r => ({
                name: r.name,
                group: r.category, amt: r.total,
                tag: r.merged ? <React.Fragment>{" "}<span className="cat-tag">{r.payees.map((p, i) => (
                  <React.Fragment key={i}>{i ? " + " : null}<Payee name={p} /></React.Fragment>))}</span></React.Fragment> : null,
                fig: moneyC(r.total),
                sub: `${dateRange(r.first, r.last)} · ${plural(r.count, "charge")}` +
                     (r.categories.length > 1 ? ` · also ${r.categories.filter(c => c !== r.category).join(", ")}` : ""),
                txns: r.txns,
              })) : null}
              // The tail is a number, not a list: 200-odd payees below the threshold say
              // nothing individually and everything in aggregate.
              rest={d?.rest.payees ? `plus ${moneyC(d.rest.total)} spread across ${plural(d.rest.payees, "smaller payee")}` : ""} />

        {/* ─── TREND: group by month, plus what moved against his own baseline ─── */}
        <SpendTrend d={d} />

        {/* ─── BY CATEGORY: this month, biggest first ─── */}
        <section className="by-source" id="by-category">
          <div className="cat-head">
            <h3>by category</h3>
            {/* Every window is already in the payload, so switching is a re-render, not a fetch. */}
            <div className="seg" role="group" aria-label="category window">
              {["week", "month", "ytd"].map(s => (
                <button type="button" id={`cat-${s}`} className={s === scope ? "on" : undefined}
                        aria-pressed={s === scope} key={s} onClick={() => setScope(s)}>{s}</button>))}
            </div>
          </div>
          <div className="sp-rows">{!cats ? null : !cats.length
            ? <p className="by-source-empty">{`nothing spent ${SCOPE_LABEL[scope]} yet`}</p>
            : cats.map((c, i) => <SpendRow key={scope + i} r={{
              name: c.category,
              tag: c.excluded ? catTag("not spending") : null,
              dim: c.excluded,
              fig: moneyC(c.amount),
              sub: (c.share != null ? `${share(c.share)} · ` : "") +
                   `${plural(c.count, "charge")}${c.group ? ` · ${c.group}` : ""}`,
              txns: c.txns,
            }} />)}</div>
        </section>

        {/* ─── MONTH BY MONTH: the sister view: earned against spent, and what was left ─── */}
        <section className="periods">
          <div className="periods-head">
            <h3>month by month</h3>
          </div>
          <table id="spend-months-table">
            <thead><tr>
              <th>month</th>
              <th>earned</th>
              <th>spent</th>
              <th>left</th>
              <th>kept</th>
            </tr></thead>
            <tbody>{!d ? null : !d.months.length
              ? <tr><td colSpan="5" className="table-empty">no months in range</td></tr>
              : d.months.map(m => {
                // A month still running has spent less simply because it is not over. Saying
                // so beats letting the current month read as a good one every time it starts.
                const partial = !m.complete;
                const kept = m.earnings ? m.net / m.earnings : null;
                return (
                  <tr className={partial ? "sp-partial" : undefined} key={m.month}>
                    <td>{fmtMonth(m.month)}{partial ? catTag("in progress") : null}</td>
                    <td>{moneyC(m.earnings)}</td>
                    <td>{moneyC(m.spend)}</td>
                    <td className={m.net < 0 ? "sp-under" : "sp-net"}>{moneyC(m.net)}</td>
                    <td>{kept == null ? "--" : share(kept)}</td>
                  </tr>);
              })}</tbody>
          </table>
        </section>

        {/* ─── TRANSACTIONS: collapsed by design: 62% of the rows are 9% of the
            money, so the ledger is the last resort, not the view. ─── */}
        <section className="periods">
          <details id="spend-txns">
            <summary>
              <span className="pw-caret"></span>
              <span>transactions</span>
              <span className="pay-note" id="spend-window">{d ? `since ${fmtShortDate(d.since)}, from YNAB · ${d.transactions.length} rows` : ""}</span>
            </summary>
            <table id="spend-txn-table">
              <thead><tr>
                <th>date</th>
                <th>payee</th>
                <th>category</th>
                <th>amount</th>
              </tr></thead>
              <tbody>{!d ? null : !d.transactions.length
                ? <tr><td colSpan="4" className="table-empty">no outflows in range</td></tr>
                : d.transactions.map((t, i) => (
                  <tr className={d.not_spend.includes(t.category) ? "sp-excluded-row" : undefined} key={i}>
                    <td>{fmtShortDate(t.date)}</td>
                    <td><Payee name={t.payee} /></td>
                    <td>{t.category || "(uncategorized)"}</td>
                    <td>{moneyC(t.amount)}</td>
                  </tr>))}</tbody>
            </table>
          </details>
        </section>

      </div>
    );
  }
  U.SpendingPanel = SpendingPanel;

  // ── Debt ────────────────────────────────────────────────────────────────────
  // consumes: /finances/api/debt, /finances/api/budget, /finances/api/debt/scenarios
  // Live YNAB balances merged with the terms in cards.db, projected by finances/debt.py.

  // The monthly payment he types sticks across reloads. Per browser, not per
  // device, localStorage is the whole store; a settings table would be a database
  // for one number.
  const BUDGET_KEY = "hub.debt.budget";

  function savedBudget() {
    try {
      const v = parseFloat(localStorage.getItem(BUDGET_KEY));
      return Number.isFinite(v) && v >= 0 ? v : null;
    } catch { return null; }   // private mode / storage disabled
  }

  function saveBudget(v) {
    try {
      if (v == null) localStorage.removeItem(BUDGET_KEY);
      else localStorage.setItem(BUDGET_KEY, String(v));
    } catch { /* not worth breaking the tab over */ }
  }

  // Card names are long; cliff labels are not wide. Drop the issuer, keep what tells
  // the cards apart. The loan is named first so the generic issuer strip can't reduce
  // "My Chase Loan" to a bare "Loan".
  function shortName(n) {
    if (/^my chase loan$/i.test(n)) return "Chase Loan";
    return n.replace(/^(Chase|CitiBank|Citi|Discover It|Discover|Amex|American Express)\s+/i, "").trim() || n;
  }

  // ── Payoff timeline ─────────────────────────────────────────────────────────
  // One lane per card carrying a balance: a bar from this month to the month the
  // card clears, so "which card dies when" is read off lane order and bar length,
  // and raising the payment visibly shortens the bars. A promo cliff is a dashed
  // line across every lane; the part of a bar past it is drawn in the alert colour,
  // because that is money still owed at the full rate. A thin total-owed line
  // underneath keeps the debt-free date on the same axis.

  const PAD = { t: 24, r: 76, b: 26 };
  const LANE = 34, TOTAL_H = 44;
  const GAP = 6;

  function DebtChart({ d }) {
    const wrapRef = useRef(null);
    const svgRef = useRef(null);
    const [cw, setCw] = useState(0);
    const [hover, setHover] = useState(null);   // { i, px, boxW } while the pointer is on the chart
    // The SVG scales to its container, so draw at the container's width: measure after
    // every render, and again (debounced) when the window resizes. A hidden tab measures 0;
    // it keeps the last real width and re-measures when it is shown again.
    useLayoutEffect(() => {
      const w = wrapRef.current ? wrapRef.current.clientWidth : 0;
      if (w && w !== cw) setCw(w);
    });
    useEffect(() => {
      let t;
      const onResize = () => {
        clearTimeout(t);
        t = setTimeout(() => { if (wrapRef.current?.clientWidth) setCw(wrapRef.current.clientWidth); }, 150);
      };
      window.addEventListener("resize", onResize);
      return () => { window.removeEventListener("resize", onResize); clearTimeout(t); };
    }, []);

    const timeline = d ? (d.timeline || []) : [];
    // Earliest payoff on top: the lanes read in the order the cards die.
    const cards = d ? (d.cards || []).filter(c => c.balance > 0.005)
      .sort((a, b) => (a.payoff_date || "9999") < (b.payoff_date || "9999") ? -1 : 1) : [];
    const empty = !!d && (!timeline.length || !cards.length);

    let svgProps = { id: "debt-chart", role: "img", "aria-labelledby": "debt-chart-title" };
    let kids = null;
    let tip = null;
    if (d && !empty) {
      const W = Math.max(320, cw || 720);
      const labelW = W < 640 ? 150 : 230;
      const n = timeline.length;
      const iw = W - labelW - PAD.r;
      // Month i occupies the column [x(i), x(i+1)); the plot spans the whole projection.
      const x = (i) => labelW + i / n * iw;
      const monthIdx = (iso) => timeline.findIndex(m => m.month.slice(0, 7) === iso.slice(0, 7));
      const cliffX = (c) => {
        if (!c.promo_end || c.promo_apr == null) return null;
        const i = monthIdx(c.promo_end);
        if (i < 0) return null;
        const day = Number(c.promo_end.slice(8, 10)) || 1;
        return x(i) + (x(i + 1) - x(i)) * (day - 1) / 30;
      };
      // The bar ends part-way through its payoff month, by the share of that month's
      // money the card needed, so a $50 change moves it instead of snapping a column.
      const endX = (c) => {
        const pi = c.payoff_date ? monthIdx(c.payoff_date) : -1;
        if (c.never_pays_off || pi < 0) return x(n);
        return x(pi) + (x(pi + 1) - x(pi)) * (c.payoff_frac ?? 1);
      };
      // Two promos ending a few months apart put their labels on top of each other, so
      // each label takes the first row up where it clears the ones already placed and the
      // plot moves down a row for every extra row used. Width is estimated, not measured
      // (10px text runs about 5.8px a character).
      const cliffLabels = cards.map((c) => {
        const cx = cliffX(c);
        if (cx == null) return null;
        const owed = endX(c) > cx + 0.5;
        const text = `${shortName(c.name)} ${pct0(c.promo_apr)} ends ${fmtShortDate(c.promo_end)}` +
          `${owed ? `, ${pct0(c.apr)} after` : ", cleared before"}`;
        const w = text.length * 5.8;
        const flip = cx > W - PAD.r - 190;
        // On a phone the flipped label would start left of the chart; slide it back in.
        const x0 = Math.max(0, Math.min(flip ? cx - 6 - w : cx + 6, W - w));
        return { cx, owed, text, x0, x1: x0 + w };
      });
      const rowEnds = [];
      cliffLabels.filter(Boolean).sort((a, b) => a.x0 - b.x0).forEach((l) => {
        let r = rowEnds.findIndex(end => l.x0 > end + 8);
        if (r < 0) { r = rowEnds.length; rowEnds.push(0); }
        rowEnds[r] = l.x1;
        l.row = r;
      });
      const top = PAD.t + Math.max(0, rowEnds.length - 1) * 13;
      const laneY = (li) => top + li * (LANE + GAP);
      const totalY = laneY(cards.length) + 12;
      const plotBottom = totalY + TOTAL_H;
      const H = plotBottom + PAD.b;

      const parts = [
        <title id="debt-chart-title" key="title">{`Payoff timeline: one bar per card from ` +
          `${fmtMonth(timeline[0].month)} to the month it is paid off, with the total owed ` +
          `underneath. Payoff dates and balances are also in the cards table below.`}</title>,
      ];

      // Month columns: a light rule at each boundary, the label at the column start.
      // At most 8 labels, and never closer than 60px ("Aug 2039" is about 50px wide).
      const step = n <= 9 && iw / n >= 60 ? 1 : Math.max(Math.ceil(n / 8), Math.ceil(60 / (iw / n)));
      for (let i = 0; i <= n; i++) {
        parts.push(<line className="grid" x1={x(i)} x2={x(i)} y1={top - 4} y2={plotBottom} key={`g${i}`} />);
        if (i < n && i % step === 0 && x(i) + 54 < W) {
          parts.push(<text className="axis-x" x={x(i) + 4} y={H - PAD.b + 16} key={`ax${i}`}>{fmtMonth(timeline[i].month)}</text>);
        }
      }

      cards.forEach((c, li) => {
        const y0 = laneY(li);
        const xEnd = endX(c);
        const cx = cliffX(c);
        const crosses = cx != null && xEnd > cx + 0.5;
        const barY = y0 + 4, barH = LANE - 8;

        parts.push(<text className="lane-name" x="0" y={y0 + 14} key={`ln${li}`}>{c.name}</text>);
        parts.push(<text className="lane-bal" x="0" y={y0 + 28} key={`lb${li}`}>{`${moneyC(c.balance)}` +
          `${c.kind === "loan" ? " · loan" : ""}`}</text>);
        parts.push(<rect className="bar" x={x(0)} y={barY} width={(crosses ? cx : xEnd) - x(0)} height={barH} rx="2" key={`b${li}`} />);
        if (crosses) {
          parts.push(<rect className="bar after-cliff" x={cx} y={barY} width={xEnd - cx} height={barH} rx="2" key={`ac${li}`} />);
        }
        const end = c.never_pays_off ? "never"
          : `${fmtMonth(c.payoff_date)}${c.months_to_payoff ? ` · ${c.months_to_payoff} mo` : ""}`;
        if (xEnd - x(0) >= 120) {
          parts.push(<text className="bar-end" x={xEnd - 8} y={y0 + LANE / 2 + 4} textAnchor="end" key={`be${li}`}>{end}</text>);
        } else {
          parts.push(<text className="bar-end-out" x={xEnd + 8} y={y0 + LANE / 2 + 4} key={`bo${li}`}>{end}</text>);
        }
      });

      // Cliffs across every lane. The label says whether the card is still owed there.
      cliffLabels.forEach((l, li) => {
        if (!l) return;
        const { cx, owed } = l;
        const ly = top - 10 - (rowEnds.length - 1 - l.row) * 13;
        parts.push(<line className={`cliff-line${owed ? " owed" : ""}`} x1={cx} x2={cx} y1={ly + 4} y2={plotBottom} key={`cl${li}`} />);
        parts.push(<text className={`cliff-label${owed ? " owed" : ""}`} x={l.x0} y={ly} key={`ct${li}`}>{l.text}</text>);
      });

      // Total owed: the balance at the end of each month, from today's total down to zero.
      const maxT = Math.max(d.totals.debt, ...timeline.map(m => m.total));
      const base = plotBottom - 3;
      const ty = (v) => base - (v / maxT) * (TOTAL_H - 8);
      const pts = [[x(0), ty(d.totals.debt)], ...timeline.map((m, i) => [x(i + 1), ty(m.total)])];
      // The line reaches zero where the last card actually clears, not at the column edge.
      if (timeline[n - 1].total <= 0.005 && d.totals.debt_free_frac != null) {
        pts[n][0] = x(n - 1) + (x(n) - x(n - 1)) * d.totals.debt_free_frac;
      }
      const line = pts.map(([px, py]) => `${px},${py}`).join("L");
      parts.push(<path className="total-area" d={`M${line}L${x(n)},${base}L${x(0)},${base}Z`} key="ta" />);
      parts.push(<path className="total-line" d={`M${line}`} key="tl" />);
      parts.push(<text className="lane-name" x="0" y={totalY + 18} key="tn">total owed</text>);
      parts.push(<text className="lane-bal" x="0" y={totalY + 32} key="tb">{moneyC(d.totals.debt)}</text>);

      // Hover layer: a crosshair on the month under the pointer plus a capture rect.
      const at = (evt) => {
        const box = svgRef.current.getBoundingClientRect();
        // The SVG scales to its container, so client px must be mapped back to viewBox px.
        const vx = (evt.clientX - box.left) * (W / box.width);
        return Math.min(n - 1, Math.max(0, Math.floor((vx - labelW) / iw * n)));
      };
      const show = (evt) => {
        const box = wrapRef.current.getBoundingClientRect();
        setHover({ i: at(evt), px: evt.clientX - box.left, boxW: box.width });
      };
      const mid = hover ? (x(hover.i) + x(hover.i + 1)) / 2 : 0;
      parts.push(<line className="crosshair" id="debt-crosshair" y1={top - 4} y2={plotBottom} x1={mid} x2={mid}
                       style={hover ? undefined : { display: "none" }} key="ch" />);
      parts.push(<rect id="debt-capture" x={x(0)} y={top - 4} width={iw} height={plotBottom - top + 4} fill="transparent"
                       onPointerMove={show} onPointerDown={show} onPointerLeave={() => setHover(null)} key="cap" />);

      svgProps = Object.assign(svgProps, { viewBox: `0 0 ${W} ${H}`, width: "100%", height: String(H) });
      kids = parts;

      if (hover) {
        const m = timeline[hover.i];
        const rows = cards.map(c => c.name)
          .map(nm => [nm, m.by_card[nm] || 0])
          .filter(([, v]) => v > 0.005);
        // Flip the tooltip to the other side near the right edge so it never clips.
        tip = {
          left: `${hover.px > hover.boxW - 220 ? hover.px - 200 : hover.px + 16}px`,
          body: (
            <React.Fragment>
              <div className="tip-head">{`end of ${fmtMonth(m.month)}`}</div>
              {rows.map(([nm, v]) => <div className="tip-row" key={nm}><span>{nm}</span><b>{moneyC(v)}</b></div>)}
              <div className="tip-row total"><span>total owed</span><b>{moneyC(m.total)}</b></div>
              <div className="tip-row"><span>interest that month</span><b>{moneyC(m.interest)}</b></div>
              <div className="tip-row"><span>paid that month</span><b>{moneyC(m.paid)}</b></div>
            </React.Fragment>),
        };
      }
    }

    return (
      <div className={`chart-wrap${empty ? " chart-empty" : ""}`} id="debt-chart-wrap" ref={wrapRef}
           data-empty={empty ? "nothing owed \u2014 no trajectory to plot" : undefined}>
        {/* the <title> lives INSIDE the svg to name it for a screen reader */}
        {React.createElement("svg", Object.assign({ ref: svgRef }, svgProps), kids)}
        <div className="chart-tip" id="debt-tip" hidden={!tip} style={tip ? { left: tip.left } : undefined}>{tip ? tip.body : null}</div>
      </div>
    );
  }

  const PAY_KIND = {
    payment: ["payment", "paid down from cash"],
    balance_transfer: ["balance transfer", "moved between cards \u2014 total debt unchanged"],
    credit: ["credit", "refund or reversal"],
  };

  function DebtPanel({ active }) {
    const [data, setData] = useState(null);
    const [err, setErr] = useState(null);
    const [text, setText] = useState("");          // the monthly-payment box
    const [scen, setScen] = useState(null);
    const [derived, setDerived] = useState(null);  // /api/budget, the chain behind the seeded figure
    const D = useRef({ budget: null, derived: null, data: null, loaded: false, seq: 0, scenSeq: 0 }).current;
    const textRef = useRef("");
    const timer = useRef(null);

    function loadScenarios() {
      const base = D.data?.totals;
      if (!base) return Promise.resolve();
      // Row one is the exact figure in the box, so its interest ties to the headline;
      // the steps above it are round numbers he can actually decide to pay.
      const now = D.budget || D.data.minimums_total;
      const floor = Math.ceil(now / 50) * 50;
      const budgets = [now, ...[100, 200, 400, 700, 1000].map(x => floor + x)];
      const url = `/finances/api/debt/scenarios?budgets=${budgets.join(",")}`;
      const seq = ++D.scenSeq;
      return fetch(url).then(x => x.json()).then(r => {
        if (seq !== D.scenSeq) return;   // a newer payment already answered
        setScen(r.scenarios || []);
      }).catch(e => { console.error("[debt] scenarios fetch failed", e); });
    }

    function loadDebt() {
      const seq = ++D.seq;
      const q = new URLSearchParams();
      if (D.budget != null) q.set("budget", String(D.budget));
      return fetch(`/finances/api/debt?${q}`).then(r => r.json()).then(d => {
        if (seq !== D.seq) return;   // a newer request already answered
        if (d.error) { setErr(d.error); return; }
        if (!d.configured) {
          setErr("The book is not set up, so balances are unavailable. Sync the book and reload.");
          return;
        }
        setErr(null);
        D.data = d;
        // First load only. What he last typed wins, a monthly payment he set is a
        // decision, not a default to be overwritten every visit. Absent a saved
        // figure, seed the DERIVED capacity (projected earnings minus what he
        // actually spends); never a rounded or invented one, because the old
        // round-up-to-$10 seed produced $250, a number nobody chose, which then got
        // read back as his real capacity. If the derivation fails too, fall back to
        // the summed minimums, which is at least a true number.
        if (D.budget == null) {
          return fetch("/finances/api/budget")
            .then(r => (r.ok ? r.json() : null))
            .catch(() => null)
            .then(dv => {
              D.derived = dv;
              setDerived(dv);
              D.budget = savedBudget() ?? D.derived?.budget ?? d.minimums_total;
              textRef.current = String(D.budget);
              setText(String(D.budget));
              return loadDebt();
            });
        }
        setData(d);
        return loadScenarios();
      }).catch(e => {
        if (seq !== D.seq) return;
        console.error("[debt] fetch failed", e);
        setErr("could not load debt data \u2014 see the console.");
      });
    }

    useEffect(() => {
      if (!active || D.loaded) return;
      D.loaded = true;
      loadDebt();
    }, [active]);

    function onBudget(e) {
      const v = e.target.value;
      textRef.current = v;
      setText(v);
      clearTimeout(timer.current);
      // Each keystroke would otherwise fire a full multi-scenario simulation.
      timer.current = setTimeout(() => {
        const raw = textRef.current.trim();
        if (!raw) {
          // Emptying the field is how he gets back to the derived figure. The
          // input is deliberately NOT refilled here, rewriting the box while he
          // is mid-edit would fight his typing; the seed returns on next load.
          saveBudget(null);
          D.budget = D.derived?.budget ?? D.data?.minimums_total ?? 0;
        } else {
          const n = parseFloat(raw);
          D.budget = Number.isFinite(n) && n >= 0 ? n : 0;
          saveBudget(D.budget);
        }
        loadDebt();
      }, 250);
    }
    useEffect(() => () => clearTimeout(timer.current), []);

    const d = data;
    const t = d ? d.totals : null;
    const stats = d ? {
      debt: [moneyC(t.debt), `${(d.cards || []).filter(c => c.balance > 0.005).length} accounts carrying a balance`],
      interest: [moneyC(t.monthly_interest), `${moneyC(t.annual_interest_at_current_rates)}/yr at today's rates`],
      apr: [pct(t.blended_apr), "balance-weighted, at the rate charged today"],
      free: [t.debt_free ? fmtMonth(t.debt_free) : "never",
             t.months ? `${t.months} months · ${moneyC(t.total_interest)} interest from here`
                      : "payments don't cover the interest"],
    } : {};
    const STATS = [["debt", "total debt"], ["interest", "interest this month"], ["apr", "blended apr"], ["free", "debt free"]];

    // Show the chain, not just the number. A seeded figure with no visible
    // derivation is how $250 and $1,200 both got mistaken for his real capacity.
    const dv = derived;
    const mins = d ? `minimums total ${moneyC(d.minimums_total)}/mo` : "";
    const minsLine = !d ? "" : dv?.budget != null
      ? `${mins} · derived ${moneyC(dv.budget)} for ${dv.budget_month} = ` +
        `${moneyC(dv.projection[0].earnings)} earned − ${moneyC(dv.typical_spend)} spent ` +
        `(${dv.typical_spend_source}; ${dv.assumed_shifts_per_week} shifts/wk assumed past ` +
        `${dv.roster_horizon})`
      : mins;

    const cliffs = d ? (d.cards || []).filter(c => c.promo_end && c.balance > 0.005 && c.promo_monthly_needed != null) : [];
    // Cards table, highest rate first, which is also the order to attack them in.
    const rows = d ? [...(d.cards || [])].sort((a, b) => b.current_apr - a.current_apr || b.balance - a.balance) : [];
    // Anything the projection had to assume or reconcile is stated, not buried.
    const notes = d ? (d.cards || []).flatMap(c => (c.notes || []).map(n => [c.name, n])) : [];
    const payments = d ? (d.payments || []) : [];
    const baseInt = scen?.[0] ? scen[0].total_interest : 0;

    return (
      <div className="debt-main fin-panel" role="tabpanel" id="panel-debt" aria-labelledby="tab-debt" tabIndex={0} hidden={!active}>

        <div className="hub-error" id="debt-error" aria-live="polite" hidden={!err}>{err}</div>

        {/* ─── HEADLINE FIGURES: the four numbers worth knowing without reading anything else ─── */}
        <section className="debt-stats" id="debt-stats">
          {STATS.map(([k, title]) => {
            const [v, sub] = stats[k] || ["--", ""];
            return (
              <div className={`stat${k === "free" && d && !t.debt_free ? " bad" : ""}`} data-k={k} key={k}>
                <h3>{title}</h3>
                <div className="stat-v hub-stat-v">{v}</div><div className="stat-sub">{sub}</div>
              </div>);
          })}
        </section>

        {/* promo cards that revert to full APR on a fixed date; empty when none are close */}
        <section className="cliffs" id="debt-cliffs" hidden={!cliffs.length}>{cliffs.map(c => {
          const days = daysUntil(c.promo_end);
          // Under a year out is when the monthly number starts to hurt; flag it louder.
          const sev = days < 180 ? "serious" : "warn";
          return (
            <div className={`cliff ${sev}`} key={c.name}>
              <div className="cliff-h">{`${c.name}: ${pct0(c.promo_apr)} ends in ${days} days`}{" "}
                <span className="then">{`${fmtShortDate(c.promo_end)}, then ${pct0(c.apr)}`}</span></div>
              <div className="cliff-b">{`${moneyC(c.balance)} outstanding · `}
                <b>{`${moneyC(c.promo_monthly_needed)}/mo`}</b>{" clears it before the rate flips"}
              </div></div>);
        })}</section>

        {/* ─── TRAJECTORY: controls sit above the chart they drive ─── */}
        <section className="traj">
          <div className="traj-head">
            <h3>trajectory</h3>
            <div className="traj-controls">
              <label htmlFor="debt-budget">monthly payment</label>
              <input id="debt-budget" type="number" min="0" step="10" inputMode="decimal" aria-describedby="debt-mins"
                     value={text} onChange={onBudget} />
            </div>
          </div>
          {/* where the seeded figure came from: its own line, so the chain is readable
              instead of wrapping around the input it explains */}
          <p className="traj-basis" id="debt-mins">{minsLine}</p>

          <figure className="chart-figure">
            <DebtChart d={d} />
            <figcaption>
              A bar runs until the month that card is paid off at this monthly payment; the part past
              a dashed line is still owed after that card's 0% window ends. Exact figures are in the table below.
            </figcaption>
          </figure>
        </section>

        {/* ─── PER-CARD DETAIL: also the chart's table view ─── */}
        <section className="debt-cards">
          <h3>cards</h3>
          <table id="debt-table">
            <thead><tr>
              <th>card</th>
              <th className="hub-num">balance</th>
              <th className="hub-num">apr</th>
              <th className="hub-num">used</th>
              <th className="hub-num">min</th>
              <th className="hub-num">interest/mo</th>
              <th className="hub-num">total interest</th>
              <th>paid off</th>
            </tr></thead>
            <tbody>{rows.map(c => {
              // While a promo holds, current_apr IS the promo rate, printing both reads as
              // "0.00% 0.00% until Dec 25". Show the live rate once, and what it becomes.
              const inPromo = c.promo_end && c.promo_apr != null && daysUntil(c.promo_end) > 0;
              const zero = c.balance <= 0.005;
              return (
                <tr className={zero ? "zeroed" : ""} key={c.name}>
                  <td>{c.name}{c.kind === "loan" ? <span className="tag">loan</span> : null}
                    {c.due_day ? <div className="then">{`due the ${ordinal(c.due_day)}`}</div> : null}</td>
                  <td className="hub-num">{c.balance < -0.005
                    ? <React.Fragment>{moneyC(-c.balance)}<div className="then">credit</div></React.Fragment> : moneyC(c.balance)}</td>
                  <td className="hub-num"><span className={`rate${inPromo ? " promo" : ""}`}>{pct(c.current_apr)}</span>
                    {inPromo ? <div className="then">{`until ${fmtShortDate(c.promo_end)}, then ${pct(c.apr)}`}</div> : null}</td>
                  <td className="hub-num">{c.utilization != null
                    ? <React.Fragment>{`${zero ? 0 : c.utilization}%`}<div className="then">{`of ${money0(c.credit_limit)}`}</div></React.Fragment> : "--"}</td>
                  <td className="hub-num">{moneyC(c.min_payment)}</td>
                  <td className="hub-num">{moneyC(c.monthly_interest)}</td>
                  <td className="hub-num">{moneyC(c.total_interest)}</td>
                  <td>{zero ? <span className="good">clear</span>
                    : c.never_pays_off ? <span className="bad">never</span>
                    : c.payoff_date ? <React.Fragment>{fmtMonth(c.payoff_date)}<div className="then">{`${c.months_to_payoff} mo`}</div></React.Fragment> : "--"}</td>
                </tr>);
            })}</tbody>
          </table>
          <ul className="card-notes" id="debt-notes">{notes.map(([n, txt], i) => (
            <li key={i}><b>{n}</b>{` \u2014 ${txt}`}</li>))}</ul>
        </section>

        {/* ─── WHAT-IF: the same debt at several payment levels ─── */}
        <section className="scenarios">
          <h3>what another $100/mo buys you</h3>
          <table id="scenario-table">
            <thead><tr>
              <th className="hub-num">monthly payment</th>
              <th>debt free</th>
              <th className="hub-num">months</th>
              <th className="hub-num">total interest</th>
              <th className="hub-num">vs. now</th>
            </tr></thead>
            <tbody>{(scen || []).map((s, i) => {
              const saved = baseInt - s.total_interest;
              return (
                <tr className={i === 0 ? "current" : ""} key={i}>
                  <td className="hub-num">{moneyC(s.monthly_budget)}{i === 0 ? <span className="tag">now</span> : null}</td>
                  <td>{s.debt_free ? fmtMonth(s.debt_free) : "never"}</td>
                  <td className="hub-num">{s.months != null ? s.months : "--"}</td>
                  <td className="hub-num">{moneyC(s.total_interest)}</td>
                  <td className={`hub-num ${saved > 0 ? "good" : ""}`}>{i === 0 ? "--" : `saves ${moneyC(saved)}`}</td>
                </tr>);
            })}</tbody>
          </table>
        </section>

        {/* ─── PAYMENTS: what actually went out, and to which card ─── */}
        <section className="payments">
          <div className="payments-head">
            <h3>payments</h3>
            <span className="pay-note">last 180 days, from YNAB</span>
          </div>
          <table id="payments-table">
            <thead><tr>
              <th>date</th>
              <th>to card</th>
              <th className="hub-num">amount</th>
              <th>from</th>
              <th>kind</th>
            </tr></thead>
            <tbody>{!d ? null : !payments.length
              ? <tr><td colSpan="5" className="empty-row">no card payments in the last 180 days</td></tr>
              : payments.map((p, i) => {
                const [label, why] = PAY_KIND[p.kind] || [p.kind, ""];
                return (
                  <tr className={`pk-${p.kind}`} key={i}>
                    <td>{fmtShortDate(p.date)}</td>
                    <td>{p.card}</td>
                    <td className="hub-num">{moneyC(p.amount)}</td>
                    <td><Payee name={p.source || p.payee} /></td>
                    <td><span className="kind">{label}</span>{p.kind === "payment" ? "" : <div className="then">{why}</div>}</td>
                  </tr>);
              })}</tbody>
          </table>
        </section>

      </div>
    );
  }
  U.DebtPanel = DebtPanel;

  // ── Stocks ──────────────────────────────────────────────────────────────────
  // Reads /stocks/api/* (stocks.db stays its own file). Ported from the standalone /stocks page into
  // the finances umbrella.

  const sMoney = (n) => (n == null) ? "\u2014" : `$${Number(n).toFixed(2)}`;
  const sPct = (n) => {
    if (n == null) return "\u2014";
    const cls = n >= 0 ? "pct-pos" : "pct-neg";
    return <span className={cls}>{`${n >= 0 ? "+" : ""}${n.toFixed(2)}%`}</span>;
  };
  const sDate = (s) => s ? s.slice(0, 10) : "\u2014";

  function sortRows(list, key) {
    const arr = list.slice();
    if (key === "score") {
      arr.sort((a, b) => (b.latest_viability_score || 0) - (a.latest_viability_score || 0));
    } else if (key === "distance") {
      // stale rows sink: a game plan predating known-changed facts shouldn't rank
      // as "close to entry" beside a fresh one.
      const live = arr.filter(r => !r.stale && r.distance_to_entry_pct !== null);
      const rest = arr.filter(r => r.stale || r.distance_to_entry_pct === null);
      live.sort((a, b) => Math.abs(a.distance_to_entry_pct) - Math.abs(b.distance_to_entry_pct));
      return live.concat(rest);
    } else if (key === "ticker") {
      arr.sort((a, b) => a.ticker.localeCompare(b.ticker));
    } else {
      arr.sort((a, b) => new Date(b.last_analyzed) - new Date(a.last_analyzed));
    }
    return arr;
  }

  // fixed direction per sort key, there's no ascending/descending toggle, each
  // key always sorts the same way (see sortRows above), so aria-sort just states it.
  const SORT_DIR = { score: "descending", distance: "ascending", ticker: "ascending", recency: "descending" };
  const enterSpace = (go) => (ev) => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    ev.preventDefault();
    go();
  };

  function StocksPanel({ active }) {
    const [rows, setRows] = useState(null);
    const [sortKey, setSortKey] = useState("recency");
    const [inited, setInited] = useState(false);
    const [detail, setDetail] = useState(null);     // the last stock opened
    const [open, setOpen] = useState(false);
    const [tick, setTick] = useState(0);            // bumps on each open, to scroll to it
    const started = useRef(false);
    const asked = useRef(0);                         // newest detail request
    const detailRef = useRef(null);

    useEffect(() => {
      if (!active || started.current) return;
      started.current = true;
      setInited(true);
      fetch("/stocks/api/stocks").then(r => r.json()).then(data => {
        setRows(data);
      }).catch(e => console.error("[stocks] watchlist fetch failed", e));
    }, [active]);

    useEffect(() => {
      if (tick && detailRef.current) detailRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }, [tick]);

    function openDetail(ticker) {
      const mine = ++asked.current;
      fetch(`/stocks/api/stocks/${encodeURIComponent(ticker)}`).then(r => {
        if (!r.ok) throw new Error("not found");
        return r.json();
      }).then(s => {
        if (mine !== asked.current) return;   // another stock was picked while this loaded
        setDetail(s);
        setOpen(true);
        setTick(t => t + 1);
      }).catch(e => console.error("[stocks] detail fetch failed", e));
    }

    const s = detail;
    const latest = (s?.history?.[0]) || {};
    const v = (x) => x || "\u2014";
    // a plain function, not a component: a component declared here would remount each header on every
    // render and drop the focus a keyboard sort just gave it
    const th = (k, label, num) => {
      const on = inited && sortKey === k;
      return (
        <th className={`hub-sortable${num ? " hub-num" : ""}${on ? " hub-sorted" : ""}`} data-sort={k} key={k}
            tabIndex={inited ? 0 : undefined} aria-sort={inited ? (on ? SORT_DIR[sortKey] : "none") : undefined}
            onClick={inited ? () => setSortKey(k) : undefined}
            onKeyDown={inited ? enterSpace(() => setSortKey(k)) : undefined}>{label}</th>);
    };

    return (
      <div className="stocks-main fin-panel" role="tabpanel" id="panel-stocks" aria-labelledby="tab-stocks" tabIndex={0} hidden={!active}>

        <table className="hub-table watchlist" id="watchlist-table">
          <thead>
            <tr>
              {th("ticker", "ticker")}
              <th>company</th>
              {th("score", "score")}
              <th>verdict</th>
              <th className="hub-num">price</th>
              <th className="hub-num">entry</th>
              <th className="hub-num">target</th>
              <th className="hub-num">stop</th>
              {th("distance", "dist. to entry", true)}
              {th("recency", "last analyzed")}
            </tr>
          </thead>
          <tbody id="watchlist-body">{rows?.length ? sortRows(rows, sortKey).map(r => {
            const verdict = r.latest_verdict_summary || "";
            return (
              <tr data-ticker={r.ticker} tabIndex={0} className={r.stale ? "row-stale" : ""} key={r.ticker}
                  onClick={() => openDetail(r.ticker)} onKeyDown={enterSpace(() => openDetail(r.ticker))}>
                <td>{r.ticker}{r.stale ? <span className="stale-flag" title="stale &mdash; 30d+ since last analysis, or earnings has passed">⚠</span> : null}</td>
                <td>{r.company}</td>
                <td><span className="score-badge">{r.latest_viability_score ?? "\u2014"}</span></td>
                <td className="verdict-cell" title={verdict}>{verdict}</td>
                <td className="hub-num">{sMoney(r.current_price)}{r.price_stale ? " *" : ""}</td>
                <td className="hub-num">{sMoney(r.trade_entry_num)}</td>
                <td className="hub-num">{sMoney(r.trade_target_num)}</td>
                <td className="hub-num">{sMoney(r.trade_stop_num)}</td>
                <td className="hub-num">{sPct(r.distance_to_entry_pct)}</td>
                <td>{sDate(r.last_analyzed)}</td>
              </tr>);
          }) : null}</tbody>
        </table>
        <div className="hub-empty-state empty" id="watchlist-empty" style={{ display: rows && !rows.length ? "block" : "none" }}>no tickers analyzed yet &mdash; run <code>/stock &lt;TICKER&gt;</code> to add one.</div>

        <div className={`detail${open ? " open" : ""}`} id="detail" ref={detailRef}>
          <div className="detail-head">
            <div>
              <h2 id="d-ticker">{s ? s.ticker : ""}</h2>
              <div className="sub" id="d-sub">{s ? `${s.company} · ${s.sector} · score ${s.latest_viability_score ?? "\u2014"}` : ""}</div>
            </div>
            <button className="detail-close" id="d-close" type="button" onClick={() => setOpen(false)}>close</button>
          </div>

          <div className="case-grid">
            <div className="case-card bull"><h4>bull case</h4>
            <div id="d-bull">{s ? v(latest.bull_case) : ""}</div></div>
            <div className="case-card base"><h4>base case</h4>
            <div id="d-base">{s ? v(latest.base_case) : ""}</div></div>
            <div className="case-card bear"><h4>bear case</h4>
            <div id="d-bear">{s ? v(latest.bear_case) : ""}</div></div>
          </div>

          <div className="block-grid">
            <div className="block">
              <h3>long-term thesis</h3>
              <dl>
                <dt>thesis</dt><dd id="d-lt-thesis">{s ? v(latest.lt_thesis) : ""}</dd>
                <dt>fair value</dt><dd id="d-lt-fair">{s ? v(latest.lt_fair_value) : ""}</dd>
                <dt>allocation</dt><dd id="d-lt-alloc">{s ? v(latest.lt_allocation) : ""}</dd>
                <dt>exit triggers</dt><dd id="d-lt-exit">{s ? v(latest.lt_exit_triggers) : ""}</dd>
              </dl>
            </div>
            <div className="block">
              <h3>trade setup</h3>
              <dl>
                <dt>entry</dt><dd id="d-tr-entry">{s ? v(latest.trade_entry) : ""}</dd>
                <dt>targets</dt><dd id="d-tr-targets">{s ? v(latest.trade_targets) : ""}</dd>
                <dt>stop</dt><dd id="d-tr-stop">{s ? v(latest.trade_stop) : ""}</dd>
                <dt>timeframe</dt><dd id="d-tr-timeframe">{s ? v(latest.trade_timeframe) : ""}</dd>
                <dt>risk:reward</dt><dd id="d-tr-rr">{s ? v(latest.trade_risk_reward) : ""}</dd>
              </dl>
            </div>
          </div>

          <h3 className="hist-head">run history</h3>
          <ul className="history-list" id="d-history">{s ? ((s.history || []).length ? s.history.map((h, i) => (
            <li key={i}><span className="h-date">{sDate(h.run_date)}</span>
              <span className="h-score">{h.viability_score ?? "\u2014"}</span>
              <span className="h-verdict">{h.verdict_summary || ""}</span></li>))
            : <li>no runs recorded.</li>) : null}</ul>
        </div>

        <div className="not-advice">not financial advice &mdash; personal research notes only.</div>

      </div>
    );
  }
  U.StocksPanel = StocksPanel;
})();

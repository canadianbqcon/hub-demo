/* Ledger item page (/ledger/i/<name>). Same hand-off as the book: the template
   passes one JSON blob (script#ledger-data), every number and every chart
   coordinate comes from the server, and this file only draws it. The crosshair
   readout is state here instead of innerHTML, with the same nearest-day lookup. */
window.LedgerUI = window.LedgerUI || {};
(() => {
  const EM = "\u2014"; // the page's placeholder dash, kept out of the source text

  const commas = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const usd = (c) => {
    if (c == null) return EM;
    const a = Math.abs(Math.round(c));
    return `$${c < 0 ? "-" : ""}${commas(Math.floor(a / 100))}.${String(a % 100).padStart(2, "0")}`;
  };

  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err, info) { console.error("[ledger] render error", err, info); }
    render() {
      if (this.state.err) return <p className="why">The ledger page failed to load.</p>;
      return this.props.children;
    }
  }

  // Nearest day by x, not interpolated: every point is one real day of trades.
  // Binary search because a six-year series is ~2,000 points and this runs on every pointer move.
  function nearest(pts, x) {
    let lo = 0, hi = pts.length - 1;
    while (lo < hi) { const m = (lo + hi) >> 1; if (pts[m][0] < x) lo = m + 1; else hi = m; }
    if (lo > 0 && Math.abs(pts[lo - 1][0] - x) < Math.abs(pts[lo][0] - x)) lo--;
    return pts[lo];
  }

  function Chart({ chart }) {
    const svg = React.useRef(null);
    const [hit, setHit] = React.useState(null);
    const pts = chart.points;
    const move = (ev) => {
      if (!pts.length) return;
      const r = svg.current.getBoundingClientRect();
      const vb = svg.current.viewBox.baseVal;
      setHit(nearest(pts, (ev.clientX - r.left) / r.width * vb.width));
    };
    const p = hit;
    return (
      <div className="chart" id="chart" data-hover={p ? "1" : "0"}>
        <div className="readout" id="readout">
          {p ? (
            <>
              <span className="day">{p[2]}</span>
              <span className="price">{usd(p[3])}</span>
              <span className="day">{p[4]} trade{p[4] === 1 ? "" : "s"}</span>
              {p[5] ? <span className="why">rejected {EM} {p[6]}</span> : null}
            </>
          ) : <span className="hint">Hover the chart for a day.</span>}
        </div>
        <svg id="plot" ref={svg} viewBox={`0 0 ${chart.w} ${chart.h}`} role="img"
             aria-label={`daily sale average and trade count, ${chart.first_day} to ${chart.last_day}`}
             onPointerMove={move} onPointerDown={move} onPointerLeave={() => setHit(null)}>
          {chart.yticks.map((t, k) => (
            <React.Fragment key={`y${k}`}>
              <line className="grid" x1={chart.pad_l} y1={t.y} x2={chart.plot_r} y2={t.y} />
              <text className="tick y" x={chart.pad_l - 8} y={t.y + 4}>{t.label}</text>
            </React.Fragment>
          ))}
          {chart.xticks.map((t, k) => (
            <React.Fragment key={`x${k}`}>
              <line className="grid" x1={t.x} y1={chart.price_top} x2={t.x} y2={chart.vol_bottom} />
              <text className="tick x" x={t.x} y={chart.axis_y}>{t.label}</text>
            </React.Fragment>
          ))}

          <polyline className="line" points={chart.line} vectorEffect="non-scaling-stroke" />
          {chart.rejected.map((r, k) => (
            <circle key={k} className="rej" cx={r.x} cy={r.y} r="3" vectorEffect="non-scaling-stroke" />
          ))}

          {chart.bars.map((b, k) => (
            <rect key={k} className="bar" x={b.x} y={chart.vol_bottom - b.h} width="1.5" height={b.h} />
          ))}
          <line className="frame" x1={chart.pad_l} y1={chart.vol_bottom} x2={chart.plot_r} y2={chart.vol_bottom} />
          <text className="rail-label" x={chart.pad_l - 8} y={chart.vol_bottom}>{chart.vmax} trades</text>

          <line className="cross" id="crossLine" x1={p ? p[0] : 0} y1={chart.price_top} x2={p ? p[0] : 0} y2={chart.vol_bottom} />
          <circle className="cross-dot" id="crossDot" cx={p ? p[0] : 0} cy={p ? p[1] : 0} r="3.5" />
          <rect id="hit" x={chart.pad_l} y={chart.price_top} width={chart.plot_r - chart.pad_l}
                height={chart.vol_bottom - chart.price_top} fill="transparent" />
        </svg>
      </div>
    );
  }

  function History({ chart }) {
    if (!chart) {
      return (
        <p className="why">
          No daily series stored for this item. Per-item history is pulled for the holdings carrying 95% of the
          book's value, so the long tail carries a mark without a chart rather than a chart built from nothing.
        </p>
      );
    }
    const n = chart.rejected_n;
    return (
      <>
        <p className="why">
          {chart.days} days of daily sale average, with trade count as the rail beneath.{" "}
          {n ? (
            <>
              {n} day{n !== 1 ? "s" : ""} sat more than 3x above the trailing
              30-day median and {n !== 1 ? "were" : "was"} rejected {EM} drawn as an open circle
              rather than deleted, because a filter that hides its own discards cannot be checked. Hover one to see
              what it was measured against.
            </>
          ) : "Nothing in this series tripped the outlier filter."}
        </p>
        <Chart chart={chart} />
      </>
    );
  }

  function Item({ data, root }) {
    const { i, chart, depth_target } = data;
    // the marker the parity check and the template's load fallback look for
    React.useEffect(() => { root.setAttribute("data-react-mounted", "ledger-item"); }, []);
    const thin = ["Knife", "Gloves"].indexOf(i.item_type) >= 0;
    return (
      <>
        <div className="hero">
          <h1>{i.name}</h1>
          <span className="big">{usd(i.unit_cents)}</span>
          <span className={`chip ${i.confidence === "n/a" ? "na" : i.confidence}`}>{i.confidence}</span>
          <span className="meta">
            {i.qty > 1 ? `${i.qty} held, ${usd(i.mark_cents)} of the book · ` : ""}
            {i.window || "no window"} {"·"} {i.volume} trades
          </span>
        </div>

        <section>
          <h2>The mark and its working</h2>
          <p className="why">
            The adaptive window is the shortest one carrying {depth_target} trades. Every window's answer is
            below, not just the chosen one {EM} windows disagreeing is the thing worth seeing, and resolving that
            silently behind the reader would be the same trick as quoting a number with no basis.
          </p>
          <table>
            <thead><tr>
              <th>Window</th><th className="num">Median</th><th className="num">Low</th>
              <th className="num">High</th><th className="num">Trades</th>
            </tr></thead>
            <tbody>
              {i.working.map((w) => (
                <tr key={w.window} className={(w.chosen ? "chosen" : "") + (w.volume ? "" : " thin-row")}>
                  <td>{w.window}</td>
                  <td className="num">{usd(w.median_cents)}</td>
                  <td className="num">{usd(w.low_cents)}</td>
                  <td className="num">{usd(w.high_cents)}</td>
                  <td className="num">{w.volume || EM}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section>
          <h2>History</h2>
          <History chart={chart} />
        </section>

        <section>
          <h2>The venue board</h2>
          <p className="why">
            Nothing here is averaged across venues {EM} a blended price exists on zero exchanges. Net is the listing
            floor after that venue's own seller fee, and it is the only column that ranks. Withdrawal, processor
            and FX friction is another 2{"–"}5% on top and is not in this table; net after fee is not cash in hand.
            Sale median and volume are Skinport's own trades and stay on Skinport's row, because CSFloat and
            Waxpeer publish listings only on a free feed.
          </p>
          <table>
            <thead><tr>
              <th>Venue</th><th className="num">Listing floor</th><th className="num">Depth</th>
              <th className="num">Sale median</th><th className="num">Sale volume</th>
              <th className="num">Fee</th><th className="num">Net</th>
            </tr></thead>
            <tbody>
              {i.board.map((v, k) => (
                <tr key={v.venue} className={k === 0 && v.net_cents ? "chosen" : ""}>
                  <td>{v.venue}</td>
                  <td className="num">{usd(v.floor_cents)}</td>
                  <td className="num">{v.depth != null ? v.depth : EM}</td>
                  <td className="num">{usd(v.sale_median_cents)}</td>
                  <td className="num">{v.sale_volume || EM}</td>
                  <td className="num">{v.fee_pct.toFixed(1)}%</td>
                  <td className="num">{usd(v.net_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section>
          <h2>Float comps</h2>
          {i.float_value != null ? (
            <p className="why">Float {i.float_value.toFixed(6)}{i.paint_seed != null ? `, paint seed ${i.paint_seed}` : ""}.</p>
          ) : (
            <div className="gap">
              <strong>This item's float is uncaptured{thin ? `, and on a ${i.item_type.toLowerCase()} that is the input that decides the price` : ""}.</strong>{" "}
              The public Steam inventory endpoint returns generic <code>%propid:6%</code> action links with no
              D-parameter, so inspect links {EM} and therefore float values {EM} are not derivable from it. Capturing one
              needs a logged-in Steam session. Until then the mark above is a class median for this exterior, not a
              price for this copy, and the comparison band this block would draw is not drawn.
            </div>
          )}
        </section>
      </>
    );
  }

  const root = document.querySelector("main.wrap");
  const data = JSON.parse(document.getElementById("ledger-data").textContent);
  window.LedgerUI.Item = Item;
  ReactDOM.createRoot(root).render(<Boundary><Item data={data} root={root} /></Boundary>);
})();

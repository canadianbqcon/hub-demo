/* Ledger book (/ledger/). The server still does every read and every calculation;
   the template hands this file one JSON blob (script#ledger-data) and the body is
   drawn here. Money is formatted from integer cents, with the same rounding as the
   Jinja usd / usd0 helpers it replaces. First file of the ledger surface, so it
   creates the namespace. */
window.LedgerUI = window.LedgerUI || {};
(() => {
  const EM = "\u2014"; // the page's placeholder dash, kept out of the source text

  const commas = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const usd = (c) => {
    if (c == null) return EM;
    const a = Math.abs(Math.round(c));
    return `$${c < 0 ? "-" : ""}${commas(Math.floor(a / 100))}.${String(a % 100).padStart(2, "0")}`;
  };
  // whole dollars; an exact .50 rounds to even, as Python's format does
  const usd0 = (c) => {
    if (c == null) return EM;
    const a = Math.abs(c), d = Math.floor(a / 100), r = a % 100;
    const w = r > 50 || (r === 50 && d % 2 === 1) ? d + 1 : d;
    return `$${c < 0 ? "-" : ""}${commas(w)}`;
  };
  // Jinja's urlencode: percent-encode everything but unreserved characters and "/"
  const quote = (n) => encodeURIComponent(n).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`).replace(/%2F/g, "/");
  // %+.1f: a stored -0.0 prints its sign too
  const pct = (t) => (t == null ? EM : `${(t < 0 || Object.is(t, -0) ? "-" : "+") + Math.abs(t).toFixed(1)}%`);

  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err, info) { console.error("[ledger] render error", err, info); }
    render() {
      if (this.state.err) return <p className="foot">The ledger page failed to load.</p>;
      return this.props.children;
    }
  }

  function Marks({ b, change, windows }) {
    const ex = b.executable;
    const mix = windows.filter((w) => b.window_mix[w]);
    return (
      <section className="marks">
        <div className="mark">
          <h3>Marketable inventory</h3>
          <div className="big">{usd(b.mark_cents)}</div>
          <div className="sub">
            {`Adaptive-window sale median times quantity, ${b.priced_items} of ${b.total_items} items priced. `}
            {mix.map((w, k) => (
              <React.Fragment key={w}><em>{b.window_mix[w]}</em> on {w}{k < mix.length - 1 ? ", " : ""}</React.Fragment>
            ))}
            {`. ${b.unmarketable_items} untradable items are $0 and excluded.`}
          </div>
        </div>

        <div className="mark">
          <h3>Executable</h3>
          {ex ? (
            <>
              <div className="range">{`${usd0(ex.low_cents)} – ${usd0(ex.high_cents)}`}</div>
              <div className="sub">
                Batched to <em>{ex.venue}</em>
                {`, ${ex.covered} items. Seller fee ${ex.seller_fee_pct.toFixed(1)}%, then withdrawal and FX friction ${Math.trunc(ex.friction_pct[0])}–${Math.trunc(ex.friction_pct[1])}% on top of it. `
                  + (ex.uncovered_mark_cents ? `${usd(ex.uncovered_mark_cents)} of the mark is not listed there. ` : "")
                  + "No midpoint: the spread is the answer."}
              </div>
            </>
          ) : (<><div className="range">{EM}</div><div className="sub">No venue board yet.</div></>)}
        </div>

        <div className="mark">
          <h3>Since last snapshot</h3>
          {change.delta_cents == null ? (
            <>
              <div className="range">{EM}</div>
              <div className="verdict noise">First snapshot</div>
              <div className="sub">Nothing to compare against yet. The change figure needs a second run.</div>
            </>
          ) : (
            <>
              <div className="range">{(change.delta_cents > 0 ? "+" : "") + usd(change.delta_cents)}</div>
              <div className={`verdict ${change.verdict === "real move" ? "real" : "noise"}`}>{change.verdict}</div>
              <div className="sub">
                {`Against ${usd(change.prev_mark_cents)} on ${change.prev_taken_at}. A move counts as real only past `}<em>{usd(change.band_cents)}</em>
                {` ${EM} how far the mark can shift from nothing but which window each item landed on.`}
              </div>
            </>
          )}
        </div>
      </section>
    );
  }

  function Row({ r, idx }) {
    const cls = (t) => `num ${t && t > 0 ? "up" : ""}${t && t < 0 ? "down" : ""}`;
    return (
      <tr className={`${r.marketable ? "" : "dim"} ${idx === 4 ? "top-cut" : ""}`}>
        <td className="name"><a href={`/ledger/i/${quote(r.name)}`}>{r.name}</a></td>
        <td className="num">{r.qty}</td>
        <td className="num">{r.marketable ? usd(r.mark_cents) : EM}</td>
        <td>{r.window || EM}</td>
        <td className="num">{r.depth_30d || EM}</td>
        <td><span className={`chip ${r.confidence === "n/a" ? "na" : r.confidence}`}>{r.confidence}</span></td>
        <td className={cls(r.trend_30d)}>{pct(r.trend_30d)}</td>
        <td className={cls(r.trend_90d)}>{pct(r.trend_90d)}</td>
        <td>{r.best_route || EM}</td>
      </tr>
    );
  }

  function Book({ data, root }) {
    const { b, change, windows } = data;
    // the marker the parity check and the template's load fallback look for
    React.useEffect(() => { root.setAttribute("data-react-mounted", "ledger-book"); }, []);
    if (!b.rows.length) {
      return <p className="foot">No snapshot yet. Run <code>collect.py</code> and this fills in.</p>;
    }
    return (
      <>
        <Marks b={b} change={change} windows={windows} />
        <div className="tbl-scroll"><table>
          <thead>
            <tr>
              <th>Item</th>
              <th className="num">Qty</th>
              <th className="num">Mark</th>
              <th>Window</th>
              <th className="num">30d trades</th>
              <th>Confidence</th>
              <th className="num">30d</th>
              <th className="num">90d</th>
              <th>Route</th>
            </tr>
          </thead>
          <tbody>{b.rows.map((r, k) => <Row key={r.name} r={r} idx={k} />)}</tbody>
        </table></div>
        <p className="foot">
          <strong>Reading the chips.</strong> <span className="chip solid">solid</span> is 30 or more trades inside a
          window of 7 days or shorter. <span className="chip thin">thin</span> means the window had to stretch to 30 or
          90 days to find that many. <span className="chip stale">stale</span> carries the last mark an item had and is
          never zeroed. <span className="chip na">n/a</span> is untradable and excluded from every total.
          A trend cell is blank where no daily sale series is stored for that item {EM} per-item history is pulled for
          the holdings carrying 95% of the value, and a substitute number in the same column would be a different
          quantity wearing the same label. Top five holdings are {data.top5_share}% of the mark.
          Route is the venue whose listing floor nets the most after its own seller fee; nothing is averaged across
          venues, because a blended price exists on zero exchanges.
        </p>
      </>
    );
  }

  const root = document.querySelector("main.wrap");
  const data = JSON.parse(document.getElementById("ledger-data").textContent);
  window.LedgerUI.Book = Book;
  ReactDOM.createRoot(root).render(<Boundary><Book data={data} root={root} /></Boundary>);
})();

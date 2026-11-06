/* Orders.jsx — every parcel, across every decision. The purchases page used to
   answer "what should I buy"; this half answers "where is the thing I bought"
   and then, once it lands, "how long do I have to send it back".

   Three panes, 2026-09-05, and the shape is the page's own: the same
   .pe-body rail + .pe-split the decisions half runs, because a database that
   selects one thing and opens it wants one layout, not one per module. It was
   a single full-width list of rows until now, which meant every order showed
   every field at once and none of them had room.

   LEFT is the whole table, one row per order, and the row says only what you
   pick by: what it is, where from, where it has got to. MIDDLE is the one
   order you picked, opened out into four cards — parcel, money, return,
   origin — two up, because they are four separate reads, not four headings.
   RIGHT is the supplementary read: where it is in its journey, the dates
   around that, and the map of where it is going.

   Every field is the inline Editable the rest of the page uses, so adding a
   tracking number an email never carried is a click on the blank, not a form. */

const { useState: oUseState, useEffect: oUseEffect, useCallback: oUseCallback,
        useRef: oUseRef } = React;

const ORDER_STATUSES = ["ordered", "shipped", "out for delivery", "delivered", "returned", "cancelled"];
const OPEN_STATUSES = ["ordered", "shipped", "out for delivery"];
/* The journey, in order. returned and cancelled are not further along than
   delivered — they are ways out of the track — so the progress line runs the
   three moving states into delivered and says the exit separately. */
const ORDER_TRACK = ["ordered", "shipped", "out for delivery", "delivered"];

/* The return window in words. A number of days is not the thing you want to
   read at a glance — "6 days left" is, and "closed" is, and a delivered item
   with no window recorded needs to say so rather than render an empty cell. */
function returnLine(o) {
  if (o.returned_on) return { text: `returned ${o.returned_on}`, tone: "done" };
  if (!o.return_by_effective) return { text: "no return window", tone: "none" };
  const left = o.return_days_left;
  if (left == null) return { text: `return by ${o.return_by_effective}`, tone: "open" };
  if (left < 0) return { text: `return window closed ${o.return_by_effective}`, tone: "closed" };
  if (left === 0) return { text: "last day to return", tone: "urgent" };
  return { text: `${left} day${left === 1 ? "" : "s"} left to return`, tone: left <= 3 ? "urgent" : "open" };
}

const isOpenReturn = (o) => !o.returned_on && o.return_days_left != null && o.return_days_left >= 0;

// Overlapping on purpose: an order can be both "delivered" and "returns
// open" at once, same idiom as jobs' applying = applying + applied; a row
// shows when ANY switched-on option matches it.
const ORDERS_LF_CFG = {
  key: "purchases.orders",
  search: { placeholder: "search an order…", fields: (o) => `${o.item} ${o.vendor} ${o.order_number}` },
  facet: {
    label: "status", allLabel: "statuses",
    options: [
      { key: "open", label: "in transit", match: (o) => OPEN_STATUSES.includes(o.ship_status) },
      { key: "delivered", label: "delivered", match: (o) => o.ship_status === "delivered" },
      { key: "returns", label: "returns open", match: (o) => isOpenReturn(o) },
      { key: "returned", label: "returned", match: (o) => o.ship_status === "returned" },
      { key: "cancelled", label: "cancelled", match: (o) => o.ship_status === "cancelled" },
    ],
    defaultOn: ["open", "delivered", "returns", "returned", "cancelled"],
  },
  sorts: [
    // by order date (created when the order date is blank); ISO strings compare as text
    { key: "newest", label: "newest", dir: "desc",
      cmp: (a, b) => (a.ordered_on || a.created || "").localeCompare(b.ordered_on || b.created || "") },
    { key: "status", label: "status", cmp: (a, b) => ORDER_STATUSES.indexOf(a.ship_status) - ORDER_STATUSES.indexOf(b.ship_status) },
    { key: "total", label: "total", dir: "desc", cmp: (a, b) => (a.total ?? -Infinity) - (b.total ?? -Infinity) },
  ],
  defaultSort: "newest",
};

/* ── LEFT — every order, one row each ──────────────────────────────────────
   Same rail the decisions half uses, down to the class names: the shared
   filter control, then the list. A row carries only what you choose by.
   Everything else is a click away in the middle. */
function OrdersRail({ orders, shown, lfRef, selectedId, onSelect, collapsed, onToggleCollapse,
                      onNew, onScan, scanning }) {
  // What the open parcels are worth: the money that is out of the account and
  // not yet in the flat. It is the only cross-order figure the rail can state
  // honestly, the same way the decisions rail sums open budgets. Reads every
  // order, not the filtered set; "what's out there", not "what's shown".
  const inFlightValue = orders
    .filter(o => OPEN_STATUSES.includes(o.ship_status) && o.total != null)
    .reduce((a, o) => a + o.total, 0);

  return (
    <aside className={`pe-rail${collapsed ? " collapsed" : ""}`}>
      <div className="pe-rail-head">
        <h2 className="pe-rail-title">orders</h2>
        <button type="button" className="icon-btn" title="Collapse" aria-label={collapsed ? "expand rail" : "collapse rail"}
          onClick={onToggleCollapse}>{collapsed ? "›" : "‹"}</button>
      </div>

      <div className="pe-rail-summary">
        <div ref={lfRef} />
      </div>

      <div className="pe-rail-list">
        {!shown.length
          ? <div className="empty-hint">
              {orders.length ? "No matches." : "No orders yet. Add one below, or scan your email."}
            </div>
          : null}
        {shown.map(o => (
          <button key={o.id} type="button"
            className={"pe-proj-row ord-rail-row is-" + o.ship_status.replace(/ /g, "-")
              + (o.id === selectedId ? " active" : "")}
            onClick={() => onSelect(o.id)}>
            <span className="pe-proj-name">{o.item}</span>
            <span className="pe-proj-sub">
              <span className="pe-proj-stage">{o.ship_status}</span>
              {o.vendor ? <span className="ord-rail-vendor">{o.vendor}</span> : null}
            </span>
            {o.total != null ? <span className="pe-proj-budget">{fmtMoney(o.total, o.currency)}</span> : null}
          </button>
        ))}
      </div>

      {inFlightValue ? (
        <div className="pe-rail-money">
          <div className="pmoney">
            <span className="pmoney-n">{fmtMoney(inFlightValue)}</span>
            <span className="pmoney-l">paid · still in transit</span>
          </div>
        </div>
      ) : null}

      <div className="pe-rail-actions">
        <button type="button" className="sidebar-btn primary" onClick={onNew}>+ new order</button>
        <button type="button" className="sidebar-btn" disabled={scanning} onClick={onScan}>
          {scanning ? "reading email…" : "scan email"}
        </button>
      </div>
    </aside>
  );
}

/* ── MIDDLE — the one order you picked, opened out ─────────────────────────
   Four cards, in the order the questions get asked: where is it, what did it
   cost, how long have I got, and where did it come from. */
function OrderCards({ o, onPatch, setModal, onDelete }) {
  const patch = (field) => (nv) => onPatch(o.id, { [field]: nv });
  const track = window.trackingUrl ? window.trackingUrl(o.carrier, o.tracking_number) : null;
  const trackLabel = window.trackingLabel ? window.trackingLabel(o.carrier, o.tracking_number) : "track ↗";

  return (
    <div className="pe-tab ord-cards">

      {/* parcel — the card this tab exists for. A missing tracking number is
          the blank he came here to fill, so it says so rather than sitting
          empty. */}
      <section className="panel">
        <div className="panel-head">
          <h2 className="panel-title">parcel</h2>
          {track ? <a className="icon-btn ord-track-link" href={track} target="_blank" rel="noopener">{trackLabel}</a> : null}
        </div>
        <div className="panel-body panel-pad ord-fields">
          <div className="ord-field">
            <span className="ord-field-k">status</span>
            <EditableSelect value={o.ship_status} options={ORDER_STATUSES} onSave={patch("ship_status")} />
          </div>
          <div className="ord-field">
            <span className="ord-field-k">carrier</span>
            <EditableSelect value={o.carrier} placeholder="carrier"
              options={["", ...(window.CARRIER_OPTIONS || []).filter(Boolean)]} onSave={patch("carrier")} />
          </div>
          <div className={`ord-field${o.tracking_number ? "" : " is-missing"}`}>
            <span className="ord-field-k">tracking</span>
            <Editable value={o.tracking_number} placeholder="+ add tracking number" onSave={patch("tracking_number")} />
          </div>
          <div className="ord-field">
            <span className="ord-field-k">delivering to</span>
            <Editable value={o.delivery_address} placeholder="+ add the address"
              onSave={patch("delivery_address")} />
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><h2 className="panel-title">money</h2></div>
        <div className="panel-body panel-pad ord-fields">
          <div className="ord-field">
            <span className="ord-field-k">paid</span>
            <Editable value={o.total} number displayFn={v => fmtMoney(v, o.currency)} onSave={patch("total")} />
          </div>
          <div className="ord-field">
            <span className="ord-field-k">vendor</span>
            <Editable value={o.vendor} placeholder="vendor" onSave={patch("vendor")} />
          </div>
          <div className="ord-field">
            <span className="ord-field-k">order no.</span>
            <Editable value={o.order_number} placeholder="—"
              displayFn={v => (v ? `#${v}` : "—")} onSave={patch("order_number")} />
          </div>
          <div className="ord-field">
            <span className="ord-field-k">ordered</span>
            <Editable value={o.ordered_on} placeholder="—" onSave={patch("ordered_on")} />
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><h2 className="panel-title">return</h2></div>
        <div className="panel-body panel-pad ord-fields">
          <div className="ord-field">
            <span className="ord-field-k">window</span>
            <Editable value={o.return_days} number placeholder="—"
              displayFn={v => (v == null || v === "" ? "—" : `${v} days`)} onSave={patch("return_days")} />
          </div>
          <div className="ord-field">
            <span className="ord-field-k">return by</span>
            <Editable value={o.return_by} placeholder={o.return_by_effective || "—"} onSave={patch("return_by")} />
          </div>
          <div className="ord-field">
            <span className="ord-field-k">returned</span>
            <Editable value={o.returned_on} placeholder="—" onSave={patch("returned_on")} />
          </div>
          <div className="ord-field is-wide">
            <span className="ord-field-k">policy</span>
            <Editable value={o.return_policy} multiline placeholder="+ what the vendor's policy actually says"
              onSave={patch("return_policy")} />
          </div>
        </div>
      </section>

      <section className="panel is-wide">
        <div className="panel-head">
          <h2 className="panel-title">origin</h2>
          {o.source === "email" ? <span className="panel-meta">lifted from email</span> : null}
          {o.source === "decision" ? <span className="panel-meta">from a decision</span> : null}
        </div>
        <div className="panel-body panel-pad ord-fields">
          {o.decision_name ? (
            <div className="ord-field">
              <span className="ord-field-k">decision</span>
              <span className="ord-field-v">{o.decision_name}</span>
            </div>
          ) : null}
          <div className="ord-field is-wide">
            <span className="ord-field-k">product</span>
            <Editable value={o.url} placeholder="+ product URL" onSave={patch("url")} />
          </div>
          <div className="ord-field is-wide">
            <span className="ord-field-k">notes</span>
            <Editable value={o.notes} multiline placeholder="+ anything worth remembering" onSave={patch("notes")} />
          </div>
        </div>
        <div className="panel-body panel-pad card-actions">
          <button type="button" className="icon-btn" onClick={() => setModal({ type: "edit-order", order: o })}>edit every field</button>
          <button type="button" className="icon-btn danger" onClick={() => onDelete(o)}>delete order</button>
        </div>
      </section>
    </div>
  );
}

/* Where it lands. One pin, on the Hub's own basemap — the same ground the trip
   maps and the food board draw on, so a map on this page is not a second kind
   of map. There is only ever one point, so there is nothing to fit: it opens
   at street zoom on the address itself.

   No pin without coordinates, and the panel says which of the two reasons it
   is — no address typed yet, or an address the geocoder could not place —
   because those need different things done about them. */
function OrderMap({ o }) {
  const host = oUseRef(null);
  const lat = o.delivery_lat, lng = o.delivery_lng;

  oUseEffect(() => {
    if (lat == null || lng == null || !host.current || !window.L) return;
    const map = L.map(host.current, { scrollWheelZoom: false, attributionControl: false })
      .setView([lat, lng], 15);
    if (window.hubBasemap) hubBasemap(map);
    L.circleMarker([lat, lng], { radius: 7, weight: 2, color: "#fff", fillOpacity: 1 })
      .addTo(map);
    // Leaflet measures the container at construction, and this one is inside a
    // pane that is still laying out. Without the recount the map paints one
    // tile in the corner of a box it thinks is 0x0.
    const t = setTimeout(() => map.invalidateSize(), 60);
    return () => { clearTimeout(t); map.remove(); };
  }, [lat, lng]);

  return (
    <div className="panel">
      <div className="panel-head"><h2 className="panel-title">delivering to</h2></div>
      <div className="panel-body">
        {lat != null && lng != null
          ? <div className="ord-map" ref={host} />
          : <div className="panel-pad ord-map-null">
              {(o.delivery_address || "").trim()
                ? <>couldn't place <b>{o.delivery_address}</b> on the map — the address may need a city and zip on it.</>
                : "no delivery address on this order yet. add one in the parcel card and the pin follows."}
            </div>}
      </div>
      {(o.delivery_address || "").trim()
        ? <div className="panel-pad ord-map-addr">{o.delivery_address}</div> : null}
    </div>
  );
}


/* ── RIGHT — the supplementary read ────────────────────────────────────────
   Not a fifth card: the things you glance at rather than edit. Where it is on
   its journey, the dates that hang off that, and the map of where it lands. */
function OrderSide({ o, onPatch }) {
  const patch = (field) => (nv) => onPatch(o.id, { [field]: nv });
  const exited = o.ship_status === "returned" || o.ship_status === "cancelled";
  const reached = exited ? ORDER_TRACK.length - 1 : ORDER_TRACK.indexOf(o.ship_status);
  const ret = returnLine(o);

  return (
    <aside className="pe-context ord-side">
      <div className="panel">
        <div className="panel-head"><h2 className="panel-title">journey</h2></div>
        <div className="panel-body panel-pad">
          <ol className="ord-prog">
            {ORDER_TRACK.map((s, i) => (
              <li key={s} className={"ord-prog-step" + (i <= reached ? " is-done" : "")
                + (i === reached && !exited ? " is-now" : "")}>
                <span className="ord-prog-dot" aria-hidden="true" />
                <span className="ord-prog-l">{s}</span>
              </li>
            ))}
          </ol>
          {exited ? <div className="ord-prog-exit">{o.ship_status}</div> : null}
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h2 className="panel-title">dates</h2></div>
        <div className="panel-body panel-pad ord-fields">
          <div className="ord-field">
            <span className="ord-field-k">ordered</span>
            <Editable value={o.ordered_on} placeholder="—" onSave={patch("ordered_on")} />
          </div>
          <div className="ord-field">
            <span className="ord-field-k">eta</span>
            <Editable value={o.eta} placeholder="—" onSave={patch("eta")} />
          </div>
          <div className="ord-field">
            <span className="ord-field-k">delivered</span>
            <Editable value={o.delivered_on} placeholder="—" onSave={patch("delivered_on")} />
          </div>
          <div className={`ord-return tone-${ret.tone}`}>{ret.text}</div>
          {OPEN_STATUSES.includes(o.ship_status) ? (
            <button type="button" className="sidebar-btn" onClick={() => onPatch(o.id, { ship_status: "delivered" })}>
              mark delivered
            </button>
          ) : null}
        </div>
      </div>

      <OrderMap o={o} />
    </aside>
  );
}

function OrdersTab({ setModal, reloadKey }) {
  const [orders, setOrders] = oUseState([]);
  const [selectedId, setSelectedId] = oUseState(null);
  const [collapsed, setCollapsed] = oUseState(false);
  const [err, setErr] = oUseState(null);
  const [scanning, setScanning] = oUseState(false);
  const lfRef = oUseRef(null);
  const { rows: shown } = useListFilter(lfRef, ORDERS_LF_CFG, orders);

  const load = oUseCallback(async () => {
    try { setOrders(await papi("GET", "/api/orders")); setErr(null); }
    catch (e) { console.error("[orders] load failed", e); setErr(String(e)); }
  }, []);
  oUseEffect(() => { load(); }, [load, reloadKey]);

  const patch = oUseCallback(async (id, body) => {
    await papi("PATCH", `/api/orders/${id}`, body);
    await load();
  }, [load]);

  const remove = (o) => setModal({
    type: "confirm", title: `Delete "${o.item}"?`,
    body: "This removes the order and its email links. The decision it came from is untouched.",
    confirmLabel: "Delete order",
    onConfirm: async () => { await papi("DELETE", `/api/orders/${o.id}`); setSelectedId(null); await load(); },
  });

  const scan = async () => {
    setScanning(true);
    try {
      const r = await papi("POST", "/api/orders/scan", { days: 45 });
      await load();
      const made = r.created?.length || 0, fixed = r.updated?.length || 0;
      const blank = (r.created || []).filter(c => c.needs_tracking).length;
      window.__pToast?.("ok",
        made || fixed
          ? `${made} new · ${fixed} updated${blank ? ` · ${blank} still need a tracking number` : ""}`
          : `nothing new in ${r.scanned} emails`);
    } catch (e) {
      console.error("[orders] scan failed", e);
      window.__pToast?.("err", "Couldn't read your order email.");
    } finally { setScanning(false); }
  };

  // The middle is never empty while the rail has something in it: filtering
  // down to a list that excludes your selection has to move the selection,
  // or the page reads as broken.
  oUseEffect(() => {
    if (!shown.length) { if (selectedId !== null) setSelectedId(null); return; }
    if (!shown.some(o => o.id === selectedId)) setSelectedId(shown[0].id);
  }, [shown, selectedId]);

  const selected = shown.find(o => o.id === selectedId) || null;

  return (
    <>
      <OrdersRail
        orders={orders} shown={shown} lfRef={lfRef} selectedId={selectedId} onSelect={setSelectedId}
        collapsed={collapsed} onToggleCollapse={() => setCollapsed(c => !c)}
        onNew={() => setModal({ type: "new-order", onDone: load })}
        onScan={scan} scanning={scanning}
      />
      <main className="pe-arena">
        <div className="pe-focus-head">
          <div className="pe-focus-top">
            <h2 className="pe-focus-title">
              {selected
                ? <Editable value={selected.item} onSave={(nv) => patch(selected.id, { item: nv })} />
                : "orders"}
            </h2>
          </div>
          {selected ? (
            <div className="pe-facts">
              <div className="pfact"><span className="pfact-n">{fmtMoney(selected.total, selected.currency)}</span><span className="pfact-l">paid</span></div>
              <div className="pfact"><span className="pfact-n">{selected.ship_status}</span><span className="pfact-l">status</span></div>
              {selected.vendor ? <div className="pfact"><span className="pfact-n">{selected.vendor}</span><span className="pfact-l">vendor</span></div> : null}
            </div>
          ) : null}
        </div>

        <div className="pe-split" data-split="orders">
          <div className="pe-focus-body">
            {err ? <div className="empty-hint">Couldn't load your orders. <button type="button" className="icon-btn" onClick={load}>Retry</button></div> : null}
            {!err && !selected ? (
              <div className="research-null">
                <div className="research-null-what">{orders.length ? "nothing in this filter" : "no orders yet"}</div>
                <div className="research-null-how">
                  add one by hand, or <b>scan email</b> to pull order and shipping confirmations out of Gmail.
                </div>
              </div>
            ) : null}
            {selected ? <OrderCards o={selected} onPatch={patch} setModal={setModal} onDelete={remove} /> : null}
          </div>
          {selected ? <OrderSide o={selected} onPatch={patch} /> : null}
        </div>
      </main>
    </>
  );
}

Object.assign(window, { OrdersTab, ORDER_STATUSES, ORDER_TRACK, returnLine });

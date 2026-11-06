/* The trip cost figures as React components (2026-10-13): the landing card's "your share" stat
   today, the trip page's money cells once trips.js converts. The cost math itself stays in
   trips-cost.js (window.TripCost, still loaded as a plain script and still called by trips.js);
   this file only draws it. First file of the trips surface, so it creates the namespace. */
window.TripsUI = window.TripsUI || {};
(() => {

const money = (n) => n == null || n === "" ? "—"
  : `$${Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/* What a total actually cost, in the currencies it actually cost it. A stay paid entirely in
   points reads as points and never invents a dollar figure for it; a booking that took both
   shows both. plain gives the words-only form a title="" needs, since an attribute cannot
   render the mark. Same rule as the trip page. */
function priceText(p, plain) {
  const parts = [];
  if (p.cash) parts.push(money(p.cash));
  if (p.ur) parts.push((plain ? "" : "\u0001") + Number(Math.round(p.ur)).toLocaleString() + (plain ? " points" : ""));
  return parts.join(" + ");
}

/* The Chase Ultimate Rewards mark, same four paths the plain page inlined. */
function Chase() {
  return (
    <svg className="ur-mark" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M8.584 0C8.116 0 7.737.379 7.737.847V6.786H23.428L16.281 0Z" />
      <path d="M24 8.584C24 8.116 23.621 7.737 23.153 7.737H17.214V23.428L24 16.281Z" />
      <path d="M15.416 24C15.884 24 16.263 23.621 16.263 23.153V17.214H.572L7.719 24Z" />
      <path d="M0 15.416C0 15.884.379 16.263.847 16.263H6.786V.572L0 7.719Z" />
    </svg>
  );
}

/* priceText with the mark drawn as an element: split on the placeholder, put <Chase/> in it. */
function Price({ p }) {
  return <>{priceText(p).split("\u0001").flatMap((s, i) => i ? [<Chase key={i} />, s] : [s])}</>;
}

/* The per-viewer "your share" stat on a trip card. Same model the trip page runs
   (TripCost.tripMoney), off the rows the summary ships. Renders nothing when there is no
   figure, like the plain card. */
function TripsCost({ trip }) {
  const m = window.TripCost.tripMoney(trip);
  const done = (x) => x.cash || x.ur;
  const yours = done(m.committed) ? m.committed : m.projected;
  if (!priceText(yours)) return null;
  const title = (done(m.committed) ? "committed" : "projected — nothing booked yet")
    + (m.party > 1 ? ` · your share, split ${m.party} ways of ${priceText(done(m.group.committed) ? m.group.committed : m.group.projected, true)}` : "");
  return (
    <span className="stat" title={title}>
      <span className="stat-n"><Price p={yours} /></span>
      <span className="stat-l">your share</span>
    </span>
  );
}

window.TripsUI.TripsCost = TripsCost;
window.TripsUI.Price = Price;
window.TripsUI.priceText = priceText;
})();

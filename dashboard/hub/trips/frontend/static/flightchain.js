/* ============================================================
   hub · trips — connecting-segment collapse.

   The flights table stores one row per SEGMENT, and the only thing
   grouping them is `direction`. That is fine when the rows really are
   alternatives (three "considering" JFK→SAL fares), and wrong when they
   are two halves of one journey: UA1618 EWR→IAD and UA204 IAD→CMH are
   both direction='outbound', so the board read them as rival options,
   labelled the leg EWR→IAD, and ran the arrival timeline off the Dulles
   landing instead of the Columbus one.

   chain() folds nose-to-tail segments on the same confirmation into a
   single row carrying the real endpoints, the summed fare, and a `via`
   list. No DOM, no fetch, no state — same shape as triptime.js.
   ============================================================ */
((root) => {
  

  var ticket = (r) => String((r?.confirmation) || "").trim().toUpperCase();
  var num = (v) => Number(v) || 0;

  /* seg[] -> one row. Departure end from the first segment, arrival end from
     the last, fare summed (the convention is to park the whole itinerary price
     on the first leg and leave the rest null, so this is usually a no-op). */
  function merge(seg) {
    var a = seg[0], z = seg[seg.length - 1], m = {}, via = [], nums = [], cost = 0, i, k;
    for (k in a) if (Object.hasOwn(a, k)) m[k] = a[k];
    for (i = 0; i < seg.length; i++) {
      cost += num(seg[i].cost);
      if (seg[i].flight_num && seg[i].flight_num !== "—") nums.push(seg[i].flight_num);
      if (i < seg.length - 1 && seg[i].to_airport) via.push(seg[i].to_airport);
    }
    m.to_airport = z.to_airport;
    m.arrival_time = z.arrival_time;
    m.terminal_to = z.terminal_to;
    m.flight_num = nums.join(" + ");
    m.cost = cost || null;
    m.segments = seg;     // the real rows, for anything that needs them back
    m.via = via;          // ["IAD"] — the stops between the two endpoints
    return m;
  }

  /* Rows of ONE direction group -> the same rows with connections collapsed.
     Order matters: rows arrive in departure order (db.py sorts on
     departure_time), and the chain is built forward from each unclaimed row.
     Two rows only chain when they share a non-empty confirmation and meet at
     an airport, so alternatives — which share neither — are left alone. */
  function chain(rows) {
    var list = rows || [], used = [], out = [], i, j;
    for (i = 0; i < list.length; i++) {
      if (used[i]) continue;
      used[i] = 1;
      const seg = [list[i]], origin = list[i].from_airport;
      for (;;) {
        let tail = seg[seg.length - 1], hit = -1;
        for (j = 0; j < list.length; j++) {
          if (used[j]) continue;
          const c = list[j];
          if (!ticket(c) || ticket(c) !== ticket(tail)) continue;
          if (!c.from_airport || !tail.to_airport || c.from_airport !== tail.to_airport) continue;
          // a leg that lands back where it started is a round trip filed under
          // one direction, not a connection — don't swallow the way home
          if (origin && c.to_airport === origin) continue;
          hit = j; break;
        }
        if (hit < 0) break;
        seg.push(list[hit]);
        used[hit] = 1;
      }
      out.push(seg.length === 1 ? list[i] : merge(seg));
    }
    return out;
  }

  var API = { chain: chain };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  root.FlightChain = API;
})(typeof globalThis !== "undefined" ? globalThis : this);

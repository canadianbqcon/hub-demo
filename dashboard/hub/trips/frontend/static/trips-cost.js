/* hub · trips — the cost model, shared by the trip page and the landing page.

   It used to live inline in trips.js, which is why the landing card showed a
   different (and wrong) number: it had no access to any of this and fell back to
   SUM(expenses.amount), a figure that ignores the stay, the fares and the car.
   One model, two pages — the landing now runs the same arithmetic the trip page
   does, off the same rows.

   Money lives in four tables (housing.total_cost, flights.cost,
   transportation.cost, expenses.amount). Two figures come out:
     committed — rows actually locked in (booked / confirmed / paid)
     projected — committed plus the cheapest still-open option per open choice

   And two POINTS OF VIEW on each, which is the thing this file exists to get
   right:
     mine  — what the trip costs SAM. A seven-person Airbnb is not his bill.
     group — what the trip costs everyone together. Still true, still shown.

   ponytail: an even split, because that is how these trips settle up — one
     person books the house, everybody sends their seventh. A row that someone
     covers alone would need a payer/split column on the row; there isn't one,
     and inventing it before a trip needs it is the wrong order. */
(() => {
  

  var COMMITTED = ["booked", "confirmed", "paid"];
  var DEAD = ["unavailable", "rejected", "cancelled", "skip"];
  var isCommitted = (r) => COMMITTED.indexOf(r.status) >= 0;
  var isDead = (r) => DEAD.indexOf(r.status) >= 0;
  var isOpen = (r) => !isCommitted(r) && !isDead(r);
  var rowCost = (r) => Number(r.total_cost != null ? r.total_cost : (r.cost != null ? r.cost : r.amount)) || 0;
  // Sam's own flight rows. An empty `passenger` means his seat; a named one is
  // a fellow traveller's ticket, which rides in the same table so it can reach the
  // trip calendar, but is not his money and is not a fare he is choosing between.
  var myFlights = (t) => (t.flights || []).filter((f) => !(f.passenger || "").trim());
  // WHO OWNS THE BOARD. There is no owner flag on `members`, so the contact slug
  // is the marker, falling back to the first name on the roster — the same rule
  // the flights board already uses (meMember in trips.js).
  var ME_SLUG = "sam-rivera";
  function ownerId(t) {
    var M = (t?.members || []).filter((m) => String(m.name || "").trim());
    var me = M.filter((m) => (m.contact_slug || "") === ME_SLUG)[0] || M[0];
    return me ? String(me.id) : null;
  }

  /* ── WHO "YOU" MEANS ───────────────────────────────────────────────────────
     Every per-person figure on the cost tab is labelled "your share", and until
     now "your" was always Sam — on the shared link too, which is how Aria
     opened her own itinerary and was shown HIS $560.00 fare, HIS half of the
     Hyatt and HIS bag money as hers. The model had no idea who was reading.
     It does now: the mirror already binds a reader (window.TRIP_VIEWER, the
     guest_codes key a passcode unlocked) for the flights board, and the same
     key answers this question. Empty on Hub, so Hub is unchanged: no viewer
     means the owner, exactly as before.
     A viewer who is not on THIS trip's roster resolves to nobody rather than
     falling back to the owner — a stranger's share is $0.00, and quietly
     handing them Sam's figures is the bug this exists to kill.
     ponytail: read lazily, like isGuest, because this file is parsed before the
       script tag that sets the key. */
  var viewerKey = () => typeof window !== "undefined" ? String(window.TRIP_VIEWER || "").trim() : "";
  // db.member_key spelled in JS: a contact slug when the member has a wiki
  // contact node, otherwise "name:" + their name lowercased. Both spellings have
  // to match, or half the crew never matches their own code.
  var memberKey = (m) => (m && (m.contact_slug || "").trim())
      || `name:${String((m?.name) || "").trim().toLowerCase()}`;
  function meId(t) {
    var v = viewerKey();
    if (!v) return ownerId(t);
    var hit = (t?.members || []).filter((m) => memberKey(m) === v)[0];
    return hit ? String(hit.id) : null;
  }

  /* The roster and the boarding pass do not have to agree on a name. A ticket
     has to match a passport; the crew list is what Sam calls people. Nina
     Ford flies as Sophia Ford. And one row can carry two people: Denver's
     outbound is booked as "Aaron + Jasmine". So the match runs per NAME TOKEN —
     each token names a member if exactly one member's name carries it.
     ponytail: a token two members share (Josh and Amanda Ortiz on `ortiz`) is
       an ambiguity and names nobody, rather than being guessed at. A contact_slug
       on the flight row would make this exact.
     Lives here rather than in trips.js because "which member does this passenger
     field name" is a model question — the flights board now reads this one. */
  var nameBits = (s) => String(s || "").toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
  function membersNamed(t, who) {
    var M = (t?.members || []).filter((m) => (m.name || "").trim());
    var out = [];
    nameBits(who).forEach((tok) => {
      var hit = M.filter((m) => nameBits(m.name).indexOf(tok) >= 0);
      if (hit.length === 1 && out.indexOf(hit[0]) < 0) out.push(hit[0]);
    });
    return out;
  }
  // WHOSE SEAT A FLIGHT ROW IS, as member ids. An explicit split_with wins (it is
  // ids, so it is exact); otherwise the name on the ticket; a blank passenger is
  // the owner's, which is what that empty field has always meant.
  function seatIds(t, f) {
    var ids = splitIds(f);
    if (ids) return ids;
    var who = (f.passenger || "").trim();
    if (!who) { const o = ownerId(t); return o ? [o] : []; }
    return membersNamed(t, who).map((m) => String(m.id));
  }
  // …and the flights HIS MONEY is on, which is a different question from which
  // seat he sits in. A ticket he bought for another traveller left his account on
  // this trip, so it is a line in this trip's cost whoever is flying on it. It
  // comes back to him in the LEDGER, not here — `split_with` says who owes it,
  // and an unassigned one surfaces in `fronted`.
  // Sam, 2026-08-25: "flights in the cost tab should only show all of the
  // flights that I paid for … Aria's flight should not be another. It should be
  // considered a flight you [paid for]."
  // This is deliberately NOT myFlights: the flights BOARD still shows only his
  // own legs as his, and Aria's ticket still renders under "travelling with you".
  // Whose seat it is and whose card it was are two different questions.
  // The third clause is the reader's: a guest who booked her own ticket has it in
  // no other clause — nobody on the board paid for it, so it is not the owner's
  // money — and dropping it left her cost tab reading $0.00 for a flight she is
  // sitting on. Dead on Hub, where the reader IS the owner.
  // It makes the "trip's bill" card reader-dependent by exactly that fare: her
  // page counts her self-booked seat, everyone else's cannot see it. That is the
  // honest direction — the fare is real trip money the board simply never knew
  // about — and the alternative is telling her her own ticket costs nothing.
  var myFares = (t) => {
    var me = meId(t), owner = ownerId(t);
    return (t.flights || []).filter((f) => {
      if (!(f.passenger || "").trim()) return true;                  // the owner's own seat
      if (owner && String(f.paid_by || "").trim() === owner) return true;  // his card, her seat
      return me !== owner && !!me && seatIds(t, f).indexOf(me) >= 0;  // the reader's own ticket
    });
  };
  // The public mirror sets body.guest; Hub never does. A guest gets the
  // itinerary, not the fares — and flight money has to leave the MODEL, not just
  // the flights board, or the cost tab and the trip total hand it straight back.
  // Read lazily: this file is parsed before the body exists.
  var isGuest = () => typeof document !== "undefined" && !!document.body
      && document.body.classList.contains("guest");
  var TRANSPORT_BUCKET = {
    car_rental: "carrental", "car rental": "carrental", rental: "carrental",
    "rental car": "carrental", car: "carrental", turo: "turo",
  };
  var busOf = (x) => TRANSPORT_BUCKET[String(x.type || "").trim().toLowerCase()] || "other";
  var isCar = (x) => busOf(x) !== "other";
  var sumCost = (rows) => rows.reduce((s, r) => s + rowCost(r), 0);
  // points_transfer (Chase UR actually spent to produce the award) is the
  // truer figure when it exists — it's the one currency he can value
  // precisely (see UR_CENTS below). A stay/seat redeemed straight out of an
  // existing partner balance, with no fresh transfer behind it, has no
  // points_transfer at all; points_total (the redemption itself) is the only
  // real figure on that row, so it stands in. Never both — points_total on a
  // row that also has points_transfer would double the same money.
  var rowUR = (r) => {
    var transferred = Number(r.points_transfer) || 0;
    return transferred || (Number(r.points_total) || 0);
  };

  /* ── THE PUBLIC PAGE IS IN DOLLARS ────────────────────────────────────────
     A guest cannot act on "24,000 World of Hyatt". They are reading this to know
     what the trip costs and what they owe, and a points figure answers neither.
     So on the public mirror ONLY, the UR pool is converted and folded into cash;
     Sam's own board keeps points as points, because points are what he
     actually spent.

     The rate is what he can CASH OUT at, not what a good transfer might fetch:
     1.25c, the Chase Travel portal floor on the Sapphire Preferred, per
     wiki/notes/card-strategy-2026.md — "guaranteed, no transfer needed,
     available on every booking", and the rate every figure in that note uses.
     It was 1.7c until 2026-08-25, his own aspirational Aeroplan-transfer
     valuation from wiki/notes/flight-rewards-redemption-practice.md. That
     number priced a trip at what the points MIGHT be worth if a specific
     transfer lands, which is not what a bill is for. Sam, 2026-08-25:
     "it should be the default point conversion, being whatever the cash value
     is of my unlimited reward points if I were to do cash back."
     ponytail: one rate over every points figure rowUR returns, whether it came
       from a fresh Chase transfer or straight out of a partner balance — a
       different rate per programme would need its own table and no trip has
       needed that granularity yet.
     If the rate changes, this constant is the one place it moves. */
  var UR_CENTS = 0.0125;
  // …and a row that was redeemed at its own rate says so, in its own column:
  // `cents_per_point`, cents per point, migration 016. NULL or 0 falls back to
  // the trip-wide default above, which is the right answer for a row with no
  // redemption of its own.
  //
  // This replaced RATE_EXCEPTIONS, a name-keyed override
  // (`{ "Hyatt Regency Columbus": 0.0340013698630137 }`) that produced two
  // different prices for one row: the cost table priced trip 59's stay at the
  // flat rate ($600.00) while the settlement priced it at the exception
  // ($1,200.00), and the landing page could never see the exception at all
  // because its cost query never selected `name`. One column, one price.
  var rateFor = (r) => {
    var cents = Number(r?.cents_per_point);
    return cents > 0 ? cents / 100 : UR_CENTS;
  };
  var sumUR = (rows) => rows.reduce((s, r) => s + rowUR(r), 0);
  var cheapest = (rows) => rows.filter((r) => rowCost(r) > 0)
               .sort((a, b) => rowCost(a) - rowCost(b))[0] || null;

  /* ── What splits and what doesn't ──────────────────────────────────────────
     A house and a car are one thing the group buys together, so each head owes
     a share. A seat and a plate of food are bought one head at a time — his
     flight row is already his money alone (myFares keeps only his seat and the
     tickets he fronted, and a fronted one carries its own split_with) and
     every expense row is his own spending, so neither is divided.
     This is the same rule the row-level readouts have always used: the housing
     board prints "each at 7" and the rideshare board prints "each". Only the
     trip TOTAL never got it. */
  var SHARED = { housing: true, transportation: true };
  var PERSONAL = { flights: true, expenses: true };

  // An `estimated` expense whose category names a table that already holds
  // priced rows is a placeholder for that choice, not a cost on top of it.
  // ponytail: matched on category text. It's the only signal in the schema; a
  // `covers` FK on expenses would make it exact if this ever gets ambiguous.
  var EXPENSE_COVERS = {
    flight: "flights", flights: "flights", airfare: "flights",
    lodging: "housing", housing: "housing", stay: "housing", hotel: "housing", accommodation: "housing",
    transport: "transportation", transportation: "transportation", ground: "transportation",
  };
  // Matched on the leading word, not the whole string. "Flights (Sophia)" is the
  // flights table with a passenger stapled to the label — an exact-match lookup
  // missed it, and the row it duplicated (a ticket he fronted, now counted in
  // myFares) was billed twice: $250.00 under flights and $250.00 again under
  // other.
  function coversTable(cat) {
    var c = String(cat || "").trim().toLowerCase();
    return EXPENSE_COVERS[c] || EXPENSE_COVERS[c.split(/[^a-z]+/)[0]] || null;
  }
  function supersededExpense(trip, e) {
    var table = coversTable(e.category);
    if (!table) return null;
    var rows = trip?.[table] || [];
    // Once the covering table holds a committed row, the expense line is a
    // second description of that same booking, whatever status it carries.
    if (rows.some(isCommitted)) return table;
    // Nothing booked yet: an estimated line is a placeholder for a choice the
    // priced rows already represent. A line marked paid while the choice is
    // still open is real money on top and stays counted.
    if (e.status !== "estimated") return null;
    return rows.some((r) => rowCost(r) > 0) ? table : null;
  }

  // How many heads a shared row splits across. The crew list is the answer; the
  // trip page's party control can override it for "what if the seventh comes".
  function partyOf(trip, override) {
    if (override != null) return Math.max(1, override);
    var n = (trip?.members || []).length || trip?.n_crew || 1;
    return Math.max(1, n);
  }

  // Any cost row can be explicitly tagged with WHO it splits between
  // (row.split_with, a comma-separated members.id list from the "split
  // between" checkboxes) — the Dino Express shuttle is Sam + Megan, not
  // the whole four-person crew, and a tagged flight or expense becomes a
  // shared cost the same way housing/transportation always have been.
  // Untagged rows keep the old default: SHARED tables split across the full
  // party, everything else (flights/expenses/activities) is Sam's alone.
  function splitIds(r) {
    var raw = String(r?.split_with || "").trim();
    if (!raw) return null;
    var ids = raw.split(",").map((s) => s.trim()).filter(Boolean);
    return ids.length ? ids : null;
  }
  function splitCountFor(r, table, party) {
    var ids = splitIds(r);
    if (ids) return ids.length;
    return SHARED[table] ? party : 1;
  }

  // WHO FRONTED IT. One members.id, as text — the person whose card was
  // charged. Empty means nobody has claimed the line: it still counts toward
  // the trip's total, it just cannot enter a settlement, because inventing an
  // owner is how a payback list starts lying about who owes whom.
  // A payer is a members.id, always. `expenses.paid_by` predates the crew list
  // and holds a TYPED NAME on the rows already in the database ("Sam"), and
  // a name cannot be settled against — matched to nobody, it would walk into the
  // ledger as a phantom eighth traveller who owes and is owed nothing. So the id
  // is checked against the crew, and anything that is not one of them reads as
  // unclaimed, which is the honest answer and the one the rail asks about.
  function payerOf(r, crewIds) {
    var v = String(r?.paid_by || "").trim();
    if (!v) return null;
    if (crewIds && crewIds.indexOf(v) < 0) return null;
    return v;
  }
  // WHO IT IS FOR. An explicit split_with wins on any table. Untagged, a shared
  // row is the whole crew and a personal row is its own payer's — which nets to
  // zero and creates no debt, exactly right for a seat he bought for himself.
  function participantsOf(r, table, crewIds, payer) {
    var ids = splitIds(r);
    if (ids) return ids;
    if (SHARED[table]) return crewIds.slice();
    return payer ? [payer] : [];
  }
  function crewIdsOf(trip) {
    return (trip?.members || []).map((m) => String(m.id));
  }
  /* HOW MUCH OF A LINE IS HIS. `split` only ever counted the heads a line
     divides between; it never asked whether he is one of them. So a ticket
     tagged for Aria alone (split_with = her id, one head, split = 1) landed in
     his own per-person total at FULL price, and the cost tab billed him for
     both seats on a two-person trip.
     The per-person view answers one question — what does he actually pay when
     all is said and done — so a line he is not on is worth zero to him. The
     money he fronted for someone else is not lost from the page: it is what
     the ledger's "who fronted it" and "settle up" cards exist to hand back.
     A line with NOBODY named stays entirely his. That is the board's default
     for an unassigned row (participantsOf returns [] for a personal row with no
     payer) and the only honest reading — dropping it would quietly delete an
     un-owned expense from his own total.
     Sam, 2026-08-26: "It's not both of the flights for both people … It's
     about what you are supposed to pay at the end of the day." */
  // A line with NOBODY named is the OWNER's, not the reader's. Left as "always
  // mine" it billed a guest for every unclaimed row on the board — Austin's two
  // $220.00 fares and its $700 house all carry no payer. `isOwner` omitted means
  // owner-is-reader, which is Hub and every caller that predates the viewer.
  function myFactor(ids, me, isOwner) {
    if (!ids?.length) return isOwner === false ? 0 : 1;
    return me && ids.indexOf(me) >= 0 ? 1 / ids.length : 0;
  }

  /* Every row that counts, tagged with its table and whether it is settled or
     still open. One pass — the totals, the per-category breakdown and the chart
     all read this instead of re-deriving the same filters three times. */
  function costRows(trip, partyOverride) {
    var t = trip || {};
    var party = partyOf(t, partyOverride);
    var guest = isGuest();
    // Flights stay IN the model on the public page. They were pulled out when the
    // guest surface had no way to state a fare in dollars, so the only options
    // were a points figure or nothing. It has one now — the UR conversion below —
    // and a cost tab that silently omits the biggest line is not a cost tab: the
    // trip total, the group's bill and every "what do I owe" read off it are
    // wrong by the whole flights column. The FLIGHTS BOARD still hides the fare
    // per-leg; the accounting is a different question from the booking detail.
    var H = t.housing || [], F = myFares(t), X = t.transportation || [];
    var E = (t.expenses || []).filter((e) => !supersededExpense(t, e));

    var out = [];
    var crewIds = crewIdsOf(t);
    var me = meId(t), owner = ownerId(t), iAmOwner = me === owner;
    function take(rows, table, state) {
      rows.forEach((r) => {
        var cash = rowCost(r), ur = rowUR(r);
        var payer = payerOf(r, crewIds);
        // Fold, don't show both: a guest line reading "$0.00 + 24,000 UR" is the
        // problem, not the fix. The whole row lands in one currency. Guest-only —
        // that fold is a payback breakdown for other travellers, who need one
        // actionable dollar figure. Hub keeps cash and UR separate in this total;
        // his own words: "for me I want the true point cash spread." The row's
        // display layer (priceText in trips.js) adds the UR's cash value next to
        // it for his reference, but this total never folds it in on Hub.
        if (guest && ur) { cash += ur * rateFor(r); ur = 0; }
        // What those points are worth in dollars AT THIS ROW'S RATE. It rides
        // along beside the points rather than replacing them, because every
        // total this feeds is a sum over rows priced at different rates — a
        // pooled points figure has no single rate left to convert by, which is
        // how the rail printed 30,000 points as $600.00 while the row it came
        // from billed $1,200.00. Nothing here converts; it carries.
        var ids = participantsOf(r, table, crewIds, payer);
        // A FLIGHT NAMES ITS OWN OCCUPANT. Falling through to the payer put a
        // ticket on the card that bought it and nobody else, so a seat somebody
        // booked themselves — no payer on the board at all — belonged to no one
        // and read as $0.00 on the page of the very person sitting in it.
        if (!ids.length && table === "flights") ids = seatIds(t, r);
        var split = splitCountFor(r, table, party);
        // A shared row with nobody named is still shared. The landing summary can
        // carry a head count with no roster behind it (`n_crew`), and read as
        // "nobody named" that handed the whole house to whoever was reading.
        var mine = (!ids.length && SHARED[table]) ? 1 / split : myFactor(ids, me, iAmOwner);
        out.push({ row: r, table: table, state: state, cash: cash, ur: ur,
                   urCash: ur * rateFor(r),
                   split: split,
                   mine: mine,
                   payer: payer, ids: ids });
      });
    }
    take(H.filter(isCommitted), "housing", "committed");
    take(F.filter(isCommitted), "flights", "committed");
    take(X.filter(isCommitted), "transportation", "committed");
    take(E.filter(isCommitted), "expenses", "committed");

    // Housing and flights are ALTERNATIVES — six Airbnbs are one stay, three
    // JFK→SAL fares are one seat — so an undecided group contributes only its
    // cheapest option, and flights do it per direction. Buses, trains and
    // expenses are additive line items and contribute their whole open sum.
    // Rentals and Turo are alternatives to EACH OTHER — five Denver quotes and
    // two Turo listings are one car, not seven.
    // ponytail: one car per trip. A trip that genuinely needs two vehicles books
    //   both and the committed sum counts them; only the open projection collapses.
    if (!H.some(isCommitted)) { const h = cheapest(H.filter(isOpen)); if (h) take([h], "housing", "open"); }
    // Per TRAVELLER per direction, not per direction: since myFares can hold a
    // seat he is buying for someone else, "the cheapest JFK→SAL" would otherwise
    // pick one fare to cover two people flying.
    var keyOf = (f) => `${(f.passenger || "").trim().toLowerCase()}|${f.direction || "outbound"}`;
    var dirs = [];
    F.forEach((f) => { var k = keyOf(f); if (dirs.indexOf(k) < 0) dirs.push(k); });
    dirs.forEach((d) => {
      var leg = F.filter((f) => keyOf(f) === d);
      if (leg.some(isCommitted)) return;
      var c = cheapest(leg.filter(isOpen));
      if (c) take([c], "flights", "open");
    });
    var cars = X.filter(isCar), rest = X.filter((x) => !isCar(x));
    if (!cars.some(isCommitted)) { const c2 = cheapest(cars.filter(isOpen)); if (c2) take([c2], "transportation", "open"); }
    take(rest.filter(isOpen), "transportation", "open");
    take(E.filter(isOpen), "expenses", "open");

    return { rows: out, party: party };
  }

  function zero() { return { cash: 0, ur: 0, urCash: 0 }; }
  // `per` means HIS share, which is r.mine — not 1/r.split. See myFactor.
  function add(acc, r, per) {
    var f = per ? (r.mine != null ? r.mine : 1 / (r.split || 1)) : 1;
    acc.cash += r.cash * f;
    acc.ur += r.ur * f;
    acc.urCash += r.urCash * f;
    return acc;
  }

  /* The whole money picture for one trip.

     `mine` / `group` each carry committed, projected and open, in both
     currencies. A trip is not paid for in one currency — the Hyatt cost 24,000
     Chase UR and no cash, the flights cost UR AND $120.00 in taxes — so nothing
     here ever converts points to dollars or the reverse. */
  function tripMoney(trip, partyOverride) {
    var cr = costRows(trip, partyOverride);
    function view(per) {
      var done = zero(), open = zero();
      cr.rows.forEach((r) => { add(r.state === "committed" ? done : open, r, per); });
      return {
        committed: done,
        open: open,
        projected: { cash: done.cash + open.cash, ur: done.ur + open.ur,
                     urCash: done.urCash + open.urCash },
      };
    }
    var m = view(true), g = view(false);
    // The group gets its own breakdown too — the cost tab's rail answers "what
    // does this cost everyone", which is the half the per-person body drops.
    g.byCategory = byCategory(cr, false);
    m.group = g;
    m.party = cr.party;
    m.byCategory = byCategory(cr, true);
    m.rows = cr.rows;
    return m;
  }

  // Chart input: one entry per money table, committed and still-open kept apart
  // so the bar can show what is already spent against what the trip would cost
  // if every open choice went the cheap way.
  var CATEGORIES = [
    { key: "housing", label: "stay" },
    { key: "flights", label: "flights" },
    { key: "transportation", label: "ground" },
    { key: "expenses", label: "other" },
  ];
  function byCategory(cr, per) {
    return CATEGORIES.map((c) => {
      var mine = cr.rows.filter((r) => r.table === c.key);
      var done = zero(), open = zero();
      mine.forEach((r) => { add(r.state === "committed" ? done : open, r, per); });
      return {
        key: c.key, label: c.label, shared: !!SHARED[c.key],
        committed: done, open: open,
        total: { cash: done.cash + open.cash, ur: done.ur + open.ur,
                 urCash: done.urCash + open.urCash },
      };
    });
  }

  /* ── THE LEDGER: who put the money down, and who owes them ────────────────
     The totals answer "what does this trip cost." They never answered the
     question a group trip actually ends on — one person's card paid for the
     house, another's paid for the van, and at the end everybody sends money to
     somebody. That lived in prose inside `description` ("booked by Jasmine",
     "fronted by Sam — $450 owed back") where no figure could read it.

     Per person:
       paid  — what left their account, IN THE CURRENCY THEY SPENT. A stay booked
               on 24,000 World of Hyatt points cost points, and saying so is the
               whole reason this file never converts anything.
       owed  — their share of every line they are on, IN DOLLARS.
       net   — paid minus owed, in dollars. Positive means the trip owes THEM.

     A DEBT IS ALWAYS IN DOLLARS. Nobody settles up by transferring Chase points
     to another traveller — they send money. So a line bought with points still
     produces a cash debt: each person's share is valued at the same rate the
     board already uses for that row (rateFor — the 1.25c cash-out floor, or the
     row's own rate where one is set). This is the one place a conversion is
     correct, and it is the only
     place it happens: the bill above still reads 24,000 points, because that is
     what was actually spent.

     COMMITTED ROWS ONLY. An assumed price is not a debt: nobody has paid the
     $200 Saturday-night rideshare, so nobody is owed for it and nobody owes it.
     The moment it is booked and claimed, it enters here on its own.

     ponytail: one payer per row. A line two people genuinely split at the till
       is two rows, which is also how the receipt reads. */
  var EPS = { cash: 0.005, ur: 1 };
  // What one row is worth as a debt: its cash plus its points at that row's rate.
  var debtValue = (r) => r.cash + r.ur * rateFor(r.row || {});

  function ledger(trip, partyOverride) {
    var t = trip || {};
    var crew = t.members || [];
    var cr = costRows(t, partyOverride);
    var acc = {};
    var seat = (id) => {
      if (!acc[id]) acc[id] = { id: String(id), name: "", paid: zero(), owed: zero(), net: zero() };
      return acc[id];
    };
    // Running dollar totals kept beside the display figures: `paid` has to stay
    // dual-currency on screen, but only one number can be netted and settled.
    var put = {}, got = {};
    crew.forEach((m) => { seat(String(m.id)).name = m.name || String(m.id); });

    var unclaimed = { cash: 0, ur: 0, urCash: 0, rows: 0 };
    var fronted = [];
    var counted = 0;
    // Shares the owed tab marks paid (owed.src keys, sent as trip.settled_debts).
    // Same line key as finances/trip_debts.py: a flight by its confirmation, so
    // both legs of one ticket settle together; anything else by its row id.
    var settledSet = new Set(t.settled_debts || []);
    function settled(r, id) {
      var conf = r.table === "flights" ? String(r.row.confirmation || "").trim() : "";
      var key = "trip:" + (r.row.trip_id != null ? r.row.trip_id : t.id) + "/" + r.table + "/" + (conf || r.row.id);
      return settledSet.has(key + "/member:" + id);
    }
    function post(r) {
      if (!r.cash && !r.ur) return;                 // a free leg on another row's ticket
      if (!r.payer) {
        unclaimed.cash += r.cash; unclaimed.ur += r.ur;
        unclaimed.urCash += r.urCash; unclaimed.rows += 1;
        return;
      }
      counted += 1;
      var p = seat(r.payer);
      p.paid.cash += r.cash; p.paid.ur += r.ur; p.paid.urCash += r.urCash || 0;
      var worth = debtValue(r);
      put[r.payer] = (put[r.payer] || 0) + worth;
      var n = r.ids.length || 1;
      (r.ids.length ? r.ids : [r.payer]).forEach((id) => {
        var q = seat(id);
        q.owed.cash += worth / n;
        // Paid back already: the share still counts as theirs, it just no
        // longer moves money in the settle-up.
        if (id !== r.payer && settled(r, id)) { put[r.payer] -= worth / n; return; }
        got[id] = (got[id] || 0) + worth / n;
      });
    }
    // Tickets bought for other travellers now ride in cr.rows (they are his
    // money), but the ledger has its own pass for them below — the only one that
    // can tell a fronted ticket with nobody ticked from one that settles back.
    // Posting them in both places would bill the same debt twice.
    cr.rows.forEach((r) => {
      if (r.state !== "committed") return;
      if (r.table === "flights" && (r.row.passenger || "").trim()) return;
      post(r);
    });

    /* A ticket he bought for SOMEBODY ELSE. tripMoney drops those on purpose —
       he is not flying on it, so it is not his cost — but it is his money until
       they pay him back, which is the whole question this ledger answers. So
       the foreign tickets come back in here, and only here.
       With nobody ticked, there is no honest default: the passenger field is a
       typed name, not a crew id, so the model cannot know which member owes it.
       Those land in `fronted` — money someone is holding the bill for with no
       payer-back assigned — instead of being silently netted to zero against
       the person who bought it. */
    var guest = isGuest();
    (t.flights || []).forEach((f) => {
      if (!(f.passenger || "").trim()) return;      // his own seat, already posted above
      if (!isCommitted(f)) return;
      var cash = rowCost(f), ur = rowUR(f);
      if (!cash && !ur) return;
      if (guest && ur) { cash += ur * rateFor(f); ur = 0; }
      var payer = payerOf(f, crewIdsOf(t)), ids = splitIds(f);
      var urCash = ur * rateFor(f);
      if (payer && !ids) { fronted.push({ row: f, table: "flights", cash: cash, ur: ur, urCash: urCash, payer: payer }); return; }
      post({ row: f, table: "flights", cash: cash, ur: ur, urCash: urCash, payer: payer, ids: ids || [] });
    });

    var people = Object.keys(acc).map((id) => {
      var a = acc[id];
      a.net = { cash: (put[id] || 0) - (got[id] || 0), ur: 0, urCash: 0 };
      if (!a.name) a.name = id;                     // paid_by pointing at a departed member
      return a;
    }).sort((a, b) => b.net.cash - a.net.cash);

    return {
      people: people,
      transfers: transfers(people),
      unclaimed: unclaimed,
      fronted: fronted,
      claimed: counted,
      party: cr.party,
    };
  }

  /* Fewest payments that clear the board. Biggest debtor pays the biggest
     creditor until one of them is square, repeat — the standard greedy, which
     on a group this size gives at most (people - 1) payments and never asks
     anyone to send two cheques to the same person.
     One currency, because a payment between two people is dollars: every net
     reaching here has already had its points valued by debtValue. */
  function transfers(people) {
    var out = [], owed = [], owes = [];
    people.forEach((p) => {
      if (p.net.cash > EPS.cash) owed.push({ p: p, v: p.net.cash });
      else if (p.net.cash < -EPS.cash) owes.push({ p: p, v: -p.net.cash });
    });
    owed.sort((a, b) => b.v - a.v);
    owes.sort((a, b) => b.v - a.v);
    var i = 0, j = 0;
    while (i < owes.length && j < owed.length) {
      const amt = Math.min(owes[i].v, owed[j].v);
      out.push({ from: owes[i].p.id, fromName: owes[i].p.name,
                 to: owed[j].p.id, toName: owed[j].p.name, cash: amt, ur: 0 });
      owes[i].v -= amt; owed[j].v -= amt;
      if (owes[i].v <= EPS.cash) i += 1;
      if (owed[j].v <= EPS.cash) j += 1;
    }
    return out.sort((a, b) => b.cash - a.cash);
  }

  // Every committed line one person put money down for, newest question first:
  // "what am I actually holding the bill for." Used by the rail's fronted-by
  // card so a figure is never a dead end — you can see the rows behind it.
  function rowsPaidBy(trip, memberId, partyOverride) {
    return costRows(trip, partyOverride).rows.filter((r) => r.state === "committed" && r.payer === String(memberId));
  }

  window.TripCost = {
    COMMITTED: COMMITTED, DEAD: DEAD,
    isCommitted: isCommitted, isDead: isDead, isOpen: isOpen,
    rowCost: rowCost, rowUR: rowUR, sumCost: sumCost, sumUR: sumUR, cheapest: cheapest,
    myFlights: myFlights, myFares: myFares, meId: meId, ownerId: ownerId, ME_SLUG: ME_SLUG,
    viewerKey: viewerKey, memberKey: memberKey, nameBits: nameBits, membersNamed: membersNamed,
    seatIds: seatIds, isGuest: isGuest, UR_CENTS: UR_CENTS, rateFor: rateFor, busOf: busOf, isCar: isCar, TRANSPORT_BUCKET: TRANSPORT_BUCKET,
    EXPENSE_COVERS: EXPENSE_COVERS, coversTable: coversTable, supersededExpense: supersededExpense,
    SHARED: SHARED, PERSONAL: PERSONAL, CATEGORIES: CATEGORIES,
    partyOf: partyOf, costRows: costRows, tripMoney: tripMoney,
    splitIds: splitIds, splitCountFor: splitCountFor,
    payerOf: payerOf, participantsOf: participantsOf, crewIdsOf: crewIdsOf, myFactor: myFactor,
    ledger: ledger, transfers: transfers, rowsPaidBy: rowsPaidBy, EPS: EPS, debtValue: debtValue,
  };
})();

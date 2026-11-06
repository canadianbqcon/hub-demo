/* Finances · 2 of 5 (React): the transactions tab, the local book (data/book.db) through
   /finances/api/book/*: SimpleFIN rows plus the imported history. Ported from finances.js lines
   2101-2334. The plain page read its filter inputs off the DOM at request time and drew rows with
   innerHTML; here the filters stay uncontrolled inputs read through refs at request time (they are
   reads, not saves), and every field a save sends (memo, category, split legs) is controlled state
   hydrated from the loaded row. The newest request wins: a slower answer for an older filter is
   dropped. Assigns into window.FinancesUI; declares nothing else at top level. */
(() => {
  const { useState, useEffect, useRef } = React;
  const U = window.FinancesUI;
  const { moneyC, fmtShortDate, postJSON, getJSON, Payee } = U;
  const bookApi = "/finances/api/book";

  function bookTimeLabel(at) { return `${fmtShortDate(at.slice(0, 10))} ${at.slice(11, 16)}`; }

  function CatOptions({ cats }) {
    const groups = {};
    cats.forEach(c => {
      if (!groups[c.group_name]) groups[c.group_name] = [];
      groups[c.group_name].push(c);
    });
    return (
      <React.Fragment>
        <option value="">(uncategorized)</option>
        {Object.entries(groups).map(([g, cs]) => (
          <optgroup label={g} key={g}>{cs.map(c => <option value={c.id} key={c.id}>{c.name}</option>)}</optgroup>))}
      </React.Fragment>
    );
  }

  function bookWrite(uid, body, say) {
    return postJSON(`${bookApi}/transactions/${encodeURIComponent(uid)}`, body, "PATCH").then(res => {
      if (res.error) { say(`save failed: ${res.error}`); return false; }
      return true;
    });
  }

  // One row. The memo and category are controlled and start from the server's values; the memo is
  // sent when he leaves the box or presses Enter with a changed value (the plain input's change event).
  function TxnRow({ t, cats, say, reload, toggleSplit }) {
    const [memo, setMemo] = useState(t.memo == null ? "" : t.memo);
    const [cat, setCat] = useState(t.category_id == null ? "" : String(t.category_id));
    const last = useRef(memo);
    const commitMemo = () => {
      if (memo === last.current) return;
      last.current = memo;
      bookWrite(t.uid, { memo }, say);
    };
    return (
      <tr className="book-row" data-uid={t.uid}>
        <td className="book-date">{fmtShortDate(t.date)}</td>
        <td className="book-payee"><Payee name={t.payee} />{t.pending ? <React.Fragment>{" "}<span className="pay-note">pending</span></React.Fragment> : null}</td>
        <td className="book-catc">{t.splits.length ? "split" : t.transfer ? "transfer"
          : <select className="book-cat" aria-label="category" value={cat}
                    onChange={e => {
                      const v = e.target.value;
                      setCat(v);
                      if (!v) { reload(); return; }   // un-categorizing is not offered; restore the row
                      bookWrite(t.uid, { category_id: v }, say).then(ok => { if (ok) reload(); });
                    }}><CatOptions cats={cats} /></select>}</td>
        <td className="book-memo"><input className="book-memo-in" value={memo} aria-label="memo" placeholder="memo"
                                         onChange={e => setMemo(e.target.value)} onBlur={commitMemo}
                                         onKeyDown={e => { if (e.key === "Enter") commitMemo(); }} /></td>
        <td className="book-amt">{moneyC(t.amount)}</td>
        <td className="book-act">{!t.approved && !t.pending
          ? <React.Fragment><button type="button" className="hub-btn" data-approve
                                    onClick={() => bookWrite(t.uid, { approved: true }, say).then(ok => { if (ok) reload(); })}>approve</button>{" "}</React.Fragment>
          : null}{t.transfer ? null : <button type="button" className="hub-btn" data-split onClick={() => toggleSplit(t.uid)}>split</button>}</td>
      </tr>
    );
  }

  // One split leg. `cents` is relative to the parent's sign: a leg running the
  // parent's way shows positive, a leg against it (a refund inside a charge) negative.
  function SplitEditor({ t, cats, say, close, saved }) {
    const sign = t.amount_cents < 0 ? -1 : 1;
    const total = sign * t.amount_cents;
    const [legs, setLegs] = useState(() => (t.splits.length
      ? t.splits.map(l => ({ cents: sign * l.amount_cents, cat: l.category_id, memo: l.memo }))
      : [{ cents: sign * t.amount_cents, cat: t.category_id, memo: "" }, { cents: 0, cat: null, memo: "" }])
      .map(l => ({ amt: (l.cents / 100).toFixed(2), cat: l.cat == null ? "" : String(l.cat), memo: l.memo || "" })));
    const set = (i, k, v) => setLegs(prev => prev.map((l, j) => j === i ? Object.assign({}, l, { [k]: v }) : l));
    const cents = (l) => Math.round((parseFloat(l.amt) || 0) * 100);
    const left = total - legs.reduce((a, l) => a + cents(l), 0);
    function save() {
      if (left !== 0) { say("the legs must add up to the full amount."); return; }
      const body = { legs: legs.map(l => ({ amount_cents: sign * cents(l), category_id: l.cat || null, memo: l.memo })) };
      postJSON(`${bookApi}/transactions/${encodeURIComponent(t.uid)}/split`, body).then(res => {
        if (res.error) say(`split failed: ${res.error}`); else saved();
      });
    }
    return (
      <tr className="book-split-row" data-uid={t.uid} data-sign={sign} data-total={total}>
        <td colSpan="6"><div className="book-legs">{legs.map((l, i) => (
          <div className="hub-btn-row book-leg" key={i}>
            <input className="book-leg-amt" inputMode="decimal" value={l.amt} aria-label="leg amount"
                   onChange={e => set(i, "amt", e.target.value)} />
            <select className="book-leg-cat" aria-label="leg category" value={l.cat}
                    onChange={e => set(i, "cat", e.target.value)}><CatOptions cats={cats} /></select>
            <input className="book-leg-memo" value={l.memo} placeholder="memo" aria-label="leg memo"
                   onChange={e => set(i, "memo", e.target.value)} /></div>))}</div>
          <div className="hub-btn-row"><button type="button" className="hub-btn" data-leg-add
                                               onClick={() => setLegs(prev => prev.concat([{ amt: "0.00", cat: "", memo: "" }]))}>add leg</button>
            <button type="button" className="hub-btn hub-btn--accent" data-leg-save onClick={save}>save split</button>
            <button type="button" className="hub-btn" data-leg-cancel onClick={close}>cancel</button>
            <span className="pay-note book-left">{left === 0 ? "balanced" : `${moneyC(left / 100)} left to assign`}</span></div></td>
      </tr>
    );
  }

  // An unlinked SimpleFIN account in the last sync offers a link row: pick the book account, confirm the id.
  function LinkRow({ u, free, say, linked }) {
    const [acct, setAcct] = useState(free[0] ? String(free[0].id) : "");
    const [sfid, setSfid] = useState(u.simplefin_id || "");
    return (
      <span className="hub-btn-row" data-sfname={u.name}>
        <select aria-label="book account" value={acct} onChange={e => setAcct(e.target.value)}>
          {free.map(a => <option value={a.id} key={a.id}>{a.name}</option>)}</select>
        <input className="book-sfid" placeholder="SimpleFIN account id" value={sfid} aria-label="SimpleFIN account id"
               onChange={e => setSfid(e.target.value)} />
        <button type="button" className="hub-btn" data-link onClick={() => {
          postJSON(`${bookApi}/link-account`, { account_id: acct, simplefin_id: sfid }).then(res => {
            if (res.error) { say(`link failed: ${res.error}`); return; }
            say("linked; the next sync fills it in.");
            linked();
          });
        }}>link</button></span>
    );
  }

  function TransactionsPanel({ active }) {
    const [accounts, setAccounts] = useState([]);
    const [cats, setCats] = useState(null);
    const [txns, setTxns] = useState(null);
    const [account, setAccount] = useState("");
    const [msg, say] = useState("");
    const [sync, setSync] = useState(null);
    const [gen, setGen] = useState(0);              // bumps with every table rebuild
    const [syncGen, setSyncGen] = useState(0);      // and with every sync-line rebuild
    const [editors, setEditors] = useState({});     // uid -> open split editor
    const B = useRef({ loaded: false, seq: 0, timer: null, account: "" }).current;
    const q = useRef(null), cat = useRef(null), review = useRef(null), since = useRef(null), until = useRef(null);
    const latest = useRef(null);

    function loadTxns() {
      const seq = ++B.seq;
      const f = new URLSearchParams();
      const put = (k, v) => { if (v) f.set(k, v); };
      put("q", q.current.value.trim());
      put("account", B.account);
      put("category", cat.current.value);
      put("review", review.current.checked ? "1" : "");
      put("since", since.current.value);
      put("until", until.current.value);
      return getJSON(`${bookApi}/transactions?${f}`).then(d => {
        if (seq !== B.seq) return;   // a newer filter already answered
        const list = d.transactions || [];
        setTxns(list);
        setEditors({});
        setGen(g => g + 1);
        say(`${list.length} rows${list.length === d.limit ? ` (newest ${d.limit}; narrow the filters for more)` : ""}`);
      }).catch(() => { say("could not load transactions."); });
    }
    function loadAccounts() {
      return getJSON(`${bookApi}/accounts`).then(d => { setAccounts(d.accounts || []); });
    }
    function loadSync() {
      return getJSON(`${bookApi}/sync`).then(d => { setSync(d); setSyncGen(g => g + 1); })
        .catch(e => console.error("[book] sync read failed", e));
    }
    const pick = (v) => { B.account = v; setAccount(v); };
    latest.current = loadTxns;

    useEffect(() => {
      if (!active || B.loaded) return;
      B.loaded = true;
      Promise.all([
        getJSON(`${bookApi}/categories`).then(d => { setCats(d.categories || []); }),
        loadAccounts(),
      ]).then(() => { loadSync(); loadTxns(); })
        .catch(() => say("could not load the book."));
    }, [active]);

    // The search box: debounced while typing, and sent at once when he commits it (blur or Enter),
    // which is the plain input's native change event.
    useEffect(() => {
      const el = q.current;
      const onChange = () => latest.current();
      el.addEventListener("change", onChange);
      return () => el.removeEventListener("change", onChange);
    }, []);
    useEffect(() => () => clearTimeout(B.timer), []);

    function toggleSplit(uid) {
      setEditors(prev => {
        const n = Object.assign({}, prev);
        if (n[uid]) delete n[uid]; else n[uid] = true;
        return n;
      });
    }

    let syncLine = "";
    let syncErrs = null;
    let syncBtn = {};
    if (sync) {
      if (!sync.last) {
        syncLine = "never synced.";
        syncBtn = { disabled: false };
      } else {
        const l = sync.last;
        syncLine = `last sync ${bookTimeLabel(l.at)} · ${l.status} · ${l.added} new, ${l.updated} updated`;
        syncBtn = { disabled: !sync.can_sync, title: sync.can_sync ? "" : `one pull an hour; next at ${bookTimeLabel(sync.next_sync_at)}` };
        const free = accounts.filter(a => !a.linked);
        syncErrs = l.errors.map((e, i) => {
          const u = l.unlinked.find(x => e.includes(`'${x.name}'`));
          return (
            <div className="hub-callout-warn" key={`${syncGen}:${i}`}>{e}{u
              ? <LinkRow u={u} free={free} say={say} linked={() => loadAccounts().then(() => loadSync())} /> : null}</div>);
        });
      }
    }

    return (
      <div className="book-main fin-panel" role="tabpanel" id="panel-transactions" aria-labelledby="tab-transactions" tabIndex={0} hidden={!active}>

        <section className="periods">
          <div className="hub-btn-row" id="book-chips" role="group" aria-label="accounts">{accounts.map(a => {
            const on = String(a.id) === account;
            return (
              <button type="button" className={`hub-btn${on ? " hub-btn--accent" : ""}`} data-acct={a.id}
                      aria-pressed={on} key={a.id}
                      onClick={() => { pick(account === String(a.id) ? "" : String(a.id)); loadTxns(); }}>
                {a.name}{" "}<b>{moneyC(a.owed ? Math.abs(a.balance) : a.balance)}</b>{a.owed ? (a.balance < 0 ? " credit" : " owed") : ""}</button>);
          })}</div>
          <p className="pay-note" id="book-sync-line">{syncLine}</p>
          <div id="book-sync-errors">{syncErrs}</div>
          <div className="hub-btn-row">
            <button className="hub-btn" type="button" id="book-sync-now" disabled={syncBtn.disabled} title={syncBtn.title}
                    onClick={() => {
                      say("syncing…");
                      fetch(`${bookApi}/sync`, { method: "POST" }).then(res => {
                        if (res.status === 429) say("synced less than an hour ago; try again later.");
                        else if (res.status === 409) say("a sync is already running; try again in a minute.");
                        return Promise.all([loadAccounts(), loadSync(), loadTxns()]);
                      }).catch(e => console.error("[book] sync failed", e));
                    }}>sync now</button>
          </div>
        </section>

        <section className="periods">
          <form className="hub-btn-row" id="book-filters" role="search" onSubmit={e => e.preventDefault()}>
            <input type="search" id="book-q" placeholder="search payee, memo, amount" aria-label="search" ref={q}
                   onInput={() => { clearTimeout(B.timer); B.timer = setTimeout(() => latest.current(), 250); }} />
            <select id="book-f-account" aria-label="account" value={account}
                    onChange={e => { pick(e.target.value); loadTxns(); }}>
              <option value="">all accounts</option>
              {accounts.map(a => <option value={a.id} key={a.id}>{a.name}</option>)}</select>
            <select id="book-f-category" aria-label="category" ref={cat} onChange={() => loadTxns()}>
              <option value="">all categories</option>
              {cats ? <React.Fragment><option value="none">uncategorized</option>
                {cats.map(c => <option value={c.id} key={c.id}>{c.full_name}</option>)}</React.Fragment> : null}</select>
            <label className="pay-note"><input type="checkbox" id="book-f-review" ref={review} onChange={() => loadTxns()} /> needs review</label>
            <input type="date" id="book-f-since" aria-label="from date" ref={since} onChange={() => loadTxns()} />
            <input type="date" id="book-f-until" aria-label="to date" ref={until} onChange={() => loadTxns()} />
          </form>
          <p className="pay-note" id="book-count">{msg}</p>
          <table id="book-txn-table">
            <thead><tr>
              <th>date</th>
              <th>payee</th>
              <th>category</th>
              <th>memo</th>
              <th>amount</th>
              <th></th>
            </tr></thead>
            <tbody>{!txns ? null : !txns.length
              ? <tr><td colSpan="6" className="table-empty">no transactions match</td></tr>
              : txns.map(t => (
                <React.Fragment key={`${t.uid}:${gen}`}>
                  <TxnRow t={t} cats={cats || []} say={say} reload={loadTxns} toggleSplit={toggleSplit} />
                  {editors[t.uid]
                    ? <SplitEditor t={t} cats={cats || []} say={say} close={() => toggleSplit(t.uid)}
                                   saved={loadTxns} /> : null}
                </React.Fragment>))}</tbody>
          </table>
        </section>

      </div>
    );
  }
  U.TransactionsPanel = TransactionsPanel;
})();

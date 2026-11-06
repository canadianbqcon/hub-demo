/* Finances · 5 of 5 (React): the page body, the tab choice with its #hash, the footer clock and the
   mount. Ported from finances.js lines 874-912 (initTabs), 54-55 (the clock) and the boot lines.
   The React root is the template's <main id="body">; the shell, top bar and footer stay as they
   were. Render errors land in Boundary; errors in async code and event handlers are logged where
   they happen, as on the plain page. */
(() => {
  const { useState, useEffect, useRef } = React;
  const U = window.FinancesUI;
  const root = document.getElementById("body");

  // deep-linkable: #earnings ... #transactions; /stocks/ redirects to /finances/#stocks
  const fromHash = () => U.TABS.find(t => `#${t}` === location.hash) || "earnings";

  function App() {
    const [tab, setTab] = useState(fromHash);
    const [focusTick, setFocusTick] = useState(0);
    const focusTab = useRef(null);

    useEffect(() => {
      root.setAttribute("data-react-mounted", "finances");
    }, []);

    // the hash follows the tab (replaced, not pushed), including the first paint's #earnings
    useEffect(() => {
      const frag = `#${tab}`;
      if (location.hash !== frag) history.replaceState(null, "", frag);
    }, [tab]);

    useEffect(() => {
      if (focusTab.current) document.getElementById(`tab-${focusTab.current}`).focus();
    }, [focusTick]);

    const select = (t, focus) => {
      setTab(t);
      if (focus) { focusTab.current = t; setFocusTick(n => n + 1); }
    };

    return (
      <React.Fragment>
        <U.Tabs tab={tab} select={select} />
        <U.EarningsPanel active={tab === "earnings"} />
        <U.SpendingPanel active={tab === "spending"} />
        <U.DebtPanel active={tab === "debt"} />
        <U.OwedPanel active={tab === "owed"} />
        <U.StocksPanel active={tab === "stocks"} />
        <U.TransactionsPanel active={tab === "transactions"} />
      </React.Fragment>
    );
  }

  // Render errors land here; async/handler errors are caught where they happen.
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err) { console.error("[finances] render failed", err); }
    render() { return this.state.err ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  ReactDOM.createRoot(root).render(<Boundary><App /></Boundary>);
})();

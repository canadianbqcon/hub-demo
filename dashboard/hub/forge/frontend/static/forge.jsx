/* forge.jsx - the Forge builder's mount.

   Assembles the page from the part files (forge-shop, forge-blocks, forge-stats,
   forge-runes) the way the interface note in forge-shop.jsx lays out: the bar, the
   .buildhead strip, the step nav, the three step sections, the note dialog. It waits for
   st.ready (the seven bakes and ForgeLib), runs st.boot() so the state exists before the
   first render, and calls st.afterMount(#step3) from an effect once the body is in the
   DOM. The head preflight in forge.html still starts the fetches; this awaits them.

   #forge-root is display:contents in the template so its children stay direct grid items
   of body, which is what the page's fixed-row layout is written against. */
window.ForgeUI = window.ForgeUI || {};

(() => {
  const { useState, useEffect } = React;
  const UI = window.ForgeUI;
  const st = UI.state;

  /* The items step. The plan step is UI.Plan (loadout.jsx). */
  function Items() {
    st.useStore();
    return (
      <div id="step2" hidden={st.step !== 'items'}>
        <UI.PatchStrip />
        <main>
          <UI.Shop hover={UI.hoverShelves} />
          <UI.Blocks hoverSlots={UI.hoverSlots} hoverNodes={UI.hoverNodes} />
        </main>
      </div>
    );
  }

  function Bar() {
    st.useStore();
    return (
      <UI.Bar current="">
        <span className="meta" id="statsPatch">{st.statsPatchLabel()}</span>
        <span className="meta" id="patch">{st.patchLabel()}</span>
      </UI.Bar>
    );
  }

  function Page() {
    const [ready, setReady] = useState(false);
    const [err, setErr] = useState(null);
    useEffect(() => {
      st.ready.then(() => { st.boot(); setReady(true); }).catch(e => { console.error('[forge] boot failed', e); setErr(e); });
    }, []);
    // after the first full render, so #step3 exists for the plan to mount into
    useEffect(() => {
      if (ready) st.afterMount(document.getElementById('step3'));
    }, [ready]);
    if (err) throw err;
    if (!ready) return null;
    return (
      <React.Fragment>
        <Bar />
        <UI.Roles />
        <UI.StepNav />
        <UI.Runes />
        <Items />
        <UI.Plan />
        <UI.NoteDialog />
      </React.Fragment>
    );
  }

  /* Render errors land here; the plain page had no equivalent, so a failed render says so. */
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err) { console.error('[forge] render failed', err); }
    render() { return this.state.err ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  function Root() {
    useEffect(() => {
      document.getElementById('forge-root').setAttribute('data-react-mounted', 'forge');
    }, []);
    return <Boundary><Page /></Boundary>;
  }

  ReactDOM.createRoot(document.getElementById('forge-root')).render(<Root />);
})();

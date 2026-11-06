/* login: the password gate form. React port of the plain form templates/login.html renders (the no-JS page).
   The form is a plain urlencoded POST to /login (one field, password); the server
   compares it and re-renders the card with the error. The template hands the error
   text over in data-error on the mount root. */
(() => {
  const { useEffect, Component } = React;
  const host = document.getElementById("login-root");  // div.card
  // Signed out: drop what the offline worker kept from the signed-in pages.
  if (window.caches) caches.keys().then(ks => ks.forEach(k => { caches.delete(k); }));

  function Card() {
    useEffect(() => { host.setAttribute("data-react-mounted", "login"); }, []);
    const error = host.getAttribute("data-error");
    return <React.Fragment>
      <h1 className="wordmark">hub</h1>
      <p className="tagline">Enter the password to continue.</p>
      <form method="post" autoComplete="off">
        <input type="password" name="password" placeholder="Password" autoFocus aria-label="Password" />
        <button type="submit">Unlock</button>
        {error ? <p className="error">{error}</p> : null}
      </form>
    </React.Fragment>;
  }

  class Boundary extends Component {
    constructor(p) { super(p); this.state = {failed: false}; }
    static getDerivedStateFromError() { return {failed: true}; }
    componentDidCatch(e) { console.error("login body failed", e); }
    render() { return this.state.failed ? <p className="error">page failed to load</p> : this.props.children; }
  }

  if (host) ReactDOM.createRoot(host).render(<Boundary><Card /></Boundary>);
})();

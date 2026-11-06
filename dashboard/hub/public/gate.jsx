/* The mirror keypad body (2026-10-13): React port of the two inline scripts in
   trips/frontend/gate.html (keypad, signup form). Same ids, classes and copy as the
   plain page. POSTs keep their exact JSON bodies and Content-Type. The state lives
   in one ref object, as the plain script's closure variables did, so the document
   keydown handler and the buttons always see the same digits. */
(() => {
const { useState, useEffect, useRef } = React;

/* id, what to say when it is empty. Order is the tab order, so the first
   complaint is about the topmost blank field. */
const FIELDS = [
  ["firstField", "your first name first"],
  ["lastField", "your last name too"],
  ["phoneField", "a phone number, so Sam knows it's you"],
  ["emailField", "an email as well"]
];
const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"];

function Gate() {
  const [, bump] = useState(0);
  const redraw = () => bump((n) => n + 1);
  const st = useRef({ digits: [], signup: false, busy: false, msg: "", ok: false, bad: false }).current;
  const refs = useRef({}).current;
  const host = useRef(null);

  const say = (text, ok) => { st.msg = text || ""; st.ok = !!ok; redraw(); };

  const reject = (text) => {
    st.msg = text; st.ok = false; st.digits = []; st.bad = true; redraw();
    setTimeout(() => { st.bad = false; redraw(); }, 400);
  };

  /* Each caller names its own literal URL so the public-area lint can see it. */
  const json = (body) => ({
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  const post = (send, onOk) => {
    if (st.busy) return;
    st.busy = true;
    send().then((r) => r.json().then((j) => ({ ok: r.ok, j: j }))).then((res) => {
      st.busy = false;
      if (res.ok) { onOk(res.j); } else { reject(res.j.error || "something went wrong"); }
    }).catch(() => {
      st.busy = false;
      reject("couldn't reach the server");
    });
  };

  const submitCode = () => {
    /* The server picks the door: straight to the board unless this person owes
       answers, in which case the preferences wall comes first. */
    post(() => fetch("/gate", json({ code: st.digits.join("") })), (j) => {
      location.href = (j?.next) || "/trips/";
    });
  };

  const setMode = (on) => {
    st.signup = on; st.digits = []; st.msg = ""; st.ok = false;
    if (!on) { redraw(); return; }
    /* Unhide the fields now and focus inside the tap: iOS opens the keyboard only
       for a focus() made in the user's own gesture, never from a timer. */
    ReactDOM.flushSync(redraw);
    if (refs.firstField) refs.firstField.focus();
  };

  const submitSignup = () => {
    const vals = {};
    for (let i = 0; i < FIELDS.length; i++) {
      const el = refs[FIELDS[i][0]], v = el.value.trim();
      if (!v) { say(FIELDS[i][1]); el.focus(); return; }
      vals[FIELDS[i][0].replace("Field", "")] = v;
    }
    post(() => fetch("/gate/request", json({
      first_name: vals.first, last_name: vals.last,
      phone: vals.phone, email: vals.email, code: st.digits.join("")
    })), () => {
      FIELDS.forEach((f) => { refs[f[0]].value = ""; });
      setMode(false);
      say("sent \u2014 you're in once Sam approves it", true);
    });
  };

  const push = (d) => {
    if (st.digits.length >= 4) return;
    st.digits.push(d); st.msg = ""; st.ok = false; redraw();
    if (st.digits.length === 4 && !st.signup) submitCode();
  };

  const back = () => { st.digits.pop(); say(""); };

  /* A keyboard works too. Typing in a field ignores digits; Enter still submits. */
  useEffect(() => {
    host.current.setAttribute("data-react-mounted", "gate");
    const onKey = (e) => {
      const typing = document.activeElement && document.activeElement.tagName === "INPUT";
      if (typing && e.key !== "Enter") return;
      if (/^[0-9]$/.test(e.key)) { push(e.key); }
      else if (e.key === "Backspace") { back(); }
      else if (e.key === "Enter" && st.signup && st.digits.length === 4) { submitSignup(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const on = st.signup;
  const slot = (i) => (
    <div key={i} className={`slot${st.digits[i] !== undefined ? " filled" : ""}`}>
      {st.digits[i] === undefined ? "" : "•"}
    </div>
  );
  return (
    <div ref={host} style={{ display: "contents" }}>
      <Boundary fallback={null}><Topbar crumb="trips" /></Boundary>
      <div className="gate">
        <h1 className="gate-title" id="title">{on ? "create a code" : "trips"}</h1>
        <p className="gate-sub" id="sub">{on ? "pick any four digits you'll remember" : "enter your code"}</p>

        <div className="gate-fields" id="fields" hidden={!on}>
          <div className="gate-pair">
            <input className="gate-name" id="firstField" type="text" maxLength="40"
                   autoComplete="given-name" placeholder="first name" ref={(e) => { refs.firstField = e; }} />
            <input className="gate-name" id="lastField" type="text" maxLength="40"
                   autoComplete="family-name" placeholder="last name" ref={(e) => { refs.lastField = e; }} />
          </div>
          <input className="gate-name" id="phoneField" type="tel" maxLength="30"
                 autoComplete="tel" placeholder="phone number" ref={(e) => { refs.phoneField = e; }} />
          <input className="gate-name" id="emailField" type="email" maxLength="120"
                 autoComplete="email" placeholder="email" ref={(e) => { refs.emailField = e; }} />
        </div>

        <div className={`slots${st.bad ? " bad" : ""}`} id="slots">
          {[0, 1, 2, 3].map(slot)}
        </div>

        <div className="keys">
          {KEYS.map((d) => <button type="button" key={d} data-d={d} onClick={() => push(d)}>{d}</button>)}
          <button type="button" className="key-wide" id="back" onClick={back}>{"←"}</button>
          <button type="button" data-d="0" onClick={() => push("0")}>0</button>
          <button type="button" className="key-wide" id="go" hidden={!(on && st.digits.length === 4)} onClick={submitSignup}>{"✓"}</button>
        </div>

        <p className={`gate-msg${st.ok ? " ok" : ""}`} id="msg">{st.msg}</p>

        <div className={`gate-alt${on ? " quiet" : ""}`} id="alt">
          <p className="hint">Don't have a code yet?</p>
          <button type="button" id="toggle" onClick={() => setMode(!st.signup)}>{on ? "back" : "Create your own code"}</button>
        </div>
      </div>
    </div>
  );
}

class Boundary extends React.Component {
  constructor(p) { super(p); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e) { console.error("gate body failed", e); }
  render() {
    if (!this.state.failed) return this.props.children;
    return "fallback" in this.props ? this.props.fallback : <p className="gate-msg">page failed to load</p>;
  }
}

const root = document.getElementById("gate-root");
if (root) ReactDOM.createRoot(root).render(<Boundary><Gate /></Boundary>);
})();

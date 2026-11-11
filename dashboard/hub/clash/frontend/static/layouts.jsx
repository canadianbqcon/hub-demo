/* layouts.jsx: /clash/layouts. Saved base layouts per Town Hall: link, image, notes. */

function Form({ tag, init, onDone, onCancel }) {
  const [th, setTh] = React.useState(init ? init.th_level : 10);
  const [link, setLink] = React.useState(init ? init.link : "");
  const [notes, setNotes] = React.useState(init ? init.notes : "");
  const [file, setFile] = React.useState(null);
  const [err, setErr] = React.useState("");
  const save = (e) => {
    e.preventDefault();
    const f = new FormData();
    f.append("tag", tag); f.append("th_level", th); f.append("link", link); f.append("notes", notes);
    if (init) f.append("id", init.id);
    if (file) f.append("image", file);
    api(init ? "PUT" : "POST", "/clash/api/layouts", f)
      .then(onDone)
      .catch((x) => setErr(String(x.message || x)));
  };
  return (
    <form className="cx-slab" onSubmit={save}>
      <div className="row">
        <label>Town Hall <input type="number" min="1" max="30" value={th} onChange={(e) => setTh(e.target.value)} required /></label>
        <label>Link <input type="url" value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://link.clashofclans.com/..." /></label>
        <label>Image (PNG, JPEG or WebP, up to 10 MB) <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setFile(e.target.files[0] || null)} /></label>
      </div>
      <p><textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes" /></p>
      {err && <p className="err">{err}</p>}
      <div className="row"><button className="pri" type="submit">{init ? "Save changes" : "Add layout"}</button>
        {onCancel && <button type="button" onClick={onCancel}>Cancel</button>}</div>
    </form>
  );
}

function Card({ l, onEdit, onDelete }) {
  return (
    <div className="cx-slab lay">
      <h4>Town Hall {l.th_level}</h4>
      {l.image_file && <a href={"/clash/layouts/img/" + l.image_file} target="_blank" rel="noopener"><img src={"/clash/layouts/img/" + l.image_file} alt={"Town Hall " + l.th_level + " layout"} /></a>}
      {l.link && <a href={l.link} target="_blank" rel="noopener">Copy layout link</a>}
      {l.notes && <p className="notes">{l.notes}</p>}
      <div className="row"><button onClick={() => onEdit(l)}>Edit</button><button onClick={() => onDelete(l)}>Delete</button></div>
    </div>
  );
}

function LayoutsApp() {
  const [d, setD] = React.useState(null);
  const [edit, setEdit] = React.useState(null);
  const [err, setErr] = React.useState("");
  const load = () => api("GET", "/clash/api/layouts?tag=" + encodeURIComponent(tagQ))
    .then(setD).catch((e) => setErr(String(e.message || e)));
  React.useEffect(() => { load(); }, []);
  const del = (l) => {
    if (!confirm("Delete the Town Hall " + l.th_level + " layout and its image?")) return;
    api("DELETE", "/clash/api/layouts?id=" + l.id).then(load, (e) => setErr(String(e.message)));
  };
  const done = () => { setEdit(null); load(); };
  return (
    <div className="hub-shell gaming-shell" data-screen-label="clash layouts">
      <Topbar crumb="clash layouts" />
      <main className="gaming-body">
        <div className="gx cx cp g-clash">
        <header className="gx-page"><div><h1>Layouts</h1><p>Your saved base layouts per Town Hall</p></div></header>
        <div className="row"><a className="cx-lnk" href="/clash/">Back to tracker</a><a className="cx-lnk" href="/clash/plan">Plan</a></div>
        {err && <p className="err">Could not load layouts ({err})</p>}
        {d && !d.tag && <p>No account yet. Paste an export on the tracker first.</p>}
        {d && d.tag && (edit && edit.id
          ? <Form key={edit.id} tag={d.tag} init={edit} onDone={done} onCancel={() => setEdit(null)} />
          : <Form tag={d.tag} onDone={done} />)}
        {d && <div className="lays">{d.layouts.map((l) => <Card key={l.id} l={l} onEdit={setEdit} onDelete={del} />)}</div>}
        {d && d.tag && d.layouts.length === 0 && <p>No layouts saved yet.</p>}
        </div>
      </main>
      <StatusStrip />
    </div>
  );
}
ReactDOM.createRoot(document.getElementById("root")).render(<LayoutsApp />);

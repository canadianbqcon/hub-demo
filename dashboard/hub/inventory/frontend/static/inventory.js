/* Inventory page. Reads /inventory/api/*: a rail of computers, two tabs over the list
   (My programs, On this computer) and a scope strip. Uninstall asks first and only ever
   sends a program key; the server looks the command up. */
(function () {
  "use strict";
  var API = "/inventory/api/";
  var CATS = ["Everyday apps", "Creative and media", "Games", "Developer tools", "Drivers and hardware", "Runtimes and system parts"];
  var HOOD = ["Drivers and hardware", "Runtimes and system parts"];
  var GLYPH = {
    pc: '<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M8 20h8M12 16v4"/>',
    mac: '<rect x="5" y="3" width="14" height="10" rx="1.5"/><path d="M3 17h18l-1.5 3h-15z"/>'
  };
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); };
  var size = function (mb) { return mb == null ? "" : mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : Math.max(mb, 1) + " MB"; };
  var total = function (xs) { return xs.reduce(function (a, i) { return a + (i.size || 0); }, 0); };

  var S = {machines: [], progs: {}, merr: {}, sel: null, tab: "rec", q: "", only: null, open: {}, busy: false, error: ""};

  function getJSON(url) {
    return fetch(url).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || r.status); return j; });
    });
  }
  function say(msg) { $("statusMsg").textContent = msg; }

  // ---- data ----
  function isMacName(m) { return /mac/i.test(m.machine); }
  function hasMac() {
    return S.machines.some(function (m) {
      return isMacName(m) || (S.progs[m.machine] || []).some(function (p) { return p.side === "Mac"; });
    });
  }
  // the scanner already lays manual.json over programs.json
  function current() { return S.sel && !S.sel.mac ? S.progs[S.sel.machine] || [] : []; }
  function filt(xs) {
    var q = S.q.trim().toLowerCase();
    return xs.filter(function (i) { return !q || [i.name, i.publisher, i.cat, i.path].join(" ").toLowerCase().indexOf(q) >= 0; });
  }
  function byCat(items) {
    var g = {};
    items.forEach(function (i) { (g[i.cat] = g[i.cat] || []).push(i); });
    return CATS.filter(function (k) { return g[k]; }).map(function (k) { return {name: k, items: g[k]}; });
  }
  var byName = function (a, b) { return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1; };

  // ---- rail ----
  function renderRail() {
    var tab = function (id, label, g, n, on) {
      return '<button type="button" class="hub-t3p-tab hub-nav-item' + (on ? " active" : "") + '" data-m="' + esc(id) + '"><span class="hub-t3p-tab-label hub-nav-label"><svg class="hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true">' + g + "</svg>" + esc(label) + '</span><span class="inv-n">' + esc(n) + "</span></button>";
    };
    var html = S.machines.map(function (m) {
      return tab(m.machine, m.machine, isMacName(m) ? GLYPH.mac : GLYPH.pc, (S.progs[m.machine] || []).length, S.sel && S.sel.machine === m.machine);
    }).join("");
    if (!hasMac()) html += tab("__mac", "Mac", GLYPH.mac, "-", S.sel && S.sel.mac);
    $("invNav").innerHTML = html;
    $("crumbSection").textContent = S.sel ? (S.sel.mac ? "Mac" : S.sel.machine) : "";
  }

  // ---- shared pieces ----
  function onChips(i) {
    var yes = S.machines.filter(function (m) { return (S.progs[m.machine] || []).some(function (p) { return p.key === i.key; }); })
      .map(function (m) { return '<i class="it-yes">' + esc(m.machine) + "</i>"; }).join("");
    var unk = hasMac() ? "" : '<i class="it-unk">Mac not scanned</i>';
    return '<div class="inv-kv"><span>On computers</span><b class="it-on">' + (yes || '<i class="it-unk">none scanned</i>') + unk + "</b></div>";
  }
  function detail(i) {
    var local = S.sel && S.sel.local;
    var un = i.uninstall_text || (i.uninstall ? i.uninstall.join(" ") : "");
    var canRun = !!(i.uninstall && i.uninstall.length) && local;
    var why = !local ? "run on that computer" : !i.uninstall ? (!i.uninstall_text ? "no uninstaller registered" : i.side === "Windows" ? "run it in a Windows terminal" : "run in a terminal, needs sudo") : "";
    return '<div class="inv-det">' +
      '<div class="inv-kv"><span>Installed in</span><code class="inv-cmd">' + esc(i.path || "not recorded by its installer") + "</code></div>" +
      '<div class="inv-kv"><span>Uninstall</span><div class="inv-cmds"><code class="inv-cmd">' + esc(un || "no uninstaller registered") + "</code>" +
        (i.registry_uninstall ? '<code class="inv-cmd inv-cmd-alt">Windows registry: ' + esc(i.registry_uninstall) + "</code>" : "") + "</div></div>" +
      '<div class="inv-kv"><span>Get it back</span><code class="inv-cmd">' + esc(i.restore || "reinstall by hand") + "</code></div>" +
      '<div class="inv-det-act"><button type="button" class="hub-btn hub-btn--danger inv-un" data-key="' + esc(i.key) + '"' + (canRun ? "" : " disabled") + ">Uninstall</button>" +
      (why ? '<span class="inv-when">' + esc(why) + "</span>" : "") +
      (i.date ? '<span class="inv-when">installed ' + esc(i.date) + "</span>" : "") + "</div></div>";
  }
  function row(i, withOn, right) {
    return '<details class="ij-r" data-key="' + esc(i.key) + '"' + (S.open[i.key] ? " open" : "") + "><summary><b>" + esc(i.name) + "</b>" + (right || "") + "</summary>" +
      (withOn ? onChips(i) : "") + detail(i) + "</details>";
  }
  function card(title, sum, inner) {
    return '<div class="hub-t3p-card hub-plate-card"><div class="hub-section-head"><span class="hub-section-head-t">' + esc(title) + '</span><span class="hub-section-head-sum">' + esc(sum) + "</span></div>" + inner + "</div>";
  }

  // ---- list ----
  function renderList() {
    var el = $("invList");
    if (S.error) { el.innerHTML = card("Could not load", "error", '<p class="inv-note">' + esc(S.error) + "</p>"); return; }
    if (!S.sel) { el.innerHTML = '<p class="inv-note">loading</p>'; return; }
    if (S.sel.mac) {
      el.innerHTML = card("Mac", "not scanned yet", "<p class=\"inv-note\">The Mac adds its programs the first time its Hub runs a scan, and they show here after the Mac syncs.</p>");
      return;
    }
    var all = current();
    var rec = all.filter(function (i) { return HOOD.indexOf(i.cat) < 0; });
    var head = '<div class="hub-tabs it-tabs"><button type="button" class="hub-tab' + (S.tab === "rec" ? " active" : "") + '" data-t="rec">My programs <em>' + rec.length +
      '</em></button><button type="button" class="hub-tab' + (S.tab === "now" ? " active" : "") + '" data-t="now">On this computer <em>' + all.length + "</em></button></div>";
    var merr = S.merr[S.sel.machine] ? '<p class="inv-note">Hand-added list not read: ' + esc(S.merr[S.sel.machine]) + "</p>" : "";
    el.innerHTML = merr + head + '<div class="it-body">' + (S.tab === "rec" ? recordHtml(filt(rec)) : nowHtml(filt(all))) + "</div>";
  }
  function recordHtml(rec) {
    if (!rec.length) return '<p class="inv-note">No programs match.</p>';
    return byCat(rec).map(function (g) {
      return card(g.name, g.items.length, g.items.slice().sort(byName).map(function (i) { return row(i, true); }).join(""));
    }).join("");
  }
  function nowHtml(now) {
    if (!now.length) return '<p class="inv-note">No programs match.</p>';
    var groups = byCat(now), tot = total(now) || 1;
    var g = groups.filter(function (x) { return x.name === S.only; })[0];
    if (!g) g = groups.slice().sort(function (a, b) { return total(b.items) - total(a.items); })[0];
    var rows = g.items.slice().sort(function (a, b) { return (b.size || -1) - (a.size || -1); });
    return '<div class="ij-map">' + groups.map(function (x) {
      var t = total(x.items);
      return '<button type="button" class="hub-btn ij-b' + (g === x ? " on" : "") + '" style="flex-grow:' + Math.max(t / tot * 100, 6).toFixed(1) + '" data-c="' + esc(x.name) + '"><b>' + esc(x.name) + "</b><span>" + size(t) + " · " + x.items.length + "</span></button>";
    }).join("") + "</div>" +
      card(g.name, size(total(rows)) + " · biggest first", rows.map(function (i) {
        return row(i, false, '<span class="inv-num">' + (size(i.size) || "size unknown") + "</span>");
      }).join(""));
  }

  // ---- scope strip ----
  function exporterLine(name, e) {
    var ok = e && e.outcome === "ok";
    var okAt = e && e.last_success ? e.last_success.replace("T", " ").slice(0, 16) : "never";
    var word = ok ? "ok" : e && e.outcome === "absent" ? "absent" : (e && e.outcome) || "unknown";
    var note = !e || ok ? "" : e.outcome === "absent" ? "not found in the Hub's environment" :
      [e.error, e.last_success ? "list shown is from " + okAt : ""].filter(Boolean).join(" · ");
    return '<div class="hub-kv-row"><span>' + esc(name) + '</span><b><span class="hub-pill ' + (ok ? "is-good" : "is-warn") + '">' + esc(word) + "</span></b></div>" +
      (note ? '<div class="inv-exnote">' + esc(note) + "</div>" : "");
  }
  function renderScope() {
    var el = $("invScope");
    if (!S.sel || S.sel.mac) {
      el.innerHTML = '<div class="hub-detail-card"><div class="hub-detail-card-head">On Mac</div><div class="hub-kv-row"><span>scan</span><b>not scanned yet</b></div></div>';
      return;
    }
    var m = S.sel, all = current();
    var kinds = byCat(all).map(function (g) {
      return '<div class="hub-kv-row"><span>' + esc(g.name) + "</span><b>" + g.items.length + ' <i class="inv-sz">' + size(total(g.items)) + "</i></b></div>";
    }).join("");
    var ex = Object.keys(m.exporters || {}).map(function (k) { return exporterLine(k, m.exporters[k]); }).join("");
    el.innerHTML = '<div class="hub-detail-card"><div class="hub-detail-card-head">On ' + esc(m.machine) + "</div>" +
      '<div class="hub-kv-row"><span>programs</span><b>' + all.length + '</b></div><div class="hub-kv-row"><span>disk used</span><b>' + size(total(all)) +
      '</b></div><div class="hub-kv-row"><span>last scan</span><b>' + esc(m.scanned ? m.scanned.replace("T", " ").slice(0, 16) : "never") + "</b></div></div>" +
      '<div class="hub-detail-card"><div class="hub-detail-card-head">By kind</div>' + kinds + "</div>" +
      '<div class="hub-detail-card"><div class="hub-detail-card-head">Scanner</div>' + (ex || '<div class="hub-kv-row"><span>no scanner report</span></div>') + "</div>";
  }

  function render() {
    renderRail(); renderList(); renderScope();
    var m = S.sel;
    $("invScan").disabled = S.busy || !(m && m.local);
    $("invScan").textContent = S.busy ? "Scanning" : "Scan now";
    $("statusMeta").textContent = m && !m.mac ? current().length + " programs" : "";
  }

  // ---- loading ----
  function load() {
    return getJSON(API + "machines").then(function (ms) {
      S.machines = ms;
      return Promise.all(ms.map(function (m) {
        return getJSON(API + "programs/" + encodeURIComponent(m.machine)).then(function (d) { S.progs[m.machine] = d.programs || []; S.merr[m.machine] = d.manual_error || ""; }, function () { S.progs[m.machine] = []; });
      }));
    }).then(function () {
      var keep = S.sel && !S.sel.mac ? S.machines.filter(function (m) { return m.machine === S.sel.machine; })[0] : null;
      S.sel = keep || (S.sel && S.sel.mac ? S.sel : S.machines.filter(function (m) { return m.local; })[0] || S.machines[0] || {mac: true});
      S.error = "";
    }).catch(function (e) { S.error = String(e.message || e); });
  }

  // ---- poll until the machine's scan stamp moves past `before`, then reload ----
  function waitScan(m, before, doneMsg) {
    var tries = 0;
    (function poll() {
      getJSON(API + "machines").then(function (ms) {
        var now = ms.filter(function (x) { return x.machine === m.machine; })[0];
        if ((now && now.scanned !== before) || ++tries > 90) {
          S.busy = false;
          return load().then(function () { render(); say(now && now.scanned !== before ? doneMsg : "scan still running, check back"); });
        }
        setTimeout(poll, 2000);
      }).catch(function () { if (++tries > 90) { S.busy = false; render(); say("scan status unavailable"); } else setTimeout(poll, 2000); });
    })();
  }

  // ---- scan now ----
  function scan() {
    var m = S.sel; if (!m || !m.local || S.busy) return;
    var before = m.scanned; S.busy = true; render(); say("scanning " + m.machine);
    fetch(API + "scan", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"}).then(function (r) {
      if (r.status !== 202) return r.json().then(function (j) { throw new Error(j.error || r.status); });
      waitScan(m, before, "scan finished");
    }).catch(function (e) { S.busy = false; render(); say("scan did not start: " + e.message); });
  }

  // ---- uninstall: confirm dialog, then post the key only ----
  function confirmUninstall(key) {
    var i = current().filter(function (p) { return p.key === key; })[0];
    if (!i || !i.uninstall) return;
    var scrim = $("invModal");
    scrim.innerHTML = '<div class="hub-modal" role="dialog" aria-modal="true" aria-labelledby="invMT"><div class="hub-modal-title" id="invMT">Uninstall ' + esc(i.name) + '?</div>' +
      '<div class="hub-modal-body">This runs on ' + esc(S.sel.machine) + ' and removes the program:<br><code class="inv-cmd">' + esc(i.uninstall_text || i.uninstall.join(" ")) + "</code></div>" +
      '<div class="hub-modal-actions"><button type="button" class="hub-modal-btn" id="invNo">Cancel</button><button type="button" class="hub-modal-btn hub-modal-btn--danger" id="invYes">Uninstall</button></div></div>';
    scrim.hidden = false;
    var close = function () { scrim.hidden = true; scrim.innerHTML = ""; document.removeEventListener("keydown", esck); };
    var esck = function (e) { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", esck);
    scrim.onclick = function (e) { if (e.target === scrim) close(); };
    $("invNo").onclick = close;
    $("invYes").onclick = function () { close(); runUninstall(i); };
    $("invNo").focus();
  }
  function runUninstall(i) {
    var m = S.sel, before = m.scanned;
    say("uninstalling " + i.name);
    fetch(API + "uninstall", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({key: i.key})})
      .then(function (r) { return r.json().then(function (j) { return {s: r.status, j: j}; }); })
      .then(function (x) {
        if (x.s !== 200) return say("uninstall refused: " + (x.j.error || x.s));
        var msg = x.j.ok ? i.name + " uninstalled" : i.name + " uninstall failed (exit " + x.j.exit + "): " + String(x.j.output || "").slice(-160);
        S.busy = true; render(); say(msg + ", rescanning");
        waitScan(m, before, msg + ", list updated");
      }).catch(function (e) { say("uninstall failed: " + e.message); });
  }

  // ---- phone drawer ----
  function drawer(open) {
    $("invRail").classList.toggle("is-open", open);
    $("invScrim").hidden = !open;
    $("navToggle").setAttribute("aria-expanded", String(open));
  }

  function wire() {
    $("invNav").addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-m]"); if (!b) return;
      S.sel = b.dataset.m === "__mac" ? {mac: true} : S.machines.filter(function (m) { return m.machine === b.dataset.m; })[0];
      S.only = null; drawer(false); render();
    });
    $("invList").addEventListener("click", function (ev) {
      var t = ev.target.closest("[data-t]"); if (t) { S.tab = t.dataset.t; return render(); }
      var c = ev.target.closest("[data-c]"); if (c) { S.only = c.dataset.c; return render(); }
      var u = ev.target.closest(".inv-un"); if (u && !u.disabled) confirmUninstall(u.dataset.key);
    });
    $("invList").addEventListener("toggle", function (ev) {
      var d = ev.target; if (d.tagName !== "DETAILS") return;
      if (d.open) S.open[d.dataset.key] = 1; else delete S.open[d.dataset.key];
    }, true);
    $("invQ").addEventListener("input", function (e) { S.q = e.target.value; renderList(); });
    $("invScan").addEventListener("click", scan);
    $("navToggle").addEventListener("click", function () { drawer(!$("invRail").classList.contains("is-open")); });
    $("invScrim").addEventListener("click", function () { drawer(false); });
  }

  wire();
  say("loading");
  load().then(function () { render(); say(S.error ? "could not load" : "ready"); });
})();

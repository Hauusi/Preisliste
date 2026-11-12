// Vertriebswissen-Startseite: links Hersteller, rechts Artikelgruppen, Mitte Infos (oder Karte).
// Hersteller wählen hebt die Artikelgruppen hervor, zu denen es etwas gibt (und umgekehrt); Hersteller + Gruppe
// zeigt nur die gemeinsamen Infos („Redtronic × Leuchtbalken“). Ohne Script funktionieren alle Links normal.
(function () {
  var detail = document.querySelector("[data-kb-detail]");
  if (!detail) { return; }
  var root = document.querySelector("[data-kb]"), kinds = {};
  try { JSON.parse(root.getAttribute("data-topics") || "[]").forEach(function (t) { kinds[t.id] = t.kind === "Hersteller" ? "hersteller" : "gruppe"; }); } catch (e) { /* leer */ }
  var state = { f: null, g: null }, seq = 0;
  readPanel();

  function num(v) { return v ? +v : null; }
  function readPanel() {
    var p = detail.querySelector("[data-panel]");
    state.f = p ? num(p.getAttribute("data-f")) : null;
    state.g = p ? num(p.getAttribute("data-g")) : null;
    mark(p);
  }
  // Listen: Auswahl markieren, Passendes hervorheben und nach oben holen
  function mark(p) {
    function ids(attr) { return (p.getAttribute(attr) || "").split(",").filter(Boolean).map(Number); }
    var rel = { gruppe: p && state.f ? ids("data-rel-f") : null, hersteller: p && state.g ? ids("data-rel-g") : null };
    var fest = { gruppe: p && state.f ? ids("data-asg-f") : [], hersteller: p && state.g ? ids("data-asg-g") : [] };
    document.querySelectorAll("[data-list]").forEach(function (ul) {
      var kind = ul.getAttribute("data-kind"), sel = kind === "hersteller" ? state.f : state.g, r = rel[kind];
      ul.classList.toggle("has-rel", !!r);
      ul.querySelectorAll("li").forEach(function (li) {
        var id = +li.querySelector("[data-pick]").getAttribute("data-pick");
        li.classList.toggle("active", id === sel);
        li.classList.toggle("rel", !!r && r.indexOf(id) >= 0);
        li.classList.toggle("fest", fest[kind].indexOf(id) >= 0);
        addButton(li, kind, id, r ? (kind === "gruppe" ? state.f : state.g) : null);
      });
      var hint = ul.parentNode.querySelector("[data-rel-hint]"), other = kind === "hersteller" ? state.g : state.f;
      if (hint) {
        hint.hidden = !r;
        if (r) {
          var name = (document.querySelector('[data-list] [data-pick="' + other + '"] span') || {}).textContent || "";
          hint.textContent = fest[kind].length ? "Oben: zu " + name + " zugeordnet · + ordnet weitere zu"
            : r.length ? "Hervorgehoben: mit Infos zu " + name + " · + ordnet fest zu"
            : "Noch nichts zu " + name + " · + ordnet zu";
        }
      }
    });
  }
  // „+“ in der Zeile: Artikelgruppe dem gewählten Hersteller zuordnen (bzw. umgekehrt), ohne Seitenwechsel
  var csrf = root.getAttribute("data-csrf") || "";
  function addButton(li, kind, id, other) {
    var b = li.querySelector(".kb-row-add");
    if (!other || li.classList.contains("fest")) { if (b) { b.hidden = true; } return; }
    if (!b) {
      b = document.createElement("button"); b.type = "button"; b.className = "kb-row-add"; b.textContent = "+";
      li.appendChild(b);
      b.addEventListener("click", function () {
        var maker = kind === "gruppe" ? b.dataset.other : b.dataset.id, group = kind === "gruppe" ? b.dataset.id : b.dataset.other;
        var body = new URLSearchParams({ csrf_token: csrf, hersteller: maker, gruppe: group });
        b.disabled = true;
        fetch("/wissen/sortiment", { method: "POST", credentials: "same-origin", body: body, headers: { "X-CSRF-Token": csrf } })
          .then(function () { b.disabled = false; return load({ fromMap: true, keepScroll: true }); })
          .then(function () { if (window.kbMap) { window.kbMap.reload(state.f || state.g); } });
      });
    }
    var oname = (document.querySelector('[data-list] [data-pick="' + other + '"] span') || {}).textContent || "";
    var name = li.querySelector("span").textContent;
    b.dataset.id = id; b.dataset.other = other; b.hidden = false;
    b.title = kind === "gruppe" ? name + " zu " + oname + " hinzufügen" : oname + " zu " + name + " hinzufügen";
    b.setAttribute("aria-label", b.title);
  }
  function url() {
    if (state.f && state.g) { return "/wissen?f=" + state.f + "&g=" + state.g; }
    return state.f || state.g ? "/wissen?t=" + (state.f || state.g) : "/wissen";
  }
  function load(opts) {
    opts = opts || {};
    var my = ++seq, top = detail.scrollTop;
    var src = state.f && state.g ? "/wissen/kombi?f=" + state.f + "&g=" + state.g
      : state.f || state.g ? "/wissen/" + (state.f || state.g) + "/kurz" : "/wissen/ueberblick";
    detail.classList.add("loading");
    return fetch(src, { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.text(); })
      .then(function (html) {
        if (my !== seq) { return; }
        detail.innerHTML = html;
        detail.classList.remove("loading");
        detail.scrollTop = opts.keepScroll ? top : 0;
        readPanel();
        try { history.replaceState(null, "", url()); } catch (e) { /* egal */ }
        if (!opts.fromMap && window.kbMap) { window.kbMap.select(state.f || state.g); }
        if (!opts.fromMap && !opts.keepScroll && window.innerWidth < 1100) { detail.scrollIntoView({ behavior: "smooth", block: "start" }); }
      })
      .catch(function () { if (my === seq) { location.href = url(); } });
  }
  // Wählen: in den Listen und auf der Karte kombinieren (Hersteller + Gruppe), nochmal klicken = abwählen;
  // Links im Infofenster wählen genau dieses eine Thema.
  function pick(id, only, fromMap, keep) {
    var kind = kinds[id] || "hersteller", key = kind === "hersteller" ? "f" : "g";
    if (only) { state.f = state.g = null; state[key] = id; }
    else { state[key] = state[key] === id && !fromMap && !keep ? null : id; }
    showTab("infos");
    load({ fromMap: fromMap });
  }

  document.addEventListener("click", function (ev) {
    var a = ev.target.closest && ev.target.closest("[data-pick], [data-only], [data-combine], [data-panel-close]");
    if (!a || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) { return; }
    ev.preventDefault();
    if (a.hasAttribute("data-panel-close")) {
      state.f = state.g = null; load(); if (window.kbMap) { window.kbMap.select(null); } return;
    }
    if (a.hasAttribute("data-only")) { pick(+a.getAttribute("data-only"), true); return; }
    if (a.hasAttribute("data-combine")) { pick(+a.getAttribute("data-combine"), false, false, true); return; }
    pick(+a.getAttribute("data-pick"), !a.closest("[data-list]"));
  });
  document.addEventListener("kb:pick", function (ev) { if (ev.detail.id) { pick(ev.detail.id, false, true); } });

  // Umschalter Infos | Karte
  var tabs = document.querySelectorAll("[data-tab]");
  function showTab(name) {
    tabs.forEach(function (t) { t.setAttribute("aria-selected", t.getAttribute("data-tab") === name ? "true" : "false"); });
    document.querySelectorAll("[data-pane]").forEach(function (p) { p.hidden = p.getAttribute("data-pane") !== name; });
    if (name === "karte" && window.kbMap) { window.kbMap.show(); window.kbMap.select(state.f || state.g); }
  }
  tabs.forEach(function (t) { t.addEventListener("click", function () { showTab(t.getAttribute("data-tab")); }); });

  // Formulare im Infofenster (Eintragen, stimmt noch, melden) ohne Seitenwechsel
  detail.addEventListener("submit", function (ev) {
    var form = ev.target.closest("[data-panel-form]");
    if (!form) { return; }
    ev.preventDefault();
    var btn = form.querySelector("button[type=submit]");
    if (btn) { btn.disabled = true; }
    var body = new URLSearchParams(new FormData(form)), csrf = body.get("csrf_token") || "";
    fetch(form.action, { method: "POST", credentials: "same-origin", body: body, headers: { "X-CSRF-Token": csrf } })
      .then(function (r) {
        var m = /[?&]fehler=([^&#]*)/.exec(r.url);
        if (!r.ok) { throw new Error("Nicht gespeichert (Fehler " + r.status + ")"); }
        if (m) { throw new Error(decodeURIComponent(m[1].replace(/\+/g, " "))); }
        if (/sortiment/.test(form.action) && window.kbMap) { window.kbMap.reload(state.f || state.g); }
        return load({ fromMap: true, keepScroll: true }).then(function () {
          var hit = /#(e\d+)$/.exec(r.url), el = hit && document.getElementById(hit[1]);
          if (el) { el.classList.add("just"); el.scrollIntoView({ block: "nearest" }); }
        });
      })
      .catch(function (e) {
        if (btn) { btn.disabled = false; }
        var err = form.querySelector(".kb-d-err") || document.createElement("p");
        err.className = "kb-d-err"; err.textContent = e.message; form.appendChild(err);
      });
  });
  detail.addEventListener("keydown", function (ev) {  // Strg+Enter im Eintragsfeld speichert
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey) && ev.target.matches(".kb-d-add textarea")) {
      ev.preventDefault(); ev.target.form.requestSubmit();
    }
  });

  // Listen filtern (jede Liste für sich); Enter öffnet den ersten Treffer
  document.querySelectorAll("[data-side]").forEach(function (side) {
    var filter = side.querySelector("[data-list-filter]"), none = side.querySelector("[data-list-none]");
    if (!filter) { return; }
    filter.addEventListener("input", function () {
      var q = filter.value.trim().toLowerCase(), shown = 0;
      side.querySelectorAll("[data-list] li").forEach(function (li) {
        var on = !q || (li.getAttribute("data-name") || "").indexOf(q) >= 0;
        li.hidden = !on; if (on) { shown++; }
      });
      if (none) { none.hidden = shown > 0; }
    });
    filter.addEventListener("keydown", function (ev) {
      if (ev.key !== "Enter") { return; }
      ev.preventDefault();
      var first = side.querySelector("[data-list] li:not([hidden]) [data-pick]");
      if (first) { pick(+first.getAttribute("data-pick"), false); }
    });
  });
})();

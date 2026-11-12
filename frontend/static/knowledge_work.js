// Vertriebswissen-Startseite: Liste links (filtern, auswählen), Infofenster rechts (nachladen, schnell ergänzen).
// Ohne Script funktionieren alle Links und Formulare normal (Seite mit ?t=ID).
(function () {
  var detail = document.querySelector("[data-kb-detail]");
  if (!detail) { return; }
  var current = null, seq = 0;
  var cur = detail.querySelector("[data-panel]");
  if (cur && cur.getAttribute("data-panel")) { current = +cur.getAttribute("data-panel"); }

  function markList(id) {
    document.querySelectorAll("[data-list] li").forEach(function (li) {
      var a = li.querySelector("[data-pick]");
      li.classList.toggle("active", !!a && +a.getAttribute("data-pick") === id);
    });
  }
  function load(id, fromMap, keepScroll) {
    var my = ++seq, top = detail.scrollTop;
    detail.classList.add("loading");
    return fetch(id ? "/wissen/" + id + "/kurz" : "/wissen/ueberblick", { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.text(); })
      .then(function (html) {
        if (my !== seq) { return; }
        detail.innerHTML = html;
        detail.classList.remove("loading");
        detail.scrollTop = keepScroll ? top : 0;
        current = id;
        markList(id);
        try { history.replaceState(null, "", id ? "/wissen?t=" + id : "/wissen"); } catch (e) { /* egal */ }
        if (!fromMap && window.kbMap) { window.kbMap.select(id); }
        // Auf schmalen Bildschirmen steht das Fenster unter der Karte: hinscrollen
        if (id && !fromMap && window.innerWidth < 1100) { detail.scrollIntoView({ behavior: "smooth", block: "start" }); }
      })
      .catch(function () { if (my === seq) { location.href = id ? "/wissen?t=" + id : "/wissen"; } });
  }

  document.addEventListener("click", function (ev) {
    var a = ev.target.closest && ev.target.closest("[data-pick], [data-panel-close]");
    if (!a || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) { return; }
    ev.preventDefault();
    if (a.hasAttribute("data-panel-close")) { load(null); if (window.kbMap) { window.kbMap.select(null); } return; }
    load(+a.getAttribute("data-pick"));
  });
  document.addEventListener("kb:pick", function (ev) { if (ev.detail.id !== current || ev.detail.id) { load(ev.detail.id, true); } });

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
        return load(current, true, true).then(function () {
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
  // Strg+Enter im Eintragsfeld speichert
  detail.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey) && ev.target.matches(".kb-d-add textarea")) {
      ev.preventDefault(); ev.target.form.requestSubmit();
    }
  });

  // Liste filtern
  var filter = document.querySelector("[data-list-filter]"), none = document.querySelector("[data-list-none]");
  if (filter) {
    filter.addEventListener("input", function () {
      var q = filter.value.trim().toLowerCase(), shown = 0;
      document.querySelectorAll("[data-list] li").forEach(function (li) {
        var on = !q || (li.getAttribute("data-name") || "").indexOf(q) >= 0;
        li.hidden = !on; if (on) { shown++; }
      });
      if (none) { none.hidden = shown > 0; }
    });
    filter.addEventListener("keydown", function (ev) {  // Enter: ersten Treffer öffnen
      if (ev.key !== "Enter") { return; }
      ev.preventDefault();
      var first = document.querySelector("[data-list] li:not([hidden]) [data-pick]");
      if (first) { load(+first.getAttribute("data-pick")); }
    });
  }
})();

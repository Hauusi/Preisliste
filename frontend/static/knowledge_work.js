// Vertriebswissen-Startseite (Mindmap): links Hersteller, rechts Artikelgruppen, Mitte Karte.
// Anklicken = Infos erscheinen als Blasen um den Punkt. Hersteller: seine Standard-Infos. Artikelgruppe: alles zur
// Gruppe (alle Hersteller). Erst Hersteller, dann Gruppe: Pfeil und nur die Infos dieser Gruppe beim Hersteller.
// Klick auf eine Blase: kleines Fenster mit ganzem Text, Bearbeiten, Löschen. „+ Info“ trägt direkt dort ein.
(function () {
  var root = document.querySelector("[data-kb]"), mapBox = document.querySelector("[data-kb-map]");
  if (!root || !mapBox) { return; }
  var csrf = root.getAttribute("data-csrf") || "", kinds = {}, names = {};
  try {
    JSON.parse(root.getAttribute("data-topics") || "[]").forEach(function (t) {
      kinds[t.id] = t.kind === "Hersteller" ? "hersteller" : t.kind === "Serie" ? "serie" : "gruppe"; names[t.id] = t.name;
    });
  } catch (e) { /* leer */ }
  var state = { f: num(root.getAttribute("data-sel-f")), g: num(root.getAttribute("data-sel-g")) }, seq = 0, current = null;
  var pop = mapBox.querySelector("[data-pop]"), say = document.querySelector("[data-map-say]");
  var TYPES = { bezug: "Bezugsweg / Bedingung", kalk: "Kalkulation", pflicht: "Pflicht-Zubehör", liefer: "Lieferzeit / Kontakt", hinweis: "Hinweis" };
  if (location.search) { try { history.replaceState(null, "", "/wissen"); } catch (e) { /* egal */ } }

  function num(v) { return v ? +v : null; }
  function el(tag, cls, text, parent) {
    var n = document.createElement(tag); if (cls) { n.className = cls; } if (text != null) { n.textContent = text; }
    if (parent) { parent.appendChild(n); } return n;
  }
  function send(url, values) {
    var body = new URLSearchParams(); body.append("csrf_token", csrf);
    Object.keys(values).forEach(function (k) { [].concat(values[k]).forEach(function (v) { if (v != null) { body.append(k, v); } }); });
    return fetch(url, { method: "POST", credentials: "same-origin", body: body, headers: { "X-CSRF-Token": csrf } })
      .then(function (r) {
        var m = /[?&]fehler=([^&#]*)/.exec(r.url);
        if (!r.ok) { throw new Error("Nicht gespeichert (Fehler " + r.status + ")"); }
        if (m) { throw new Error(decodeURIComponent(m[1].replace(/\+/g, " "))); }
        return r;
      });
  }

  // ---------- Auswahl ----------
  function anchorOf() {  // Punkt auf der Karte, um den die Blasen stehen (Serie: ihre Artikelgruppe)
    if (state.g) { return kinds[state.g] === "serie" ? (current && current.anchor) || null : state.g; }
    return state.f;
  }
  function pick(id, keep) {
    var key = kinds[id] === "hersteller" ? "f" : "g";
    state[key] = state[key] === id && !keep ? null : id;  // nochmal anklicken = nur dieses abwählen
    refresh();
  }
  function clearAll() { if (state.f || state.g) { state.f = state.g = null; refresh(); } }
  function refresh() {
    closePop();
    markLists([]);
    var my = ++seq;
    if (!state.f && !state.g) {
      current = null; setSay(); renderList(null);
      if (window.kbMap) { window.kbMap.select(null); window.kbMap.bubbles(null); }
      return;
    }
    var q = [];
    if (state.f) { q.push("f=" + state.f); }
    if (state.g) { q.push("g=" + state.g); }
    fetch("/api/wissen/blasen?" + q.join("&"), { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.json(); })
      .then(function (d) {
        if (my !== seq) { return; }
        current = d;
        markLists(d.lit || []);
        setSay();
        var anchor = anchorOf(), from = state.f && state.g ? state.f : null;
        var list = items(d), narrow = mapBox.clientWidth < 600;  // Handy: Blasen als Liste unter der Karte
        if (window.kbMap) {
          window.kbMap.select(from || anchor, from ? anchor : null);
          window.kbMap.bubbles(anchor, from, narrow ? [] : list);
        }
        renderList(narrow ? list : null);
      })
      .catch(function () { if (my === seq) { state.f = state.g = null; refresh(); } });
  }
  function items(d) {
    var list = d.bubbles.slice(), sel = state.f && state.g, f = state.f, g = state.g;
    if (sel && kinds[g] === "gruppe" && !d.assigned) {
      list.push({ kind: "zuordnen", type: "zuordnen", label: "+ " + names[f] + " führt " + names[g], text: "Artikelgruppe dem Hersteller zuordnen" });
    }
    list.push({ kind: "add", type: "add", label: "+ Info", text: "Neue Info eintragen" });
    if (sel && kinds[g] === "gruppe") { list.push({ kind: "add-serie", type: "add", label: "+ Serie", text: "Serie von " + names[f] + " in " + names[g] + " anlegen" }); }
    if (!sel) {
      var t = g || f;
      list.push({ kind: "link", type: "link", label: "Steckbrief bearbeiten ›", text: "Alles zu " + names[t] + " bearbeiten", link: "/wissen/" + t });
    }
    return list;
  }
  function setSay() {
    if (!say) { return; }
    var f = state.f, g = state.g;
    say.textContent = f && g ? names[f] + " → " + names[g] + ": nur die Infos dieser Artikelgruppe bei " + names[f] + "."
      : g ? names[g] + ": alle Infos, alle Hersteller." + (kinds[g] === "serie" ? "" : "")
      : f ? names[f] + ": Standard-Infos. Rechts eine Artikelgruppe wählen für " + names[f] + " × Gruppe."
      : "Hersteller oder Artikelgruppe anklicken – die Infos erscheinen als Blasen.";
  }
  // Listen: Auswahl markieren; beim gewählten Hersteller leuchten seine Artikelgruppen und Serien auf
  function markLists(lit) {
    document.querySelectorAll("[data-list]").forEach(function (ul) {
      var kind = ul.getAttribute("data-kind");
      ul.querySelectorAll("li").forEach(function (li) {
        var a = li.querySelector("[data-pick]"), id = +a.getAttribute("data-pick");
        li.classList.toggle("active", id === (kind === "hersteller" ? state.f : state.g));
        li.classList.toggle("lit", kind === "gruppe" && lit.indexOf(id) >= 0);
      });
    });
  }

  document.addEventListener("click", function (ev) {
    var a = ev.target.closest && ev.target.closest("[data-list] [data-pick]");
    if (!a || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) { return; }
    ev.preventDefault();
    pick(+a.getAttribute("data-pick"));
  });
  document.addEventListener("kb:pick", function (ev) { if (ev.detail.id) { pick(ev.detail.id, ev.detail.keep); } else { clearAll(); } });
  document.querySelectorAll("[data-side] .kb-list-scroll").forEach(function (box) {
    box.addEventListener("click", function (ev) { if (!ev.target.closest("a, button, input, li")) { clearAll(); } });
  });

  var bubList = document.querySelector("[data-bub-list]");
  function renderList(list) {
    if (!bubList) { return; }
    bubList.textContent = ""; bubList.hidden = !list;
    (list || []).forEach(function (it) {
      var b = el("button", "kb-bub-item b-" + it.type + (it.kind === "add" || it.kind === "add-serie" ? " act" : "") + (it.stale ? " stale" : ""), it.label, bubList);
      b.type = "button";
      b.addEventListener("click", function () {
        var r = b.getBoundingClientRect(), o = mapBox.getBoundingClientRect();
        document.dispatchEvent(new CustomEvent("kb:bubble", { detail: { item: it, x: mapBox.clientWidth / 2, y: Math.min(r.top - o.top, mapBox.clientHeight - 40) } }));
        mapBox.scrollIntoView({ block: "nearest" });
      });
    });
  }
  // ---------- Fenster an der Blase ----------
  function closePop() { if (pop) { pop.hidden = true; pop.textContent = ""; } }
  function openPop(x, y, build) {
    pop.textContent = ""; pop.hidden = false;
    var close = el("button", "icon-btn kb-pop-x", "×", pop); close.type = "button"; close.setAttribute("aria-label", "Schließen");
    close.addEventListener("click", closePop);
    build(pop);
    var w = pop.offsetWidth, h = pop.offsetHeight, W = mapBox.clientWidth, H = mapBox.clientHeight;
    pop.style.left = Math.max(8, Math.min(x - w / 2, W - w - 8)) + "px";
    pop.style.top = (y + 8 + h > H - 8 ? Math.max(8, y - h - 40) : y + 8) + "px";
    var first = pop.querySelector("textarea, input:not([type=hidden])"); if (first) { first.focus(); }
  }
  function errorLine(box) { var p = box.querySelector(".kb-pop-err") || el("p", "kb-pop-err", "", box); return p; }
  function after(p) {  // nach dem Speichern: Blasen neu laden (Auswahl bleibt)
    return p.then(function () { refresh(); });
  }
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && pop && !pop.hidden) { closePop(); } });
  document.addEventListener("kb:view", function () { /* Fenster bleibt, wo es ist */ });

  document.addEventListener("kb:bubble", function (ev) {
    var it = ev.detail.item, x = ev.detail.x, y = ev.detail.y;
    if (it.kind === "link") { location.href = it.link; return; }
    if (it.kind === "zuordnen") {
      send("/wissen/sortiment", { hersteller: state.f, gruppe: state.g }).then(function () { if (window.kbMap) { window.kbMap.reload(anchorOf()); } refresh(); });
      return;
    }
    openPop(x, y, function (box) {
      if (it.kind === "add" || it.kind === "add-serie") { return addForm(box, it.kind === "add-serie"); }
      if (it.type_label) { el("span", "kb-pop-kind t-" + it.type, it.type_label, box); }
      el("p", "kb-pop-text", it.text, box);
      if (it.kind === "eintrag") {
        el("p", "kb-pop-meta", it.who + ", " + it.when + (it.flag ? " · gemeldet: " + it.flag : it.stale ? " · Prüffrist abgelaufen" : ""), box);
        var row = el("div", "kb-pop-actions", null, box);
        var edit = el("button", "secondary", "Bearbeiten", row); edit.type = "button";
        edit.addEventListener("click", function () { editForm(box, it); });
        if (it.stale) {
          var ok = el("button", "secondary", "Stimmt noch", row); ok.type = "button";
          ok.addEventListener("click", function () { after(send("/wissen/eintrag/" + it.entry + "/geprueft", {})); });
        }
        var del = el("a", "button secondary danger-text", "Löschen", row); del.href = "/wissen/eintrag/" + it.entry + "/loeschen";
      } else if (it.kind === "serie") {
        var r2 = el("div", "kb-pop-actions", null, box);
        var open = el("button", "secondary", "Serie öffnen", r2); open.type = "button";
        open.addEventListener("click", function () { state.g = it.series; refresh(); });
      } else if (it.link) {
        var r3 = el("div", "kb-pop-actions", null, box);
        var chg = el("a", "button secondary", "Ändern", r3); chg.href = it.link;
      }
    });
  });
  function typeSelect(current) {
    var s = document.createElement("select"); s.name = "art"; s.setAttribute("aria-label", "Art");
    var auto = el("option", null, "Art automatisch", s); auto.value = "";
    Object.keys(TYPES).forEach(function (k) { var o = el("option", null, TYPES[k], s); o.value = k; if (k === current) { o.selected = true; } });
    return s;
  }
  function editForm(box, it) {
    box.querySelectorAll(":scope > :not(.kb-pop-x)").forEach(function (n) { n.remove(); });
    var form = el("form", "kb-pop-form", null, box);
    var ta = el("textarea", null, null, form); ta.value = it.text; ta.rows = 3; ta.maxLength = 1000; ta.required = true; ta.setAttribute("aria-label", "Text");
    var sel = typeSelect(it.type); form.appendChild(sel);
    var row = el("div", "kb-pop-actions", null, form);
    var save = el("button", null, "Speichern", row); save.type = "submit";
    var cancel = el("button", "secondary", "Abbrechen", row); cancel.type = "button"; cancel.addEventListener("click", closePop);
    ta.focus();
    form.addEventListener("submit", function (ev) {
      ev.preventDefault(); save.disabled = true;
      after(send("/wissen/eintrag/" + it.entry, { text: ta.value, art: sel.value || it.type, themen: it.topics }))
        .catch(function (e) { save.disabled = false; errorLine(form).textContent = e.message; });
    });
  }
  function addForm(box, serie) {
    var f = state.f, g = state.g, form = el("form", "kb-pop-form", null, box);
    if (serie) {
      el("p", "kb-pop-head", "Neue Serie von " + names[f] + " in " + names[g], form);
      var name = el("input", null, null, form); name.name = "name"; name.required = true; name.maxLength = 120; name.placeholder = "z. B. Spartan";
    } else {
      var target = f && g ? names[f] + " × " + names[g] : names[g || f];
      el("p", "kb-pop-head", "Neue Info zu " + target, form);
      var ta = el("textarea", null, null, form); ta.rows = 3; ta.maxLength = 1000; ta.required = true;
      ta.placeholder = "Einfach reinschreiben, z. B. Lieferzeit 6 Wochen"; ta.setAttribute("aria-label", "Neue Info");
      var sel = typeSelect(""); form.appendChild(sel);
      ta.addEventListener("keydown", function (ev) { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); form.requestSubmit(); } });
    }
    var row = el("div", "kb-pop-actions", null, form);
    var save = el("button", null, serie ? "Anlegen" : "Eintragen", row); save.type = "submit";
    form.addEventListener("submit", function (ev) {
      ev.preventDefault(); save.disabled = true;
      var req = serie ? send("/wissen/serie", { name: name.value, gruppe: g, hersteller: f })
        : send("/wissen/eintrag", { text: ta.value, art: sel.value, themen: [f, g].filter(Boolean), vorgabe: g || f });
      req.then(function () {
        if (serie) { location.href = "/wissen?f=" + f + "&g=" + g; return; }  // neue Serie: Listen neu aufbauen
        refresh();
      }).catch(function (e) { save.disabled = false; errorLine(form).textContent = e.message; });
    });
  }

  // ---------- Listen filtern ----------
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
      if (first) { pick(+first.getAttribute("data-pick"), true); }
    });
  });

  // Start: Auswahl aus einem Link (?f=…&g=…) übernehmen, sobald die Karte steht
  if (state.f || state.g) {
    var tries = 0, wait = setInterval(function () {
      if ((window.kbMap && window.kbMap.ready && window.kbMap.ready()) || ++tries > 40) { clearInterval(wait); refresh(); }
    }, 100);
  } else { setSay(); }
})();

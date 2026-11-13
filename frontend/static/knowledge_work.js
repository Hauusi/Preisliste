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
  var openSub = null, subItems = null, lastList = null;  // aufgeklappte Serie: { series, key, name }
  var pop = mapBox.querySelector("[data-pop]"), say = document.querySelector("[data-map-say]");
  var TYPES = { bezug: "Bezugsweg / Bedingung", kalk: "Kalkulation", pflicht: "Pflicht-Zubehör", liefer: "Lieferzeit / Kontakt", hinweis: "Hinweis" };
  if (location.search) { try { history.replaceState(null, "", "/wissen"); } catch (e) { /* egal */ } }

  function num(v) { return v ? +v : null; }
  function el(tag, cls, text, parent) {
    var n = document.createElement(tag); if (cls) { n.className = cls; } if (text != null) { n.textContent = text; }
    if (parent) { parent.appendChild(n); } return n;
  }
  function send(url, values) {
    var hasFile = values.datei instanceof File, body = hasFile ? new FormData() : new URLSearchParams();
    body.append("csrf_token", csrf);
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
    openSub = null; subItems = null;
    refresh();
  }
  function clearAll() { if (state.f || state.g) { state.f = state.g = null; openSub = null; subItems = null; refresh(); } }
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
        markLists(d.lit || [], d.info_g || {}, d.info_f || {});
        setSay();
        var anchor = anchorOf(), from = state.f && state.g ? state.f : null;
        if (kinds[state.g] === "serie") { return showSeries(d, anchor); }
        var list = items(d), narrow = mapBox.clientWidth < 600;  // Handy: Blasen als Liste unter der Karte
        lastList = list;
        if (window.kbMap) {
          window.kbMap.select(from || anchor, from ? anchor : null);
          window.kbMap.bubbles(anchor, from, narrow ? [] : list);
        }
        renderList(narrow ? list : null);
        if (openSub && list.some(function (x) { return x.key === openSub.key; })) { loadSub(openSub, true); } else { openSub = null; subItems = null; }
      })
      .catch(function () { if (my === seq) { state.f = state.g = null; refresh(); } });
  }
  // Überschrift-Blasen: Einträge nach ihrer Überschrift (sonst Art) gruppieren, Angaben und Artikelvergleich je eine
  // feste Überschrift. ctx unterscheidet die Ebene (Hauptblasen / Serie), target = Serie für „+ Info hier“.
  var collapsed = {}, ORDER = ["angabe", "artikel", "bezug", "kalk", "pflicht", "liefer", "hinweis"];
  function group(bubbles, ctx, target) {
    var heads = {}, order = [], rest = [];
    bubbles.forEach(function (b) {
      var name, fixed = false;
      if (b.kind === "eintrag") { name = b.heading || TYPES[b.type] || "Hinweis"; }
      else if (b.kind === "angabe" && b.type === "artikel") { name = "Artikelvergleich"; fixed = true; }
      else if (b.kind === "angabe") { name = "Angaben"; fixed = true; }
      else { rest.push(b); return; }
      var k = (fixed ? "f:" : "e:") + name.toLowerCase();
      if (!heads[k]) {
        heads[k] = { kind: "heading", name: name, fixed: fixed, children: [], ids: [], key: "h:" + ctx + ":" + k, target: target || null,
                     type: fixed ? (b.type === "artikel" ? "artikel" : "angabe") : b.type };
        order.push(k);
      }
      heads[k].children.push(b);
      if (b.entry) { heads[k].ids.push(b.entry); }
    });
    var out = order.map(function (k) {
      var h = heads[k], n = h.children.length;
      h.label = h.name + " (" + n + ")";
      h.text = h.name + ": " + n + (n === 1 ? " Info" : " Infos") + (h.fixed ? "" : " · anklicken zum Umbenennen oder Zuklappen");
      h.collapsed = !!collapsed[h.key];
      return h;
    });
    out.sort(function (a, b) { return (a.fixed ? 0 : 1) - (b.fixed ? 0 : 1) || ORDER.indexOf(a.type) - ORDER.indexOf(b.type) || a.name.localeCompare(b.name); });
    return out.concat(rest);
  }
  function headingNames() {  // Überschriften der aktuellen Ansicht (für die Auswahl beim Eintragen)
    var seen = {}, out = [];
    (function walk(list) {
      (list || []).forEach(function (it) {
        if (it.kind === "heading" && !it.fixed && !seen[it.name]) { seen[it.name] = 1; out.push(it.name); }
        if (it.children) { walk(it.children); }
      });
    })(lastList);
    Object.keys(TYPES).forEach(function (k) { if (!seen[TYPES[k]]) { out.push(TYPES[k]); } });
    return out;
  }
  // Serie gewählt (rechts in der Liste): Hersteller → Artikelgruppe → Serien-Blase, daran ihre Infos
  function showSeries(d, anchor) {
    var sid = state.g, nm = names[sid] || "", from = state.f || d.series_maker || null;
    var head = /^serie/i.test(nm) ? nm : "Serie " + nm;
    var item = { kind: "serie", type: "serie", key: "s" + sid, series: sid, name: nm,
                 label: (names[anchor] ? names[anchor] + " · " : "") + head, text: head + (names[anchor] ? " (" + names[anchor] + ")" : "") };
    var subs = group(d.bubbles, "s" + sid, { id: sid, name: nm }).concat([{ kind: "add", type: "add", key: "add-" + sid, label: "+ Info zu " + nm,
                                   text: "Neue Info zur Serie " + nm, target: sid, targetName: nm }]);
    item.children = subs;
    openSub = { series: sid, key: item.key, name: nm }; subItems = subs; lastList = [item];
    if (window.kbMap) {
      window.kbMap.select(from || anchor, from ? anchor : null);
      if (mapBox.clientWidth < 600) { window.kbMap.bubbles(anchor, from, []); }
      else { window.kbMap.bubbles(anchor, from, [item]); window.kbMap.subBubbles(item.key, subs); }
    }
    renderList(mapBox.clientWidth < 600 ? [item] : null);
  }
  // Serie aufklappen: ihre Infos als Unter-Blasen an der Serien-Blase, dazu „+ Info zu …“
  function loadSub(sub, again) {
    fetch("/api/wissen/blasen?g=" + sub.series, { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.json(); })
      .then(function (d) {
        if (!again && openSub && openSub.series !== sub.series) { return; }
        openSub = sub;
        subItems = group(d.bubbles, "s" + sub.series, { id: sub.series, name: sub.name })
          .concat([{ kind: "add", type: "add", key: "add-" + sub.series, label: "+ Info zu " + sub.name,
                     text: "Neue Info zur Serie " + sub.name, target: sub.series, targetName: sub.name }]);
        (lastList || []).forEach(function (x) { if (x.key === sub.key) { x.children = subItems; } });
        if (!subItems.length) { subItems = []; }
        if (mapBox.clientWidth < 600) { renderList(lastList); } else if (window.kbMap) { window.kbMap.subBubbles(sub.key, subItems); }
      });
  }
  function toggleSub(it) {
    if (openSub && openSub.series === it.series) {
      openSub = null; subItems = null;
      (lastList || []).forEach(function (x) { if (x.key === it.key) { x.children = null; } });
      if (mapBox.clientWidth < 600) { renderList(lastList); } else if (window.kbMap) { window.kbMap.subBubbles(it.key, null); }
      return;
    }
    loadSub({ series: it.series, key: it.key, name: it.name || it.label.replace(/^Serie\s+/i, "") });
  }
  function items(d) {
    var list = group(d.bubbles, "m"), sel = state.f && state.g, f = state.f, g = state.g;
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
    var serie = g && kinds[g] === "serie", grp = serie && current && current.anchor ? names[current.anchor] : "";
    if (serie) {
      var mk = names[f || (current && current.series_maker)] || "";
      say.textContent = (mk ? mk + " → " : "") + (grp ? grp + " → " : "") + (/^serie/i.test(names[g]) ? "" : "Serie ") + names[g] + ": alle Infos zur Serie.";
      return;
    }
    say.textContent = f && g ? names[f] + " → " + names[g] + ": nur die Infos dieser Artikelgruppe bei " + names[f] + "."
      : g ? names[g] + ": alle Infos, alle Hersteller." + (kinds[g] === "serie" ? "" : "")
      : f ? names[f] + ": Standard-Infos. Rechts eine Artikelgruppe wählen für " + names[f] + " × Gruppe."
      : "Hersteller oder Artikelgruppe anklicken – die Infos erscheinen als Blasen.";
  }
  // Listen: Auswahl markieren; beim gewählten Hersteller leuchten seine Artikelgruppen und Serien auf
  function markLists(lit, infoG, infoF) {
    infoG = infoG || {}; infoF = infoF || {};
    document.querySelectorAll("[data-list]").forEach(function (ul) {
      var kind = ul.getAttribute("data-kind"), info = kind === "hersteller" ? infoF : infoG;
      ul.classList.toggle("has-info", Object.keys(info).length > 0);
      ul.querySelectorAll("li").forEach(function (li) {
        var a = li.querySelector("[data-pick]"), id = +a.getAttribute("data-pick"), n = info[id] || 0;
        li.classList.toggle("active", id === (kind === "hersteller" ? state.f : state.g));
        li.classList.toggle("lit", kind === "gruppe" && lit.indexOf(id) >= 0);
        li.classList.toggle("info", n > 0);  // hier stecken Infos zur Auswahl
        var badge = a.querySelector(".kb-info-n");
        if (n > 0) {
          if (!badge) { badge = el("b", "kb-info-n", null, a); }
          badge.textContent = n; badge.title = n + (n === 1 ? " Info" : " Infos") + " dazu";
        } else if (badge) { badge.remove(); }
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
    var flat = [];
    (function walk(items, depth) {
      (items || []).forEach(function (it) {
        flat.push({ it: it, depth: depth });
        if (it.children && !it.collapsed) { walk(it.children, depth + 1); }
      });
    })(list, 0);
    flat.forEach(function (x) {
      var it = x.it;
      var b = el("button", "kb-bub-item b-" + it.type + (it.kind === "add" || it.kind === "add-serie" ? " act" : "") + (it.stale ? " stale" : "")
                 + (it.kind === "heading" ? " head" : "") + (x.depth ? " sub d" + Math.min(x.depth, 3) : "")
                 + (it.children && !it.collapsed ? " open" : ""), it.label, bubList);
      b.type = "button";
      b.addEventListener("click", function () {
        var r = b.getBoundingClientRect(), o = mapBox.getBoundingClientRect();
        document.dispatchEvent(new CustomEvent("kb:bubble", { detail: { item: it, x: mapBox.clientWidth / 2, y: Math.min(r.top - o.top, mapBox.clientHeight - 40) } }));
        mapBox.scrollIntoView({ block: "nearest" });
      });
      if (it.file) { fileLink(it.file, bubList, "kb-bub-file" + (x.depth ? " sub d" + Math.min(x.depth, 3) : "")); }
    });
  }
  function fileLink(file, parent, cls) {
    var a = el("a", cls || "kb-pop-file", (file.kind === "msg" ? "E-Mail · " : "PDF · ") + file.name, parent);
    a.href = file.url; a.target = "_blank"; a.rel = "noopener"; a.title = file.name + " öffnen";
    return a;
  }
  function fileInput(form) {
    var lab = el("label", "kb-pop-filelabel", null, form);
    el("span", null, "PDF oder Outlook-E-Mail (.msg) anhängen (optional)", lab);
    var inp = el("input", null, null, lab); inp.type = "file"; inp.name = "datei"; inp.accept = "application/pdf,.pdf,.msg,application/vnd.ms-outlook";
    return inp;
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
    if (it.kind === "serie") { closePop(); if (kinds[state.g] !== "serie") { toggleSub(it); } return; }
    if (it.kind === "zuordnen") {
      send("/wissen/sortiment", { hersteller: state.f, gruppe: state.g }).then(function () { if (window.kbMap) { window.kbMap.reload(anchorOf()); } refresh(); });
      return;
    }
    if (it.kind === "heading") { return openPop(x, y, function (box) { headingPop(box, it); }); }
    openPop(x, y, function (box) {
      if (it.kind === "add" || it.kind === "add-serie") {
        box._target = it.target ? { id: it.target, name: it.targetName } : null;
        return addForm(box, it.kind === "add-serie");
      }
      if (it.type_label) { el("span", "kb-pop-kind t-" + it.type, it.type_label, box); }
      el("p", "kb-pop-text", it.text, box);
      if (it.file) { fileLink(it.file, box); }
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
  function headingPop(box, it) {
    el("p", "kb-pop-head", it.name, box);
    el("p", "kb-pop-meta", it.children.length + (it.children.length === 1 ? " Info" : " Infos") + (it.fixed ? " · feste Überschrift" : ""), box);
    if (!it.fixed) {
      var form = el("form", "kb-pop-form", null, box);
      var lab = el("label", "kb-pop-filelabel", null, form); el("span", null, "Überschrift umbenennen", lab);
      var inp = el("input", null, null, lab); inp.value = it.name; inp.maxLength = 80; inp.required = true;
      var row = el("div", "kb-pop-actions", null, form);
      var save = el("button", null, "Umbenennen", row); save.type = "submit";
      var add = el("button", "secondary", "+ Info hier", row); add.type = "button";
      add.addEventListener("click", function () {
        box.querySelectorAll(":scope > :not(.kb-pop-x)").forEach(function (n) { n.remove(); });
        box._target = it.target ? { id: it.target.id, name: it.target.name } : null; box._heading = it.name;
        addForm(box, false);
      });
      form.addEventListener("submit", function (ev) {
        ev.preventDefault(); save.disabled = true;
        var oldKey = it.key;
        after(send("/wissen/ueberschrift", { eintrag: it.ids, name: inp.value }).then(function (r) {
          if (collapsed[oldKey]) { delete collapsed[oldKey]; }
          return r;
        })).catch(function (e) { save.disabled = false; errorLine(form).textContent = e.message; });
      });
    }
    var r2 = el("div", "kb-pop-actions", null, box);
    var tog = el("button", "secondary", it.collapsed ? "Aufklappen" : "Zuklappen", r2); tog.type = "button";
    tog.addEventListener("click", function () {
      it.collapsed = !it.collapsed; collapsed[it.key] = it.collapsed; closePop();
      if (mapBox.clientWidth < 600) { renderList(lastList); } else if (window.kbMap) { window.kbMap.redraw(); }
    });
  }
  function headingInput(form, value) {  // Überschrift wählen oder neu eintippen; leer = automatisch nach Art
    var lab = el("label", "kb-pop-filelabel", null, form);
    el("span", null, "Überschrift (leer = automatisch nach Art)", lab);
    var inp = el("input", null, null, lab); inp.maxLength = 80; inp.value = value || "";
    var id = "kb-heads-" + Math.random().toString(36).slice(2); inp.setAttribute("list", id);
    var dl = el("datalist", null, null, lab); dl.id = id;
    headingNames().forEach(function (n) { var o = el("option", null, null, dl); o.value = n; });
    return inp;
  }
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
    var head = headingInput(form, it.heading);
    var file = fileInput(form), drop = null;
    if (it.file) {
      file.previousSibling.textContent = "Anhang ersetzen (jetzt: " + it.file.name + ")";
      var dl = el("label", "inline-label kb-pop-check", null, form);
      drop = el("input", null, null, dl); drop.type = "checkbox";
      dl.appendChild(document.createTextNode(" Anhang entfernen"));
    }
    var row = el("div", "kb-pop-actions", null, form);
    var save = el("button", null, "Speichern", row); save.type = "submit";
    var cancel = el("button", "secondary", "Abbrechen", row); cancel.type = "button"; cancel.addEventListener("click", closePop);
    ta.focus();
    form.addEventListener("submit", function (ev) {
      ev.preventDefault(); save.disabled = true;
      var req = send("/wissen/eintrag/" + it.entry, { text: ta.value, art: sel.value || it.type, themen: it.topics, ueberschrift: head.value });
      if (file.files[0]) { req = req.then(function () { return send("/wissen/eintrag/" + it.entry + "/datei", { datei: file.files[0] }); }); }
      else if (drop && drop.checked) { req = req.then(function () { return send("/wissen/eintrag/" + it.entry + "/datei", { entfernen: "1" }); }); }
      after(req).catch(function (e) { save.disabled = false; errorLine(form).textContent = e.message; });
    });
  }
  function addForm(box, serie) {
    var f = state.f, g = state.g, form = el("form", "kb-pop-form", null, box), target = box._target;
    if (serie) {
      el("p", "kb-pop-head", "Neue Serie von " + names[f] + " in " + names[g], form);
      var name = el("input", null, null, form); name.name = "name"; name.required = true; name.maxLength = 120; name.placeholder = "z. B. Spartan";
    } else {
      var label = target ? "Serie " + target.name : f && g ? names[f] + " × " + names[g] : names[g || f];
      el("p", "kb-pop-head", "Neue Info zu " + label, form);
      var ta = el("textarea", null, null, form); ta.rows = 3; ta.maxLength = 1000; ta.required = true;
      ta.placeholder = "Einfach reinschreiben, z. B. Lieferzeit 6 Wochen"; ta.setAttribute("aria-label", "Neue Info");
      var sel = typeSelect(""); form.appendChild(sel);
      var head = headingInput(form, box._heading || "");
      var file = fileInput(form);
      file.addEventListener("change", function () { ta.required = !file.files[0]; });  // nur PDF: Text darf leer sein (Dateiname)
      ta.addEventListener("keydown", function (ev) { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); form.requestSubmit(); } });
    }
    var row = el("div", "kb-pop-actions", null, form);
    var save = el("button", null, serie ? "Anlegen" : "Eintragen", row); save.type = "submit";
    form.addEventListener("submit", function (ev) {
      ev.preventDefault(); save.disabled = true;
      var req = serie ? send("/wissen/serie", { name: name.value, gruppe: g, hersteller: f })
        : send("/wissen/eintrag", { text: ta.value, art: sel.value, themen: target ? [target.id] : [f, g].filter(Boolean),
                                    vorgabe: target ? target.id : g || f, datei: file.files[0] || null, ueberschrift: head.value });
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

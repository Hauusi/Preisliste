// Vertriebswissen: Vorschlag beim Tippen (Art, Zuordnung, Schreibweise – vom Server, gleiche Regeln wie beim
// Speichern), Zuordnungs-Chips, Suche mit Strg+K. Ohne Script funktioniert alles über die normalen Formulare.
(function () {
  var root = document.querySelector("[data-kb]");
  if (!root) { return; }
  var csrf = root.getAttribute("data-csrf");
  var topics = {};
  try { JSON.parse(root.getAttribute("data-topics") || "[]").forEach(function (t) { topics[t.id] = t; }); } catch (e) { /* leer */ }
  function $(s, el) { return (el || root).querySelector(s); }
  function $$(s, el) { return Array.prototype.slice.call((el || root).querySelectorAll(s)); }

  // ---------- Schnellerfassung ----------
  var form = $("[data-capture]");
  if (form) {
    form.classList.add("js");
    var text = $("[data-capture-text]", form), chips = $("[data-capture-chips]", form);
    var add = $("[data-capture-add]", form), preview = $("[data-capture-preview]", form), tidyEl = $("[data-capture-tidy]", form);
    var vorgabe = $('input[name="vorgabe"]', form);
    var detected = [], manual = [], removed = {}, manualType = false, timer = null, seq = 0;

    function current() {
      var ids = [];
      manual.concat(detected).forEach(function (id) { if (!removed[id] && ids.indexOf(id) < 0 && topics[id]) { ids.push(id); } });
      // nichts erkannt: der geöffnete Steckbrief (wie beim Speichern ohne Script)
      if (!ids.length && vorgabe && !removed[+vorgabe.value] && topics[+vorgabe.value]) { ids.push(+vorgabe.value); }
      return ids;
    }
    var suggestions = [], fieldsBox = $("[data-capture-fields]", form), fieldList = $("[data-capture-fieldlist]", form), ticked = {};
    // Erkannte Mindestmenge/Lieferzeit: Häkchen „als Angabe übernehmen“ beim ersten zugeordneten Thema (nie automatisch)
    function renderFields(ids) {
      fieldList.textContent = "";
      var target = topics[ids[0]];
      fieldsBox.hidden = !suggestions.length || !target;
      if (fieldsBox.hidden) { return; }
      suggestions.forEach(function (sg) {
        var label = document.createElement("label"), cb = document.createElement("input");
        label.className = "inline-label kb-field-check";
        cb.type = "checkbox"; cb.name = "angabe_" + sg.field; cb.value = target.id + "|" + sg.value;
        cb.checked = !!ticked[sg.field + cb.value];
        cb.addEventListener("change", function () { ticked[sg.field + cb.value] = cb.checked; });
        label.appendChild(cb);
        label.appendChild(document.createTextNode(" " + sg.label + " bei " + target.name));
        fieldList.appendChild(label);
      });
    }
    function renderChips() {
      chips.textContent = "";
      var ids = current();
      renderFields(ids);
      if (!ids.length) {
        var h = document.createElement("span"); h.className = "hint"; h.textContent = "nichts erkannt – bitte zuordnen";
        chips.appendChild(h);
      }
      ids.forEach(function (id) {
        var c = document.createElement("span"); c.className = "kb-chip strong";
        c.appendChild(document.createTextNode(topics[id].name));
        var x = document.createElement("button"); x.type = "button"; x.textContent = "×";
        x.setAttribute("aria-label", "Zuordnung entfernen: " + topics[id].name);
        x.addEventListener("click", function () { removed[id] = true; renderChips(); });
        var hidden = document.createElement("input"); hidden.type = "hidden"; hidden.name = "themen"; hidden.value = id;
        c.appendChild(x); c.appendChild(hidden); chips.appendChild(c);
      });
    }
    function autosize() { text.style.height = "auto"; text.style.height = Math.min(text.scrollHeight + 2, 220) + "px"; }
    function ask() {
      var my = ++seq, value = text.value;
      if (!value.trim()) { detected = []; preview.hidden = true; renderChips(); return; }
      fetch("/wissen/vorschlag", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify({ text: value })
      }).then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.json(); }).then(function (d) {
        if (my !== seq) { return; }  // veraltete Antwort
        detected = d.themen || [];
        if (!manualType) { var radio = $('input[name="art"][value="' + d.art + '"]', form); if (radio) { radio.checked = true; } }
        tidyEl.textContent = d.text;
        preview.hidden = !d.text;
        suggestions = d.angaben || [];
        renderChips();
      }).catch(function () { /* ohne Vorschlag: Server erkennt beim Speichern */ });
    }
    text.addEventListener("input", function () { autosize(); clearTimeout(timer); timer = setTimeout(ask, 250); });
    text.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (text.value.trim()) { form.requestSubmit(); } }
    });
    $$('input[name="art"]', form).forEach(function (r) { r.addEventListener("click", function () { manualType = true; }); });
    add.addEventListener("change", function () {
      var id = +add.value;
      if (id) { delete removed[id]; if (manual.indexOf(id) < 0) { manual.push(id); } renderChips(); }
      add.value = "";
    });
    form.addEventListener("submit", function (e) {
      if (!current().length) { e.preventDefault(); add.focus(); chips.classList.add("warn"); }
    });
    renderChips();
    if (text.value.trim()) { autosize(); ask(); }  // vorbelegt (z. B. aus „Suchen ohne Treffer“)
  }

  // ---------- Suche: Treffer beim Tippen, Strg+K ----------
  var search = $("[data-kb-search]"), results = $("[data-kb-results]"), sel = -1, stimer = null, sseq = 0;
  function items() { return $$(".kb-res", results); }
  function mark(i) { items().forEach(function (n, k) { n.setAttribute("aria-selected", k === i ? "true" : "false"); }); sel = i; }
  function find() {
    var q = search.value.trim(), my = ++sseq;
    if (!q) { results.hidden = true; return; }
    fetch("/api/wissen/suche?q=" + encodeURIComponent(q), { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); }).then(function (d) {
        if (my !== sseq) { return; }
        results.textContent = "";
        (d.treffer || []).forEach(function (h) {
          var a = document.createElement("a"); a.className = "kb-res"; a.href = h.url; a.setAttribute("role", "option");
          var b = document.createElement("b"); b.textContent = h.title;
          var s = document.createElement("small"); s.textContent = h.sub;
          a.appendChild(b); a.appendChild(s); results.appendChild(a);
        });
        if (!results.childNodes.length) {
          var p = document.createElement("p"); p.className = "hint"; p.textContent = "Nichts gefunden – Enter für die ausführliche Suche.";
          results.appendChild(p);
        }
        results.hidden = false; sel = -1;
      }).catch(function () { results.hidden = true; });
  }
  if (search) {
    search.addEventListener("input", function () { clearTimeout(stimer); stimer = setTimeout(find, 180); });
    search.addEventListener("keydown", function (e) {
      var list = items();
      if (e.key === "ArrowDown" && list.length) { e.preventDefault(); mark((sel + 1) % list.length); }
      else if (e.key === "ArrowUp" && list.length) { e.preventDefault(); mark((sel - 1 + list.length) % list.length); }
      else if (e.key === "Enter" && sel >= 0 && list[sel]) { e.preventDefault(); location.href = list[sel].href; }
      else if (e.key === "Escape") { results.hidden = true; search.blur(); }
    });
    document.addEventListener("click", function (e) { if (!e.target.closest(".kb-search")) { results.hidden = true; } });
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); search.focus(); search.select(); }
    });
  }
})();

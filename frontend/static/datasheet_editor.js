// Datenblatt-Editor: links Bausteine, rechts Live-Vorschau.
// Jede Änderung wird nach kurzer Pause automatisch gespeichert; der Server prüft den Inhalt und schickt die neu
// berechneten A4-Seiten zurück (gleiche Vorlage wie der Druck). Ziehen am Griff sortiert Bausteine und Zeilen,
// Bilder lassen sich per Ziehen zwischen Plätzen tauschen oder als Datei hineinziehen.
// Dazu: Menü je Baustein/Zeile, Rückgängig (Verlauf je Tab), Prüfliste, Zoom und Seitenwechsel in der Vorschau.
(function () {
  var root = document.querySelector("[data-editor]");
  if (!root) { return; }
  var sheetId = root.getAttribute("data-sheet");
  var csrf = root.getAttribute("data-csrf");
  var blocksBox = root.querySelector("[data-blocks]");
  var preview = root.querySelector("[data-preview]");
  var scrollBox = root.querySelector("[data-preview-scroll]");
  var statusEl = root.querySelector("[data-status]");
  var warnBox = root.querySelector("[data-warnings]");
  var pageLabel = root.querySelector("[data-page-label]");
  var titleEl = root.querySelector("[data-live-title]");
  var OPEN_KEY = "ds-open-" + sheetId, UNDO_KEY = "ds-undo-" + sheetId, ZOOM_KEY = "ds-zoom";
  // Bilder mit zwei Fassungen (freigestellt / Original mit Hintergrund)
  var twins = {};
  (root.getAttribute("data-twins") || "").split(" ").forEach(function (n) { if (n) { twins[n] = true; } });
  // Versatz der Produktbilder oben rechts in mm, per Maus in der Vorschau verschoben: {Kennung: [x, y]}
  var offsets = {};
  try { offsets = JSON.parse(root.getAttribute("data-offsets") || "{}") || {}; } catch (e) { offsets = {}; }
  // Bildgrößen in Prozent, per Ziehen an der Ecke in der Vorschau: {Kennung: Prozent}
  var sizes = {};
  try { sizes = JSON.parse(root.getAttribute("data-sizes") || "{}") || {}; } catch (e) { sizes = {}; }

  function $(sel, el) { return (el || root).querySelector(sel); }
  function $$(sel, el) { return Array.prototype.slice.call((el || root).querySelectorAll(sel)); }
  function val(el, sel) { var x = $(sel, el); return x ? x.value.trim() : ""; }
  function own(container, sel) {  // nur direkte Zeilen dieses Containers (keine verschachtelten)
    return container ? $$(sel, container).filter(function (x) { return x.parentElement === container; }) : [];
  }
  function store(kind, key, value) {
    try { (kind === "s" ? sessionStorage : localStorage).setItem(key, value); } catch (e) { /* ohne Speicher */ }
  }
  function load(kind, key) {
    try { return (kind === "s" ? sessionStorage : localStorage).getItem(key); } catch (e) { return null; }
  }

  // ---------- Inhalt aus dem Formular lesen ----------
  function slotNames(box) {
    return box ? $$("[data-slot]", box).map(function (s) { return s.getAttribute("data-name"); }).filter(Boolean) : [];
  }
  function card(typ) { return $('[data-card][data-typ="' + typ + '"]'); }
  function cards() { return own(blocksBox, "[data-card]"); }
  function visible(el) { return !el.classList.contains("off") && !el.classList.contains("hidden-block"); }
  function propsOf(list, named) {
    return own(list, "[data-row]").map(function (r) {
      return { name: named ? val(r, '[data-f="name"]') : "", wert: val(r, '[data-f="wert"]'), sichtbar: visible(r) };
    });
  }

  function serialize() {
    var intro = card("intro"), spez = card("spez"), anw = card("anwendung");
    return {
      kopf: { titel: val(root, '[data-f="kopf.titel"]'), untertitel: val(root, '[data-f="kopf.untertitel"]') },
      fuss: { version: val(root, '[data-f="fuss.version"]') },
      einleitung: $('[data-f="einleitung"]', intro).value.trim(),
      // Eigenschaften mit Namen (Spezifikationstabelle) und Aufzählungspunkte (ohne Namen) in einer Liste
      eigenschaften: propsOf($('[data-list="eigenschaften"]', intro), true)
        .concat(propsOf($('[data-list="punkte"]', intro), false)),
      bilder_oben: slotNames($('[data-imgs="bilder_oben"]', intro)),
      bild_versatz: offsets,
      bild_groesse: sizes,
      aufteilung: ($('[data-f="aufteilung"]', intro) || { value: "normal" }).value,
      spez: { zusatz: val(spez, '[data-f="spez.zusatz"]'), zusatz_farben: $('[data-f="spez.zusatz_farben"]', spez).value,
        zeilen: own($('[data-list="spez"]', spez), "[data-row]").map(function (r) {
          return { merkmal: val(r, '[data-f="merkmal"]'), wert: $('[data-f="wert"]', r).value.trim() };
        }) },
      zeichnungen: slotNames($('[data-imgs="zeichnungen"]', spez)),
      bilder_unten: slotNames($('[data-imgs="bilder_unten"]', anw)),
      bloecke: cards().map(blockData)
    };
  }

  function blockData(c) {
    var typ = c.getAttribute("data-typ");
    var b = { typ: typ, neue_seite: $('[data-f="neue_seite"]', c).checked, sichtbar: visible(c) };
    if (typ === "bild") {
      b.bild = slotNames($('[data-imgs="bild"]', c))[0] || null;
      b.hoehe = $('[data-f="hoehe"]', c).value;
    } else if (typ === "tabelle") {
      b.titel = val(c, '[data-f="titel"]');
      b.zusatz = val(c, '[data-f="zusatz"]');
      b.bild = slotNames($('[data-imgs="bild"]', c))[0] || null;
      b.bild_pos = $('[data-f="bild_pos"]', c).value;
      b.zeilenbilder = $('[data-f="zeilenbilder"]', c).value;
      b.spalten = $$("[data-col]", c).map(function (i) { return i.value.trim(); });
      b.zeilen = own($('[data-list="zeilen"]', c), "[data-row]").map(function (r) {
        var grp = r.classList.contains("has-group") ? $(".t-grp [data-slot]", r).getAttribute("data-name") : "";
        return { bild: $(".t-img [data-slot]", r).getAttribute("data-name") || null, gruppe: grp || null,
                 artnr: val(r, '[data-f="artnr"]'),
                 farbe: $('[data-f="farbe"]', r).value, beschreibung: val(r, '[data-f="beschreibung"]'),
                 werte: $$("[data-w]", r).map(function (i) { return i.value.trim(); }) };
      });
    }
    return b;
  }

  // ---------- Kurzinfo je Karte, Spaltenanzeige ----------
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  function refreshCards() {
    cards().forEach(function (c) {
      var typ = c.getAttribute("data-typ"), sub = $("[data-sub]", c), text = "";
      if (typ === "intro") {
        var n = own($('[data-list="eigenschaften"]', c), "[data-row]").filter(function (r) {
          return visible(r) && val(r, '[data-f="wert"]'); }).length;
        var pts = own($('[data-list="punkte"]', c), "[data-row]").filter(function (r) {
          return visible(r) && val(r, '[data-f="wert"]'); }).length;
        var pics = slotNames($('[data-imgs="bilder_oben"]', c)).length;
        text = [$('[data-f="einleitung"]', c).value.trim() ? "Text" : "ohne Text", plural(n, "Eigenschaft", "Eigenschaften"),
                plural(pts, "Punkt", "Punkte"), plural(pics, "Bild", "Bilder")].join(", ");
      } else if (typ === "spez") {
        text = plural(own($('[data-list="spez"]', c), "[data-row]").length, "weitere Zeile", "weitere Zeilen");
      } else if (typ === "anwendung") {
        text = plural(slotNames($('[data-imgs="bilder_unten"]', c)).length, "Bild", "Bilder");
      } else if (typ === "bild") {
        text = slotNames($('[data-imgs="bild"]', c)).length ? "" : "noch kein Bild";
      } else if (typ === "tabelle") {
        var title = [val(c, '[data-f="titel"]'), val(c, '[data-f="zusatz"]')].filter(Boolean).join(" - ");
        var rows = own($('[data-list="zeilen"]', c), "[data-row]");
        text = (title || "ohne Überschrift") + ", " + plural(rows.length, "Zeile", "Zeilen");
        c.classList.toggle("no-rows", !rows.length);
        // Werte nur für benannte Zusatzspalten; von den leeren Namensfeldern nur das erste zeigen
        var firstEmpty = true;
        $$("[data-col]", c).forEach(function (input) {
          var k = input.getAttribute("data-col"), name = input.value.trim();
          input.hidden = !name && !firstEmpty;
          if (!name) { firstEmpty = false; }
          $$('[data-wcell="' + k + '"]', c).forEach(function (cell) { cell.hidden = !name; });
          var head = $('[data-colhead="' + k + '"]', c);
          if (head) { head.textContent = name; }
          $$('[data-w="' + k + '"]', c).forEach(function (w) { w.placeholder = name; w.setAttribute("aria-label", name); });
        });
      }
      if ($('[data-f="neue_seite"]', c).checked) { text = "neue Seite · " + text; }
      if (!visible(c)) { text = "ausgeblendet · " + text; }
      sub.textContent = text;
    });
    var foot = $("[data-foot-sub]");
    if (foot) { foot.textContent = "Version " + (val(root, '[data-f="fuss.version"]') || "fehlt"); }
    var reset = $("[data-reset-images]");
    if (reset) { reset.hidden = !Object.keys(offsets).length && !Object.keys(sizes).length; }
  }

  // ---------- Speichern + Live-Vorschau ----------
  var timer = null, inflight = false, again = false;
  function setStatus(text, kind) {
    statusEl.textContent = text;
    statusEl.className = "dse-status" + (kind ? " " + kind : "");
  }
  function changed(structural) {
    if (structural) { pendingStructural = true; }
    refreshCards();
    refreshChecks();
    titleEl.textContent = [val(root, '[data-f="kopf.titel"]'), val(root, '[data-f="kopf.untertitel"]')]
      .filter(Boolean).join(" – ") || "Neues Datenblatt";
    setStatus("Wird gespeichert …", "busy");
    clearTimeout(timer);
    timer = setTimeout(save, 350);
  }
  function post(content) {
    return fetch("/datenblatt/" + sheetId + "/inhalt", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ inhalt: content })
    }).then(function (r) {
      if (!r.ok) { throw new Error(r.status === 401 ? "abgemeldet – bitte neu anmelden" : "Fehler " + r.status); }
      return r.json();
    });
  }
  function save() {
    timer = null;
    if (inflight) { again = true; return; }
    inflight = true;
    var content = serialize(), json = JSON.stringify(content), structural = pendingStructural;
    pendingStructural = false;
    post(content).then(function (data) {
      remember(json, structural);
      preview.innerHTML = data.html;
      setStatus("Gespeichert " + data.gespeichert, "ok");
      afterRender();
    }).catch(function (e) {
      setStatus("Nicht gespeichert: " + e.message, "err");
    }).then(function () {
      inflight = false;
      if (again) { again = false; save(); }
    });
  }
  window.addEventListener("beforeunload", function (e) {
    if (timer || inflight) { e.preventDefault(); e.returnValue = ""; }
  });

  // ---------- Rückgängig: frühere Stände je Tab (sessionStorage), Wiederherstellen = speichern + neu laden ----------
  var pendingStructural = false, lastPush = 0, lastSaved = null, undoStack = [];
  try { undoStack = JSON.parse(load("s", UNDO_KEY) || "[]") || []; } catch (e) { undoStack = []; }
  var undoBtn = $(".dse-top [data-undo]");
  function updateUndo() { undoBtn.disabled = !undoStack.length; }
  function remember(json, structural) {
    if (lastSaved !== null && json !== lastSaved && (structural || Date.now() - lastPush > 4000)) {
      undoStack.push(lastSaved);  // Stand vor dieser Änderung; Tippen wird zu Schritten von einigen Sekunden gebündelt
      undoStack = undoStack.slice(-30);
      lastPush = Date.now();
      store("s", UNDO_KEY, JSON.stringify(undoStack));
    }
    lastSaved = json;
    updateUndo();
  }
  function undo() {
    if (!undoStack.length || inflight) { return; }
    clearTimeout(timer);
    timer = null;
    var prev = undoStack.pop();
    store("s", UNDO_KEY, JSON.stringify(undoStack));
    inflight = true;
    setStatus("Wird zurückgenommen …", "busy");
    post(JSON.parse(prev)).then(function () {
      inflight = false;
      location.reload();
    }).catch(function (e) {
      inflight = false;
      undoStack.push(prev);
      store("s", UNDO_KEY, JSON.stringify(undoStack));
      setStatus("Nicht zurückgenommen: " + e.message, "err");
    });
  }
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "z") {
      // In Textfeldern gilt das Rückgängig des Browsers
      if (e.target.closest && e.target.closest("input, textarea, select, [contenteditable]")) { return; }
      e.preventDefault();
      undo();
    }
  });
  var toast = $("[data-toast]"), toastTimer = null;
  function showToast(text) {
    $("[data-toast-text]", toast).textContent = text;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.hidden = true; }, 7000);
  }

  function afterRender() {
    if (window.dsPlace) { window.dsPlace(preview); }
    if (typeof hideHandle === "function") { hideHandle(); }
    fitPreview();
    if (window.dsCheck) { window.dsCheck(preview, warnBox); }
    updatePager();
  }

  // ---------- Vorschau: Zoom und Seitenwechsel (A4 = 210 mm ≈ 794 px) ----------
  var zoomSel = $("[data-zoom]");
  zoomSel.value = load("l", ZOOM_KEY) || "fit";
  if (!zoomSel.value) { zoomSel.value = "fit"; }
  function fitPreview() {
    var z = zoomSel.value === "fit" ? Math.min(1, Math.max(0.3, (scrollBox.clientWidth - 24) / 794)) : parseFloat(zoomSel.value);
    preview.style.zoom = z.toFixed(3);
    preview.classList.toggle("zoomed", zoomSel.value !== "fit");
  }
  zoomSel.addEventListener("change", function () { store("l", ZOOM_KEY, zoomSel.value); fitPreview(); updatePager(); });
  window.addEventListener("resize", fitPreview);
  function pages() { return $$(".sheet", preview); }
  function boxScrolls() { return scrollBox.scrollHeight > scrollBox.clientHeight + 1; }
  function currentPage() {
    var list = pages(), top = boxScrolls() ? scrollBox.getBoundingClientRect().top : 0;
    var limit = top + (boxScrolls() ? scrollBox.clientHeight : window.innerHeight) / 3, cur = 0;
    list.forEach(function (p, i) { if (p.getBoundingClientRect().top <= limit) { cur = i; } });
    return cur;
  }
  function updatePager() {
    var n = pages().length;
    pageLabel.textContent = n > 1 ? "Seite " + (currentPage() + 1) + " von " + n : "1 Seite";
    $$("[data-page-step]").forEach(function (b) { b.hidden = n < 2; });
  }
  function goPage(i) {
    var p = pages()[i];
    if (!p) { return; }
    if (boxScrolls()) {
      scrollBox.scrollTo({ top: p.getBoundingClientRect().top - scrollBox.getBoundingClientRect().top + scrollBox.scrollTop - 12,
                           behavior: "smooth" });
    } else { p.scrollIntoView({ behavior: "smooth", block: "start" }); }
  }
  root.addEventListener("click", function (e) {
    var step = e.target.closest("[data-page-step]");
    if (step) { goPage(Math.max(0, Math.min(pages().length - 1, currentPage() + parseInt(step.getAttribute("data-page-step"), 10)))); }
  });
  var pagerTick = null;
  scrollBox.addEventListener("scroll", function () { clearTimeout(pagerTick); pagerTick = setTimeout(updatePager, 80); });
  window.addEventListener("scroll", function () { clearTimeout(pagerTick); pagerTick = setTimeout(updatePager, 80); });

  // ---------- Karten auf-/zuklappen, Klick in der Vorschau ----------
  function openState() {
    try { return JSON.parse(load("l", OPEN_KEY) || "null"); } catch (e) { return null; }
  }
  function storeOpen() {
    store("l", OPEN_KEY, JSON.stringify($$("[data-card]").map(function (c) { return c.classList.contains("open"); })));
  }
  function setOpen(c, open) {
    c.classList.toggle("open", open);
    var btn = $("[data-collapse]", c);
    if (btn) { btn.setAttribute("aria-expanded", open ? "true" : "false"); }
    if (open) { $$("textarea", c).forEach(autosize); }  // zugeklappt lässt sich die Höhe nicht messen
  }
  function reveal(c, focusSel) {
    setOpen(c, true);
    storeOpen();
    c.scrollIntoView({ behavior: "smooth", block: "start" });
    c.classList.remove("flash");
    void c.offsetWidth;
    c.classList.add("flash");
    var f = focusSel && $(focusSel, c);
    if (f) { setTimeout(function () { f.focus({ preventScroll: true }); }, 250); }
  }

  // ---------- Produktbilder in der Vorschau per Maus verschieben (Doppelklick = zurück an den Platz) ----------
  var MM = 96 / 25.4, drag = null, justMoved = false;
  function placeImg(img, xy) { img.style.transform = xy ? "translate(" + xy[0] + "mm, " + xy[1] + "mm)" : ""; }
  preview.addEventListener("pointerdown", function (e) {
    var img = e.target.closest("[data-move]");
    if (!img || e.button !== 0) { return; }
    e.preventDefault();
    var key = img.getAttribute("data-move"), start = offsets[key] || [0, 0];
    drag = { img: img, key: key, x0: e.clientX, y0: e.clientY, start: start, xy: start, moved: false };
    img.setPointerCapture(e.pointerId);
    img.classList.add("moving");
  });
  preview.addEventListener("pointermove", function (e) {
    if (!drag) { return; }
    var zoom = parseFloat(preview.style.zoom) || 1, k = 1 / (MM * zoom);
    var dx = (e.clientX - drag.x0) * k, dy = (e.clientY - drag.y0) * k;
    if (Math.abs(dx) + Math.abs(dy) > 0.5) { drag.moved = true; }
    function r(v) { return Math.max(-150, Math.min(150, Math.round(v * 2) / 2)); }
    drag.xy = [r(drag.start[0] + dx), r(drag.start[1] + dy)];
    placeImg(drag.img, drag.xy);
  });
  function endDrag() {
    if (!drag) { return; }
    drag.img.classList.remove("moving");
    if (drag.moved) {
      if (drag.xy[0] || drag.xy[1]) { offsets[drag.key] = drag.xy; } else { delete offsets[drag.key]; }
      justMoved = true;  // der folgende Klick soll nicht die Eingabe öffnen
      setTimeout(function () { justMoved = false; }, 0);
      changed(true);
    }
    drag = null;
  }
  preview.addEventListener("pointerup", endDrag);
  preview.addEventListener("pointercancel", endDrag);
  preview.addEventListener("dblclick", function (e) {
    var img = e.target.closest("[data-move]");
    if (!img) { return; }
    delete offsets[img.getAttribute("data-move")];
    delete sizes[img.getAttribute("data-size")];
    placeImg(img, null);
    img.style.removeProperty("--s");
    changed(true);
  });

  // ---------- Bildgröße: Griff an der Ecke unten rechts des Bilds unter der Maus ----------
  // Der Griff liegt außerhalb der Vorschau (position: fixed), weil die Vorschau gezoomt ist und neu gerendert wird.
  var handle = document.createElement("button");
  handle.type = "button";
  handle.className = "dse-resize";
  handle.title = "Ziehen: Bild größer/kleiner · Doppelklick: Originalgröße";
  handle.setAttribute("aria-label", "Bildgröße ändern");
  handle.hidden = true;
  document.body.appendChild(handle);
  var hovered = null, sizing = null;
  function scaleOf(img) { return (sizes[img.getAttribute("data-size")] || 100) / 100; }
  function applyScale(img, s) {
    if (s === 1) { img.style.removeProperty("--s"); } else { img.style.setProperty("--s", s); }
  }
  function showHandle(img) {
    hovered = img;
    var r = img.getBoundingClientRect();
    handle.style.left = (r.right - 9) + "px";
    handle.style.top = (r.bottom - 9) + "px";
    handle.hidden = false;
  }
  preview.addEventListener("pointerover", function (e) {
    var img = e.target.closest("[data-size]");
    if (img && !drag && !sizing) { showHandle(img); }
  });
  preview.addEventListener("pointerleave", function (e) {
    if (!sizing && e.relatedTarget !== handle) { handle.hidden = true; }
  });
  function hideHandle() { if (!sizing) { handle.hidden = true; } }  // nach neuem Rendern: Bild ist ersetzt
  handle.addEventListener("pointerleave", hideHandle);
  scrollBox.addEventListener("scroll", hideHandle);
  window.addEventListener("resize", function () { if (!sizing) { handle.hidden = true; } });
  handle.addEventListener("pointerdown", function (e) {
    if (!hovered || e.button !== 0) { return; }
    e.preventDefault();
    var r = hovered.getBoundingClientRect();
    sizing = { img: hovered, key: hovered.getAttribute("data-size"), x0: e.clientX, y0: e.clientY,
               w: Math.max(r.width, 1), h: Math.max(r.height, 1), start: scaleOf(hovered), s: scaleOf(hovered) };
    handle.setPointerCapture(e.pointerId);
    hovered.classList.add("sizing");
  });
  handle.addEventListener("pointermove", function (e) {
    if (!sizing) { return; }
    // Faktor aus der Diagonale: rechts/unten ziehen = größer, links/oben = kleiner
    var f = 1 + ((e.clientX - sizing.x0) / sizing.w + (e.clientY - sizing.y0) / sizing.h) / 2;
    sizing.s = Math.max(0.3, Math.min(3, Math.round(sizing.start * f * 20) / 20));
    applyScale(sizing.img, sizing.s);
    showHandle(sizing.img);
    handle.textContent = Math.round(sizing.s * 100) + " %";
  });
  function endSize() {
    if (!sizing) { return; }
    sizing.img.classList.remove("sizing");
    handle.textContent = "";
    var pct = Math.round(sizing.s * 100);
    if (pct !== Math.round(sizing.start * 100)) {
      if (pct === 100) { delete sizes[sizing.key]; } else { sizes[sizing.key] = pct; }
      justMoved = true;
      setTimeout(function () { justMoved = false; }, 0);
      changed(true);
    }
    sizing = null;
    handle.hidden = true;
  }
  handle.addEventListener("pointerup", endSize);
  handle.addEventListener("pointercancel", endSize);
  handle.addEventListener("dblclick", function () {
    if (!hovered) { return; }
    delete sizes[hovered.getAttribute("data-size")];
    applyScale(hovered, 1);
    handle.hidden = true;
    changed(true);
  });

  preview.addEventListener("click", function (e) {
    if (justMoved) { return; }
    var hit = e.target.closest("[data-block]");
    if (!hit) { return; }
    var key = hit.getAttribute("data-block");
    var target = key === "kopf" ? card("kopf") : key === "fuss" ? card("fuss") : cards()[+key];
    if (target) { reveal(target); }
  });

  // ---------- Menüs (⋯): schwebend über allem, damit sie in scrollenden Tabellen nicht abgeschnitten werden ----------
  function closeMenus(except) {
    $$("details.dse-menu[open]").forEach(function (m) { if (m !== except) { m.removeAttribute("open"); } });
  }
  function placeMenu(m) {
    var pop = $(".dse-menu-pop", m), r = $("summary", m).getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight) { m.open = false; return; }
    pop.style.top = pop.style.left = "0px";
    var w = pop.offsetWidth, h = pop.offsetHeight;
    var top = r.bottom + 4 + h > window.innerHeight - 8 ? Math.max(8, r.top - h - 4) : r.bottom + 4;
    pop.style.top = top + "px";
    pop.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w)) + "px";
  }
  root.addEventListener("toggle", function (e) {
    var m = e.target;
    if (!m.matches || !m.matches("details.dse-menu") || !m.open) { return; }
    closeMenus(m);
    placeMenu(m);
    var first = $("button, input", $(".dse-menu-pop", m));
    if (first) { first.focus({ preventScroll: true }); }
  }, true);
  document.addEventListener("click", function (e) {
    if (!e.target.closest("details.dse-menu")) { closeMenus(); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") { return; }
    var m = e.target.closest && e.target.closest("details.dse-menu[open]");
    closeMenus();
    if (m) { $("summary", m).focus(); }
  });
  // Beim Scrollen mitwandern (Menü liegt fest im Fenster), außer Sicht: schließen
  window.addEventListener("scroll", function () { $$("details.dse-menu[open]").forEach(placeMenu); }, true);
  window.addEventListener("resize", function () { closeMenus(); });

  // ---------- Klicks im Editor ----------
  function moveBlock(c, dir) {
    var sib = dir < 0 ? c.previousElementSibling : c.nextElementSibling;
    if (!sib) { return; }
    if (dir < 0) { blocksBox.insertBefore(c, sib); } else { blocksBox.insertBefore(sib, c); }
    c.scrollIntoView({ behavior: "smooth", block: "nearest" });
    storeOpen();
    changed(true);
  }
  function insertBlock(kind, after) {
    var block = fromTemplate(kind);
    if (after && after.nextElementSibling) { blocksBox.insertBefore(block, after.nextElementSibling); }
    else if (after) { blocksBox.appendChild(block); } else { blocksBox.appendChild(block); }
    reveal(block, "input:not([type=file])");
    changed(true);
  }
  function newRow(list, after, source) {
    var fresh = fromTemplate("trow");
    if (source) { copyRow(source, fresh); }
    if (after) { list.insertBefore(fresh, after.nextElementSibling); } else { list.appendChild(fresh); }
    refreshCards();
    return fresh;
  }
  function copyRow(src, dst) {
    $$("input[data-f], input[data-w], select[data-f]", src).forEach(function (el) {
      var sel = el.hasAttribute("data-w") ? '[data-w="' + el.getAttribute("data-w") + '"]' : '[data-f="' + el.getAttribute("data-f") + '"]';
      var target = $(sel, dst);
      if (target.tagName === "SELECT" && !target.querySelector('option[value="' + el.value + '"]')) {
        var opt = document.createElement("option"); opt.value = opt.textContent = el.value; target.appendChild(opt);
      }
      target.value = el.value;
    });
    setSlot($(".t-img [data-slot]", dst), $(".t-img [data-slot]", src).getAttribute("data-name"));
  }
  root.addEventListener("click", function (e) {
    var t = e.target;
    if (t.closest("[data-undo]")) { undo(); return; }
    if (t.closest("[data-dismiss]")) {
      var rep = t.closest("[data-import-report]");
      if (rep) { rep.hidden = true; store("s", "ds-report-" + sheetId, "1"); }
      return;
    }
    var menuItem = t.closest(".dse-menu-pop button");
    if (menuItem) { closeMenus(); }
    var collapse = t.closest("[data-collapse]");
    if (collapse) { var c = collapse.closest("[data-card]"); setOpen(c, !c.classList.contains("open")); storeOpen(); return; }
    var vis = t.closest("[data-visible]");
    if (vis) {
      var row = vis.closest("[data-prop]") || vis.closest("[data-card]");
      var cls = row.hasAttribute("data-card") ? "hidden-block" : "off";
      var off = !row.classList.contains(cls);
      row.classList.toggle(cls, off);
      vis.setAttribute("aria-pressed", off ? "false" : "true");
      changed(true);
      return;
    }
    var mv = t.closest("[data-move-block]");
    if (mv) { moveBlock(mv.closest("[data-card]"), parseInt(mv.getAttribute("data-move-block"), 10)); return; }
    var ins = t.closest("[data-insert-block]");
    if (ins) { insertBlock(ins.getAttribute("data-insert-block"), ins.closest("[data-card]")); return; }
    var dupBlock = t.closest("[data-dup-block]");
    if (dupBlock) {
      var orig = dupBlock.closest("[data-card]"), copy = orig.cloneNode(true);
      $$("details[open]", copy).forEach(function (d) { d.removeAttribute("open"); });
      var ttl = $('[data-f="titel"]', copy);
      if (ttl) { ttl.value = (ttl.value ? ttl.value + " " : "") + "(Kopie)"; }
      blocksBox.insertBefore(copy, orig.nextElementSibling);
      reveal(copy, '[data-f="titel"]');
      changed(true);
      return;
    }
    var insRow = t.closest("[data-insert-row]"), dupRow = t.closest("[data-dup-row]");
    if (insRow || dupRow) {
      var base = (insRow || dupRow).closest("[data-row]");
      var made = newRow(base.parentElement, base, dupRow ? base : null);
      $('[data-f="artnr"]', made).focus();
      changed(true);
      return;
    }
    var rem = t.closest("[data-remove]");
    if (rem) {
      var item = rem.closest("[data-row]");
      var what = item.hasAttribute("data-card") ? "Baustein „" + ($(".dse-card-name", item).textContent || "") + "“ entfernt"
        : item.classList.contains("dse-trow") ? "Zeile entfernt" : "Eintrag entfernt";
      item.remove();
      changed(true);
      storeOpen();
      showToast(what + ".");
      return;
    }
    var addRow = t.closest("[data-add-row]");
    if (addRow) {
      var kind = addRow.getAttribute("data-add-row");
      var body = addRow.closest(".dse-card-body");
      var list = kind === "trow" ? $('[data-list="zeilen"]', body) : addRow.previousElementSibling;
      var fresh = kind === "trow" ? newRow(list) : fromTemplate(kind);
      if (kind !== "trow") { list.appendChild(fresh); }
      var first = $("input:not([type=file]), textarea", fresh);
      if (first) { first.focus(); }
      changed(true);
      return;
    }
    var addBlock = t.closest("[data-add-block]");
    if (addBlock) { insertBlock(addBlock.getAttribute("data-add-block"), null); return; }
    var paste = t.closest("[data-paste]");
    if (paste) { pasteRows(paste.closest("[data-card]")); return; }
    var grpBtn = t.closest("[data-group-toggle]");
    if (grpBtn) {
      var gr = grpBtn.closest("[data-row]"), on = !gr.classList.contains("has-group");
      gr.classList.toggle("has-group", on);
      $("[data-group-label]", grpBtn).textContent = on ? "Kein eigenes Gruppenbild" : "Gruppenbild ab dieser Zeile";
      if (on) { $(".t-grp [data-slot]", gr).focus(); }
      changed(true);
      return;
    }
    var slotBg = t.closest("[data-slot-bg]");
    if (slotBg) { toggleBackground(slotBg.closest("[data-slot]")); return; }
    var slotX = t.closest("[data-slot-remove]");
    if (slotX) { setSlot(slotX.closest("[data-slot]"), ""); changed(true); return; }
    var slot = t.closest("[data-slot]");
    if (slot && !slot.classList.contains("filled")) { $("input[type=file]", slot).click(); }
  });
  root.addEventListener("input", function (e) {
    if (e.target.matches("textarea")) { autosize(e.target); }
    if (!e.target.matches("[data-paste-text]")) { changed(false); }
  });
  root.addEventListener("change", function (e) {
    if (e.target.matches("input[type=file]")) {
      var f = e.target.files[0];
      if (f) { upload(f, e.target.closest("[data-slot]")); }
      e.target.value = "";
      return;
    }
    if (!e.target.matches("[data-paste-text]")) { changed(e.target.matches("select, input[type=checkbox]")); }
  });
  root.addEventListener("keydown", function (e) {
    var slot = e.target.closest && e.target.closest("[data-slot]");
    if (slot && e.target === slot && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      $("input[type=file]", slot).click();
    }
  });

  // Artikeltabelle wie in Excel: Enter = gleiche Spalte in der nächsten Zeile (am Ende neue Zeile), Pfeile hoch/runter
  root.addEventListener("keydown", function (e) {
    var input = e.target;
    if (!input.matches || !input.matches(".dse-trow input:not([type=file])")) { return; }
    if (e.key !== "Enter" && e.key !== "ArrowDown" && e.key !== "ArrowUp") { return; }
    if (e.isComposing) { return; }
    var row = input.closest("[data-row]"), cell = input.closest("td");
    var col = Array.prototype.indexOf.call(row.children, cell);
    var target = e.key === "ArrowUp" ? row.previousElementSibling : row.nextElementSibling;
    if (!target && e.key === "Enter") {
      target = newRow(row.parentElement, row);
      col = Array.prototype.indexOf.call(row.children, $('[data-f="artnr"]', row).closest("td"));
      changed(true);
    }
    if (!target) { return; }
    e.preventDefault();
    var next = target.children[col] && $("input:not([type=file])", target.children[col]);
    if (next) { next.focus(); next.select(); }
  });

  function fromTemplate(name) {
    var tpl = $('template[data-tpl="' + name + '"]');
    return tpl.content.firstElementChild.cloneNode(true);
  }
  function autosize(t) {
    if (!t.offsetParent) { return; }  // unsichtbar (zugeklappt): später beim Aufklappen
    t.style.height = "auto";
    t.style.height = Math.min(t.scrollHeight + 2, 200) + "px";
  }

  // ---------- Bilder ----------
  function setSlot(slot, name, url) {
    slot.setAttribute("data-name", name || "");
    slot.classList.toggle("filled", !!name);
    slot.classList.toggle("cut", !!name && !!twins[name]);
    var bg = $("[data-slot-bg]", slot);
    if (bg) { bg.classList.toggle("on", !!name && name.indexOf("-o.") >= 0); }
    var img = $("img", slot);
    img.hidden = !name;
    img.src = name ? (url || "/datenblatt/" + sheetId + "/bild/" + name) : "";
    slot.title = name ? "Ziehen zum Tauschen, × zum Entfernen" : "Klicken oder Bild hierher ziehen";
  }
  function toggleBackground(slot) {
    var name = slot.getAttribute("data-name");
    fetch("/datenblatt/" + sheetId + "/bild/" + encodeURIComponent(name) + "/hintergrund", {
      method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": csrf }
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) { throw new Error(data.detail || "Fehler " + r.status); }
        return data;
      });
    }).then(function (data) {
      twins[data.name] = true;
      setSlot(slot, data.name, data.url);
      changed(true);
    }).catch(function (e) { setStatus(e.message, "err"); });
  }
  function upload(file, slot) {
    var fd = new FormData();
    fd.append("datei", file);
    if (slot.closest('[data-imgs="bilder_unten"]')) { fd.append("art", "anwendung"); }
    slot.classList.add("loading");
    setStatus(slot.closest('[data-imgs="bilder_unten"]') ? "Bild wird hochgeladen …" : "Bild wird hochgeladen und freigestellt …", "busy");
    fetch("/datenblatt/" + sheetId + "/bilder", {
      method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": csrf }, body: fd
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) { throw new Error(data.detail || "Fehler " + r.status); }
        return data;
      });
    }).then(function (data) {
      if (data.zweitfassung) { twins[data.name] = twins[data.zweitfassung] = true; }
      setSlot(slot, data.name, data.url);
      changed(true);
    }).catch(function (e) {
      setStatus("Bild nicht übernommen: " + e.message, "err");
    }).then(function () { slot.classList.remove("loading"); });
  }

  // ---------- Ziehen: Bausteine/Zeilen sortieren, Bilder tauschen, Dateien ablegen ----------
  var dragged = null, dragSlot = null;
  root.addEventListener("pointerdown", function (e) {
    // Ziehen nur am Griff, damit Text in den Feldern markierbar bleibt
    $$('[data-row][draggable="true"]').forEach(function (r) { r.draggable = false; });
    var grip = e.target.closest("[data-grip]");
    if (grip) { grip.closest("[data-row]").draggable = true; }
    var slot = e.target.closest("[data-slot]");
    if (slot) { slot.draggable = slot.classList.contains("filled") && !e.target.closest("[data-slot-remove], [data-slot-bg]"); }
  });
  root.addEventListener("dragstart", function (e) {
    var slot = e.target.closest && e.target.closest("[data-slot]");
    if (slot && slot.draggable && e.target === slot) {
      dragSlot = slot;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", "bild");
      return;
    }
    var row = e.target.closest && e.target.closest("[data-row]");
    if (!row || !row.draggable) { return; }
    dragged = row;
    row.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", "");
  });
  function rowAfter(container, y) {
    var rows = own(container, "[data-row]").filter(function (r) { return r !== dragged; });
    for (var i = 0; i < rows.length; i++) {
      var box = rows[i].getBoundingClientRect();
      if (y < box.top + box.height / 2) { return rows[i]; }
    }
    return null;
  }
  root.addEventListener("dragover", function (e) {
    var slot = e.target.closest && e.target.closest("[data-slot]");
    var hasFiles = e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], "Files") >= 0;
    if (slot && (dragSlot || hasFiles)) {
      e.preventDefault();
      $$(".dse-slot.over").forEach(function (s) { s.classList.remove("over"); });
      slot.classList.add("over");
      return;
    }
    if (!dragged) { return; }
    var container = dragged.parentElement;
    if (!container.contains(e.target)) { return; }
    e.preventDefault();
    var after = rowAfter(container, e.clientY);
    if (after) { container.insertBefore(dragged, after); } else { container.appendChild(dragged); }
  });
  root.addEventListener("dragleave", function (e) {
    var slot = e.target.closest && e.target.closest("[data-slot]");
    if (slot && !slot.contains(e.relatedTarget)) { slot.classList.remove("over"); }
  });
  root.addEventListener("drop", function (e) {
    var slot = e.target.closest && e.target.closest("[data-slot]");
    $$(".dse-slot.over").forEach(function (s) { s.classList.remove("over"); });
    if (slot && dragSlot && slot !== dragSlot) {
      e.preventDefault();
      var a = dragSlot.getAttribute("data-name"), b = slot.getAttribute("data-name");
      setSlot(slot, a);
      setSlot(dragSlot, b);
      changed(true);
    } else if (slot && e.dataTransfer.files && e.dataTransfer.files.length) {
      e.preventDefault();
      upload(e.dataTransfer.files[0], slot);
    } else if (dragged) {
      e.preventDefault();
    }
  });
  root.addEventListener("dragend", function () {
    if (dragged) {
      dragged.classList.remove("dragging");
      dragged.draggable = false;
      dragged = null;
      changed(true);
      storeOpen();
    }
    dragSlot = null;
  });
  // Tastatur: Griff fokussieren, Pfeil hoch/runter verschiebt
  root.addEventListener("keydown", function (e) {
    var grip = e.target.closest && e.target.closest("[data-grip]");
    if (!grip || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) { return; }
    e.preventDefault();
    var row = grip.closest("[data-row]"), box = row.parentElement;
    var prev = row.previousElementSibling, next = row.nextElementSibling;
    if (e.key === "ArrowUp" && prev) { box.insertBefore(row, prev); }
    if (e.key === "ArrowDown" && next) { box.insertBefore(next, row); }
    grip.focus();
    changed(true);
  });

  // ---------- Zeilen aus Excel einfügen ----------
  function pasteRows(c) {
    var area = $("[data-paste-text]", c);
    if (!area.value.trim()) { area.focus(); return; }
    var cols = $$("[data-col]", c).filter(function (i) { return i.value.trim(); }).length;
    fetch("/datenblatt/" + sheetId + "/einfuegen", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ text: area.value, spalten: cols })
    }).then(function (r) { if (!r.ok) { throw new Error("Fehler " + r.status); } return r.json(); })
      .then(function (data) {
        var list = $('[data-list="zeilen"]', c);
        data.zeilen.forEach(function (z) {
          var row = fromTemplate("trow");
          $('[data-f="artnr"]', row).value = z.artnr;
          var sel = $('[data-f="farbe"]', row);
          if (z.farbe && !sel.querySelector('option[value="' + z.farbe + '"]')) {  // seltene Farbkombination
            var opt = document.createElement("option"); opt.value = opt.textContent = z.farbe; sel.appendChild(opt);
          }
          sel.value = z.farbe;
          $('[data-f="beschreibung"]', row).value = z.beschreibung;
          z.werte.forEach(function (w, k) { var input = $('[data-w="' + k + '"]', row); if (input) { input.value = w; } });
          list.appendChild(row);
        });
        area.value = "";
        $("details.dse-paste", c).open = false;
        changed(true);
        showToast(plural(data.zeilen.length, "Zeile", "Zeilen") + " eingefügt.");
      }).catch(function (e) { setStatus("Einfügen fehlgeschlagen: " + e.message, "err"); });
  }

  // ---------- Prüfliste: was vor dem Druck noch fehlt (Klick springt zur Stelle) ----------
  var checkBox = $("[data-checklist]"), checkList = $("[data-check-list]", checkBox);
  function refreshChecks() {
    var c = serialize(), items = [];
    function add(text, target, focus) { items.push({ text: text, target: target, focus: focus }); }
    var intro = card("intro"), blocks = cards();
    if (!c.kopf.titel) { add("Titel fehlt", card("kopf"), '[data-f="kopf.titel"]'); }
    if (visible(intro)) {
      if (!c.einleitung) { add("Beschreibungstext fehlt", intro, '[data-f="einleitung"]'); }
      if (!c.bilder_oben.length) { add("Kein Produktbild", intro, '[data-imgs="bilder_oben"] [data-slot]'); }
    }
    var specs = c.eigenschaften.filter(function (e) { return e.name && e.wert && e.sichtbar; }).length + c.spez.zeilen.length;
    if (!specs) { add("Keine technischen Daten (Eigenschaften leer)", intro, '[data-list="eigenschaften"] [data-f="wert"]'); }
    var seen = {}, dup = {};
    c.bloecke.forEach(function (b, i) {
      if (b.typ !== "tabelle" || !b.sichtbar) { return; }
      var name = "„" + (b.titel || "Tabelle " + (i + 1)) + "“";
      if (!b.zeilen.length) { add("Tabelle " + name + " hat keine Zeilen", blocks[i], "[data-add-row]"); return; }
      var noNr = b.zeilen.filter(function (z) { return !z.artnr; }).length;
      if (noNr) { add(plural(noNr, "Zeile", "Zeilen") + " ohne Artikelnummer in " + name, blocks[i], '[data-f="artnr"]'); }
      var noDesc = b.zeilen.filter(function (z) { return z.artnr && !z.beschreibung; }).length;
      if (noDesc) { add(plural(noDesc, "Zeile", "Zeilen") + " ohne Beschreibung in " + name, blocks[i], '[data-f="beschreibung"]'); }
      b.zeilen.forEach(function (z) {
        var k = z.artnr.replace(/[\s\-.\/]/g, "").toLowerCase();
        if (!k) { return; }
        if (seen[k] && !dup[k]) { dup[k] = true; add("Artikelnummer " + z.artnr + " steht mehrfach im Blatt", blocks[i], '[data-f="artnr"]'); }
        seen[k] = true;
      });
    });
    c.bloecke.forEach(function (b, i) {
      if (b.typ === "bild" && b.sichtbar && !b.bild) { add("Bild-Baustein ohne Bild", blocks[i], "[data-slot]"); }
    });
    if (!c.fuss.version) { add("Version in der Fußzeile fehlt", card("fuss"), '[data-f="fuss.version"]'); }
    checkList.textContent = "";
    var MAXSHOW = 6, shown = checkBox.classList.contains("all") ? items : items.slice(0, MAXSHOW);
    shown.forEach(function (it) {
      var li = document.createElement("li"), b = document.createElement("button");
      b.type = "button";
      b.textContent = it.text;
      b.addEventListener("click", function () { if (it.target) { reveal(it.target, it.focus); } });
      li.appendChild(b);
      checkList.appendChild(li);
    });
    if (items.length > shown.length) {
      var more = document.createElement("li"), mb = document.createElement("button");
      mb.type = "button";
      mb.className = "more";
      mb.textContent = "und " + (items.length - shown.length) + " weitere anzeigen";
      mb.addEventListener("click", function () { checkBox.classList.add("all"); refreshChecks(); });
      more.appendChild(mb);
      checkList.appendChild(more);
    }
    $("[data-check-title]", checkBox).textContent = items.length ? "Noch prüfen: " + items.length : "Alles Wichtige ist ausgefüllt";
    checkBox.classList.toggle("done", !items.length);
    checkBox.hidden = false;
  }
  $("[data-check-toggle]", checkBox).addEventListener("click", function () {
    var open = !checkBox.classList.contains("collapsed");
    checkBox.classList.toggle("collapsed", open);
    this.setAttribute("aria-expanded", open ? "false" : "true");
    store("l", "ds-check-collapsed", open ? "1" : "");
  });
  if (load("l", "ds-check-collapsed") === "1") {
    checkBox.classList.add("collapsed");
    $("[data-check-toggle]", checkBox).setAttribute("aria-expanded", "false");
  }
  if (load("s", "ds-report-" + sheetId) === "1") {
    var rep = $("[data-import-report]");
    if (rep) { rep.hidden = true; }
  }

  // ---------- Start ----------
  (function restoreOpen() {
    var state = openState(), all = $$("[data-card]");
    all.forEach(function (c, i) { setOpen(c, state && state.length === all.length ? !!state[i] : i <= 1); });
  })();
  refreshCards();
  refreshChecks();
  lastSaved = JSON.stringify(serialize());
  updateUndo();
  afterRender();
})();

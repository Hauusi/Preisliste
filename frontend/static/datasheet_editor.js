// Datenblatt-Editor: links Bausteine, rechts Live-Vorschau.
// Jede Änderung wird nach kurzer Pause automatisch gespeichert; der Server prüft den Inhalt und schickt die neu
// berechneten A4-Seiten zurück (gleiche Vorlage wie der Druck). Ziehen am Griff sortiert Bausteine und Zeilen,
// Bilder lassen sich per Ziehen zwischen Plätzen tauschen oder als Datei hineinziehen.
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
  var pageCount = root.querySelector("[data-page-count]");
  var titleEl = root.querySelector("[data-live-title]");
  var OPEN_KEY = "ds-open-" + sheetId;

  function $(sel, el) { return (el || root).querySelector(sel); }
  function $$(sel, el) { return Array.prototype.slice.call((el || root).querySelectorAll(sel)); }
  function val(el, sel) { var x = $(sel, el); return x ? x.value.trim() : ""; }
  function own(container, sel) {  // nur direkte Zeilen dieses Containers (keine verschachtelten)
    return $$(sel, container).filter(function (x) { return x.parentElement === container; });
  }

  // ---------- Inhalt aus dem Formular lesen ----------
  function slotNames(box) {
    return box ? $$("[data-slot]", box).map(function (s) { return s.getAttribute("data-name"); }).filter(Boolean) : [];
  }
  function card(typ) { return $('[data-card][data-typ="' + typ + '"]'); }
  function visible(el) { return !el.classList.contains("off") && !el.classList.contains("hidden-block"); }

  function serialize() {
    var intro = card("intro"), spez = card("spez"), anw = card("anwendung");
    var content = {
      kopf: { titel: val(root, '[data-f="kopf.titel"]'), untertitel: val(root, '[data-f="kopf.untertitel"]') },
      fuss: { version: val(root, '[data-f="fuss.version"]') },
      einleitung: $('[data-f="einleitung"]', intro).value.trim(),
      eigenschaften: own($('[data-list="eigenschaften"]', intro), "[data-row]").map(function (r) {
        return { name: val(r, '[data-f="name"]'), wert: val(r, '[data-f="wert"]'), sichtbar: visible(r) };
      }),
      bilder_oben: slotNames($('[data-imgs="bilder_oben"]', intro)),
      spez: { zeilen: own($('[data-list="spez"]', spez), "[data-row]").map(function (r) {
        return { merkmal: val(r, '[data-f="merkmal"]'), wert: $('[data-f="wert"]', r).value.trim() };
      }) },
      zeichnungen: slotNames($('[data-imgs="zeichnungen"]', spez)),
      bilder_unten: slotNames($('[data-imgs="bilder_unten"]', anw)),
      bloecke: own(blocksBox, "[data-card]").map(blockData)
    };
    return content;
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
        return { bild: $("[data-slot]", r).getAttribute("data-name") || null, artnr: val(r, '[data-f="artnr"]'),
                 farbe: $('[data-f="farbe"]', r).value, beschreibung: val(r, '[data-f="beschreibung"]'),
                 werte: $$("[data-w]", r).map(function (i) { return i.value.trim(); }) };
      });
    }
    return b;
  }

  // ---------- Kurzinfo je Karte, Spaltenanzeige ----------
  function refreshCards() {
    own(blocksBox, "[data-card]").forEach(function (c) {
      var typ = c.getAttribute("data-typ"), sub = $("[data-sub]", c), text = "";
      if (typ === "intro") {
        var n = own($('[data-list="eigenschaften"]', c), "[data-row]").filter(function (r) {
          return visible(r) && val(r, '[data-f="wert"]'); }).length;
        var pics = slotNames($('[data-imgs="bilder_oben"]', c)).length;
        text = ($('[data-f="einleitung"]', c).value.trim() ? "Text, " : "ohne Text, ") +
          n + (n === 1 ? " Eigenschaft, " : " Eigenschaften, ") + pics + (pics === 1 ? " Bild" : " Bilder");
      } else if (typ === "spez") {
        var rows = own($('[data-list="spez"]', c), "[data-row]").length;
        text = rows + (rows === 1 ? " Zeile" : " Zeilen");
      } else if (typ === "anwendung") {
        var n2 = slotNames($('[data-imgs="bilder_unten"]', c)).length;
        text = n2 + (n2 === 1 ? " Bild" : " Bilder");
      } else if (typ === "bild") {
        text = slotNames($('[data-imgs="bild"]', c)).length ? "" : "noch kein Bild";
      } else if (typ === "tabelle") {
        var title = [val(c, '[data-f="titel"]'), val(c, '[data-f="zusatz"]')].filter(Boolean).join(" - ");
        var tr = own($('[data-list="zeilen"]', c), "[data-row]").length;
        text = (title || "ohne Überschrift") + " · " + tr + (tr === 1 ? " Zeile" : " Zeilen");
        // Wertefelder nur für benannte Zusatzspalten zeigen
        $$("[data-col]", c).forEach(function (input) {
          var k = input.getAttribute("data-col"), on = !!input.value.trim();
          $$('[data-w="' + k + '"]', c).forEach(function (w) { w.hidden = !on; w.placeholder = input.value.trim(); });
        });
      }
      if (!visible(c)) { text = "ausgeblendet · " + text; }
      sub.textContent = text;
    });
  }

  // ---------- Speichern + Live-Vorschau ----------
  var timer = null, inflight = false, again = false;
  function setStatus(text, kind) {
    statusEl.textContent = text;
    statusEl.className = "dse-status" + (kind ? " " + kind : "");
  }
  function changed() {
    refreshCards();
    titleEl.textContent = [val(root, '[data-f="kopf.titel"]'), val(root, '[data-f="kopf.untertitel"]')]
      .filter(Boolean).join(" – ") || "Neues Datenblatt";
    setStatus("Änderungen werden gespeichert …", "busy");
    clearTimeout(timer);
    timer = setTimeout(save, 350);
  }
  function save() {
    timer = null;
    if (inflight) { again = true; return; }
    inflight = true;
    fetch("/datenblatt/" + sheetId + "/inhalt", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ inhalt: serialize() })
    }).then(function (r) {
      if (!r.ok) { throw new Error(r.status === 401 ? "abgemeldet – bitte neu anmelden" : "Fehler " + r.status); }
      return r.json();
    }).then(function (data) {
      preview.innerHTML = data.html;
      pageCount.textContent = data.seiten + (data.seiten === 1 ? " Seite" : " Seiten");
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

  function afterRender() {
    fitPreview();
    if (window.dsCheck) { window.dsCheck(preview, warnBox); }
  }
  // Vorschau auf die Breite der Spalte skalieren (A4 = 210 mm ≈ 794 px)
  function fitPreview() {
    var w = scrollBox.clientWidth - 24;
    preview.style.zoom = Math.min(1, Math.max(0.3, w / 794)).toFixed(3);
  }
  window.addEventListener("resize", fitPreview);

  // ---------- Karten auf-/zuklappen, Klick in der Vorschau ----------
  function openState() {
    try { return JSON.parse(localStorage.getItem(OPEN_KEY) || "null"); } catch (e) { return null; }
  }
  function storeOpen() {
    try {
      localStorage.setItem(OPEN_KEY, JSON.stringify($$("[data-card]").map(function (c) { return c.classList.contains("open"); })));
    } catch (e) { /* ohne Speicher: alles bleibt wie es ist */ }
  }
  function setOpen(c, open) {
    c.classList.toggle("open", open);
    var btn = $("[data-collapse]", c);
    if (btn) { btn.setAttribute("aria-expanded", open ? "true" : "false"); }
  }
  (function restoreOpen() {
    var state = openState(), cards = $$("[data-card]");
    cards.forEach(function (c, i) { setOpen(c, state && state.length === cards.length ? !!state[i] : i <= 1); });
  })();

  function reveal(c) {
    setOpen(c, true);
    storeOpen();
    c.scrollIntoView({ behavior: "smooth", block: "start" });
    c.classList.remove("flash");
    void c.offsetWidth;
    c.classList.add("flash");
  }
  preview.addEventListener("click", function (e) {
    var hit = e.target.closest("[data-block]");
    if (!hit) { return; }
    var key = hit.getAttribute("data-block");
    var target = key === "kopf" ? card("kopf") : key === "fuss" ? card("fuss") : own(blocksBox, "[data-card]")[+key];
    if (target) { reveal(target); }
  });

  // ---------- Klicks im Editor ----------
  root.addEventListener("click", function (e) {
    var t = e.target;
    var collapse = t.closest("[data-collapse]");
    if (collapse) { var c = collapse.closest("[data-card]"); setOpen(c, !c.classList.contains("open")); storeOpen(); return; }
    var vis = t.closest("[data-visible]");
    if (vis) {
      var row = vis.closest("[data-prop]") || vis.closest("[data-card]");
      var cls = row.hasAttribute("data-card") ? "hidden-block" : "off";
      var off = !row.classList.contains(cls);
      row.classList.toggle(cls, off);
      vis.setAttribute("aria-pressed", off ? "false" : "true");
      changed();
      return;
    }
    var rem = t.closest("[data-remove]");
    if (rem) {
      var item = rem.closest("[data-row]");
      if (item.hasAttribute("data-card") && !confirm("Baustein „" + ($(".dse-card-sub", item).textContent || "") + "“ entfernen?")) { return; }
      item.remove();
      changed();
      storeOpen();
      return;
    }
    var addRow = t.closest("[data-add-row]");
    if (addRow) {
      var kind = addRow.getAttribute("data-add-row");
      var list = addRow.closest(".dse-card-body").querySelector("[data-list]");
      var fresh = fromTemplate(kind);
      list.appendChild(fresh);
      var first = $("input, textarea", fresh);
      if (first) { first.focus(); }
      changed();
      return;
    }
    var addBlock = t.closest("[data-add-block]");
    if (addBlock) {
      var block = fromTemplate(addBlock.getAttribute("data-add-block"));
      blocksBox.appendChild(block);
      reveal(block);
      changed();
      return;
    }
    var paste = t.closest("[data-paste]");
    if (paste) { pasteRows(paste.closest("[data-card]")); return; }
    var slotX = t.closest("[data-slot-remove]");
    if (slotX) { setSlot(slotX.closest("[data-slot]"), ""); changed(); return; }
    var slot = t.closest("[data-slot]");
    if (slot && !slot.classList.contains("filled")) { $("input[type=file]", slot).click(); }
  });
  root.addEventListener("input", function (e) {
    if (e.target.matches("textarea")) { autosize(e.target); }
    if (!e.target.matches("[data-paste-text]")) { changed(); }
  });
  root.addEventListener("change", function (e) {
    if (e.target.matches("input[type=file]")) {
      var f = e.target.files[0];
      if (f) { upload(f, e.target.closest("[data-slot]")); }
      e.target.value = "";
      return;
    }
    if (!e.target.matches("[data-paste-text]")) { changed(); }
  });
  root.addEventListener("keydown", function (e) {
    var slot = e.target.closest && e.target.closest("[data-slot]");
    if (slot && e.target === slot && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      $("input[type=file]", slot).click();
    }
  });

  function fromTemplate(name) {
    var tpl = $('template[data-tpl="' + name + '"]');
    return tpl.content.firstElementChild.cloneNode(true);
  }
  function autosize(t) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight + 2, 160) + "px"; }
  $$("textarea").forEach(autosize);

  // ---------- Bilder ----------
  function setSlot(slot, name, url) {
    slot.setAttribute("data-name", name || "");
    slot.classList.toggle("filled", !!name);
    var img = $("img", slot);
    img.hidden = !name;
    img.src = name ? (url || "/datenblatt/" + sheetId + "/bild/" + name) : "";
    slot.title = name ? "Ziehen zum Tauschen, × zum Entfernen" : "Klicken oder Bild hierher ziehen";
  }
  function upload(file, slot) {
    var fd = new FormData();
    fd.append("datei", file);
    slot.classList.add("loading");
    setStatus("Bild wird hochgeladen …", "busy");
    fetch("/datenblatt/" + sheetId + "/bilder", {
      method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": csrf }, body: fd
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) { throw new Error(data.detail || "Fehler " + r.status); }
        return data;
      });
    }).then(function (data) {
      setSlot(slot, data.name, data.url);
      changed();
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
    if (slot) { slot.draggable = slot.classList.contains("filled") && !e.target.closest("[data-slot-remove]"); }
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
      changed();
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
      changed();
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
    changed();
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
          $('[data-f="farbe"]', row).value = z.farbe;
          $('[data-f="beschreibung"]', row).value = z.beschreibung;
          z.werte.forEach(function (w, k) { var input = $('[data-w="' + k + '"]', row); if (input) { input.value = w; } });
          list.appendChild(row);
        });
        area.value = "";
        $("details", c).open = false;
        changed();
      }).catch(function (e) { setStatus("Einfügen fehlgeschlagen: " + e.message, "err"); });
  }

  refreshCards();
  afterRender();
})();

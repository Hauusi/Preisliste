// Vertriebswissen: Karte aller Hersteller und Artikelgruppen mit ihren Verbindungen (SVG, ohne Bibliothek).
// Kräfte-Layout: Knoten stoßen sich ab, Verbindungen ziehen an. Klick hebt Nachbarn hervor, Doppelklick öffnet den
// Steckbrief, Ziehen am Hintergrund verschiebt, Mausrad/Knöpfe zoomen, Knoten lassen sich ziehen.
(function () {
  var box = document.querySelector("[data-kb-map]");
  if (!box) { return; }
  var svg = box.querySelector("svg"), info = box.querySelector("[data-map-info]"), empty = box.querySelector("[data-map-empty]");
  var NS = "http://www.w3.org/2000/svg";
  var data = null, nodes = [], edges = [], byId = {}, selected = null, infoLayer = null;
  var view = { x: -400, y: -260, w: 800, h: 520 };
  var LABEL = { artikel: "Artikel", bezug: "Bezug über", pflicht: "Pflicht-Zubehör", eintrag: "gemeinsame Einträge" };
  var STAGE = { erste: "erste Wahl", gut: "gut", notfalls: "nur wenn nötig", abraten: "abraten", offen: "noch nicht bewertet" };

  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) { n.setAttribute(k, attrs[k]); }
    if (parent) { parent.appendChild(n); }
    return n;
  }
  function types() {
    var on = {};
    document.querySelectorAll("[data-map-type]").forEach(function (c) { on[c.getAttribute("data-map-type")] = c.checked; });
    return on;
  }
  function showOff() { var c = document.querySelector("[data-map-off]"); return c && c.checked; }

  function build() {
    var on = types(), off = showOff();
    nodes = data.nodes.filter(function (n) { return off || !n.off; });
    byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });
    edges = data.edges.filter(function (e) { return on[e.type] && byId[e.a] && byId[e.b]; });
    nodes.forEach(function (n) { n.deg = 0; n.links = []; });
    edges.forEach(function (e) { byId[e.a].deg++; byId[e.b].deg++; byId[e.a].links.push(e); byId[e.b].links.push(e); });
    empty.hidden = edges.length > 0;
    layout();
    draw();
    fit();
  }

  // Startpositionen gespeichert behalten (nach Filterwechsel springt nichts), sonst im Kreis
  function layout() {
    var fresh = nodes.filter(function (n) { return n.x === undefined; });
    fresh.forEach(function (n, i) {
      var a = (i / Math.max(fresh.length, 1)) * Math.PI * 2;
      var r = n.deg ? 140 : 300;
      n.x = Math.cos(a) * r + (i % 3) * 7; n.y = Math.sin(a) * r * 0.7 + (i % 5) * 5;
    });
    for (var step = 0; step < 320; step++) {
      var t = 1 - step / 320;
      for (var i = 0; i < nodes.length; i++) {
        var p = nodes[i]; p.vx = 0; p.vy = 0;
        for (var j = 0; j < nodes.length; j++) {
          if (i === j) { continue; }
          var q = nodes[j], dx = p.x - q.x, dy = p.y - q.y, d2 = dx * dx + dy * dy + 0.01;
          var f = 5200 / d2;
          p.vx += dx * f / Math.sqrt(d2); p.vy += dy * f / Math.sqrt(d2);
        }
        var g = p.deg ? 0.012 : 0.004;  // Verbundene in die Mitte, Einzelne außen
        p.vx -= p.x * g; p.vy -= p.y * g * 1.3;
      }
      edges.forEach(function (e) {
        var a = byId[e.a], b = byId[e.b], dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
        var k = (d - 150) * 0.04;
        a.vx += dx / d * k; a.vy += dy / d * k; b.vx -= dx / d * k; b.vy -= dy / d * k;
      });
      nodes.forEach(function (n) {
        if (n.pinned) { return; }
        var m = Math.min(Math.sqrt(n.vx * n.vx + n.vy * n.vy), 40 * t + 2);
        var len = Math.sqrt(n.vx * n.vx + n.vy * n.vy) || 1;
        n.x += n.vx / len * m; n.y += n.vy / len * m;
      });
    }
  }

  function radius(n) { return 9 + Math.min(Math.sqrt(n.n || 0) * 3.2, 14) + (n.deg ? 3 : 0); }

  function draw() {
    svg.textContent = "";
    var gEdges = el("g", { "class": "m-edges" }, svg), gNodes = el("g", { "class": "m-nodes" }, svg);
    var defs = el("defs", {}, svg);
    ["bezug", "pflicht"].forEach(function (t) {
      var mk = el("marker", { id: "mk-" + t, viewBox: "0 0 10 10", refX: "10", refY: "5", markerWidth: "7", markerHeight: "7",
                              orient: "auto-start-reverse", "class": "mk-" + t }, defs);
      el("path", { d: "M0,0 L10,5 L0,10 z" }, mk);
    });
    svg.insertBefore(defs, gEdges);
    var gLabels = el("g", { "class": "m-elabels" }, svg);
    svg.insertBefore(gLabels, gNodes);
    infoLayer = el("g", { "class": "m-infos" }, svg);
    edges.forEach(function (e) {
      var cls = "m-edge e-" + e.type + (e.stage ? " s-" + e.stage : "");
      e.line = el("line", { "class": cls, "stroke-width": Math.min(1.5 + e.n * 0.8, 6) }, gEdges);
      if (e.source && (e.type === "bezug" || e.type === "pflicht")) { e.line.setAttribute("marker-end", "url(#mk-" + e.type + ")"); }
      if (e.label) { e.text = el("text", { "class": "m-elabel e-" + e.type, "text-anchor": "middle" }, gLabels); e.text.textContent = e.label; }
      var title = el("title", {}, e.line);
      title.textContent = byId[e.a].name + " – " + byId[e.b].name + ": " + LABEL[e.type] + (e.stage ? " (" + STAGE[e.stage] + ")" : "");
    });
    nodes.forEach(function (n) {
      var g = el("g", { "class": "m-node k-" + n.kind + (n.deg ? "" : " lonely") + (n.off ? " off" : "") + (n.owner ? " mine" : ""),
                        tabindex: "0", role: "button", "aria-label": n.name + (n.kind === "gruppe" ? " (Artikelgruppe)" : " (Hersteller)") }, gNodes);
      var r = radius(n);
      if (n.kind === "gruppe") { el("rect", { x: -r, y: -r, width: 2 * r, height: 2 * r, rx: 6 }, g); }
      else { el("circle", { r: r }, g); }
      var label = el("text", { y: r + 15, "text-anchor": "middle" }, g);
      label.textContent = n.name.length > 26 ? n.name.slice(0, 25) + "…" : n.name;
      n.g = g; n.r = r;
      g.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") { location.href = "/wissen/" + n.id; }
        if (ev.key === " ") { ev.preventDefault(); select(n); }
      });
      g.addEventListener("pointerdown", function (ev) { startDrag(ev, n); });
    });
    place();
    if (selected && byId[selected.id]) { select(byId[selected.id], true); } else { select(null); }
  }

  function place() {
    edges.forEach(function (e) {
      var a = byId[e.a], b = byId[e.b];
      if (e.source === e.b) { var t = a; a = b; b = t; }  // Richtung: von der Bedingung zum Ziel
      // Pfeilspitze am Rand des Zielknotens enden lassen
      var dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1, cut = e.source ? (b.r || 12) + 4 : 0;
      e.line.setAttribute("x1", a.x); e.line.setAttribute("y1", a.y);
      e.line.setAttribute("x2", b.x - dx / d * cut); e.line.setAttribute("y2", b.y - dy / d * cut);
      if (e.text) { e.text.setAttribute("x", ((a.x + b.x) / 2).toFixed(1)); e.text.setAttribute("y", ((a.y + b.y) / 2 - 5).toFixed(1)); }
    });
    nodes.forEach(function (n) { n.g.setAttribute("transform", "translate(" + n.x.toFixed(1) + "," + n.y.toFixed(1) + ")"); });
    if (selected) { drawInfos(selected); }
  }

  // ---------- Info-Kärtchen rund um das gewählte Thema ----------
  function fontSize() { return Math.max(9, Math.min(13 * view.w / Math.max(box.clientWidth, 1), 34)); }
  function wrap(text, max) {
    var words = text.split(/\s+/), lines = [""];
    words.forEach(function (w) {
      var cur = lines[lines.length - 1];
      if ((cur + " " + w).trim().length > max && cur) { lines.push(w); } else { lines[lines.length - 1] = (cur + " " + w).trim(); }
    });
    if (lines.length > 3) { lines = lines.slice(0, 3); lines[2] = lines[2].replace(/.{0,2}$/, "…"); }
    return lines;
  }
  function drawInfos(n) {
    infoLayer.textContent = "";
    if (!n || !n.info || !n.info.length || box.clientWidth < 500) { return null; }  // schmal: Liste im Kasten
    var bb = { x0: n.x - n.r, y0: n.y - n.r, x1: n.x + n.r, y1: n.y + n.r + 20 };
    var fs = fontSize(), items = n.info, count = items.length, narrow = box.clientWidth < 500;
    var R = n.r + fs * (count > 4 ? 13 : 10);
    // Kärtchen gleichmäßig im Kreis, mit Lücke dort, wo die meisten Verbindungen hingehen
    var ax = 0, ay = 0;
    n.links.forEach(function (e) { var o = byId[e.a === n.id ? e.b : e.a]; ax += o.x - n.x; ay += o.y - n.y; });
    var start = (ax || ay) ? Math.atan2(ay, ax) + Math.PI / Math.max(count, 1) : -Math.PI / 2;
    items.forEach(function (it, i) {
      var a = start + i * 2 * Math.PI / count, x = n.x + Math.cos(a) * R * (narrow ? 0.85 : 1.35), y = n.y + Math.sin(a) * R * (narrow ? 1.25 : 1);
      var lines = wrap(it.text, narrow ? 20 : 30), w = Math.max.apply(null, lines.map(function (l) { return l.length; })) * fs * 0.56 + fs * 1.4;
      var h = lines.length * fs * 1.3 + fs * 0.9;
      bb.x0 = Math.min(bb.x0, x - w / 2); bb.x1 = Math.max(bb.x1, x + w / 2);
      bb.y0 = Math.min(bb.y0, y - h / 2); bb.y1 = Math.max(bb.y1, y + h / 2);
      el("line", { x1: n.x, y1: n.y, x2: x, y2: y, "class": "m-info-link t-" + it.type }, infoLayer);
      var g = el("g", { "class": "m-info t-" + it.type + (it.stale ? " stale" : ""), transform: "translate(" + (x - w / 2).toFixed(1) + "," + (y - h / 2).toFixed(1) + ")",
                        role: "link", tabindex: "0" }, infoLayer);
      el("rect", { width: w.toFixed(1), height: h.toFixed(1), rx: (fs * 0.5).toFixed(1) }, g);
      el("rect", { width: (fs * 0.3).toFixed(1), height: h.toFixed(1), "class": "bar" }, g);
      lines.forEach(function (l, k) {
        var t = el("text", { x: (fs * 0.85).toFixed(1), y: (fs * (1.25 + k * 1.3)).toFixed(1) }, g);
        t.textContent = l;
      });
      var title = el("title", {}, g); title.textContent = it.text + (it.stale ? " (bitte prüfen)" : "");
      var url = "/wissen/" + n.id + (it.entry ? "#e" + it.entry : it.type === "artikel" ? "#vergleich" : "#angaben");
      var target = it.target && byId[it.target];
      if (target) {
        el("line", { x1: x, y1: y, x2: target.x, y2: target.y, "class": "m-info-target t-" + it.type }, infoLayer).parentNode.insertBefore(
          infoLayer.lastChild, infoLayer.firstChild);
        el("text", { x: (w - fs * 0.6).toFixed(1), y: (fs * 1.25).toFixed(1), "text-anchor": "end", "class": "m-info-go" }, g).textContent = "→";
      }
      g.addEventListener("pointerdown", function (ev) { ev.stopPropagation(); drag = target ? { jump: target } : { link: url }; moved = false; });
      g.addEventListener("keydown", function (ev) { if (ev.key === "Enter") { location.href = url; } });
    });
    return bb;
  }
  // Kärtchen sichtbar halten: Ansicht so weit verschieben, dass alles drin ist (Kärtchen wachsen mit dem Zoom mit,
  // deshalb hilft nur Verschieben; passt es nicht, wird das Thema mittig gesetzt)
  function reveal(bb, n) {
    if (!bb) { return; }
    var m = fontSize(), nx = view.x, ny = view.y;
    if (bb.x1 - bb.x0 + 2 * m > view.w) { nx = n.x - view.w / 2; }
    else if (bb.x0 - m < view.x) { nx = bb.x0 - m; }
    else if (bb.x1 + m > view.x + view.w) { nx = bb.x1 + m - view.w; }
    if (bb.y1 - bb.y0 + 2 * m > view.h) { ny = n.y - view.h / 2; }
    else if (bb.y0 - m < view.y) { ny = bb.y0 - m; }
    else if (bb.y1 + m > view.y + view.h) { ny = bb.y1 + m - view.h; }
    if (nx !== view.x || ny !== view.y) { view.x = nx; view.y = ny; applyView(); }
  }

  function select(n, keep) {
    selected = n;
    reveal(drawInfos(n), n);
    svg.classList.toggle("focus", !!n);
    var near = {};
    if (n) { near[n.id] = true; n.links.forEach(function (e) { near[e.a] = near[e.b] = true; }); }
    nodes.forEach(function (x) { x.g.classList.toggle("hi", !!n && !!near[x.id]); x.g.classList.toggle("sel", !!n && x === n); });
    edges.forEach(function (e) {
      var on = !!n && (e.a === n.id || e.b === n.id);
      e.line.classList.toggle("hi", on);
      if (e.text) { e.text.classList.toggle("hi", on); }
    });
    if (!n) { info.hidden = true; return; }
    info.textContent = "";
    var h = document.createElement("b"); h.textContent = n.name; info.appendChild(h);
    var sub = document.createElement("span");
    sub.textContent = (n.kind === "gruppe" ? "Artikelgruppe" : "Hersteller") + " · " + n.entries + (n.entries === 1 ? " Eintrag" : " Einträge") +
      (n.products ? " · " + n.products + " Artikel" : "");
    info.appendChild(sub);
    var ul = document.createElement("ul");
    n.links.slice().sort(function (a, b) { return a.type < b.type ? -1 : 1; }).forEach(function (e) {
      var other = byId[e.a === n.id ? e.b : e.a], li = document.createElement("li"), a = document.createElement("a");
      a.href = "/wissen/" + other.id; a.textContent = other.name;
      li.className = "e-" + e.type + (e.stage ? " s-" + e.stage : "");
      li.appendChild(a);
      li.appendChild(document.createTextNode(" · " + LABEL[e.type] + (e.stage ? ": " + STAGE[e.stage] : "")));
      ul.appendChild(li);
    });
    if (!n.links.length) { var none = document.createElement("li"); none.textContent = "noch keine Verbindung"; ul.appendChild(none); }
    info.appendChild(ul);
    var open = document.createElement("a"); open.className = "button"; open.href = "/wissen/" + n.id; open.textContent = "Steckbrief öffnen";
    info.appendChild(open);
    // Auf schmalen Bildschirmen stehen die Infos als Liste im Kasten statt als Kärtchen rund um den Kreis
    var narrowList = document.createElement("ol");
    narrowList.className = "kb-map-infolist";
    (n.info || []).forEach(function (it) {
      var li = document.createElement("li"), a = document.createElement("a");
      li.className = "t-" + it.type + (it.stale ? " stale" : "");
      a.href = "/wissen/" + n.id + (it.entry ? "#e" + it.entry : it.type === "artikel" ? "#vergleich" : "#angaben");
      a.textContent = it.text;
      li.appendChild(a);
      narrowList.appendChild(li);
    });
    if (n.info && n.info.length) { info.appendChild(narrowList); }
    info.hidden = false;
  }

  // ---------- Ansicht: Zoom, Verschieben, Knoten ziehen ----------
  function applyView() {
    svg.setAttribute("viewBox", [view.x, view.y, view.w, view.h].map(function (v) { return v.toFixed(1); }).join(" "));
    // Schrift auf dem Bildschirm etwa gleich groß halten (sonst winzig auf dem Handy, riesig beim Hineinzoomen)
    var k = view.w / Math.max(box.clientWidth, 1);
    svg.style.setProperty("--fs", Math.max(9, Math.min(13 * k, 34)).toFixed(1) + "px");
    if (selected && infoLayer) { drawInfos(selected); }
  }
  function fit() {
    if (!nodes.length) { applyView(); return; }
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    nodes.forEach(function (n) { x0 = Math.min(x0, n.x - 40); y0 = Math.min(y0, n.y - 30); x1 = Math.max(x1, n.x + 40); y1 = Math.max(y1, n.y + 40); });
    var ratio = box.clientWidth / Math.max(box.clientHeight, 1), w = Math.max(x1 - x0, Math.min(box.clientWidth * 0.75, 700)), h = Math.max(y1 - y0, 300);
    if (w / h < ratio) { w = h * ratio; } else { h = w / ratio; }
    view = { x: (x0 + x1) / 2 - w / 2, y: (y0 + y1) / 2 - h / 2, w: w, h: h };
    applyView();
  }
  function zoom(f, cx, cy) {
    if (cx === undefined) { cx = view.x + view.w / 2; cy = view.y + view.h / 2; }
    var w = Math.min(Math.max(view.w / f, 200), 6000), h = w * view.h / view.w;
    view.x = cx - (cx - view.x) * w / view.w; view.y = cy - (cy - view.y) * h / view.h; view.w = w; view.h = h;
    applyView();
  }
  function toSvg(ev) {
    var r = svg.getBoundingClientRect();
    return { x: view.x + (ev.clientX - r.left) / r.width * view.w, y: view.y + (ev.clientY - r.top) / r.height * view.h };
  }
  var drag = null, moved = false;
  function startDrag(ev, n) {
    ev.stopPropagation();
    drag = { node: n, start: toSvg(ev), x: n.x, y: n.y, id: ev.pointerId };
    moved = false;
    svg.setPointerCapture(ev.pointerId);
  }
  svg.addEventListener("pointerdown", function (ev) {
    drag = { pan: true, cx: ev.clientX, cy: ev.clientY, vx: view.x, vy: view.y };
    moved = false;
    svg.setPointerCapture(ev.pointerId);
  });
  svg.addEventListener("pointermove", function (ev) {
    if (!drag) { return; }
    if (drag.pan) {
      var r = svg.getBoundingClientRect(), dx = (ev.clientX - drag.cx) / r.width * view.w, dy = (ev.clientY - drag.cy) / r.height * view.h;
      if (Math.abs(dx) + Math.abs(dy) > 2) { moved = true; }
      view.x = drag.vx - dx; view.y = drag.vy - dy; applyView();
    } else {
      var p = toSvg(ev);
      if (Math.abs(p.x - drag.start.x) + Math.abs(p.y - drag.start.y) > 3) { moved = true; }
      drag.node.x = drag.x + p.x - drag.start.x; drag.node.y = drag.y + p.y - drag.start.y; drag.node.pinned = true;
      place();
    }
  });
  // Klick/Doppelklick selbst auswerten: der Zeiger ist am SVG festgehalten, Klicks erreichen die Kreise nicht
  var lastTap = { node: null, t: 0 };
  function endDrag() {
    if (drag && !moved) {
      if (drag.link) { location.href = drag.link; return; }
      if (drag.jump) { var j = drag.jump; drag = null; lastTap = { node: j, t: 0 }; select(j); return; }  // zur Gegenseite springen
      if (drag.pan) { if (connect.on) { setConnect(true); } else { select(null); } }
      else if (connect.on) { connectTap(drag.node); }
      else {
        var now = Date.now();
        if (lastTap.node === drag.node && now - lastTap.t < 400) { location.href = "/wissen/" + drag.node.id; return; }
        var again = selected === drag.node && now - lastTap.t >= 400;
        lastTap = { node: drag.node, t: now };
        select(again ? null : drag.node);  // nochmal anklicken = abwählen, Karte zeigt wieder nur die Themen
      }
    }
    drag = null;
    moved = false;
  }
  // ---------- Verbinden: erst Thema A antippen, dann B; kleines Fenster fragt, welche Verbindung ----------
  var connect = { on: false, from: null }, connectBtn = document.querySelector("[data-map-connect]");
  var csrf = (document.querySelector("[data-kb]") || {}).getAttribute ? document.querySelector("[data-kb]").getAttribute("data-csrf") : "";
  var hint = document.createElement("p"); hint.className = "kb-connect-hint"; hint.hidden = true; box.appendChild(hint);
  var dialog = document.createElement("form"); dialog.className = "kb-connect"; dialog.hidden = true; box.appendChild(dialog);
  function setConnect(on) {
    connect.on = on; connect.from = null;
    if (connectBtn) { connectBtn.setAttribute("aria-pressed", on ? "true" : "false"); }
    box.classList.toggle("connecting", on);
    hint.hidden = !on; hint.textContent = "Verbinden: erstes Thema antippen (z. B. Nordic Lights)";
    dialog.hidden = true;
    nodes.forEach(function (x) { x.g.classList.remove("from"); });
    if (on) { select(null); }
  }
  if (connectBtn) { connectBtn.addEventListener("click", function () { setConnect(!connect.on); }); }
  function connectTap(n) {
    if (!connect.from) {
      connect.from = n; n.g.classList.add("from");
      hint.textContent = n.name + " → jetzt das zweite Thema antippen (z. B. Riedfeld)";
      return;
    }
    if (n === connect.from) { setConnect(true); return; }
    openDialog(connect.from, n);
  }
  function field(label, input) {
    var l = document.createElement("label"); l.appendChild(document.createTextNode(label)); l.appendChild(input); return l;
  }
  function input(attrs) { var i = document.createElement("input"); for (var k in attrs) { i.setAttribute(k, attrs[k]); } return i; }
  function openDialog(a, b) {
    hint.hidden = true;
    dialog.textContent = "";
    var head = document.createElement("div"); head.className = "kb-connect-head";
    var title = document.createElement("b"); title.textContent = a.name + " → " + b.name;
    var swap = document.createElement("button"); swap.type = "button"; swap.className = "link"; swap.textContent = "⇄ umdrehen";
    swap.addEventListener("click", function () { openDialog(b, a); });
    head.appendChild(title); head.appendChild(swap); dialog.appendChild(head);
    function option(value, text, checked, extra) {
      var row = document.createElement("label"); row.className = "kb-connect-opt";
      var r = input({ type: "radio", name: "art", value: value }); if (checked) { r.checked = true; }
      row.appendChild(r);
      var span = document.createElement("span"); span.innerHTML = ""; text.forEach(function (part) {
        if (typeof part === "string") { span.appendChild(document.createTextNode(part)); } else { span.appendChild(part); }
      });
      row.appendChild(span);
      if (extra) { row.appendChild(extra); }
      dialog.appendChild(row);
      return r;
    }
    var moq = input({ type: "number", min: "1", max: "99999", name: "moq", value: a.moq || "", placeholder: "36", "aria-label": "Mindestbestellmenge" });
    var qty = input({ type: "number", min: "1", max: "999", name: "menge", value: "1", "aria-label": "Stück" });
    var note = input({ type: "text", name: "text", maxlength: "1000", placeholder: "z. B. gleiche Halter, austauschbar", "aria-label": "Hinweis" });
    var bothMakers = a.kind === "hersteller" && b.kind === "hersteller";
    option("bezug", ["Anfragen an " + a.name + " unter ", moq, " Stück gehen an " + b.name], bothMakers);
    option("pflicht", [a.name + " braucht ", qty, " × " + b.name + " (Pflicht-Zubehör)"], !bothMakers);
    option("hinweis", ["Hinweis zu beiden: "], false, note);
    var err = document.createElement("p"); err.className = "kb-connect-err"; err.hidden = true; dialog.appendChild(err);
    var row = document.createElement("div"); row.className = "kb-connect-actions";
    var ok = document.createElement("button"); ok.type = "submit"; ok.textContent = "Verbinden";
    var cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "secondary"; cancel.textContent = "Abbrechen";
    cancel.addEventListener("click", function () { setConnect(true); });
    row.appendChild(ok); row.appendChild(cancel); dialog.appendChild(row);
    dialog.onsubmit = function (ev) {
      ev.preventDefault();
      var art = (dialog.querySelector("input[name=art]:checked") || {}).value, steps = [];
      if (art === "bezug") {
        if (moq.value && String(moq.value) !== String(a.moq || "")) { steps.push(["/wissen/" + a.id + "/feld/moq", { wert: moq.value }]); }
        steps.push(["/wissen/" + a.id + "/feld/bezug_klein", { wert: b.id }]);
      } else if (art === "pflicht") {
        steps.push(["/wissen/" + a.id + "/feld/pflicht", { wert: b.id, menge: qty.value || 1 }]);
      } else if (art === "hinweis") {
        if (!note.value.trim()) { note.focus(); return; }
        steps.push(["/wissen/eintrag", { text: note.value, themen: [a.id, b.id] }]);
      } else { return; }
      ok.disabled = true;
      steps.reduce(function (chain, st) { return chain.then(function () { return send(st[0], st[1]); }); }, Promise.resolve())
        .then(function () { setConnect(false); reload(a.id); })
        .catch(function (e) { err.textContent = e.message; err.hidden = false; ok.disabled = false; });
    };
    dialog.hidden = false;
    (moq.value ? dialog.querySelector("input[name=art]:checked") : moq).focus();
  }
  function send(url, values) {
    var body = new URLSearchParams();
    body.append("csrf_token", csrf);
    Object.keys(values).forEach(function (k) {
      [].concat(values[k]).forEach(function (v) { body.append(k, v); });
    });
    return fetch(url, { method: "POST", credentials: "same-origin", body: body, headers: { "X-CSRF-Token": csrf } })
      .then(function (r) {
        var m = /[?&]fehler=([^&#]*)/.exec(r.url);
        if (!r.ok) { throw new Error("Nicht gespeichert (Fehler " + r.status + ")"); }
        if (m) { throw new Error(decodeURIComponent(m[1].replace(/\+/g, " "))); }
      });
  }
  // Karte neu laden, Positionen behalten, gewähltes Thema wieder auswählen
  function reload(selectId) {
    fetch("/api/wissen/karte", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var old = {};
        data.nodes.forEach(function (n) { old[n.id] = n; });
        d.nodes.forEach(function (n) { var o = old[n.id]; if (o) { n.x = o.x; n.y = o.y; n.pinned = true; } });
        data = d;
        selected = null;
        var keep = view;
        build();
        view = keep; applyView();
        if (byId[selectId]) { select(byId[selectId]); }
      });
  }

  svg.addEventListener("pointerup", endDrag);
  svg.addEventListener("pointercancel", endDrag);
  svg.addEventListener("wheel", function (ev) {
    ev.preventDefault();
    var p = toSvg(ev);
    zoom(ev.deltaY < 0 ? 1.15 : 1 / 1.15, p.x, p.y);
  }, { passive: false });
  document.querySelectorAll("[data-map-zoom]").forEach(function (b) {
    b.addEventListener("click", function () { zoom(parseFloat(b.getAttribute("data-map-zoom"))); });
  });
  var fitBtn = document.querySelector("[data-map-fit]");
  if (fitBtn) { fitBtn.addEventListener("click", fit); }
  document.querySelectorAll("[data-map-type], [data-map-off]").forEach(function (c) { c.addEventListener("change", build); });
  window.addEventListener("resize", fit);

  fetch("/api/wissen/karte", { credentials: "same-origin", headers: { Accept: "application/json" } })
    .then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.json(); })
    .then(function (d) { data = d; build(); })
    .catch(function () { empty.textContent = "Karte konnte nicht geladen werden. Seite neu laden."; empty.hidden = false; });
})();

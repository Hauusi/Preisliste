// Vertriebswissen: Karte aller Hersteller und Artikelgruppen mit ihren Verbindungen (SVG, ohne Bibliothek).
// Kräfte-Layout: Knoten stoßen sich ab, Verbindungen ziehen an. Klick hebt Nachbarn hervor, Doppelklick öffnet den
// Steckbrief, Ziehen am Hintergrund verschiebt, Mausrad/Knöpfe zoomen, Knoten lassen sich ziehen.
(function () {
  var box = document.querySelector("[data-kb-map]");
  if (!box) { return; }
  var svg = box.querySelector("svg"), info = box.querySelector("[data-map-info]"), empty = box.querySelector("[data-map-empty]");
  var NS = "http://www.w3.org/2000/svg";
  var data = null, nodes = [], edges = [], byId = {}, selected = null;
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
    edges.forEach(function (e) {
      var cls = "m-edge e-" + e.type + (e.stage ? " s-" + e.stage : "");
      e.line = el("line", { "class": cls, "stroke-width": Math.min(1.5 + e.n * 0.8, 6) }, gEdges);
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
      e.line.setAttribute("x1", a.x); e.line.setAttribute("y1", a.y); e.line.setAttribute("x2", b.x); e.line.setAttribute("y2", b.y);
    });
    nodes.forEach(function (n) { n.g.setAttribute("transform", "translate(" + n.x.toFixed(1) + "," + n.y.toFixed(1) + ")"); });
  }

  function select(n, keep) {
    selected = n;
    svg.classList.toggle("focus", !!n);
    var near = {};
    if (n) { near[n.id] = true; n.links.forEach(function (e) { near[e.a] = near[e.b] = true; }); }
    nodes.forEach(function (x) { x.g.classList.toggle("hi", !!n && !!near[x.id]); x.g.classList.toggle("sel", !!n && x === n); });
    edges.forEach(function (e) { e.line.classList.toggle("hi", !!n && (e.a === n.id || e.b === n.id)); });
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
    info.hidden = false;
  }

  // ---------- Ansicht: Zoom, Verschieben, Knoten ziehen ----------
  function applyView() {
    svg.setAttribute("viewBox", [view.x, view.y, view.w, view.h].map(function (v) { return v.toFixed(1); }).join(" "));
    // Schrift auf dem Bildschirm etwa gleich groß halten (sonst winzig auf dem Handy, riesig beim Hineinzoomen)
    var k = view.w / Math.max(box.clientWidth, 1);
    svg.style.setProperty("--fs", Math.max(9, Math.min(13 * k, 34)).toFixed(1) + "px");
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
      if (drag.pan) { select(null); }
      else {
        var now = Date.now();
        if (lastTap.node === drag.node && now - lastTap.t < 400) { location.href = "/wissen/" + drag.node.id; }
        lastTap = { node: drag.node, t: now };
        select(drag.node);
      }
    }
    drag = null;
    moved = false;
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

// Vertriebswissen: Karte aller Hersteller und Artikelgruppen mit ihren Verbindungen (SVG, ohne Bibliothek).
// Kräfte-Layout: Knoten stoßen sich ab, Verbindungen ziehen an. Klick hebt Nachbarn hervor, Doppelklick öffnet den
// Steckbrief, Ziehen am Hintergrund verschiebt, Mausrad/Knöpfe zoomen, Knoten lassen sich ziehen.
(function () {
  var box = document.querySelector("[data-kb-map]");
  if (!box) { return; }
  var svg = box.querySelector("svg"), empty = box.querySelector("[data-map-empty]");
  var NS = "http://www.w3.org/2000/svg";
  var data = null, nodes = [], edges = [], byId = {}, selected = null, pair = null, pairLayer = null, bubbleLayer = null, bub = null, groups = [], groupLayer = null;
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
    var on = { artikel: true, bezug: true, pflicht: true, eintrag: false };  // ohne Häkchen: Standard
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
    groups = (data.groups || []).map(function (g, i) {
      return { id: g.id, name: g.name, color: i % 6, members: g.members.filter(function (id) { return byId[id]; }) };
    }).filter(function (g) { return g.members.length > 1; });
    groups.forEach(function (g) { g.members.forEach(function (id) { byId[id].deg = byId[id].deg || 1; }); });
    empty.hidden = edges.length > 0 || groups.length > 0;
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
    groups.forEach(function (g) {  // Firmengruppen starten beisammen, sonst verhaken sich die Gruppen ineinander
      var root = byId[g.id] || byId[g.members[0]];
      g.members.forEach(function (id, k) {
        var n = byId[id];
        if (n === root || fresh.indexOf(n) < 0) { return; }
        var a = k / g.members.length * Math.PI * 2;
        n.x = root.x + Math.cos(a) * 70; n.y = root.y + Math.sin(a) * 50;
      });
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
        var k = (d - (e.label ? 270 : 150)) * 0.04;  // beschriftete Pfeile länger, damit der Text Platz hat
        a.vx += dx / d * k; a.vy += dy / d * k; b.vx -= dx / d * k; b.vy -= dy / d * k;
      });
      groups.forEach(function (g) {  // Firmengruppe: Töchter bleiben bei der Mutter, damit die Blase kompakt ist
        var root = byId[g.id] || byId[g.members[0]];
        g.members.forEach(function (id) {
          var n = byId[id]; if (n === root) { return; }
          var dx = root.x - n.x, dy = root.y - n.y, d = Math.sqrt(dx * dx + dy * dy) || 1, k = (d - 120) * 0.05;
          n.vx += dx / d * k; n.vy += dy / d * k; root.vx -= dx / d * k * 0.5; root.vy -= dy / d * k * 0.5;
        });
        nodes.forEach(function (o) {  // fremde Firmen aus der Gruppe heraushalten
          if (g.members.indexOf(o.id) >= 0) { return; }
          g.members.forEach(function (id) {
            var n = byId[id], dx = o.x - n.x, dy = o.y - n.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
            if (d < 170) { var k = (170 - d) * 0.06; o.vx += dx / d * k; o.vy += dy / d * k; }
          });
        });
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
    groupLayer = el("g", { "class": "m-groups" }, svg);
    groups.forEach(function (g) {
      g.path = el("path", { "class": "m-group c" + g.color }, groupLayer);
      g.label = el("text", { "class": "m-group-label c" + g.color }, groupLayer);
      g.label.textContent = g.name + "-Gruppe";
      var t = el("title", {}, g.path); t.textContent = "Firmengruppe " + g.name;
    });
    groupLayer.style.display = showGroups() ? "" : "none";
    var gEdges = el("g", { "class": "m-edges" }, svg), gNodes = el("g", { "class": "m-nodes" }, svg);
    var defs = el("defs", {}, svg);
    ["bezug", "pflicht", "pair"].forEach(function (t) {
      var mk = el("marker", { id: "mk-" + t, viewBox: "0 0 10 10", refX: "10", refY: "5", markerWidth: "7", markerHeight: "7",
                              orient: "auto-start-reverse", "class": "mk-" + t }, defs);
      el("path", { d: "M0,0 L10,5 L0,10 z" }, mk);
    });
    svg.insertBefore(defs, gEdges);
    var gLabels = el("g", { "class": "m-elabels" }, svg);
    svg.insertBefore(gLabels, gNodes);
    pairLayer = el("g", { "class": "m-pair" }, svg);  // Pfeil Hersteller → Artikelgruppe (bei Auswahl beider)
    svg.insertBefore(pairLayer, gNodes);
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
    bubbleLayer = el("g", { "class": "m-bubbles" }, svg);
    place();
    if (selected && byId[selected.id]) { select(byId[selected.id], true, pair ? pair[1] : null); } else { select(null, true); }
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
    groups.forEach(drawGroup);
    drawPair();
    drawBubbles();
  }
  // ---------- Blasen: je Info eine Blase um den gewählten Punkt (Mindmap) ----------
  var COLORS = ["bezug", "kalk", "pflicht", "liefer", "hinweis", "angabe", "artikel", "serie", "add", "link", "zuordnen"];
  function wrapText(t, max, lines) {
    var words = String(t).split(/\s+/), out = [""];
    words.forEach(function (w) {
      var cur = out[out.length - 1];
      if ((cur + " " + w).trim().length > max && cur) { out.push(w); } else { out[out.length - 1] = (cur + " " + w).trim(); }
    });
    if (out.length > lines) { out = out.slice(0, lines); out[lines - 1] = out[lines - 1].replace(/.{0,1}$/, "…"); }
    return out;
  }
  function drawBubbles() {
    if (!bubbleLayer) { return; }
    bubbleLayer.textContent = "";
    if (!bub || !byId[bub.anchor]) { return; }
    var a = byId[bub.anchor], fs = 13 * view.w / Math.max(box.clientWidth, 1), items = bub.items, n = items.length;  // Bildschirmschrift ~13 px
    if (!n) { return; }
    var sizes = items.map(function (it) {
      var lines = wrapText(it.label, it.kind === "add" || it.kind === "link" ? 30 : 26, 3);
      var w = Math.max.apply(null, lines.map(function (l) { return l.length; })) * fs * 0.56 + fs * 1.8;
      return { lines: lines, w: w, h: lines.length * fs * 1.3 + fs * 1.0 };
    });
    // Lücke in Richtung des Herstellers (Pfeil), sonst ringsum; bei vielen Blasen zweiter/dritter Ring
    var gap = 0, dir = -Math.PI / 2;
    if (bub.from && byId[bub.from]) { var f = byId[bub.from]; dir = Math.atan2(f.y - a.y, f.x - a.x); gap = Math.PI / 2.2; }
    var avg = sizes.reduce(function (s, z) { return s + z.w; }, 0) / n;
    var placed = 0, ring = 0, pos = [];
    while (placed < n && ring < 6) {
      var R = (a.r || 12) + fs * 5 + avg * 0.55 + ring * (fs * 4.2 + 30);
      var cap = Math.max(4, Math.floor((2 * Math.PI - gap) * R * 1.2 / (avg * 0.95 + fs)));
      var take = Math.min(cap, n - placed);
      for (var i = 0; i < take; i++) {
        var ang = dir + gap / 2 + (2 * Math.PI - gap) * (take === 1 ? 0.5 : (i + 0.5) / take) + ring * 0.25;
        pos.push({ x: a.x + Math.cos(ang) * R * 1.35, y: a.y + Math.sin(ang) * R * 0.95 });
      }
      placed += take; ring++;
    }
    // Überlappungen auflösen: Blasen gegeneinander und von den gewählten Punkten wegschieben
    var fixed = [a].concat(bub.from && byId[bub.from] ? [byId[bub.from]] : []);
    var pad = fs * 0.7;
    for (var it = 0; it < 120; it++) {
      var movedAny = false;
      for (var i1 = 0; i1 < pos.length; i1++) {
        var p1 = pos[i1], z1 = sizes[i1];
        for (var i2 = i1 + 1; i2 < pos.length; i2++) {
          var p2 = pos[i2], z2 = sizes[i2];
          var ox = (z1.w + z2.w) / 2 + pad - Math.abs(p1.x - p2.x), oy = (z1.h + z2.h) / 2 + pad - Math.abs(p1.y - p2.y);
          if (ox > 0 && oy > 0) {
            movedAny = true;
            if (ox < oy * 1.6) { var sx = (p1.x < p2.x ? -1 : 1) * ox / 2; p1.x += sx; p2.x -= sx; }
            else { var sy = (p1.y < p2.y ? -1 : 1) * oy / 2; p1.y += sy; p2.y -= sy; }
          }
        }
        fixed.forEach(function (q) {  // Punkt samt Namen frei lassen
          var qr = (q.r || 12) + fs * 1.5, ox2 = z1.w / 2 + qr + pad - Math.abs(p1.x - q.x), oy2 = z1.h / 2 + qr + fs * 1.5 - Math.abs(p1.y - q.y);
          if (ox2 > 0 && oy2 > 0) {
            movedAny = true;
            var dx = p1.x - q.x, dy = p1.y - q.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
            p1.x += dx / d * Math.min(ox2, oy2); p1.y += dy / d * Math.min(ox2, oy2);
          }
        });
      }
      if (!movedAny) { break; }
    }
    var lines = el("g", { "class": "m-bub-links" }, bubbleLayer);
    items.forEach(function (it, i) {
      var p = pos[i], z = sizes[i]; if (!p) { return; }
      el("line", { x1: a.x, y1: a.y, x2: p.x, y2: p.y, "class": "m-bub-link b-" + it.type }, lines);
      var g = el("g", { "class": "m-bub b-" + it.type + (it.stale ? " stale" : "") + (it.kind === "add" || it.kind === "zuordnen" ? " act" : ""),
                        transform: "translate(" + (p.x - z.w / 2).toFixed(1) + "," + (p.y - z.h / 2).toFixed(1) + ")", role: "button", tabindex: "0" }, bubbleLayer);
      el("rect", { width: z.w.toFixed(1), height: z.h.toFixed(1), rx: Math.min(z.h / 2, fs * 1.2).toFixed(1) }, g);
      z.lines.forEach(function (l, k) {
        var t = el("text", { x: (z.w / 2).toFixed(1), y: (fs * (1.25 + k * 1.3)).toFixed(1), "text-anchor": "middle" }, g);
        t.style.fontSize = fs.toFixed(2) + "px";  // passend zur Blasengröße (CSSOM, kein style-Attribut wegen CSP)
        t.textContent = l;
      });
      var title = el("title", {}, g); title.textContent = it.text || it.label;
      g.addEventListener("pointerdown", function (ev) { ev.stopPropagation(); drag = { bubble: i }; moved = false; });
      g.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); bubbleEvent(i, g); } });
      it.g = g;
    });
  }
  function bubbleEvent(i, g) {
    var r = g.getBoundingClientRect(), o = box.getBoundingClientRect();
    document.dispatchEvent(new CustomEvent("kb:bubble", { detail: { item: bub.items[i],
      x: r.left - o.left + r.width / 2, y: r.top - o.top + r.height, top: r.top - o.top } }));
  }
  // Ansicht so legen, dass Punkt und alle Blasen zu sehen sind
  function frameBubbles() {
    if (!bub || !bubbleLayer || !box.clientWidth) { return; }
    var bb; try { bb = bubbleLayer.getBBox(); } catch (e) { return; }
    var pts = [byId[bub.anchor]].concat(bub.from && byId[bub.from] ? [byId[bub.from]] : []);
    var x0 = Math.min(bb.x, Math.min.apply(null, pts.map(function (p) { return p.x - 60; }))), x1 = Math.max(bb.x + bb.width, Math.max.apply(null, pts.map(function (p) { return p.x + 60; })));
    var y0 = Math.min(bb.y, Math.min.apply(null, pts.map(function (p) { return p.y - 40; }))), y1 = Math.max(bb.y + bb.height, Math.max.apply(null, pts.map(function (p) { return p.y + 50; })));
    var ratio = box.clientWidth / box.clientHeight, w = (x1 - x0) * 1.1, h = (y1 - y0) * 1.15;
    if (w / h < ratio) { w = h * ratio; } else { h = w / ratio; }
    view = { x: (x0 + x1) / 2 - w / 2, y: (y0 + y1) / 2 - h / 2, w: Math.max(w, 300), h: Math.max(h, 300 / ratio) };
    applyView(); applyView();  // zweimal: Schriftgröße hängt vom Zoom ab, Blasen werden danach neu vermessen
  }
  function drawPair() {
    if (!pairLayer) { return; }
    pairLayer.textContent = "";
    if (!pair) { return; }
    var a = pair[0], b = pair[1], dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
    var x1 = a.x + dx / d * ((a.r || 12) + 4), y1 = a.y + dy / d * ((a.r || 12) + 4);
    var x2 = b.x - dx / d * ((b.r || 12) + 8), y2 = b.y - dy / d * ((b.r || 12) + 8);
    el("line", { x1: x1, y1: y1, x2: x2, y2: y2, "class": "m-pair-halo" }, pairLayer);
    el("line", { x1: x1, y1: y1, x2: x2, y2: y2, "class": "m-pair-line", "marker-end": "url(#mk-pair)" }, pairLayer);
  }

  function fontSize() { return Math.max(9, Math.min(13 * view.w / Math.max(box.clientWidth, 1), 34)); }

  // ---------- Firmengruppen: weiche Blase um alle Firmen der Gruppe, folgt beim Verschieben ----------
  function showGroups() { var c = document.querySelector("[data-map-groups]"); return !c || c.checked; }
  // Blase wie „Bubble Sets“: Feld positiv um die Mitglieder (Kreis + Name) und entlang verbindender Linien,
  // negativ um fremde Firmen. Linien weichen fremden Firmen in einem Bogen aus. Umriss per Marching Squares.
  function nodeBox(n, fs) {  // Kreis plus Name darunter als Rechteck
    var r = n.r || 12, w = Math.max(r, Math.min(n.name.length, 26) * fs * 0.3);
    return [n.x - w, n.y - r, n.x + w, n.y + r + fs * 1.5];
  }
  function distBox(b, x, y) {
    var dx = Math.max(b[0] - x, 0, x - b[2]), dy = Math.max(b[1] - y, 0, y - b[3]);
    return Math.sqrt(dx * dx + dy * dy);
  }
  function distSeg(a, b, x, y) {
    var dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy || 1;
    var t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / l2));
    var px = a[0] + t * dx - x, py = a[1] + t * dy - y;
    return Math.sqrt(px * px + py * py);
  }
  function hits(a, b, obstacles, clear) {  // fremde Firmen, die der Linie a→b zu nahe kommen
    return obstacles.filter(function (o) {
      var cx = (o[0] + o[2]) / 2, cy = (o[1] + o[3]) / 2;
      return distSeg(a, b, cx, cy) - Math.max(o[2] - o[0], o[3] - o[1]) / 2 < clear;
    });
  }
  function cost(path, obstacles, clear) {  // erst möglichst wenig Berührungen, dann möglichst kurz
    var n = 0, len = 0;
    for (var i = 0; i < path.length - 1; i++) {
      n += hits(path[i], path[i + 1], obstacles, clear).length;
      len += Math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1]);
    }
    return n * 1e6 + len;
  }
  function route(a, b, obstacles, clear, depth) {  // Linie a→b, die fremden Firmen im Bogen ausweicht
    var hit = null, best = Infinity;
    hits(a, b, obstacles, clear).forEach(function (o) {
      var m = Math.hypot((o[0] + o[2]) / 2 - (a[0] + b[0]) / 2, (o[1] + o[3]) / 2 - (a[1] + b[1]) / 2);
      if (m < best) { best = m; hit = o; }
    });
    if (!hit || depth > 3) { return [a, b]; }
    var cx = (hit[0] + hit[2]) / 2, cy = (hit[1] + hit[3]) / 2;
    var dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1;
    var nx = -dy / l, ny = dx / l;  // senkrecht zur Linie, beide Seiten probieren
    var reach = Math.hypot(hit[2] - hit[0], hit[3] - hit[1]) / 2 + clear * 1.3;
    var t = Math.max(0, Math.min(1, ((cx - a[0]) * dx + (cy - a[1]) * dy) / (l * l)));
    var bestPath = null, bestCost = Infinity;
    [1, -1].forEach(function (side) {
      var w = [cx + nx * reach * side, cy + ny * reach * side];
      if (t <= 0 || t >= 1) { w = [cx + nx * reach * side + dx / l * reach * (t <= 0 ? -0.5 : 0.5), cy + ny * reach * side + dy / l * reach * (t <= 0 ? -0.5 : 0.5)]; }
      var left = route(a, w, obstacles, clear, depth + 1), right = route(w, b, obstacles, clear, depth + 1);
      var path = left.concat(right.slice(1)), c = cost(path, obstacles, clear);
      if (c < bestCost) { bestCost = c; bestPath = path; }
    });
    return bestPath;
  }
  function contours(f, cols, rows, x0, y0, cell, iso) {  // Marching Squares → geschlossene Linienzüge
    var segs = [];
    function v(i, j) { return f[j * cols + i]; }
    function lerp(i1, j1, i2, j2) {
      var a = v(i1, j1), b = v(i2, j2), t = (iso - a) / ((b - a) || 1e-9);
      return [x0 + (i1 + (i2 - i1) * t) * cell, y0 + (j1 + (j2 - j1) * t) * cell];
    }
    for (var j = 0; j < rows - 1; j++) {
      for (var i = 0; i < cols - 1; i++) {
        var c = (v(i, j) > iso ? 8 : 0) | (v(i + 1, j) > iso ? 4 : 0) | (v(i + 1, j + 1) > iso ? 2 : 0) | (v(i, j + 1) > iso ? 1 : 0);
        if (c === 0 || c === 15) { continue; }
        var top = function () { return lerp(i, j, i + 1, j); }, right = function () { return lerp(i + 1, j, i + 1, j + 1); };
        var bottom = function () { return lerp(i, j + 1, i + 1, j + 1); }, left = function () { return lerp(i, j, i, j + 1); };
        switch (c) {
          case 1: case 14: segs.push([left(), bottom()]); break;
          case 2: case 13: segs.push([bottom(), right()]); break;
          case 3: case 12: segs.push([left(), right()]); break;
          case 4: case 11: segs.push([top(), right()]); break;
          case 6: case 9: segs.push([top(), bottom()]); break;
          case 7: case 8: segs.push([left(), top()]); break;
          case 5: segs.push([left(), top()]); segs.push([bottom(), right()]); break;
          case 10: segs.push([top(), right()]); segs.push([left(), bottom()]); break;
        }
      }
    }
    // Teilstücke zu Ringen verbinden
    function k(p) { return Math.round(p[0] * 10) + "," + Math.round(p[1] * 10); }
    var ends = {}, used = new Array(segs.length), loops = [];
    segs.forEach(function (s, idx) { [0, 1].forEach(function (e) { var kk = k(s[e]); (ends[kk] = ends[kk] || []).push(idx); }); });
    for (var s0 = 0; s0 < segs.length; s0++) {
      if (used[s0]) { continue; }
      used[s0] = true;
      var loop = [segs[s0][0], segs[s0][1]], cur = segs[s0][1], guard = 0;
      while (guard++ < segs.length) {
        var next = (ends[k(cur)] || []).filter(function (idx) { return !used[idx]; })[0];
        if (next === undefined) { break; }
        used[next] = true;
        var s = segs[next], p = k(s[0]) === k(cur) ? s[1] : s[0];
        loop.push(p); cur = p;
      }
      if (loop.length > 4) { loops.push(loop); }
    }
    return loops;
  }
  function drawGroup(g) {
    if (!g.path) { return; }
    var fs = Math.min(fontSize(), 16), pad = fs * 2.2, mine = {};  // stark herausgezoomt (Handy): Abstände begrenzen
    g.members.forEach(function (id) { mine[id] = true; });
    var members = g.members.map(function (id) { return byId[id]; });
    var mBoxes = members.map(function (n) { return nodeBox(n, fs); });
    var others = nodes.filter(function (n) { return !mine[n.id]; }).map(function (n) { return nodeBox(n, fs); });
    // Verbindungen: kürzester Baum (Prim) zwischen den Mitgliedern, jede Linie weicht fremden Firmen aus
    var lines = [], inTree = [0], rest = members.map(function (n, i) { return i; }).slice(1);
    while (rest.length) {
      var bi = -1, bj = -1, bd = Infinity;
      inTree.forEach(function (i) { rest.forEach(function (j) {
        var d = Math.hypot(members[i].x - members[j].x, members[i].y - members[j].y);
        if (d < bd) { bd = d; bi = i; bj = j; }
      }); });
      var path = route([members[bi].x, members[bi].y], [members[bj].x, members[bj].y], others, pad * 0.9, 0);
      for (var s = 0; s < path.length - 1; s++) { lines.push([path[s], path[s + 1]]); }
      inTree.push(bj); rest.splice(rest.indexOf(bj), 1);
    }
    // Rechenraster über dem Bereich der Gruppe
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    mBoxes.forEach(function (b) { x0 = Math.min(x0, b[0]); y0 = Math.min(y0, b[1]); x1 = Math.max(x1, b[2]); y1 = Math.max(y1, b[3]); });
    lines.forEach(function (l) { l.forEach(function (p) { x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]); }); });
    x0 -= pad * 1.5; y0 -= pad * 1.5; x1 += pad * 1.5; y1 += pad * 1.5;
    var cell = Math.max(fs * 0.5, Math.sqrt((x1 - x0) * (y1 - y0) / 14000));
    var cols = Math.ceil((x1 - x0) / cell) + 1, rows = Math.ceil((y1 - y0) / cell) + 1, f = new Float32Array(cols * rows);
    var near = others.filter(function (b) { return b[2] > x0 - pad && b[0] < x1 + pad && b[3] > y0 - pad && b[1] < y1 + pad; });
    for (var j = 0; j < rows; j++) {
      for (var i = 0; i < cols; i++) {
        if (i === 0 || j === 0 || i === cols - 1 || j === rows - 1) { f[j * cols + i] = -1; continue; }  // Rand immer außen → Ringe geschlossen
        var x = x0 + i * cell, y = y0 + j * cell, v = 0, d, q;
        for (q = 0; q < mBoxes.length; q++) { d = distBox(mBoxes[q], x, y); if (d < pad) { v += (1 - d / pad) * (1 - d / pad); } }
        for (q = 0; q < lines.length; q++) { d = distSeg(lines[q][0], lines[q][1], x, y); if (d < pad * 0.7) { v += 0.7 * (1 - d / (pad * 0.7)) * (1 - d / (pad * 0.7)); } }
        for (q = 0; q < near.length; q++) { d = distBox(near[q], x, y); if (d < pad) { v -= 2.5 * (1 - d / pad) * (1 - d / pad); } }
        f[j * cols + i] = v;
      }
    }
    var loops = contours(f, cols, rows, x0, y0, cell, 0.3), d = "", top = null;
    function inside(poly, x, y) {  // Punkt im Linienzug (Strahlverfahren)
      var c = false;
      for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
        var a = poly[i], b = poly[j];
        if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) { c = !c; }
      }
      return c;
    }
    // Nur Teile behalten, die eine Firma der Gruppe enthalten (Reste von Umweg-Linien fallen weg); Löcher bleiben
    var keep = loops.filter(function (l) { return members.some(function (n) { return inside(l, n.x, n.y); }); });
    loops = keep.concat(loops.filter(function (l) {
      return keep.indexOf(l) < 0 && keep.some(function (k) { return inside(k, l[0][0], l[0][1]); });
    }));
    loops.forEach(function (loop) {
      var pts = loop.filter(function (p, idx) { return idx % 2 === 0; });  // ausdünnen, dann weich verbinden
      if (pts.length < 3) { return; }
      function mid(a, b) { return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; }
      var st = mid(pts[pts.length - 1], pts[0]);
      d += "M" + st[0].toFixed(1) + "," + st[1].toFixed(1);
      pts.forEach(function (p, idx) {
        var m = mid(p, pts[(idx + 1) % pts.length]);
        d += " Q" + p[0].toFixed(1) + "," + p[1].toFixed(1) + " " + m[0].toFixed(1) + "," + m[1].toFixed(1);
        if (!top || p[1] < top[1]) { top = p; }
      });
      d += " Z";
    });
    g.path.setAttribute("d", d);
    if (!top) { g.label.setAttribute("x", "-9999"); return; }
    g.label.setAttribute("x", top[0].toFixed(1));
    g.label.setAttribute("y", (top[1] - fs * 0.35).toFixed(1));
    g.label.setAttribute("text-anchor", "middle");
  }
  // Auswahl: Nachbarn hervorheben und der Seite Bescheid geben (Infofenster rechts lädt die Infos)
  // Mit zweitem Thema (Hersteller × Artikelgruppe): nur diese beiden und ihre Verbindung hervorheben
  function select(n, quiet, second) {
    selected = n;
    pair = n && second ? [n, second] : null;
    drawPair();
    svg.classList.toggle("focus", !!n);
    var near = {};
    if (n && second) { near[n.id] = near[second.id] = true; }
    else if (n) { near[n.id] = true; n.links.forEach(function (e) { near[e.a] = near[e.b] = true; }); }
    nodes.forEach(function (x) { x.g.classList.toggle("hi", !!n && !!near[x.id]); x.g.classList.toggle("sel", !!n && (x === n || x === second)); });
    edges.forEach(function (e) {
      var on = !!n && !!(second ? near[e.a] && near[e.b] : e.a === n.id || e.b === n.id);
      e.line.classList.toggle("hi", on);
      if (e.text) { e.text.classList.toggle("hi", on); }
    });
    if (!quiet) { document.dispatchEvent(new CustomEvent("kb:pick", { detail: { id: n ? n.id : null, from: "map" } })); }
  }
  // Ins Bild holen, wenn das Thema außerhalb der Ansicht liegt
  function show(n) {
    var m = 60;
    if (n.x < view.x + m || n.x > view.x + view.w - m || n.y < view.y + m || n.y > view.y + view.h - m) {
      view.x = n.x - view.w / 2; view.y = n.y - view.h / 2; applyView();
    }
  }

  // ---------- Ansicht: Zoom, Verschieben, Knoten ziehen ----------
  function applyView() {
    svg.setAttribute("viewBox", [view.x, view.y, view.w, view.h].map(function (v) { return v.toFixed(1); }).join(" "));
    // Schrift auf dem Bildschirm etwa gleich groß halten (sonst winzig auf dem Handy, riesig beim Hineinzoomen)
    var k = view.w / Math.max(box.clientWidth, 1);
    svg.style.setProperty("--fs", Math.max(9, Math.min(13 * k, 34)).toFixed(1) + "px");
    groups.forEach(drawGroup);  // Abstand der Blase hängt vom Zoom ab
    drawBubbles();
  }
  function fit() {
    if (!box.clientWidth || !box.clientHeight) { return; }  // Karte verborgen: beim Anzeigen einpassen
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
    if (!drag || drag.bubble !== undefined) { return; }
    if (drag.pan) {
      var r = svg.getBoundingClientRect(), dx = (ev.clientX - drag.cx) / r.width * view.w, dy = (ev.clientY - drag.cy) / r.height * view.h;
      if (Math.abs(dx) + Math.abs(dy) > 2) { moved = true; }
      view.x = drag.vx - dx; view.y = drag.vy - dy; applyView();
    } else {
      var p = toSvg(ev);
      if (Math.abs(p.x - drag.start.x) + Math.abs(p.y - drag.start.y) > 3) { moved = true; }
      drag.node.x = drag.x + p.x - drag.start.x; drag.node.y = drag.y + p.y - drag.start.y; drag.node.pinned = drag.node.dragged = true;
      place();
    }
  });
  // Klick/Doppelklick selbst auswerten: der Zeiger ist am SVG festgehalten, Klicks erreichen die Kreise nicht
  var lastTap = { node: null, t: 0 };
  function pickEvent(id, keep) { document.dispatchEvent(new CustomEvent("kb:pick", { detail: { id: id, from: "map", keep: !!keep } })); }
  function endDrag() {
    if (drag && !moved && drag.bubble !== undefined) {
      var i = drag.bubble; drag = null; if (bub && bub.items[i]) { bubbleEvent(i, bub.items[i].g); } return;
    }
    if (drag && drag.bubble !== undefined) { drag = null; moved = false; return; }
    if (drag && !moved) {
      // Klick auf leere Fläche: alles abwählen; Klick auf einen Kreis: wählen bzw. (schon gewählt) nur ihn abwählen
      if (drag.pan) { if (connect.on) { setConnect(true); } else { pickEvent(null); } }
      else if (connect.on) { connectTap(drag.node); }
      else {
        var now = Date.now();
        if (lastTap.node === drag.node && now - lastTap.t < 400) { location.href = "/wissen/" + drag.node.id; return; }
        lastTap = { node: drag.node, t: now };
        pickEvent(drag.node.id);
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
    if (on) { select(null, true); }
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
  // Fenster: Bezugsregel (Satz zum Ausfüllen) und – wenn zwei Themen gewählt sind – Pflicht-Zubehör oder Hinweis
  function openDialog(a, b) {
    hint.hidden = true;
    dialog.textContent = "";
    var head = document.createElement("div"); head.className = "kb-connect-head";
    var title = document.createElement("b"); title.textContent = b ? a.name + " → " + b.name : "Bezugsregel für " + a.name;
    head.appendChild(title);
    if (b) {
      var swap = document.createElement("button"); swap.type = "button"; swap.className = "link"; swap.textContent = "⇄ umdrehen";
      swap.addEventListener("click", function () { openDialog(b, a); });
      head.appendChild(swap);
    }
    dialog.appendChild(head);
    function option(value, parts, checked) {
      var row = document.createElement("label"); row.className = "kb-connect-opt";
      var r = input({ type: "radio", name: "art", value: value }); if (checked) { r.checked = true; }
      row.appendChild(r);
      var span = document.createElement("span");
      parts.forEach(function (part) { span.appendChild(typeof part === "string" ? document.createTextNode(part) : part); });
      row.appendChild(span);
      dialog.appendChild(row);
      return r;
    }
    function bold(t) { var x = document.createElement("b"); x.textContent = t; return x; }
    var rule = a.rule || {};
    var moq = input({ type: "number", min: "1", max: "99999", name: "moq", value: rule.moq || a.moq || "", placeholder: "36", "aria-label": "Mindestmenge" });
    var stockLabel = document.createElement("label"); stockLabel.className = "kb-rule-check";
    var stock = input({ type: "checkbox", name: "lagerware", value: "1" }); stock.checked = !!rule.stock;
    stockLabel.appendChild(stock); stockLabel.appendChild(document.createTextNode(" oder wenn Lagerware"));
    var via = null;
    if (!b) {
      via = document.createElement("select"); via.name = "via"; via.setAttribute("aria-label", "Sonst bestellen bei");
      var none = document.createElement("option"); none.value = ""; none.textContent = "bitte wählen"; via.appendChild(none);
      data.nodes.filter(function (x) { return x.kind === "hersteller" && x.id !== a.id; })
        .sort(function (x, y) { return x.name.localeCompare(y.name); })
        .forEach(function (x) { var o = document.createElement("option"); o.value = x.id; o.textContent = x.name; if (rule.via === x.id) { o.selected = true; } via.appendChild(o); });
    }
    var ruleNote = input({ type: "text", name: "notiz", maxlength: "200", value: rule.note || "", placeholder: "Bemerkung, z. B. dort andere Kalkulation", "aria-label": "Bemerkung" });
    var canRule = a.kind === "hersteller";
    if (canRule && !b) { dialog.classList.add("single"); } else { dialog.classList.remove("single"); }
    if (canRule) {
      option("regel", ["Bezugsregel: bei ", bold(a.name), " bestellen ab ", moq, " Stück ", stockLabel, ". Sonst bestellen bei ",
                       b ? bold(b.name) : via, ".", ruleNote], true);
    }
    var qty, note;
    if (b) {
      qty = input({ type: "number", min: "1", max: "999", name: "menge", value: "1", "aria-label": "Stück" });
      note = input({ type: "text", name: "text", maxlength: "1000", placeholder: "z. B. gleiche Halter, austauschbar", "aria-label": "Hinweis" });
      if (a.kind === "hersteller" && b.kind === "hersteller") {
        option("konzern", ["Firmengruppe: ", bold(b.name), " ist Tochterfirma von ", bold(a.name)], false);
      }
      option("pflicht", [a.name + " braucht ", qty, " × " + b.name + " (Pflicht-Zubehör)"], !canRule);
      option("hinweis", ["Hinweis zu beiden: ", note], false);
    }
    if (!canRule && !b) { return; }
    var err = document.createElement("p"); err.className = "kb-connect-err"; err.hidden = true; dialog.appendChild(err);
    var row = document.createElement("div"); row.className = "kb-connect-actions";
    var ok = document.createElement("button"); ok.type = "submit"; ok.textContent = "Speichern";
    var cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "secondary"; cancel.textContent = "Abbrechen";
    cancel.addEventListener("click", function () { if (connect.on) { setConnect(true); } else { dialog.hidden = true; } });
    row.appendChild(ok); row.appendChild(cancel); dialog.appendChild(row);
    dialog.onsubmit = function (ev) {
      ev.preventDefault();
      var art = (dialog.querySelector("input[name=art]:checked") || {}).value, req;
      if (art === "regel") {
        if (!moq.value && !stock.checked) { err.textContent = "Mindestmenge eintragen oder „oder wenn Lagerware“ anhaken."; err.hidden = false; moq.focus(); return; }
        var target = b ? b.id : via.value;
        if (!target) { err.textContent = "Bitte wählen, bei wem sonst bestellt wird."; err.hidden = false; via.focus(); return; }
        req = send("/wissen/" + a.id + "/bezugsregel", { moq: moq.value, lagerware: stock.checked ? "1" : "", via: target, notiz: ruleNote.value });
      } else if (art === "konzern") {
        req = send("/wissen/" + a.id + "/firmengruppe", { tochter: b.id });
      } else if (art === "pflicht") {
        req = send("/wissen/" + a.id + "/feld/pflicht", { wert: b.id, menge: qty.value || 1 });
      } else if (art === "hinweis") {
        if (!note.value.trim()) { note.focus(); return; }
        req = send("/wissen/eintrag", { text: note.value, themen: [a.id, b.id] });
      } else { return; }
      ok.disabled = true;
      req.then(function () {
        setConnect(false); dialog.hidden = true; reload(a.id);
        pickEvent(a.id, true);  // Infofenster aktualisieren, Auswahl behalten
      })
        .catch(function (e) { err.textContent = e.message; err.hidden = false; ok.disabled = false; });
    };
    dialog.hidden = false;
    // Radio-Auswahl folgt dem Feld, in das man tippt
    if (!dialog.dataset.wired) dialog.addEventListener("focusin", function (ev) {
      var opt = ev.target.closest && ev.target.closest(".kb-connect-opt");
      if (opt && ev.target.type !== "radio") { opt.querySelector("input[type=radio]").checked = true; }
    });
    dialog.dataset.wired = "1";
    (canRule ? (moq.value ? (b ? ok : via) : moq) : qty).focus();
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
        // Positionen übernehmen, Layout mit der neuen Verbindung nachrechnen; selbst verschobene Kreise bleiben
        d.nodes.forEach(function (n) { var o = old[n.id]; if (o) { n.x = o.x; n.y = o.y; n.pinned = n.dragged = !!o.dragged; } });
        data = d;
        selected = null;
        build();
        if (byId[selectId]) { select(byId[selectId], true); }
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
  var groupBox = document.querySelector("[data-map-groups]");
  if (groupBox) { groupBox.addEventListener("change", function () { if (groupLayer) { groupLayer.style.display = showGroups() ? "" : "none"; } }); }
  window.addEventListener("resize", function () { if (box.clientWidth) { fit(); } });
  window.kbMap = {
    select: function (id, second) {
      var n = byId[id], m = byId[second] || null;
      select(n || null, true, m);
      if (!n || !box.clientWidth) { return; }
      if (m) {  // beide ins Bild: Ansicht auf die Mitte, notfalls herauszoomen
        var w = Math.max(view.w, Math.abs(m.x - n.x) * 1.6 + 200), h = w * view.h / view.w;
        if (Math.abs(m.y - n.y) * 1.6 + 160 > h) { h = Math.abs(m.y - n.y) * 1.6 + 160; w = h * view.w / view.h; }
        view = { x: (n.x + m.x) / 2 - w / 2, y: (n.y + m.y) / 2 - h / 2, w: w, h: h }; applyView();
      } else { show(n); }
    },
    show: function () { fit(); },
    ready: function () { return !!data; },
    // Blasen setzen: anchor = Punkt, um den sie stehen; from = Hersteller (Lücke Richtung Pfeil); items = Infos
    bubbles: function (anchor, from, items) {
      bub = anchor ? { anchor: anchor, from: from, items: items || [] } : null;
      svg.classList.toggle("bubbling", !!bub);  // übrige Karte fast ausblenden, nur Auswahl und Blasen zählen
      drawBubbles();
      if (bub) { frameBubbles(); }
    },
    // Gewählte Punkte in den freien Bereich [x0, x1] (Pixel im Kartenkasten) schieben, notfalls herauszoomen
    frame: function (ids, x0, x1) {
      var pts = ids.map(function (i) { return byId[i]; }).filter(Boolean);
      if (!pts.length || !box.clientWidth) { return; }
      var r = svg.getBoundingClientRect(), o = box.getBoundingClientRect(), off = r.left - o.left, k = view.w / r.width;
      var minX = Math.min.apply(null, pts.map(function (n) { return n.x; })) - 70, maxX = Math.max.apply(null, pts.map(function (n) { return n.x; })) + 70;
      var freeW = (x1 - x0) * k;
      if (freeW <= 0) { return; }
      if (maxX - minX > freeW) { var f = (maxX - minX) / freeW; zoom(1 / f, (minX + maxX) / 2, view.y + view.h / 2); k = view.w / r.width; freeW = (x1 - x0) * k; }
      var left = view.x + (x0 - off) * k, right = left + freeW;
      if (minX >= left && maxX <= right) { return; }
      view.x += ((minX + maxX) / 2) - (left + right) / 2;
      applyView();
    },
    // Punkt, von dem das Infofeld ausgeht: gewählter Kreis bzw. Mitte des Pfeils (Pixel relativ zum Kartenkasten)
    anchor: function (id, second) {
      var a = byId[id], b = byId[second];
      if (!a || !box.clientWidth) { return null; }
      var x = b ? (a.x + b.x) / 2 : a.x, y = b ? (a.y + b.y) / 2 : a.y, r = svg.getBoundingClientRect(), o = box.getBoundingClientRect();
      return { x: r.left - o.left + (x - view.x) / view.w * r.width, y: r.top - o.top + (y - view.y) / view.h * r.height,
               r: b ? 6 : (a.r || 12) * r.width / view.w };
    },  // Karte war verborgen (Reiter „Karte“): jetzt Größe kennen und einpassen
    reload: function (id) { if (data) { reload(id); } }
  };

  fetch("/api/wissen/karte", { credentials: "same-origin", headers: { Accept: "application/json" } })
    .then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.json(); })
    .then(function (d) {
      data = d; build();
    })
    .catch(function () { empty.textContent = "Karte konnte nicht geladen werden. Seite neu laden."; empty.hidden = false; });
})();

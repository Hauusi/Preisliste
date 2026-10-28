// Datenblatt: Drucken und Prüfung, ob eine Seite überläuft oder der Titel keinen Platz für den Balken lässt.
// Wird von der Druckansicht und vom Editor (Live-Vorschau) verwendet.
(function () {
  function check(doc, box) {
    if (!doc) { return []; }
    var full = [], longTitle = false;
    doc.querySelectorAll(".sheet").forEach(function (page) {
      var body = page.querySelector(".sheet-body");
      var over = body && body.scrollHeight > body.clientHeight + 2;
      page.classList.toggle("too-full", !!over);
      if (over) { full.push(page.getAttribute("data-page")); }
      var bar = page.querySelector(".head-bar");
      // Balken unter 10 mm: Titel läuft sonst aus der Seite (Breite unabhängig vom Zoom der Vorschau gemessen)
      if (bar && page.offsetWidth && bar.offsetWidth / page.offsetWidth * 210 < 10) { longTitle = true; }
    });
    var msgs = [];
    if (full.length) {
      msgs.push("Seite " + full.join(", ") + " ist zu voll und wird abgeschnitten (rot umrandet). " +
                "Text kürzen, Zeilen oder Bilder reduzieren oder einen Baustein mit „neue Seite“ beginnen.");
    }
    if (longTitle) {
      msgs.push("Der Titel ist zu lang für eine Zeile, der blaue Balken hat keinen Platz mehr. Titel kürzen " +
                "(Teile davon passen in den Untertitel).");
    }
    if (box) {
      box.textContent = "";
      msgs.forEach(function (m) { var p = document.createElement("p"); p.textContent = m; box.appendChild(p); });
      box.hidden = !msgs.length;
    }
    return msgs;
  }
  window.dsCheck = check;

  document.querySelectorAll("[data-print]").forEach(function (b) {
    b.addEventListener("click", function () { window.print(); });
  });
  if (document.body.classList.contains("ds-print")) {
    window.addEventListener("load", function () {
      check(document.querySelector(".ds-doc"), document.querySelector("[data-warnings]"));
    });
  }
})();

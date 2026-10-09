// Datenblatt-Vorschau: Drucken und Warnung, wenn eine Seite überläuft. Alles funktioniert auch ohne JavaScript.
(function () {
  document.querySelectorAll("[data-print]").forEach(function (b) {
    b.addEventListener("click", function () { window.print(); });
  });
  function check() {
    var full = [];
    document.querySelectorAll(".page").forEach(function (page) {
      var body = page.querySelector(".page-body");
      var over = body && body.scrollHeight > body.clientHeight + 2;
      page.classList.toggle("too-full", !!over);
      if (over) { full.push(page.getAttribute("data-page")); }
    });
    var msg = document.querySelector("[data-overflow-msg]");
    if (msg) {
      msg.hidden = !full.length;
      msg.querySelector("[data-overflow-pages]").textContent = full.join(", ");
    }
  }
  window.addEventListener("load", check);
})();

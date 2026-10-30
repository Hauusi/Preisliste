// Kopfleiste: Menü „Weitere“ schließen, wenn außerhalb geklickt oder Escape gedrückt wird.
(function () {
  var menu = document.querySelector("[data-nav-more]");
  if (!menu) { return; }
  document.addEventListener("click", function (e) {
    if (menu.open && !menu.contains(e.target)) { menu.open = false; }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && menu.open) { menu.open = false; menu.querySelector("summary").focus(); }
  });
})();

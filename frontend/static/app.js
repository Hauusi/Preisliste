// Kleine Komfortfunktionen. Alles funktioniert auch ohne JavaScript.
(function () {
  document.querySelectorAll("[data-file-input]").forEach(function (input) {
    var zone = input.closest(".dropzone");
    var label = zone && zone.querySelector("[data-file-label]");
    input.addEventListener("change", function () {
      if (label && input.files.length) { label.textContent = input.files[0].name; zone.classList.add("has-file"); }
    });
    ["dragenter", "dragover"].forEach(function (e) { input.addEventListener(e, function () { zone.classList.add("drag"); }); });
    ["dragleave", "drop"].forEach(function (e) { input.addEventListener(e, function () { zone.classList.remove("drag"); }); });
  });
})();
// Auswahlfelder mit data-autosubmit laden die Prüfseite mit der neuen Auswahl neu
(function () {
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { el.form.submit(); });
  });
})();

// Laufender Job: nur Status, Fortschritt und Meldung nachladen statt die ganze Seite neu zu laden.
// Ist der Job fertig, wird die Seite einmal neu geladen (Ergebnis, Links, automatische Weiterleitung).
(function () {
  var box = document.querySelector("[data-job-poll]");
  if (!box) return;
  var id = box.getAttribute("data-job-poll");
  var status = box.querySelector("[data-job-status]");
  var bar = box.querySelector("[data-job-bar]");
  var count = box.querySelector("[data-job-count]");
  var message = box.querySelector("[data-job-message]");

  function poll() {
    fetch("/api/jobs/" + id, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (j) {
        if (j.status !== "WARTEND" && j.status !== "LAEUFT") { location.reload(); return; }
        if (status) status.textContent = j.status;
        if (bar && j.gesamt) { bar.max = j.gesamt; bar.value = j.fortschritt || 0; }
        if (count) count.textContent = j.gesamt ? (j.fortschritt || 0) + " / " + j.gesamt : "";
        if (message) message.textContent = j.meldung || "";
        setTimeout(poll, 2000);
      })
      .catch(function () { setTimeout(poll, 5000); });  // Netzfehler: später erneut versuchen
  }
  setTimeout(poll, 2000);
})();

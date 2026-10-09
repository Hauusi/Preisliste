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
// Felder nur zeigen, wenn eine Auswahl passt (z. B. Händlerrabatt nur bei UVP, Kurs nur bei Fremdwährung)
(function () {
  document.querySelectorAll("[data-toggle-target]").forEach(function (sel) {
    var target = document.getElementById(sel.getAttribute("data-toggle-target"));
    var want = sel.getAttribute("data-toggle-value");
    function update() {
      var show = want.charAt(0) === "!" ? sel.value !== want.slice(1) : sel.value === want;
      if (target) { target.hidden = !show; }
    }
    sel.addEventListener("change", update);
    update();
  });
})();
// Eingabe sofort in eine Vorschau übernehmen (z. B. Datenblatt-Kopfzeile), leer = Beispieltext
(function () {
  document.querySelectorAll("[data-live]").forEach(function (input) {
    var target = document.querySelector(input.getAttribute("data-live"));
    if (!target) { return; }
    input.addEventListener("input", function () {
      target.textContent = input.value.trim() || input.getAttribute("data-live-default") || "";
    });
  });
})();
// Datenblatt-Eigenschaften: verschieben (Ziehen am Griff oder Pfeiltasten), ein-/ausblenden, entfernen, hinzufügen
(function () {
  var list = document.querySelector("[data-props]");
  if (!list) { return; }
  var dragged = null;

  function setVisible(row, on) {
    row.classList.toggle("off", !on);
    row.querySelector("input[name=e_sichtbar]").value = on ? "1" : "0";
    var btn = row.querySelector("[data-toggle-visible]");
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.title = on ? "Ausblenden" : "Einblenden";
  }
  function rowAfter(y) {
    var rows = Array.prototype.filter.call(list.querySelectorAll("[data-prop]"), function (r) { return r !== dragged; });
    for (var i = 0; i < rows.length; i++) {
      var box = rows[i].getBoundingClientRect();
      if (y < box.top + box.height / 2) { return rows[i]; }
    }
    return null;
  }

  list.addEventListener("click", function (e) {
    var row = e.target.closest("[data-prop]");
    if (!row) { return; }
    if (e.target.closest("[data-toggle-visible]")) { setVisible(row, row.classList.contains("off")); }
    if (e.target.closest("[data-remove-prop]")) { row.remove(); }
  });
  // Ziehen nur am Griff, damit Text in den Feldern markierbar bleibt
  list.addEventListener("pointerdown", function (e) {
    var row = e.target.closest("[data-prop]");
    if (row) { row.draggable = !!e.target.closest("[data-grip]"); }
  });
  list.addEventListener("dragstart", function (e) {
    dragged = e.target.closest("[data-prop]");
    if (!dragged) { return; }
    dragged.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", "");
  });
  list.addEventListener("dragover", function (e) {
    if (!dragged) { return; }
    e.preventDefault();
    var after = rowAfter(e.clientY);
    if (after) { list.insertBefore(dragged, after); } else { list.appendChild(dragged); }
  });
  list.addEventListener("drop", function (e) { e.preventDefault(); });
  list.addEventListener("dragend", function () {
    if (dragged) { dragged.classList.remove("dragging"); dragged.draggable = false; }
    dragged = null;
  });
  list.addEventListener("keydown", function (e) {
    var grip = e.target.closest("[data-grip]");
    if (!grip || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) { return; }
    e.preventDefault();
    var row = grip.closest("[data-prop]");
    if (e.key === "ArrowUp" && row.previousElementSibling) { list.insertBefore(row, row.previousElementSibling); }
    if (e.key === "ArrowDown" && row.nextElementSibling) { list.insertBefore(row.nextElementSibling, row); }
    grip.focus();
  });

  var tpl = document.querySelector("[data-prop-template]");
  var newName = document.querySelector("[data-new-name]");
  var newValue = document.querySelector("[data-new-value]");
  function add() {
    var name = newName.value.trim();
    if (!name && !newValue.value.trim()) { newName.focus(); return; }
    var row = tpl.content.firstElementChild.cloneNode(true);
    row.querySelector("input[name=e_name]").value = name;
    row.querySelector("input[name=e_wert]").value = newValue.value.trim();
    list.appendChild(row);
    newName.value = ""; newValue.value = "";
    row.querySelector("input[name=e_wert]").focus();
  }
  document.querySelector("[data-add-prop]").addEventListener("click", add);
  [newName, newValue].forEach(function (input) {
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); add(); } });
  });
})();

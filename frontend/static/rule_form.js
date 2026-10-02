// Regel-Editor: nur die Felder des gewählten Schritttyps anzeigen, Schritte hinzufügen/entfernen.
// Ohne JavaScript bleiben alle Felder sichtbar und das Formular funktioniert trotzdem.
(function () {
  var box = document.getElementById("steps");
  if (!box) return;
  var help = JSON.parse(box.dataset.help || "{}");
  var labels = JSON.parse(box.dataset.labels || "{}");
  var addBtn = document.getElementById("add-step");

  function update(step) {
    var type = step.querySelector(".step-type").value;
    step.classList.toggle("empty", !type);
    step.querySelectorAll("[data-for]").forEach(function (el) {
      el.hidden = !type || el.dataset.for.split(" ").indexOf(type) < 0;
    });
    step.querySelector(".f-value").hidden = !type;
    step.querySelector(".f-label").hidden = !type;
    step.querySelector(".value-label").textContent = labels[type] || "Wert";
    step.querySelector(".step-help").textContent = help[type] || "";
  }

  function refreshAdd() {
    addBtn.hidden = !box.querySelector(".step.spare");
  }

  box.querySelectorAll(".step").forEach(function (step) {
    var select = step.querySelector(".step-type");
    select.addEventListener("change", function () { update(step); });
    step.querySelector(".step-remove").addEventListener("click", function () {
      select.value = "";
      step.querySelectorAll("input").forEach(function (i) { i.value = ""; });
      update(step);
    });
    update(step);
  });
  box.classList.add("js");
  addBtn.addEventListener("click", function () {
    var next = box.querySelector(".step.spare");
    if (next) { next.classList.remove("spare"); next.querySelector(".step-type").focus(); }
    refreshAdd();
  });
  refreshAdd();
})();

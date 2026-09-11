// Wires the Class Standing / Major Examination weighting presets.
//
// The server is the authority: SubjectForm.clean() applies the preset and
// rejects any custom pair that does not add up to 100. Everything here is
// convenience only, so the form still behaves correctly with JS disabled.
(function () {
  "use strict";

  var PRESETS = { "70_30": [70, 30], "60_40": [60, 40] };

  var csInput = document.getElementById("f-csps");
  var meInput = document.getElementById("f-meps");
  var customBlock = document.getElementById("custom-shares");
  var hint = document.getElementById("share-total-hint");
  var radios = document.querySelectorAll("[data-share-preset]");

  if (!csInput || !meInput || !radios.length) return;

  function selected() {
    for (var i = 0; i < radios.length; i++) {
      if (radios[i].checked) return radios[i].value;
    }
    return "custom";
  }

  function round2(n) {
    return Math.round(n * 100) / 100;
  }

  function updateHint() {
    if (!hint) return;
    if (selected() !== "custom") {
      hint.textContent = "";
      return;
    }
    var total = round2(parseFloat(csInput.value || 0) + parseFloat(meInput.value || 0));
    if (isNaN(total)) {
      hint.textContent = "";
    } else if (total === 100) {
      hint.textContent = "Adds up to 100%.";
      hint.classList.remove("form-error");
    } else {
      hint.textContent = "These add up to " + total + "%. They must add up to 100%.";
      hint.classList.add("form-error");
    }
  }

  function apply() {
    var choice = selected();
    var isCustom = choice === "custom";

    if (customBlock) customBlock.hidden = !isCustom;
    csInput.readOnly = !isCustom;
    meInput.readOnly = !isCustom;

    if (!isCustom && PRESETS[choice]) {
      csInput.value = PRESETS[choice][0];
      meInput.value = PRESETS[choice][1];
    }
    updateHint();
  }

  // In a custom split the two shares are not independent: naming one fixes
  // the other. Auto-filling the counterpart removes the most common way to
  // submit an invalid pair.
  function mirror(source, target) {
    source.addEventListener("input", function () {
      if (selected() !== "custom") return;
      var value = parseFloat(source.value);
      if (!isNaN(value) && value >= 0 && value <= 100) {
        target.value = round2(100 - value);
      }
      updateHint();
    });
  }

  for (var i = 0; i < radios.length; i++) {
    radios[i].addEventListener("change", apply);
  }
  mirror(csInput, meInput);
  mirror(meInput, csInput);
  apply();
})();
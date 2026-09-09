(function () {
  "use strict";

  var PERIODS = ["prelim", "midterm", "final"];
  var GRADE_TABLE = [
    [97, "1.00"], [94, "1.25"], [91, "1.50"], [88, "1.75"], [85, "2.00"],
    [82, "2.25"], [79, "2.50"], [76, "2.75"], [75, "3.00"],
  ];

  function numOrNull(value) {
    if (value === null || value === undefined) return null;
    var trimmed = String(value).trim();
    if (trimmed === "") return null;
    var n = parseFloat(trimmed);
    return isNaN(n) ? null : n;
  }

  function gradeFromTransmuted(tv) {
    for (var i = 0; i < GRADE_TABLE.length; i++) {
      if (tv >= GRADE_TABLE[i][0]) return GRADE_TABLE[i][1];
    }
    return "5.00";
  }

  function addRow(prefix) {
    var template = document.getElementById("cs-row-template");
    var tbody = document.getElementById("cs-rows-" + prefix);
    if (!template || !tbody) return;
    var html = template.innerHTML.split("__PREFIX__").join(prefix);
    var wrapper = document.createElement("tbody");
    wrapper.innerHTML = html.trim();
    var row = wrapper.firstElementChild;
    tbody.appendChild(row);
    row.addEventListener("input", recalculate);
    row.querySelector(".remove-row-btn").addEventListener("click", function () {
      row.remove();
      recalculate();
    });
    return row;
  }

  function computeGrade(form) {
    var passingAverage = numOrNull(form.passing_average.value);
    var csps = numOrNull(form.class_standing_percent_share.value);
    var meps = numOrNull(form.major_exam_percent_share.value);

    var csScoreSum = 0, csHpsSum = 0, csHasEntry = false;
    var meWeightedSum = 0, meWeightTotal = 0, meHasEntry = false;

    PERIODS.forEach(function (prefix) {
      var tbody = document.getElementById("cs-rows-" + prefix);
      if (tbody) {
        tbody.querySelectorAll("tr").forEach(function (row) {
          var score = numOrNull(row.querySelector(".row-score").value);
          var hps = numOrNull(row.querySelector(".row-hps").value);
          if (score !== null) {
            csHasEntry = true;
            csScoreSum += score;
            csHpsSum += (hps !== null ? hps : 100);
          }
        });
      }
      var examScore = numOrNull(form[prefix + "_exam_score"].value);
      var examHps = numOrNull(form[prefix + "_exam_hps"].value);
      var weight = numOrNull(form[prefix + "_exam_weight"].value);
      if (weight === null) weight = 33.33;
      if (examScore !== null) {
        meHasEntry = true;
        var pct = (examHps && examHps > 0) ? (examScore / examHps * 100) : 0;
        meWeightedSum += weight * pct;
        meWeightTotal += weight;
      }
    });

    var csa = (csHasEntry && csHpsSum > 0) ? (csScoreSum / csHpsSum * 100) : 0;
    var mea = (meHasEntry && meWeightTotal > 0) ? (meWeightedSum / meWeightTotal) : 0;

    var ca;
    if (csHasEntry && meHasEntry) {
      ca = ((csps || 0) / 100) * csa + ((meps || 0) / 100) * mea;
    } else if (csHasEntry) {
      ca = csa;
    } else if (meHasEntry) {
      ca = mea;
    } else {
      ca = 0;
    }

    var tv = null, grade = null;
    if (passingAverage !== null && passingAverage < 100) {
      var raw = ((ca - passingAverage) * 25) / (100 - passingAverage) + 75;
      tv = Math.floor(raw);
      grade = gradeFromTransmuted(tv);
    }

    return { csa: csa, mea: mea, ca: ca, tv: tv, grade: grade, csHasEntry: csHasEntry, meHasEntry: meHasEntry };
  }

  function fmt(value) {
    return value.toFixed(2) + "%";
  }

  function recalculate() {
    var form = document.getElementById("subject-form");
    if (!form) return;
    var result = computeGrade(form);
    document.getElementById("pv-csa").textContent = result.csHasEntry ? fmt(result.csa) : "—";
    document.getElementById("pv-mea").textContent = result.meHasEntry ? fmt(result.mea) : "—";
    document.getElementById("pv-ca").textContent = (result.csHasEntry || result.meHasEntry) ? fmt(result.ca) : "—";
    document.getElementById("pv-tv").textContent = result.tv !== null ? result.tv : "—";
    document.getElementById("pv-grade").textContent = result.grade !== null ? result.grade : "—";
  }

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("subject-form");
    if (!form) return;

    document.querySelectorAll("[data-add-row]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        addRow(btn.getAttribute("data-add-row"));
        recalculate();
      });
    });

    PERIODS.forEach(function (prefix) {
      addRow(prefix);
    });

    form.addEventListener("input", recalculate);
    recalculate();
  });
})();

(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("ai-assistant-form");
    var input = document.getElementById("ai-question-input");
    if (!form || !input) return;

    document.querySelectorAll(".ai-quick-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        input.value = btn.getAttribute("data-question") || "";
        if (form.requestSubmit) {
          form.requestSubmit();
        } else {
          form.submit();
        }
      });
    });
  });
})();

// Mobile sidebar + assistant question box.
//
// The assistant is a modal over the current page, so the background stays
// visible (blurred) behind it and closing returns the student exactly where
// they were.
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  ready(function () {
    var modal = document.querySelector("[data-ai-modal]");
    var openers = document.querySelectorAll("[data-ai-open]");
    var input = document.getElementById("ai-question-input");
    var form = document.getElementById("ai-assistant-form");

    function setOpen(open) {
      if (!modal) return;
      modal.hidden = !open;
      document.body.classList.toggle("ai-modal-open", open);
      openers.forEach(function (b) { b.setAttribute("aria-expanded", String(open)); });
      if (open && input) input.focus();
    }

    openers.forEach(function (b) {
      b.addEventListener("click", function () { setOpen(modal && modal.hidden); });
    });
    document.querySelectorAll("[data-ai-close]").forEach(function (b) {
      b.addEventListener("click", function () { setOpen(false); });
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && modal && !modal.hidden) setOpen(false);
    });

    // Arriving from the modal's subject picker: open straight away rather
    // than making the student click the launcher a second time.
    if (modal && window.location.search.indexOf("ask=1") !== -1) setOpen(true);

    document.querySelectorAll(".ai-quick-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!input || !form) return;
        input.value = btn.getAttribute("data-question") || "";
        if (form.requestSubmit) form.requestSubmit();
        else form.submit();
      });
    });

    // Enter sends; Shift+Enter makes a new line.
    if (input && form) {
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          if (input.value.trim()) {
            if (form.requestSubmit) form.requestSubmit();
            else form.submit();
          }
        }
      });
      form.addEventListener("htmx:afterRequest", function () { input.value = ""; });
    }

    var sidebar = document.querySelector("[data-sidebar]");
    var toggle = document.querySelector("[data-sidebar-toggle]");
    var scrim = document.querySelector("[data-sidebar-scrim]");

    function setNav(open) {
      if (!sidebar) return;
      sidebar.classList.toggle("is-open", open);
      if (scrim) scrim.hidden = !open;
      if (toggle) toggle.setAttribute("aria-expanded", String(open));
    }

    if (toggle) toggle.addEventListener("click", function () {
      setNav(!sidebar.classList.contains("is-open"));
    });
    if (scrim) scrim.addEventListener("click", function () { setNav(false); });
  });
})();
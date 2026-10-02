// sbobina · toggletip dismissal.
// CSS shows the bubble on hover and focus; Escape must hide it without
// moving focus or the pointer (WCAG 1.4.13). The dismissal lasts until the
// pointer or focus leaves, so the next visit shows the help again.
(function () {
  "use strict";

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") {
      return;
    }
    document.querySelectorAll(".toggletip").forEach(function (tip) {
      if (tip.matches(":hover") || tip.contains(document.activeElement)) {
        tip.classList.add("toggletip--dismissed");
      }
    });
  });

  function reset(event) {
    var tip = event.target.closest && event.target.closest(".toggletip");
    if (tip && !tip.contains(event.relatedTarget)) {
      tip.classList.remove("toggletip--dismissed");
    }
  }

  document.addEventListener("mouseout", reset);
  document.addEventListener("focusout", reset);
})();

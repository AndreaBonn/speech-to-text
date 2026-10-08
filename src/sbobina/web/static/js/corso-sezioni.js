// sbobina · course section bar (C1): the sticky row of anchors marks the
// last section whose top has scrolled up to the bar. The links work without
// this script; it only adds the "you are here" state.
(function () {
  "use strict";

  var bar = document.getElementById("corsi-sections");
  if (!bar) {
    return;
  }
  var links = Array.prototype.slice.call(bar.querySelectorAll("a[href^='#']"));
  // How far below the bar a section top may sit and still count as reached.
  var REACHED_SLACK_PX = 16;
  var pending = false;

  function markCurrent() {
    pending = false;
    var line = bar.getBoundingClientRect().bottom + REACHED_SLACK_PX;
    var current = null;
    links.forEach(function (link) {
      var section = document.getElementById(link.hash.slice(1));
      if (section && section.offsetParent !== null && section.getBoundingClientRect().top <= line) {
        current = link;
      }
    });
    links.forEach(function (link) {
      var isCurrent = link === current;
      link.classList.toggle("is-active", isCurrent);
      if (isCurrent) {
        link.setAttribute("aria-current", "location");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  }

  function schedule() {
    if (!pending) {
      pending = true;
      window.requestAnimationFrame(markCurrent);
    }
  }

  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  schedule();
})();

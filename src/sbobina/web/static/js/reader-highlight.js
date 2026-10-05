// sbobina · reader word highlight: marks the word under the audio time and
// keeps it in view unless the student scrolled by hand in the last moment.
// Split out of reader.js (F59). Words are kept in chronological order, so the
// current one is found by binary search on a 15-20k word lecture.
(function () {
  "use strict";

  var MANUAL_SCROLL_QUIET_MS = 1200;
  var TOP_MARGIN_PX = 72;
  var BOTTOM_MARGIN_PX = 96;

  function create() {
    var words = []; // flat, chronological: [{start, end, el}]
    var currentWordEl = null;
    var lastManualScrollAt = 0;

    ["wheel", "touchmove"].forEach(function (eventName) {
      window.addEventListener(
        eventName,
        function () {
          lastManualScrollAt = Date.now();
        },
        { passive: true }
      );
    });

    function findIndex(time) {
      var lo = 0;
      var hi = words.length - 1;
      var result = -1;
      while (lo <= hi) {
        var mid = (lo + hi) >> 1;
        if (words[mid].start <= time) {
          result = mid;
          lo = mid + 1;
        } else {
          hi = mid - 1;
        }
      }
      return result;
    }

    function keepInView(el) {
      if (Date.now() - lastManualScrollAt < MANUAL_SCROLL_QUIET_MS) {
        return;
      }
      var rect = el.getBoundingClientRect();
      if (rect.top < TOP_MARGIN_PX || rect.bottom > window.innerHeight - BOTTOM_MARGIN_PX) {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }

    function highlight(time) {
      var index = findIndex(time);
      var match = index >= 0 && time <= words[index].end ? words[index] : null;
      var nextEl = match ? match.el : null;
      if (nextEl === currentWordEl) {
        return;
      }
      if (currentWordEl) {
        currentWordEl.classList.remove("word--current");
      }
      if (nextEl) {
        nextEl.classList.add("word--current");
        keepInView(nextEl);
      }
      currentWordEl = nextEl;
    }

    return {
      reset: function () {
        words = [];
        currentWordEl = null;
      },
      add: function (word) {
        words.push(word);
      },
      highlight: highlight,
    };
  }

  window.SbobinaReaderHighlight = { create: create };
})();

// sbobina · S3: on a phone the rail is one scrolling row. Bring the current
// page into view and drop the edge fade once the row is scrolled to the end.
(function () {
  "use strict";

  var scroller = document.querySelector(".rail__scroll");
  if (!scroller) {
    return;
  }

  function markEnd() {
    var atEnd = scroller.scrollLeft + scroller.clientWidth >= scroller.scrollWidth - 1;
    scroller.classList.toggle("rail__scroll--end", atEnd);
  }

  var active = scroller.querySelector("[aria-current='page']");
  if (active) {
    var row = scroller.getBoundingClientRect();
    var item = active.getBoundingClientRect();
    if (item.left < row.left || item.right > row.right) {
      scroller.scrollLeft += item.left - row.left - (row.width - item.width) / 2;
    }
  }
  scroller.addEventListener("scroll", markEnd, { passive: true });
  window.addEventListener("resize", markEnd);
  markEnd();
})();

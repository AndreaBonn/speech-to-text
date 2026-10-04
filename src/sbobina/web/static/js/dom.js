// sbobina · DOM helpers shared by the list pages (courses, search, study).
// Everything is built with createElement/textContent, never innerHTML with
// data: course labels, file names and LLM output come from outside the code
// and must never reach the DOM as markup.
(function () {
  "use strict";

  function clearChildren(el) {
    while (el.firstChild) {
      el.removeChild(el.firstChild);
    }
  }

  function textCell(text, label) {
    var td = document.createElement("td");
    td.setAttribute("data-label", label);
    td.textContent = text;
    return td;
  }

  function showSkeleton(tbody, columns) {
    clearChildren(tbody);
    for (var i = 0; i < 3; i++) {
      var row = document.createElement("tr");
      var td = document.createElement("td");
      td.colSpan = columns;
      var skeleton = document.createElement("div");
      skeleton.className = "skeleton-row";
      td.appendChild(skeleton);
      row.appendChild(td);
      tbody.appendChild(row);
    }
  }

  function clearStatus(el) {
    el.hidden = true;
    clearChildren(el);
  }

  function showRetryStatus(el, message, retry) {
    clearChildren(el);
    el.hidden = false;
    var wrapper = document.createElement("div");
    wrapper.className = "queue__error";
    var span = document.createElement("span");
    span.textContent = message;
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--secondary";
    button.textContent = "Riprova";
    button.addEventListener("click", retry);
    wrapper.appendChild(span);
    wrapper.appendChild(button);
    el.appendChild(wrapper);
  }

  function renderPagination(el, meta, onPage) {
    clearChildren(el);
    if (meta.total_pages <= 1) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
    var count = document.createElement("span");
    count.className = "pagination__count";
    count.textContent =
      "Pagina " +
      meta.page +
      " di " +
      meta.total_pages +
      " · " +
      meta.total +
      " totali";
    var pages = document.createElement("div");
    pages.className = "pagination__pages";
    for (var i = 1; i <= meta.total_pages; i++) {
      pages.appendChild(paginationButton(i, meta.page, onPage));
    }
    el.appendChild(count);
    el.appendChild(pages);
  }

  function paginationButton(page, currentPage, onPage) {
    var button = document.createElement("button");
    button.type = "button";
    button.className =
      "pagination__page" + (page === currentPage ? " is-active" : "");
    button.textContent = String(page);
    if (page === currentPage) {
      button.setAttribute("aria-current", "page");
    }
    button.addEventListener("click", function () {
      onPage(page);
    });
    return button;
  }

  // Same rule as jobTitle() in corso-dettaglio.js/storico.js/jobs.js so a lecture
  // is never called something different on two pages.
  function jobTitle(job) {
    if (job.source_name) {
      return job.source_name;
    }
    var subject = job.config && job.config.subject;
    if (subject) {
      return subject;
    }
    var created = new Date(job.created_at).toLocaleDateString("it-IT");
    return "Lezione del " + created;
  }

  function formatTime(seconds) {
    var total = Math.floor(seconds);
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = String(total % 60).padStart(2, "0");
    return h > 0 ? h + ":" + String(m).padStart(2, "0") + ":" + s : m + ":" + s;
  }

  window.SbobinaDom = {
    jobTitle: jobTitle,
    formatTime: formatTime,
    clearChildren: clearChildren,
    textCell: textCell,
    showSkeleton: showSkeleton,
    clearStatus: clearStatus,
    showRetryStatus: showRetryStatus,
    renderPagination: renderPagination,
  };
})();

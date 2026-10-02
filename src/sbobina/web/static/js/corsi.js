// sbobina · courses: group of lectures by course, with a per-course lecture
// list. State lives in the URL (?corso=<key>) so the detail view is a
// shareable link and the browser back button works without reloading.
(function () {
  "use strict";

  var COURSES_URL = "/api/v1/courses";
  var JOBS_URL = "/api/v1/jobs";
  var PER_PAGE = 20;
  // Mirrors UNCATEGORIZED_COURSE_KEY/LABEL in src/sbobina/courses.py.
  var UNCATEGORIZED_KEY = "";
  var UNCATEGORIZED_LABEL = "Senza corso";
  var STATUS_LABELS = {
    queued: "In coda",
    running: "In corso",
    done: "Completata",
    failed: "Errore",
    cancelled: "Annullata",
    interrupted: "Interrotta",
  };

  var listEl = document.getElementById("corsi-list");
  var listStatusEl = document.getElementById("corsi-list-status");
  var listTbody = document.getElementById("corsi-list-tbody");
  var listEmptyEl = document.getElementById("corsi-list-empty");
  var listPaginationEl = document.getElementById("corsi-list-pagination");

  var detailEl = document.getElementById("corsi-detail");
  var detailTitleEl = document.getElementById("corsi-detail-title");
  var detailStatusEl = document.getElementById("corsi-detail-status");
  var detailTbody = document.getElementById("corsi-detail-tbody");
  var detailEmptyEl = document.getElementById("corsi-detail-empty");
  var detailPaginationEl = document.getElementById("corsi-detail-pagination");
  var backLink = document.getElementById("corsi-detail-back");

  var listPage = 1;
  var detailPage = 1;
  var currentCourseKey = null;
  var labelsByKey = {};

  // ---------- DOM helpers (textContent/createElement only, never innerHTML
  // with data: course labels and job titles come from users and must never
  // reach the DOM as markup) ----------

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

  // Mirrors jobTitle() in storico.js/jobs.js so a lecture is never called
  // something different on two pages.
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

  // ---------- URL state ----------

  function courseKeyFromUrl() {
    var params = new URLSearchParams(window.location.search);
    return params.has("corso") ? params.get("corso") : null;
  }

  function pushCourseUrl(key) {
    var url = new URL(window.location.href);
    url.searchParams.set("corso", key);
    window.history.pushState({}, "", url.toString());
  }

  function pushListUrl() {
    window.history.pushState({}, "", "/corsi");
  }

  // ---------- list view ----------

  function renderListRow(course) {
    var row = document.createElement("tr");
    row.setAttribute("data-course-key", course.key);

    var nameCell = document.createElement("td");
    nameCell.className = "cell-name";
    nameCell.setAttribute("data-label", "Corso");
    var link = document.createElement("a");
    link.href = "/corsi?corso=" + encodeURIComponent(course.key);
    link.textContent = course.label;
    link.addEventListener("click", function (event) {
      event.preventDefault();
      pushCourseUrl(course.key);
      showDetail(course.key, course.label);
    });
    nameCell.appendChild(link);
    row.appendChild(nameCell);

    row.appendChild(textCell(String(course.lecture_count), "Lezioni"));
    row.appendChild(
      textCell(
        new Date(course.last_lecture_at).toLocaleDateString("it-IT"),
        "Ultima lezione"
      )
    );
    return row;
  }

  function cacheLabels(courses) {
    courses.forEach(function (course) {
      labelsByKey[course.key] = course.label;
    });
    if (
      currentCourseKey !== null &&
      Object.prototype.hasOwnProperty.call(labelsByKey, currentCourseKey)
    ) {
      detailTitleEl.textContent = labelsByKey[currentCourseKey];
    }
  }

  function loadList(page) {
    listPage = page;
    clearStatus(listStatusEl);
    listEmptyEl.hidden = true;
    showSkeleton(listTbody, 3);
    fetch(COURSES_URL + "?page=" + page + "&per_page=" + PER_PAGE)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("corsi fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        cacheLabels(body.data);
        if (body.data.length === 0) {
          clearChildren(listTbody);
          listPaginationEl.hidden = true;
          if (page === 1) {
            listEmptyEl.hidden = false;
          }
          return;
        }
        clearChildren(listTbody);
        body.data.forEach(function (course) {
          listTbody.appendChild(renderListRow(course));
        });
        renderPagination(listPaginationEl, body.meta, loadList);
      })
      .catch(function () {
        clearChildren(listTbody);
        showRetryStatus(listStatusEl, "Impossibile caricare i corsi.", function () {
          loadList(listPage);
        });
      });
  }

  // ---------- detail view ----------

  function renderDetailRow(job) {
    var row = document.createElement("tr");
    row.setAttribute("data-job-id", job.id);

    var nameCell = document.createElement("td");
    nameCell.className = "cell-name";
    nameCell.setAttribute("data-label", "Lezione");
    if (job.status === "done") {
      var link = document.createElement("a");
      link.href = "/lettore/" + job.id;
      link.textContent = jobTitle(job);
      nameCell.appendChild(link);
    } else {
      nameCell.textContent = jobTitle(job);
    }
    row.appendChild(nameCell);

    row.appendChild(
      textCell(new Date(job.created_at).toLocaleString("it-IT"), "Data")
    );
    // Not exposed by the job record yet: no duration field to show.
    row.appendChild(textCell("—", "Durata"));

    var statusCell = document.createElement("td");
    statusCell.setAttribute("data-label", "Stato");
    var badge = document.createElement("span");
    badge.className = "badge badge--" + job.status;
    badge.textContent = STATUS_LABELS[job.status];
    statusCell.appendChild(badge);
    row.appendChild(statusCell);

    return row;
  }

  function loadDetail(key, page) {
    detailPage = page;
    clearStatus(detailStatusEl);
    detailEmptyEl.hidden = true;
    showSkeleton(detailTbody, 4);
    fetch(
      JOBS_URL +
        "?course=" +
        encodeURIComponent(key) +
        "&page=" +
        page +
        "&per_page=" +
        PER_PAGE
    )
      .then(function (response) {
        if (!response.ok) {
          throw new Error("corso jobs fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (body.data.length === 0) {
          clearChildren(detailTbody);
          detailPaginationEl.hidden = true;
          if (page === 1) {
            detailEmptyEl.hidden = false;
          }
          return;
        }
        clearChildren(detailTbody);
        body.data.forEach(function (job) {
          detailTbody.appendChild(renderDetailRow(job));
        });
        renderPagination(detailPaginationEl, body.meta, function (nextPage) {
          loadDetail(key, nextPage);
        });
      })
      .catch(function () {
        clearChildren(detailTbody);
        showRetryStatus(
          detailStatusEl,
          "Impossibile caricare le lezioni del corso.",
          function () {
            loadDetail(key, detailPage);
          }
        );
      });
  }

  function labelFor(key, knownLabel) {
    if (knownLabel) {
      return knownLabel;
    }
    if (Object.prototype.hasOwnProperty.call(labelsByKey, key)) {
      return labelsByKey[key];
    }
    return key === UNCATEGORIZED_KEY ? UNCATEGORIZED_LABEL : "Corso";
  }

  function showDetail(key, knownLabel) {
    currentCourseKey = key;
    if (knownLabel) {
      labelsByKey[key] = knownLabel;
    }
    listEl.hidden = true;
    detailEl.hidden = false;
    detailTitleEl.textContent = labelFor(key, knownLabel);
    loadDetail(key, 1);
  }

  function showList() {
    currentCourseKey = null;
    detailEl.hidden = true;
    listEl.hidden = false;
  }

  // ---------- wiring ----------

  backLink.addEventListener("click", function (event) {
    event.preventDefault();
    pushListUrl();
    showList();
  });

  window.addEventListener("popstate", function () {
    var key = courseKeyFromUrl();
    if (key === null) {
      showList();
    } else {
      showDetail(key, null);
    }
  });

  // The list is always loaded, even when the detail view opens first from a
  // shared link: it both backs the "Tutti i corsi" return and resolves the
  // course label for the heading once the fetch completes.
  loadList(1);

  var initialKey = courseKeyFromUrl();
  if (initialKey === null) {
    showList();
  } else {
    showDetail(initialKey, null);
  }
})();

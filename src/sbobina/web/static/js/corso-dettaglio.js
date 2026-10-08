// sbobina · course detail: lectures, pagination and view visibility.
// Shares course labels with the list through SbobinaCourseDetail.
(function () {
  "use strict";

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
  var detailEl = document.getElementById("corsi-detail");
  // S1: the course name is the page title; the path above leads back.
  var detailTitleEl = document.getElementById("corsi-page-title");
  var breadcrumbsEl = document.getElementById("corsi-breadcrumbs");
  var LIST_TITLE = "Corsi";
  var detailStatusEl = document.getElementById("corsi-detail-status");
  var detailTbody = document.getElementById("corsi-detail-tbody");
  var detailEmptyEl = document.getElementById("corsi-detail-empty");
  var detailPaginationEl = document.getElementById("corsi-detail-pagination");

  var detailPage = 1;
  var currentCourseKey = null;
  var labelsByKey = {};

  var dom = window.SbobinaDom;
  var materials = window.SbobinaCourseMaterials;
  var generations = window.SbobinaCourseGenerations;
  var chat = window.SbobinaCourseChat;
  var examCues = window.SbobinaCourseExamCues;
  var practice = window.SbobinaCoursePractice;
  var packageExport = window.SbobinaCourseExport;
  var retrievalStatus = window.SbobinaCourseRetrievalStatus;
  var summary = window.SbobinaCourseSummary;
  var clearChildren = dom.clearChildren;
  var textCell = dom.textCell;
  var showSkeleton = dom.showSkeleton;
  var clearStatus = dom.clearStatus;
  var showRetryStatus = dom.showRetryStatus;
  var renderPagination = dom.renderPagination;

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

  // ---------- detail view ----------

  function renderDetailRow(job) {
    var row = document.createElement("tr");
    row.setAttribute("data-job-id", job.id);

    var nameCell = document.createElement("td");
    nameCell.className = "cell-name";
    nameCell.setAttribute("data-label", "Lezione");
    if (job.status === "done") {
      var link = document.createElement("a");
      link.className = "table__link";
      link.href = "/lettore/" + job.id;
      link.textContent = jobTitle(job);
      nameCell.appendChild(link);
      var studyLink = document.createElement("a");
      studyLink.className = "table__link table__sublink";
      studyLink.href = "/studio/" + job.id;
      studyLink.textContent = "Materiali di studio";
      nameCell.appendChild(studyLink);
    } else {
      nameCell.textContent = jobTitle(job);
    }
    row.appendChild(nameCell);

    var dateCell = textCell(window.SbobinaWhen.format(job.created_at), "Data");
    dateCell.title = window.SbobinaWhen.full(job.created_at);
    row.appendChild(dateCell);

    var statusCell = document.createElement("td");
    statusCell.setAttribute("data-label", "Stato");
    var badge = document.createElement("span");
    badge.className = "badge badge--" + job.status;
    badge.textContent = STATUS_LABELS[job.status];
    statusCell.appendChild(badge);
    row.appendChild(statusCell);

    return row;
  }

  // C3: unfinished attempts (cancelled, interrupted, failed) fold into one
  // row that expands them on request; lectures stay in view.
  function renderLessons(jobs) {
    var attempts = [];
    jobs.forEach(function (job) {
      var row = renderDetailRow(job);
      if (summary.isAttempt(job.status)) {
        row.hidden = true;
        row.classList.add("course-lesson--attempt");
        attempts.push(row);
      }
      detailTbody.appendChild(row);
    });
    if (attempts.length > 0) {
      detailTbody.appendChild(attemptsToggleRow(attempts));
    }
  }

  function attemptsToggleRow(attempts) {
    var row = document.createElement("tr");
    row.className = "course-lesson__attempts";
    var cell = document.createElement("td");
    cell.colSpan = 3;
    var count = attempts.length;
    var text = document.createElement("span");
    text.textContent =
      (count === 1 ? "1 tentativo non completato" : count + " tentativi non completati") + " · ";
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--ghost btn--inline";
    button.setAttribute("aria-expanded", "false");
    button.textContent = "Mostra";
    button.addEventListener("click", function () {
      var open = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(open));
      button.textContent = open ? "Nascondi" : "Mostra";
      attempts.forEach(function (attemptRow) {
        attemptRow.hidden = !open;
      });
    });
    cell.appendChild(text);
    cell.appendChild(button);
    row.appendChild(cell);
    return row;
  }

  function setCourseView(key, label) {
    var inDetail = key !== null;
    detailTitleEl.textContent = inDetail ? label : LIST_TITLE;
    breadcrumbsEl.hidden = !inDetail;
    document.body.classList.toggle("is-course-detail", inDetail);
    if (inDetail) {
      document.body.dataset.courseKey = key;
      document.body.dataset.courseLabel = label;
    } else {
      delete document.body.dataset.courseKey;
      delete document.body.dataset.courseLabel;
    }
    document.dispatchEvent(
      new CustomEvent("sbobina:course-scope", { detail: { key: key, label: label } })
    );
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
        renderLessons(body.data);
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
    setCourseView(key, labelFor(key, knownLabel));
    summary.show(key);
    loadDetail(key, 1);
    examCues.show(key);
    materials.show(key);
    generations.show(key);
    practice.show(key);
    chat.show(key);
    packageExport.show(key);
    retrievalStatus.show(key);
  }

  function showList() {
    currentCourseKey = null;
    detailEl.hidden = true;
    listEl.hidden = false;
    setCourseView(null, null);
    summary.hide();
    examCues.hide();
    materials.hide();
    generations.hide();
    practice.hide();
    chat.hide();
    packageExport.hide();
    retrievalStatus.hide();
  }

  function refreshTitle() {
    if (
      currentCourseKey !== null &&
      Object.prototype.hasOwnProperty.call(labelsByKey, currentCourseKey)
    ) {
      setCourseView(currentCourseKey, labelsByKey[currentCourseKey]);
    }
  }

  window.SbobinaCourseDetail = {
    show: showDetail,
    hide: showList,
    labelsByKey: labelsByKey,
    refreshTitle: refreshTitle,
  };
})();

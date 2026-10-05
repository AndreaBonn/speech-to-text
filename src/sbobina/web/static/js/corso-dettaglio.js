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
  var detailTitleEl = document.getElementById("corsi-detail-title");
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
    examCues.show(key);
    materials.show(key);
    generations.show(key);
    practice.show(key);
    chat.show(key);
    packageExport.show(key);
  }

  function showList() {
    currentCourseKey = null;
    detailEl.hidden = true;
    listEl.hidden = false;
    examCues.hide();
    materials.hide();
    generations.hide();
    practice.hide();
    chat.hide();
    packageExport.hide();
  }

  function refreshTitle() {
    if (
      currentCourseKey !== null &&
      Object.prototype.hasOwnProperty.call(labelsByKey, currentCourseKey)
    ) {
      detailTitleEl.textContent = labelsByKey[currentCourseKey];
    }
  }

  window.SbobinaCourseDetail = {
    show: showDetail,
    hide: showList,
    labelsByKey: labelsByKey,
    refreshTitle: refreshTitle,
  };
})();

// sbobina · job history: paginated table, delete terminal jobs.
(function () {
  "use strict";

  var JOBS_URL = "/api/v1/jobs";
  var PER_PAGE = 20;
  var STATUS_LABELS = {
    queued: "In coda",
    running: "In corso",
    done: "Completata",
    failed: "Errore",
    cancelled: "Annullata",
    interrupted: "Interrotta",
  };

  var tbody = document.getElementById("storico-tbody");
  var emptyEl = document.getElementById("storico-empty");
  var paginationEl = document.getElementById("storico-pagination");
  var statusEl = document.getElementById("storico-status");

  var filtersEl = document.getElementById("storico-filters");
  var courseSelect = document.getElementById("storico-course");
  var bulkEl = document.getElementById("storico-bulk");
  var bulkButton = document.getElementById("storico-bulk-delete");
  var Filters = window.SbobinaHistoryFilters;
  var COURSES_URL = "/api/v1/courses?per_page=100";
  // T2: the bulk clean-up lists every unfinished attempt in one request.
  var BULK_PAGE_SIZE = 500;

  var currentPage = 1;
  var currentFilter = "all";
  var unfinishedCount = 0;

  // ---------- helpers ----------

  // Safe in text and in quoted attributes: textContent/innerHTML would leave
  // double quotes unescaped and break out of an attribute value.
  function escapeHtml(value) {
    return (value == null ? "" : String(value))
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Mirrors jobTitle() in jobs.js and _reader_title() in pages.py: the same
  // job must never be called something different on two pages.
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

  function showStatus(message) {
    statusEl.hidden = false;
    statusEl.innerHTML =
      '<div class="queue__error"><span>' +
      escapeHtml(message) +
      '</span><button type="button" class="btn btn--secondary" id="storico-retry">Riprova</button></div>';
    var retry = document.getElementById("storico-retry");
    retry.addEventListener("click", function () {
      load(currentPage);
    });
  }

  function clearStatus() {
    statusEl.hidden = true;
    statusEl.innerHTML = "";
  }

  // ---------- rows ----------

  function renderActions(job) {
    var actions = [];
    if (job.status === "done") {
      actions.push(
        '<a class="btn btn--secondary" href="/lettore/' + job.id + '">Apri</a>'
      );
    }
    // T2: deleting is never the point of a row; it stays quiet next to Apri.
    actions.push(
      '<button type="button" class="btn btn--danger-text" data-delete="' +
        job.id +
        '">Elimina</button>'
    );
    return actions.join("");
  }

  // Static markup only: the engine name never comes from user input.
  function engineNote(job) {
    var engine = job.config && job.config.transcription_engine;
    return engine === "assemblyai"
      ? ' <span class="cell-engine">Trascritta con AssemblyAI</span>'
      : "";
  }

  function renderRow(job) {
    var created =
      '<time datetime="' + escapeHtml(job.created_at) + '" title="' +
      escapeHtml(window.SbobinaWhen.full(job.created_at)) + '">' +
      window.SbobinaWhen.format(job.created_at) + "</time>";
    return (
      '<tr data-job-id="' + job.id + '">' +
      '<td class="cell-name" data-label="Lezione">' + escapeHtml(jobTitle(job)) + engineNote(job) + "</td>" +
      '<td data-label="Corso">' + escapeHtml(job.course || "Senza corso") + "</td>" +
      '<td data-label="Data">' + created + "</td>" +
      '<td data-label="Stato"><span class="badge badge--' +
      job.status +
      '">' +
      STATUS_LABELS[job.status] +
      "</span></td>" +
      '<td class="cell-actions" data-label="Azioni">' + renderActions(job) + "</td>" +
      "</tr>"
    );
  }

  function attachRowHandlers() {
    tbody.querySelectorAll("[data-delete]").forEach(function (button) {
      button.addEventListener("click", function () {
        deleteJob(button.getAttribute("data-delete"));
      });
    });
  }

  function deleteJob(jobId) {
    fetch(JOBS_URL + "/" + jobId, { method: "DELETE" })
      .then(function (response) {
        if (response.status === 204) {
          load(currentPage);
          return null;
        }
        return response.json();
      })
      .then(function (body) {
        if (!body) {
          return;
        }
        var row = tbody.querySelector('tr[data-job-id="' + jobId + '"]');
        if (!row) {
          return;
        }
        var notice = document.createElement("p");
        notice.className = "job-row__notice";
        notice.textContent =
          (body.error && body.error.message) ||
          "Il job non è eliminabile in questo stato.";
        row.querySelector(".cell-actions").appendChild(notice);
      })
      .catch(function () {
        showStatus("Impossibile eliminare la trascrizione. Riprova.");
      });
  }

  // ---------- pagination ----------

  function renderPagination(meta) {
    if (meta.total_pages <= 1) {
      paginationEl.hidden = true;
      paginationEl.innerHTML = "";
      return;
    }
    paginationEl.hidden = false;
    var pages = [];
    for (var i = 1; i <= meta.total_pages; i++) {
      pages.push(
        '<button type="button" class="pagination__page' +
          (i === meta.page ? " is-active" : "") +
          '" data-page="' +
          i +
          '"' +
          (i === meta.page ? ' aria-current="page"' : "") +
          ">" +
          i +
          "</button>"
      );
    }
    paginationEl.innerHTML =
      '<span class="pagination__count">Pagina ' +
      meta.page +
      " di " +
      meta.total_pages +
      " · " +
      meta.total +
      " totali</span>" +
      '<div class="pagination__pages">' +
      pages.join("") +
      "</div>";
    paginationEl.querySelectorAll(".pagination__page").forEach(function (button) {
      button.addEventListener("click", function () {
        load(parseInt(button.getAttribute("data-page"), 10));
      });
    });
  }

  // ---------- load ----------

  function showSkeleton() {
    tbody.innerHTML =
      '<tr><td colspan="5"><div class="skeleton-row"></div></td></tr>' +
      '<tr><td colspan="5"><div class="skeleton-row"></div></td></tr>' +
      '<tr><td colspan="5"><div class="skeleton-row"></div></td></tr>';
  }

  // ---------- filters (T1) and bulk clean-up (T2) ----------

  function courseQuery() {
    return courseSelect.value ? "&course=" + encodeURIComponent(courseSelect.value) : "";
  }

  function showCounts(statusCounts) {
    var counts = Filters.counts(statusCounts || {});
    filtersEl.querySelectorAll("[data-count]").forEach(function (el) {
      el.textContent = "(" + counts[el.getAttribute("data-count")] + ")";
    });
    unfinishedCount = counts.unfinished;
    bulkEl.hidden = unfinishedCount === 0;
    bulkButton.textContent =
      unfinishedCount === 1
        ? "Elimina il tentativo non completato"
        : "Elimina i " + unfinishedCount + " tentativi non completati";
  }

  function setFilter(filter) {
    currentFilter = filter;
    filtersEl.querySelectorAll("[data-filter]").forEach(function (button) {
      var on = button.getAttribute("data-filter") === filter;
      button.classList.toggle("is-active", on);
      button.setAttribute("aria-pressed", String(on));
    });
    load(1);
  }

  function deleteUnfinished() {
    var count = unfinishedCount;
    if (
      !window.confirm(
        "Eliminare " + (count === 1 ? "il tentativo non completato" : "i " + count + " tentativi non completati") +
          "? L'operazione non si può annullare."
      )
    ) {
      return;
    }
    bulkButton.disabled = true;
    fetch(JOBS_URL + "?per_page=" + BULK_PAGE_SIZE + Filters.statusQuery("unfinished") + courseQuery())
      .then(function (response) {
        if (!response.ok) {
          throw new Error("unfinished list failed");
        }
        return response.json();
      })
      .then(function (body) {
        return body.data.reduce(function (chain, job) {
          return chain.then(function (deleted) {
            return fetch(JOBS_URL + "/" + job.id, { method: "DELETE" }).then(function (response) {
              return deleted + (response.status === 204 ? 1 : 0);
            });
          });
        }, Promise.resolve(0));
      })
      .then(function (deleted) {
        bulkButton.disabled = false;
        load(1);
        statusEl.hidden = false;
        statusEl.textContent =
          deleted === 1 ? "Eliminato 1 tentativo." : "Eliminati " + deleted + " tentativi.";
      })
      .catch(function () {
        bulkButton.disabled = false;
        showStatus("Pulizia non riuscita: alcuni tentativi potrebbero essere rimasti. Riprova.");
      });
  }

  function loadCourses() {
    fetch(COURSES_URL)
      .then(function (response) {
        return response.ok ? response.json() : { data: [] };
      })
      .then(function (body) {
        body.data.forEach(function (course) {
          var option = document.createElement("option");
          option.value = course.key;
          option.textContent = course.label;
          courseSelect.appendChild(option);
        });
      })
      .catch(function () {
        // Without the list the history still shows every course.
      });
  }

  function load(page) {
    currentPage = page;
    clearStatus();
    emptyEl.hidden = true;
    showSkeleton();
    fetch(
      JOBS_URL + "?page=" + page + "&per_page=" + PER_PAGE +
        Filters.statusQuery(currentFilter) + courseQuery()
    )
      .then(function (response) {
        if (!response.ok) {
          throw new Error("storico fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        showCounts(body.meta.status_counts);
        if (body.data.length === 0) {
          tbody.innerHTML = "";
          paginationEl.hidden = true;
          var filtered = currentFilter !== "all" || courseSelect.value !== "";
          if (page === 1 && !filtered) {
            emptyEl.hidden = false;
          } else if (page === 1) {
            statusEl.hidden = false;
            statusEl.textContent = "Nessuna trascrizione con questi filtri.";
          }
          return;
        }
        tbody.innerHTML = body.data.map(renderRow).join("");
        attachRowHandlers();
        renderPagination(body.meta);
      })
      .catch(function () {
        tbody.innerHTML = "";
        showStatus("Impossibile caricare lo storico.");
      });
  }

  filtersEl.addEventListener("click", function (event) {
    var button = event.target.closest("[data-filter]");
    if (button) {
      setFilter(button.getAttribute("data-filter"));
    }
  });
  courseSelect.addEventListener("change", function () {
    load(1);
  });
  bulkButton.addEventListener("click", deleteUnfinished);

  loadCourses();
  load(1);
})();

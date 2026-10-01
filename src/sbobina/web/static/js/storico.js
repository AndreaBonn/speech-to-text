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

  var currentPage = 1;

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
    actions.push(
      '<button type="button" class="btn btn--danger" data-delete="' +
        job.id +
        '">Elimina</button>'
    );
    return actions.join("");
  }

  function renderRow(job) {
    var created = new Date(job.created_at).toLocaleString("it-IT");
    return (
      '<tr data-job-id="' + job.id + '">' +
      '<td class="cell-name" data-label="Lezione">' + escapeHtml(jobTitle(job)) + "</td>" +
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
      '<tr><td colspan="4"><div class="skeleton-row"></div></td></tr>' +
      '<tr><td colspan="4"><div class="skeleton-row"></div></td></tr>' +
      '<tr><td colspan="4"><div class="skeleton-row"></div></td></tr>';
  }

  function load(page) {
    currentPage = page;
    clearStatus();
    emptyEl.hidden = true;
    showSkeleton();
    fetch(JOBS_URL + "?page=" + page + "&per_page=" + PER_PAGE)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("storico fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (body.data.length === 0) {
          tbody.innerHTML = "";
          paginationEl.hidden = true;
          if (page === 1) {
            emptyEl.hidden = false;
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

  load(1);
})();

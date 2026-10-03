// sbobina · course materials: list, extraction polling, delete and download
// (upload in corso-upload.js). File names come from the uploader's disk, so they reach the DOM
// only via textContent (see dom.js), same discipline as the document reader.
(function () {
  "use strict";

  var dom = window.SbobinaDom;
  var clearChildren = dom.clearChildren;
  var clearStatus = dom.clearStatus;
  var showRetryStatus = dom.showRetryStatus;
  var renderPagination = dom.renderPagination;

  var PER_PAGE = 20;
  var POLL_MS = 4000;
  // Mirrors UNCATEGORIZED_COURSE_KEY in src/sbobina/courses.py.
  var UNCATEGORIZED_KEY = "";
  var ACTIVE_STATUSES = ["uploading", "extracting"];
  var STATUS_LABELS = {
    uploading: "Caricamento",
    extracting: "Estrazione in corso",
    ready: "Pronto",
    ready_no_text: "Pronto (senza testo)",
    failed: "Errore",
  };
  var ERROR_MESSAGES = {
    EXTRACTION_TIMEOUT: "L'estrazione ha impiegato troppo tempo.",
    EXTRACTION_FAILED: "Non è stato possibile leggere il documento.",
  };
  var OPENABLE_STATUSES = ["ready", "ready_no_text"];

  var form = document.getElementById("materials-upload-form");
  var uncategorizedNote = document.getElementById("materials-uncategorized-note");
  var statusEl = document.getElementById("materials-status");
  var listEl = document.getElementById("materials-list");
  var emptyEl = document.getElementById("materials-empty");
  var paginationEl = document.getElementById("materials-pagination");

  var currentKey = null;
  var currentPage = 1;
  var pollTimer = null;
  var hasActiveDocument = false;

  function apiBase(key) {
    return "/api/v1/courses/" + encodeURIComponent(key) + "/documents";
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function schedulePoll() {
    stopPolling();
    if (!hasActiveDocument || document.hidden || currentKey === null) {
      return;
    }
    pollTimer = setTimeout(function () {
      load(currentKey, currentPage, true);
    }, POLL_MS);
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      stopPolling();
    } else {
      schedulePoll();
    }
  });

  function formatBytes(bytes) {
    if (bytes >= 1024 * 1024) {
      return (
        (bytes / (1024 * 1024)).toLocaleString("it-IT", {
          maximumFractionDigits: 1,
        }) + " MB"
      );
    }
    return Math.ceil(bytes / 1024) + " KB";
  }

  function showMessage(message) {
    clearChildren(statusEl);
    statusEl.hidden = false;
    statusEl.textContent = message;
  }

  // ---------- list ----------

  function renderItem(doc, key) {
    var li = document.createElement("li");
    li.className = "materials__item";
    li.setAttribute("data-doc-id", doc.id);

    var nameWrap = document.createElement("div");
    nameWrap.className = "materials__name-wrap";
    var name = document.createElement("span");
    name.className = "materials__name";
    name.textContent = doc.filename;
    nameWrap.appendChild(name);
    var meta = document.createElement("span");
    meta.className = "materials__meta";
    meta.textContent =
      formatBytes(doc.size) + (doc.pages ? " · " + doc.pages + " pag." : "");
    nameWrap.appendChild(meta);
    if (doc.status === "failed") {
      var errorText = document.createElement("span");
      errorText.className = "materials__error";
      errorText.textContent =
        ERROR_MESSAGES[doc.error] || "Estrazione non riuscita.";
      nameWrap.appendChild(errorText);
    }
    li.appendChild(nameWrap);

    var badge = document.createElement("span");
    badge.className = "badge badge--" + doc.status;
    badge.textContent = STATUS_LABELS[doc.status] || doc.status;
    li.appendChild(badge);

    li.appendChild(renderActions(doc, key));
    window.SbobinaCourseOcr.decorate(li, key, doc);
    return li;
  }

  function renderActions(doc, key) {
    var actions = document.createElement("div");
    actions.className = "materials__actions";

    if (OPENABLE_STATUSES.indexOf(doc.status) !== -1) {
      var openLink = document.createElement("a");
      openLink.className = "btn btn--ghost";
      openLink.href =
        "/corsi/" + encodeURIComponent(key) + "/documenti/" + encodeURIComponent(doc.id);
      openLink.textContent = "Apri";
      actions.appendChild(openLink);
    }

    var downloadLink = document.createElement("a");
    downloadLink.className = "btn btn--ghost";
    downloadLink.href = apiBase(key) + "/" + encodeURIComponent(doc.id) + "/file";
    downloadLink.setAttribute("download", "");
    downloadLink.textContent = "Scarica";
    actions.appendChild(downloadLink);

    var deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "btn btn--danger";
    deleteButton.textContent = "Elimina";
    deleteButton.addEventListener("click", function () {
      if (
        window.confirm(
          "Eliminare «" + doc.filename + "»? L'operazione non si può annullare."
        )
      ) {
        deleteDocument(key, doc);
      }
    });
    actions.appendChild(deleteButton);

    return actions;
  }

  function deleteDocument(key, doc) {
    fetch(apiBase(key) + "/" + encodeURIComponent(doc.id), { method: "DELETE" })
      .then(function (response) {
        if (response.status === 204) {
          load(key, currentPage);
          return null;
        }
        return response.json();
      })
      .then(function (body) {
        if (body === null) {
          return;
        }
        var busy = body && body.error && body.error.code === "DOCUMENT_BUSY";
        showMessage(
          busy
            ? "Il documento è in elaborazione: riprova tra poco."
            : "Impossibile eliminare il documento."
        );
      })
      .catch(function () {
        showMessage("Impossibile eliminare il documento.");
      });
  }

  function load(key, page, isPoll) {
    currentKey = key;
    currentPage = page;
    if (!isPoll) {
      clearStatus(statusEl);
      emptyEl.hidden = true;
      listEl.hidden = true;
      clearChildren(listEl);
    }
    fetch(apiBase(key) + "?page=" + page + "&per_page=" + PER_PAGE)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("materials fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        // A late answer for a course the user already left must not paint.
        if (key !== currentKey) {
          return;
        }
        hasActiveDocument = body.data.some(function (doc) {
          return ACTIVE_STATUSES.indexOf(doc.status) !== -1;
        });
        clearChildren(listEl);
        if (body.data.length === 0) {
          listEl.hidden = true;
          paginationEl.hidden = true;
          if (page === 1) {
            emptyEl.hidden = false;
          }
          schedulePoll();
          return;
        }
        emptyEl.hidden = true;
        listEl.hidden = false;
        body.data.forEach(function (doc) {
          listEl.appendChild(renderItem(doc, key));
        });
        renderPagination(paginationEl, body.meta, function (nextPage) {
          load(key, nextPage);
        });
        schedulePoll();
      })
      .catch(function () {
        if (isPoll || key !== currentKey) {
          return;
        }
        clearChildren(listEl);
        listEl.hidden = true;
        showRetryStatus(statusEl, "Impossibile caricare i materiali.", function () {
          load(key, currentPage);
        });
      });
  }

  // Upload lives in corso-upload.js; it asks for the open course and calls
  // back when a document was accepted.
  window.SbobinaCourseUpload.bind({
    currentKey: function () {
      return currentKey;
    },
    onUploaded: function (key) {
      load(key, 1);
    },
  });

  // ---------- public API ----------

  function show(key) {
    stopPolling();
    window.SbobinaCourseOcr.forgetAll();
    var isUncategorized = key === UNCATEGORIZED_KEY;
    form.hidden = isUncategorized;
    uncategorizedNote.hidden = !isUncategorized;
    load(key, 1);
  }

  function hide() {
    stopPolling();
    window.SbobinaCourseOcr.forgetAll();
    currentKey = null;
  }

  function refresh() {
    if (currentKey !== null) {
      load(currentKey, currentPage);
    }
  }

  window.SbobinaCourseMaterials = {
    show: show,
    hide: hide,
    refresh: refresh,
  };
})();

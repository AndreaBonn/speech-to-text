// sbobina · course generations: polling list and downloads.
// The request form lives in corso-generazioni-form.js, detail rendering in
// corso-generazioni-dettaglio.js, cancel/delete in corso-generazioni-azioni.js.
// Every string from outside the code reaches
// the DOM only via textContent (see dom.js).
(function () {
  "use strict";

  var dom = window.SbobinaDom;
  var clearChildren = dom.clearChildren;
  var clearStatus = dom.clearStatus;
  var showRetryStatus = dom.showRetryStatus;
  var renderPagination = dom.renderPagination;
  var detail = window.SbobinaGenerationDetail;
  var el = detail.el;
  var formModule = window.SbobinaGenerationForm;
  var actions = window.SbobinaGenerationActions;

  var PER_PAGE = 20;
  var POLL_MS = 2000;
  var ACTIVE_STATUSES = ["queued", "running"];
  var FORMAT_LABELS = {
    multiple_choice: "Crocette",
    open: "Domande aperte",
    oral: "Orale",
    summary: "Riassunto",
  };
  var STATUS_LABELS = {
    queued: "In coda",
    running: "In corso",
    done: "Completata",
    failed: "Errore",
    interrupted: "Interrotta",
  };
  var ERROR_MESSAGES = {
    OLLAMA_UNAVAILABLE: "Ollama non risponde: avvialo e riprova.",
    INVALID_RESPONSE: "Il modello ha risposto in un formato non valido: riprova.",
    STAGE_FAILED: "La generazione si è interrotta per un errore: riprova.",
    SUPERVISOR_ERROR: "Errore interno: riprova.",
  };

  var statusEl = document.getElementById("generations-status");
  var listEl = document.getElementById("generations-list");
  // C8: what exists comes first; the form opens on request once there is any.
  var formEl = document.getElementById("generations-form");
  var newButton = document.getElementById("generations-new");
  var formOpened = false;

  function syncForm(hasItems) {
    newButton.hidden = !hasItems;
    formEl.hidden = hasItems && !formOpened;
    newButton.setAttribute("aria-expanded", String(!formEl.hidden));
  }

  newButton.addEventListener("click", function () {
    formOpened = formEl.hidden;
    syncForm(true);
    if (formOpened) {
      formEl.querySelector("select, input").focus();
    }
  });
  var emptyEl = document.getElementById("generations-empty");
  var paginationEl = document.getElementById("generations-pagination");

  var currentKey = null;
  var currentPage = 1;
  var pollTimer = null;

  function apiBase(key) {
    return "/api/v1/courses/" + encodeURIComponent(key) + "/generations";
  }

  // ---------- polling ----------

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function schedulePoll(hasActive) {
    stopPolling();
    if (!hasActive || document.hidden || currentKey === null) {
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
      load(currentKey, currentPage, true);
    }
  });

  // ---------- actions ----------

  function itemUrl(key, record) {
    return apiBase(key) + "/" + encodeURIComponent(record.id);
  }

  function reloadCurrent(key) {
    return function () {
      load(key, currentPage);
    };
  }

  function cancelGeneration(key, record) {
    actions.cancel(itemUrl(key, record), statusEl, reloadCurrent(key));
  }

  function deleteGeneration(key, record) {
    actions.remove(itemUrl(key, record), statusEl, reloadCurrent(key));
  }

  // ---------- list ----------

  function appendActiveActions(li, key, record) {
    var actions = el("div", "generations__actions");
    var cancelButton = el("button", "btn btn--secondary", "Annulla");
    cancelButton.type = "button";
    cancelButton.addEventListener("click", function () {
      cancelGeneration(key, record);
    });
    actions.appendChild(cancelButton);
    li.appendChild(actions);
  }

  // C9: the main action first (Svolgi), then Mostra and Scarica, Elimina last.
  function appendDoneActions(li, key, record) {
    var actions = el("div", "generations__actions");
    var deleteButton = el("button", "btn btn--danger-text", "Elimina");
    deleteButton.type = "button";
    deleteButton.addEventListener("click", function () {
      if (
        window.confirm("Eliminare questa generazione? L'operazione non si può annullare.")
      ) {
        deleteGeneration(key, record);
      }
    });
    if (record.status !== "done") {
      actions.appendChild(deleteButton);
      li.appendChild(actions);
      return;
    }
    var toggleButton = el("button", "btn btn--ghost", "Mostra");
    toggleButton.type = "button";
    var detailContainer = el("div", "generations__detail");
    detailContainer.hidden = true;
    toggleButton.addEventListener("click", function () {
      if (detailContainer.hidden) {
        toggleButton.textContent = "Nascondi";
        detail.load(apiBase(key) + "/" + encodeURIComponent(record.id), detailContainer);
      } else {
        toggleButton.textContent = "Mostra";
        detailContainer.hidden = true;
      }
    });
    if (record.format !== "summary") {
      actions.appendChild(window.SbobinaPracticeStart.button(itemUrl(key, record), key, statusEl));
    }
    actions.appendChild(toggleButton);
    actions.appendChild(detail.downloadLinks(apiBase(key), record));
    actions.appendChild(deleteButton);
    li.appendChild(actions);
    li.appendChild(detailContainer);
  }

  function renderItem(record, key) {
    var li = el("li", "generations__item");
    li.setAttribute("data-gen-id", record.id);
    li.setAttribute("data-status", record.status);

    var head = el("div", "generations__item-head");
    head.appendChild(
      el("span", "generations__item-title", FORMAT_LABELS[record.format] || record.format)
    );
    head.appendChild(
      el("span", "badge badge--" + record.status, STATUS_LABELS[record.status])
    );
    li.appendChild(head);

    if (record.topic) {
      li.appendChild(el("p", "generations__topic", record.topic));
    }
    if (record.status === "failed") {
      li.appendChild(
        el(
          "p",
          "banner banner--danger",
          ERROR_MESSAGES[record.error] || ERROR_MESSAGES.STAGE_FAILED
        )
      );
    }
    if (record.status === "interrupted") {
      li.appendChild(el("p", "banner banner--warning", "Generazione interrotta."));
    }

    if (ACTIVE_STATUSES.indexOf(record.status) !== -1) {
      appendActiveActions(li, key, record);
    } else {
      appendDoneActions(li, key, record);
    }
    return li;
  }

  // A poll only replaces items whose status changed, so an expanded detail
  // or solution on a finished item survives the 2 s refresh.
  function sameItems(records) {
    var items = listEl.children;
    return (
      items.length === records.length &&
      records.every(function (record, index) {
        return items[index].getAttribute("data-gen-id") === record.id;
      })
    );
  }

  function renderList(key, records, isPoll) {
    if (isPoll && sameItems(records)) {
      records.forEach(function (record, index) {
        var current = listEl.children[index];
        if (current.getAttribute("data-status") !== record.status) {
          listEl.replaceChild(renderItem(record, key), current);
        }
      });
      return;
    }
    clearChildren(listEl);
    records.forEach(function (record) {
      listEl.appendChild(renderItem(record, key));
    });
  }

  function applyPage(key, page, body, isPoll) {
    var hasActive = body.data.some(function (record) {
      return ACTIVE_STATUSES.indexOf(record.status) !== -1;
    });
    if (body.data.length === 0) {
      clearChildren(listEl);
      listEl.hidden = true;
      paginationEl.hidden = true;
      emptyEl.hidden = page !== 1;
    } else {
      emptyEl.hidden = true;
      listEl.hidden = false;
      renderList(key, body.data, isPoll);
      renderPagination(paginationEl, body.meta, function (nextPage) {
        load(key, nextPage);
      });
    }
    if (!isPoll) {
      syncForm(body.meta.total > 0);
    }
    schedulePoll(hasActive);
  }

  function showLoadError(key) {
    clearChildren(listEl);
    listEl.hidden = true;
    showRetryStatus(statusEl, "Impossibile caricare le generazioni.", function () {
      load(key, currentPage);
    });
  }

  function load(key, page, isPoll) {
    if (key === null) {
      return;
    }
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
          throw new Error("generations fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (key === currentKey) {
          applyPage(key, page, body, isPoll);
        }
      })
      .catch(function () {
        if (!isPoll && key === currentKey) {
          showLoadError(key);
        }
      });
  }

  // ---------- public API ----------

  function show(key) {
    stopPolling();
    currentKey = key;
    formOpened = false;
    formModule.show(key, {
      onSubmitted: function () {
        formOpened = false;
        load(key, 1);
      },
    });
    load(key, 1);
  }

  function hide() {
    stopPolling();
    currentKey = null;
  }

  window.SbobinaCourseGenerations = { show: show, hide: hide };
})();

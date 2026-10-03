// sbobina · course materials: OCR of a scanned PDF (start, poll, cancel).
// Decorates one materials row at a time; corso-materiali.js calls decorate()
// per row and owns the reload once a run finishes. Text never passes through
// here, only status/progress, so textContent discipline is a non-issue.
(function () {
  "use strict";

  var dom = window.SbobinaDom;
  var POLL_MS = 5000;
  var ACTIVE_STATUSES = ["queued", "running"];
  var ERROR_MESSAGES = {
    OLLAMA_UNAVAILABLE: "Ollama non risponde: avvialo e riprova.",
  };
  var DEFAULT_ERROR_MESSAGE = "OCR non riuscito.";

  // doc_id -> { key, el, status, done, total, error, timer }
  var runs = {};

  function apiBase(key, docId) {
    return (
      "/api/v1/courses/" +
      encodeURIComponent(key) +
      "/documents/" +
      encodeURIComponent(docId) +
      "/ocr"
    );
  }

  function isActive(status) {
    return ACTIVE_STATUSES.indexOf(status) !== -1;
  }

  function stopPoll(docId) {
    var run = runs[docId];
    if (run && run.timer) {
      clearTimeout(run.timer);
      run.timer = null;
    }
  }

  function forget(docId) {
    stopPoll(docId);
    delete runs[docId];
  }

  // Leaving the course drops every run: their rows are gone from the page.
  function forgetAll() {
    Object.keys(runs).forEach(forget);
  }

  function schedulePoll(docId) {
    var run = runs[docId];
    if (!run || !isActive(run.status) || document.hidden) {
      return;
    }
    run.timer = setTimeout(function () {
      poll(docId);
    }, POLL_MS);
  }

  document.addEventListener("visibilitychange", function () {
    Object.keys(runs).forEach(function (docId) {
      if (document.hidden) {
        stopPoll(docId);
      } else {
        schedulePoll(docId);
      }
    });
  });

  function statusLine(text, tone) {
    var p = document.createElement("p");
    p.className = "ocr__status" + (tone ? " ocr__status--" + tone : "");
    p.textContent = text;
    return p;
  }

  function hintLine() {
    var p = document.createElement("p");
    p.className = "ocr__hint";
    p.textContent =
      "Lento: alcuni minuti per pagina, il testo può contenere errori.";
    return p;
  }

  function startButton(docId) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--secondary ocr__start";
    button.textContent = "Estrai il testo con OCR";
    button.addEventListener("click", function () {
      start(docId);
    });
    return button;
  }

  function cancelButton(docId) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--ghost ocr__cancel";
    button.textContent = "Annulla";
    button.addEventListener("click", function () {
      cancel(docId);
    });
    return button;
  }

  function render(docId) {
    var run = runs[docId];
    if (!run || !run.el) {
      return;
    }
    dom.clearChildren(run.el);
    if (run.status === "queued") {
      run.el.appendChild(statusLine("OCR in coda"));
      run.el.appendChild(cancelButton(docId));
      return;
    }
    if (run.status === "running") {
      run.el.appendChild(
        statusLine(run.total ? "OCR: pagina " + run.done + " di " + run.total : "OCR in corso")
      );
      run.el.appendChild(cancelButton(docId));
      return;
    }
    if (run.status === "failed") {
      run.el.appendChild(
        statusLine(ERROR_MESSAGES[run.error] || DEFAULT_ERROR_MESSAGE, "danger")
      );
      run.el.appendChild(startButton(docId));
      return;
    }
    if (run.status === "interrupted") {
      run.el.appendChild(statusLine("OCR interrotto"));
      run.el.appendChild(startButton(docId));
      return;
    }
    if (run.notice) {
      run.el.appendChild(statusLine(run.notice, "danger"));
    }
    run.el.appendChild(startButton(docId));
    run.el.appendChild(hintLine());
  }

  function applyPayload(docId, body) {
    var run = runs[docId];
    if (!run) {
      return;
    }
    var data = body.data;
    run.notice = null;
    run.status = data.status;
    run.done = data.done;
    run.total = data.total;
    run.error = data.error;
    render(docId);
    if (isActive(run.status)) {
      schedulePoll(docId);
    } else if (run.status === "done") {
      forget(docId);
      if (window.SbobinaCourseMaterials && window.SbobinaCourseMaterials.refresh) {
        window.SbobinaCourseMaterials.refresh();
      }
    }
  }

  function poll(docId) {
    var run = runs[docId];
    if (!run) {
      return;
    }
    fetch(apiBase(run.key, docId))
      .then(function (response) {
        if (response.status === 404) {
          return null;
        }
        if (!response.ok) {
          throw new Error("ocr poll failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (body && runs[docId]) {
          applyPayload(docId, body);
        } else {
          schedulePoll(docId);
        }
      })
      .catch(function () {
        schedulePoll(docId);
      });
  }

  function start(docId) {
    var run = runs[docId];
    if (!run) {
      return;
    }
    fetch(apiBase(run.key, docId), { method: "POST" })
      .then(function (response) {
        if (response.status === 409) {
          poll(docId); // already queued elsewhere (another tab): show that
          return null;
        }
        if (!response.ok) {
          throw new Error("ocr start failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (body) {
          applyPayload(docId, body);
        }
      })
      .catch(function () {
        if (runs[docId]) {
          runs[docId].notice = "Impossibile avviare l'OCR: riprova.";
          render(docId);
        }
      });
  }

  function cancel(docId) {
    var run = runs[docId];
    if (!run) {
      return;
    }
    fetch(apiBase(run.key, docId) + "/cancel", { method: "POST" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("ocr cancel failed");
        }
        return response.json();
      })
      .then(function (body) {
        applyPayload(docId, body);
      })
      .catch(function () {
        // Leave the state as-is: the next poll tick will reconcile it.
      });
  }

  // ---------- public API ----------

  // Called once per materials row at every (re)render. The row element is
  // rebuilt from scratch each time, so an existing run re-attaches to the
  // new element instead of starting a second poll loop for the same doc.
  function decorate(rowEl, key, doc) {
    var docId = doc.id;
    if (doc.kind !== "pdf" || doc.status !== "ready_no_text") {
      forget(docId);
      return;
    }

    var container = document.createElement("div");
    container.className = "ocr";
    rowEl.appendChild(container);

    var run = runs[docId];
    if (run) {
      stopPoll(docId);
      run.key = key;
      run.el = container;
      render(docId);
      schedulePoll(docId);
      return;
    }

    runs[docId] = {
      key: key,
      el: container,
      status: null,
      done: 0,
      total: 0,
      error: null,
      timer: null,
    };
    render(docId);

    // Restore state across a page reload: a run may already be queued,
    // running, or finished. A 404 means OCR was never started for this doc.
    fetch(apiBase(key, docId))
      .then(function (response) {
        return response.status === 404 ? null : response.json();
      })
      .then(function (body) {
        if (body && runs[docId]) {
          applyPayload(docId, body);
        }
      })
      .catch(function () {
        // Leave the start button as the safe default.
      });
  }

  window.SbobinaCourseOcr = { decorate: decorate, forgetAll: forgetAll };
})();

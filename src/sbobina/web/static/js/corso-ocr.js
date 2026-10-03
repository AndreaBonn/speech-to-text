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
    OCR_TIMEOUT: "OCR interrotto: ci stava mettendo troppo.",
  };
  // Consecutive failed polls before the row admits its status may be stale.
  var MAX_POLL_FAILURES = 3;
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

  function actionButton(className, label, onClick) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  function startButton(docId) {
    return actionButton("btn btn--secondary ocr__start", "Estrai il testo con OCR", function () {
      start(docId);
    });
  }

  function cancelButton(docId) {
    return actionButton("btn btn--ghost ocr__cancel", "Annulla", function () {
      cancel(docId);
    });
  }

  function render(docId) {
    var run = runs[docId];
    if (!run || !run.el) {
      return;
    }
    dom.clearChildren(run.el);
    if (run.notice) {
      run.el.appendChild(statusLine(run.notice, "danger"));
    }
    if (isActive(run.status)) {
      var label = run.total ? "OCR: pagina " + run.done + " di " + run.total : "OCR in corso";
      run.el.appendChild(statusLine(run.status === "queued" ? "OCR in coda" : label));
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
    run.failures = 0;
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

  function jsonOrThrow(response) {
    if (!response.ok) {
      throw new Error("ocr request failed: " + response.status);
    }
    return response.json();
  }

  function poll(docId) {
    var run = runs[docId];
    if (!run) {
      return;
    }
    fetch(apiBase(run.key, docId))
      .then(function (response) {
        if (response.status === 404) {
          run.failures = 0; // a real answer ends a run of failures
          return null;
        }
        return jsonOrThrow(response);
      })
      .then(function (body) {
        if (body && runs[docId]) {
          applyPayload(docId, body);
        } else {
          schedulePoll(docId);
        }
      })
      .catch(function () {
        // render and schedulePoll both no-op once the run has been forgotten.
        run.failures = (run.failures || 0) + 1;
        if (run.failures >= MAX_POLL_FAILURES) {
          run.notice = "Il server non risponde: stato dell'OCR non aggiornato.";
          render(docId);
        }
        schedulePoll(docId); // keeps trying: the notice clears on the next answer
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
        return jsonOrThrow(response);
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
      .then(jsonOrThrow)
      .then(function (body) {
        applyPayload(docId, body);
      })
      .catch(function () {
        if (runs[docId]) {
          runs[docId].notice = "Annullamento non riuscito: riprova.";
          render(docId);
        }
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

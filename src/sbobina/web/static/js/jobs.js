// sbobina · upload form + live queue. Vanilla JS, no build step, no CDN.
(function () {
  "use strict";

  var JOBS_URL = "/api/v1/jobs";
  var STATUS_LABELS = {
    queued: "In coda",
    running: "In corso",
    done: "Completata",
    failed: "Errore",
    cancelled: "Annullata",
    interrupted: "Interrotta",
  };
  var STAGE_LABELS = {
    queued: "In coda",
    transcribing: "Trascrizione",
    correcting: "Correzione",
    done: "Completato",
  };
  var CANCELLABLE_STATUSES = ["queued", "running"];
  var TERMINAL_STATUSES = ["done", "failed", "cancelled", "interrupted"];

  var form = document.getElementById("upload-form");
  var dropzone = document.getElementById("dropzone");
  var dropzoneInput = document.getElementById("dropzone-input");
  var dropzonePrompt = document.getElementById("dropzone-prompt");
  var dropzoneFile = document.getElementById("dropzone-file");
  var dropzoneFileName = document.getElementById("dropzone-file-name");
  var dropzoneFileSize = document.getElementById("dropzone-file-size");
  var fileError = document.getElementById("file-error");
  var correctCheckbox = document.getElementById("correct");
  var ollamaModelSelect = document.getElementById("ollama_model");
  var ollamaModelOther = document.getElementById("ollama_model_other");
  var whisperModelSelect = document.getElementById("whisper_model");
  // Must match model_catalog.OTHER_OLLAMA_VALUE.
  var OTHER_OLLAMA_VALUE = "__altro__";
  var submitButton = document.getElementById("submit-button");
  var formError = document.getElementById("form-error");
  var queueEl = document.getElementById("queue");

  // field name (server) -> inline error element id
  var FIELD_ERROR_IDS = {
    file: "file-error",
    subject: "subject-error",
    ollama_model: "ollama_model-error",
    beam_size: "beam_size-error",
    uncertain_threshold: "uncertain_threshold-error",
  };

  var jobsById = {};
  var jobOrder = [];
  var progressById = {};
  var eventSources = {};

  // ---------- helpers ----------

  function formatBytes(bytes) {
    if (bytes >= 1024 * 1024) {
      return (bytes / (1024 * 1024)).toLocaleString("it-IT", {
        maximumFractionDigits: 1,
      }) + " MB";
    }
    return Math.ceil(bytes / 1024) + " KB";
  }

  function formatDuration(seconds) {
    if (seconds < 60) {
      return "meno di un minuto";
    }
    var minutes = Math.floor(seconds / 60);
    var rest = Math.round(seconds % 60);
    return minutes + " min " + String(rest).padStart(2, "0") + " s";
  }

  function fieldErrorId(field) {
    var bare = field.replace(/^body\./, "");
    return FIELD_ERROR_IDS[bare] || null;
  }

  // ---------- form errors ----------

  function clearFormErrors() {
    formError.hidden = true;
    formError.textContent = "";
    Object.keys(FIELD_ERROR_IDS).forEach(function (field) {
      var id = FIELD_ERROR_IDS[field];
      var el = document.getElementById(id);
      if (el) {
        el.hidden = true;
        el.textContent = "";
      }
    });
    document.querySelectorAll(".is-invalid").forEach(function (el) {
      el.classList.remove("is-invalid");
    });
    dropzone.classList.remove("dropzone--invalid");
  }

  function showFormError(message) {
    formError.hidden = false;
    formError.textContent = message;
  }

  function showFieldError(field, message) {
    var errorId = fieldErrorId(field);
    if (!errorId) {
      showFormError(message);
      return;
    }
    var errorEl = document.getElementById(errorId);
    errorEl.hidden = false;
    errorEl.textContent = message;
    var bare = field.replace(/^body\./, "");
    if (bare === "file") {
      dropzone.classList.add("dropzone--invalid");
      return;
    }
    var input = document.getElementById(bare);
    // The free-text Ollama name, not the select, holds the rejected value.
    if (bare === "ollama_model" && isOtherOllamaModel()) {
      input = ollamaModelOther;
    }
    if (input) {
      input.classList.add("is-invalid");
    }
  }

  function applyServerErrors(body) {
    var error = body && body.error;
    if (!error) {
      showFormError("Errore durante il caricamento.");
      return;
    }
    if (error.details && error.details.length > 0) {
      error.details.forEach(function (detail) {
        showFieldError(detail.field, detail.message);
      });
      return;
    }
    showFormError(error.message || "Errore durante il caricamento.");
  }

  // ---------- blur validation ----------

  function validateOnBlur(input, errorId) {
    input.addEventListener("blur", function () {
      if (!input.checkValidity()) {
        showFieldError(input.name, input.validationMessage);
      }
    });
    input.addEventListener("input", function () {
      if (input.checkValidity()) {
        var el = document.getElementById(errorId);
        if (el) {
          el.hidden = true;
        }
        input.classList.remove("is-invalid");
      }
    });
  }

  ["subject", "beam_size", "uncertain_threshold"].forEach(function (name) {
    var input = document.getElementById(name);
    if (input) {
      validateOnBlur(input, name + "-error");
    }
  });

  // ---------- dropzone ----------

  function setDropzoneFile(file) {
    if (!file) {
      dropzonePrompt.hidden = false;
      dropzoneFile.hidden = true;
      return;
    }
    dropzonePrompt.hidden = true;
    dropzoneFile.hidden = false;
    dropzoneFileName.textContent = file.name;
    dropzoneFileSize.textContent = formatBytes(file.size);
  }

  dropzoneInput.addEventListener("change", function () {
    var file = dropzoneInput.files[0] || null;
    setDropzoneFile(file);
    fileError.hidden = true;
    dropzone.classList.remove("dropzone--invalid");
  });

  ["dragenter", "dragover"].forEach(function (eventName) {
    dropzone.addEventListener(eventName, function (event) {
      event.preventDefault();
      dropzone.classList.add("dropzone--dragover");
    });
  });

  ["dragleave", "dragend"].forEach(function (eventName) {
    dropzone.addEventListener(eventName, function () {
      dropzone.classList.remove("dropzone--dragover");
    });
  });

  dropzone.addEventListener("drop", function (event) {
    event.preventDefault();
    dropzone.classList.remove("dropzone--dragover");
    var file = event.dataTransfer.files[0];
    if (!file) {
      return;
    }
    dropzoneInput.files = event.dataTransfer.files;
    setDropzoneFile(file);
    fileError.hidden = true;
    dropzone.classList.remove("dropzone--invalid");
  });

  // ---------- model selects: profile + free Ollama name ----------

  function showModelProfile(select) {
    var container = document.getElementById(select.id + "-profile");
    Array.prototype.forEach.call(
      container.querySelectorAll("[data-profile-for]"),
      function (item) {
        item.hidden = item.getAttribute("data-profile-for") !== select.value;
      }
    );
  }

  function isOtherOllamaModel() {
    return ollamaModelSelect.value === OTHER_OLLAMA_VALUE;
  }

  function syncOllamaModelDisabled() {
    ollamaModelSelect.disabled = !correctCheckbox.checked;
    ollamaModelOther.hidden = !isOtherOllamaModel();
    ollamaModelOther.disabled = !correctCheckbox.checked || !isOtherOllamaModel();
  }

  function selectedOllamaModel() {
    return isOtherOllamaModel()
      ? ollamaModelOther.value.trim()
      : ollamaModelSelect.value;
  }

  correctCheckbox.addEventListener("change", syncOllamaModelDisabled);
  ollamaModelSelect.addEventListener("change", function () {
    showModelProfile(ollamaModelSelect);
    syncOllamaModelDisabled();
    if (isOtherOllamaModel()) {
      ollamaModelOther.focus();
    }
  });
  ollamaModelOther.addEventListener("input", function () {
    document.getElementById("ollama_model-error").hidden = true;
    ollamaModelOther.classList.remove("is-invalid");
  });
  whisperModelSelect.addEventListener("change", function () {
    showModelProfile(whisperModelSelect);
  });
  syncOllamaModelDisabled();

  // ---------- submit ----------

  function setLoading(isLoading) {
    submitButton.disabled = isLoading;
    submitButton.setAttribute("aria-busy", String(isLoading));
    submitButton.classList.toggle("btn--error", false);
    submitButton.innerHTML = isLoading
      ? '<span class="btn__spinner" aria-hidden="true"></span><span class="btn__label">Invio…</span>'
      : '<span class="btn__label">Trascrivi</span>';
    Array.prototype.forEach.call(form.elements, function (el) {
      if (el !== submitButton) {
        el.disabled = isLoading;
      }
    });
    if (!isLoading) {
      syncOllamaModelDisabled();
    }
  }

  function buildFormData() {
    var data = new FormData();
    data.append("file", dropzoneInput.files[0]);
    var subject = document.getElementById("subject").value.trim();
    if (subject) {
      data.append("subject", subject);
    }
    data.append("correct", String(correctCheckbox.checked));
    data.append("ollama_model", selectedOllamaModel());
    data.append("whisper_model", whisperModelSelect.value);
    data.append("beam_size", document.getElementById("beam_size").value);
    data.append(
      "vad_filter",
      String(document.getElementById("vad_filter").checked)
    );
    data.append(
      "condition_on_previous_text",
      String(document.getElementById("condition_on_previous_text").checked)
    );
    data.append(
      "uncertain_threshold",
      document.getElementById("uncertain_threshold").value
    );
    return data;
  }

  function resetFormAfterSuccess() {
    dropzoneInput.value = "";
    setDropzoneFile(null);
    document.getElementById("subject").value = "";
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    clearFormErrors();
    if (!dropzoneInput.files[0]) {
      showFieldError("file", "Seleziona un file audio prima di continuare.");
      return;
    }
    setLoading(true);
    fetch(JOBS_URL, { method: "POST", body: buildFormData() })
      .then(function (response) {
        return response.json().then(function (body) {
          return { status: response.status, body: body };
        });
      })
      .then(function (result) {
        setLoading(false);
        if (result.status === 201) {
          resetFormAfterSuccess();
          addJob(result.body.data);
        } else {
          applyServerErrors(result.body);
        }
      })
      .catch(function () {
        setLoading(false);
        showFormError("Impossibile contattare il server. Riprova.");
      });
  });

  // ---------- queue ----------

  function isCancellable(status) {
    return CANCELLABLE_STATUSES.indexOf(status) !== -1;
  }

  function isTerminal(status) {
    return TERMINAL_STATUSES.indexOf(status) !== -1;
  }

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

  function renderProgress(job) {
    var progress = progressById[job.id];
    if (!progress || isTerminal(job.status)) {
      return "";
    }
    var hasFraction = typeof progress.progress === "number";
    var trackStyle = hasFraction
      ? ' style="--progress-value: ' + progress.progress + '"'
      : "";
    var trackClass = hasFraction ? "progress__track" : "progress__track progress--indeterminate";
    var percent = hasFraction ? Math.round(progress.progress * 100) + "%" : "";
    var metaParts = [];
    if (percent) {
      metaParts.push(percent);
    }
    if (typeof progress.speed === "number") {
      metaParts.push(progress.speed.toFixed(1) + "× la velocità reale");
    }
    if (typeof progress.eta_s === "number") {
      metaParts.push(formatDuration(progress.eta_s) + " rimanenti");
    }
    return (
      '<div class="progress">' +
      '<div class="' + trackClass + '">' +
      '<div class="progress__fill"' + trackStyle + "></div>" +
      "</div>" +
      (metaParts.length
        ? '<div class="progress__meta">' + metaParts.join(" · ") + "</div>"
        : "") +
      "</div>"
    );
  }

  function renderActions(job) {
    var actions = [];
    if (isCancellable(job.status)) {
      actions.push(
        '<button type="button" class="btn btn--danger job-row__cancel" data-job-id="' +
          job.id +
          '">Annulla</button>'
      );
    }
    if (job.status === "done") {
      actions.push(
        '<a class="btn btn--secondary" href="/lettore/' + job.id + '">Apri</a>'
      );
    }
    return actions.length
      ? '<div class="job-row__actions">' + actions.join("") + "</div>"
      : "";
  }

  function errorMessage(job) {
    if (job.status !== "failed" || !job.error) {
      return "";
    }
    var message =
      (job.error && job.error.message) || "La trascrizione non è riuscita.";
    return '<p class="job-row__error">' + escapeHtml(String(message)) + "</p>";
  }

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

  function metaStageSuffix(job) {
    // The badge already names the terminal state (and "In coda"): repeating
    // the stage here would say the same thing twice.
    if (isTerminal(job.status) || job.stage === "queued") {
      return "";
    }
    return " · " + (STAGE_LABELS[job.stage] || job.stage);
  }

  function renderJobRow(job) {
    var created = new Date(job.created_at).toLocaleString("it-IT");
    return (
      '<article class="job-row" id="job-row-' + job.id + '" data-status="' + job.status + '">' +
      '<div class="job-row__head">' +
      '<span class="job-row__title">' + escapeHtml(jobTitle(job)) + "</span>" +
      '<span class="badge badge--' + job.status + '">' + STATUS_LABELS[job.status] + "</span>" +
      "</div>" +
      '<p class="job-row__meta">' + created + metaStageSuffix(job) + "</p>" +
      renderProgress(job) +
      errorMessage(job) +
      renderActions(job) +
      "</article>"
    );
  }

  function renderQueue() {
    if (jobOrder.length === 0) {
      queueEl.innerHTML =
        '<div class="empty-state"><p class="empty-state__text">' +
        "Nessuna trascrizione in coda. Carica un file per iniziare." +
        "</p></div>";
      return;
    }
    queueEl.innerHTML = jobOrder
      .map(function (id) {
        return renderJobRow(jobsById[id]);
      })
      .join("");
  }

  function attachRowHandlers() {
    queueEl.querySelectorAll(".job-row__cancel").forEach(function (button) {
      button.addEventListener("click", function () {
        cancelJob(button.getAttribute("data-job-id"));
      });
    });
  }

  function renderAndBind() {
    renderQueue();
    attachRowHandlers();
  }

  function attachLiveJob(jobId) {
    if (eventSources[jobId]) {
      return;
    }
    var source = new EventSource(JOBS_URL + "/" + jobId + "/events");
    source.addEventListener("progress", function (event) {
      progressById[jobId] = JSON.parse(event.data);
      if (jobsById[jobId]) {
        jobsById[jobId] = Object.assign({}, jobsById[jobId], {
          status: progressById[jobId].status,
          stage: progressById[jobId].stage,
        });
      }
      renderAndBind();
    });
    source.addEventListener("end", function () {
      source.close();
      delete eventSources[jobId];
      fetch(JOBS_URL + "/" + jobId)
        .then(function (response) {
          if (!response.ok) {
            throw new Error("job fetch failed");
          }
          return response.json();
        })
        .then(function (body) {
          jobsById[jobId] = body.data;
          delete progressById[jobId];
          renderAndBind();
        })
        .catch(function () {
          // Reload the whole queue: it has its own error state and retry.
          delete progressById[jobId];
          loadQueue();
        });
    });
    eventSources[jobId] = source;
  }

  function addJob(job) {
    jobsById[job.id] = job;
    jobOrder.unshift(job.id);
    renderAndBind();
    if (!isTerminal(job.status)) {
      attachLiveJob(job.id);
    }
  }

  function cancelJob(jobId) {
    fetch(JOBS_URL + "/" + jobId + "/cancel", { method: "POST" })
      .then(function (response) {
        return response.json().then(function (body) {
          return { status: response.status, body: body };
        });
      })
      .then(function (result) {
        if (result.status === 200) {
          jobsById[jobId] = result.body.data;
          renderAndBind();
        } else {
          var row = document.getElementById("job-row-" + jobId);
          if (row) {
            var notice = document.createElement("p");
            notice.className = "job-row__notice";
            notice.textContent =
              (result.body.error && result.body.error.message) ||
              "Il job non è più annullabile.";
            row.appendChild(notice);
          }
        }
      })
      .catch(function () {
        showFormError("Impossibile annullare il job. Riprova.");
      });
  }

  function loadQueue() {
    queueEl.innerHTML =
      '<div class="skeleton-row"></div><div class="skeleton-row"></div>';
    fetch(JOBS_URL + "?page=1&per_page=10")
      .then(function (response) {
        if (!response.ok) {
          throw new Error("queue fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        jobOrder = [];
        jobsById = {};
        body.data.forEach(function (job) {
          jobsById[job.id] = job;
          jobOrder.push(job.id);
        });
        renderAndBind();
        jobOrder.forEach(function (id) {
          if (!isTerminal(jobsById[id].status)) {
            attachLiveJob(id);
          }
        });
      })
      .catch(function () {
        queueEl.innerHTML =
          '<div class="queue__error">' +
          "<span>Impossibile caricare la coda.</span>" +
          '<button type="button" class="btn btn--secondary" id="queue-retry">Riprova</button>' +
          "</div>";
        var retry = document.getElementById("queue-retry");
        if (retry) {
          retry.addEventListener("click", loadQueue);
        }
      });
  }

  loadQueue();
})();

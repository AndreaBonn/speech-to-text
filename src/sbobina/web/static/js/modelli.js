// sbobina · Whisper + Ollama model catalogue, with live download progress.
(function () {
  "use strict";

  var MODELS_URL = "/api/v1/models";
  var SYSTEM_URL = "/api/v1/system";
  var DOWNLOADS_URL = "/api/v1/models/downloads";
  // Below this fraction the bar looks frozen (the backend counts bytes
  // already cached, or writes the file only at the end): past this delay
  // switch to an indeterminate bar instead of a stuck percentage.
  var LOW_FRACTION_THRESHOLD = 0.05;
  var LOW_FRACTION_DELAY_MS = 5000;
  var RERENDER_POLL_MS = 1000;

  var whisperStatusEl = document.getElementById("models-whisper-status");
  var whisperTbody = document.getElementById("models-whisper-tbody");
  var ollamaBanner = document.getElementById("models-ollama-banner");
  var ollamaList = document.getElementById("models-ollama-list");
  var ollamaForm = document.getElementById("ollama-download-form");
  var ollamaNameInput = document.getElementById("ollama-download-name");
  var ollamaNameError = document.getElementById("ollama-download-error");
  var ollamaProgressEl = document.getElementById("ollama-download-progress");

  var catalog = { whisper: [], ollama: { status: "ready", message: "", models: [] } };
  var activeWhisperModel = null;
  // key "source:name" -> latest DownloadState.to_json()
  var downloads = {};
  // key "source:name" -> timestamp (ms) since fraction first dropped/stayed
  // below LOW_FRACTION_THRESHOLD, cleared once it moves past it or the
  // download leaves the "running" state.
  var lowFractionSince = {};
  var eventSource = null;

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

  function formatBytes(bytes) {
    if (bytes === null || bytes === undefined) {
      return null;
    }
    if (bytes >= 1024 * 1024 * 1024) {
      return (
        (bytes / (1024 * 1024 * 1024)).toLocaleString("it-IT", {
          maximumFractionDigits: 1,
        }) + " GB"
      );
    }
    if (bytes >= 1024 * 1024) {
      return (
        (bytes / (1024 * 1024)).toLocaleString("it-IT", {
          maximumFractionDigits: 1,
        }) + " MB"
      );
    }
    return Math.ceil(bytes / 1024) + " KB";
  }

  function downloadKey(source, name) {
    return source + ":" + name;
  }

  // Updates lowFractionSince for this download: starts the clock the first
  // time the fraction is seen below threshold, clears it as soon as the
  // fraction moves past it (real progress resumed).
  function trackFraction(key, state) {
    var hasFraction = state && typeof state.fraction === "number";
    if (!hasFraction || state.fraction >= LOW_FRACTION_THRESHOLD) {
      delete lowFractionSince[key];
      return;
    }
    if (!lowFractionSince[key]) {
      lowFractionSince[key] = Date.now();
    }
  }

  // ---------- progress markup ----------

  function progressMarkup(state, key) {
    if (!state || state.status !== "running") {
      return "";
    }
    var hasFraction = typeof state.fraction === "number";
    var stalled =
      hasFraction &&
      state.fraction < LOW_FRACTION_THRESHOLD &&
      !!lowFractionSince[key] &&
      Date.now() - lowFractionSince[key] >= LOW_FRACTION_DELAY_MS;
    var showFraction = hasFraction && !stalled;
    var style = showFraction
      ? ' style="--progress-value: ' + state.fraction + '"'
      : "";
    var trackClass = showFraction
      ? "progress__track"
      : "progress__track progress--indeterminate";
    var metaParts = [];
    if (stalled) {
      metaParts.push("Download in corso…");
    } else if (showFraction) {
      metaParts.push(Math.round(state.fraction * 100) + "%");
    }
    var completed = formatBytes(state.completed);
    var total = formatBytes(state.total);
    if (completed && total) {
      metaParts.push(completed + " di " + total);
    } else if (completed) {
      metaParts.push(completed);
    }
    return (
      '<div class="progress">' +
      '<div class="' + trackClass + '"><div class="progress__fill"' + style + "></div></div>" +
      (metaParts.length
        ? '<div class="progress__meta">' + metaParts.join(" · ") + "</div>"
        : "") +
      "</div>"
    );
  }

  function errorMarkup(state) {
    if (!state || state.status !== "failed") {
      return "";
    }
    return (
      '<p class="field__error">' + escapeHtml(state.message || "Download non riuscito.") + "</p>"
    );
  }

  // ---------- whisper table ----------

  function whisperStatusBadge(model) {
    return model.downloaded
      ? '<span class="badge badge--done">Scaricato</span>'
      : '<span class="badge badge--queued">Non scaricato</span>';
  }

  function whisperTags(model) {
    var tags = [];
    if (model.recommended_gpu) {
      tags.push("Consigliato per GPU");
    }
    if (model.recommended_cpu) {
      tags.push("Consigliato per CPU");
    }
    if (activeWhisperModel && (model.name === activeWhisperModel || model.aliases.indexOf(activeWhisperModel) !== -1)) {
      tags.push("In uso ora");
    }
    if (tags.length === 0) {
      return "";
    }
    return '<p class="models__tags">' + tags.join(" · ") + "</p>";
  }

  function whisperAction(model) {
    var key = downloadKey("whisper", model.name);
    var state = downloads[key];
    if (state && state.status === "running") {
      return progressMarkup(state, key);
    }
    if (model.downloaded && !(state && state.status === "failed")) {
      return "—";
    }
    var label = state && state.status === "failed" ? "Riprova" : "Scarica";
    return (
      errorMarkup(state) +
      '<button type="button" class="btn btn--secondary" data-download-source="whisper" data-download-name="' +
        escapeHtml(model.name) +
        '">' +
        label +
        "</button>"
    );
  }

  function whisperRow(model) {
    var names = [model.name].concat(model.aliases).join(", ");
    var size = formatBytes(model.size_bytes);
    return (
      '<tr>' +
      '<td class="cell-name" data-label="Modello">' + escapeHtml(names) + "</td>" +
      '<td data-label="Dimensione">' + (size || "—") + "</td>" +
      '<td data-label="Stato">' + whisperStatusBadge(model) + whisperTags(model) + "</td>" +
      '<td class="cell-actions" data-label="Azione">' + whisperAction(model) + "</td>" +
      "</tr>"
    );
  }

  function renderWhisper() {
    if (catalog.whisper.length === 0) {
      whisperTbody.innerHTML = '<tr><td colspan="4">Nessun modello Whisper disponibile.</td></tr>';
      return;
    }
    whisperTbody.innerHTML = catalog.whisper.map(whisperRow).join("");
    whisperTbody.querySelectorAll("[data-download-source]").forEach(function (button) {
      button.addEventListener("click", function () {
        startDownload(
          button.getAttribute("data-download-source"),
          button.getAttribute("data-download-name")
        );
      });
    });
  }

  // ---------- ollama section ----------

  function renderOllamaBanner() {
    var ollama = catalog.ollama;
    if (ollama.status === "ready") {
      ollamaBanner.innerHTML = "";
      return;
    }
    ollamaBanner.innerHTML =
      '<div class="banner banner--warning">' + escapeHtml(ollama.message) + "</div>";
  }

  function ollamaModelRow(model) {
    var key = downloadKey("ollama", model.model);
    var state = downloads[key];
    return (
      '<div class="models__ollama-row">' +
      '<span class="cell-name">' + escapeHtml(model.model) + "</span>" +
      '<span>' + (formatBytes(model.size) || "—") + "</span>" +
      (state && state.status === "running" ? progressMarkup(state, key) : "") +
      "</div>"
    );
  }

  function renderOllamaList() {
    renderOllamaBanner();
    var models = catalog.ollama.models;
    if (models.length === 0) {
      ollamaList.innerHTML =
        '<p class="models__tags">Nessun modello Ollama installato.</p>';
      return;
    }
    ollamaList.innerHTML = models.map(ollamaModelRow).join("");
  }

  function renderOllamaDownloadProgress() {
    var runningKeys = Object.keys(downloads).filter(function (key) {
      return key.indexOf("ollama:") === 0 && downloads[key].status !== "done";
    });
    // Models already installed render their own progress row; only show a
    // standalone row here for a name typed into the form (not yet listed).
    var installed = catalog.ollama.models.map(function (model) {
      return downloadKey("ollama", model.model);
    });
    var pending = runningKeys.filter(function (key) {
      return installed.indexOf(key) === -1;
    });
    if (pending.length === 0) {
      ollamaProgressEl.innerHTML = "";
      return;
    }
    ollamaProgressEl.innerHTML = pending
      .map(function (key) {
        var state = downloads[key];
        return (
          '<div class="models__ollama-row">' +
          '<span class="cell-name">' + escapeHtml(state.name) + "</span>" +
          progressMarkup(state, key) +
          errorMarkup(state) +
          "</div>"
        );
      })
      .join("");
  }

  function renderAll() {
    renderWhisper();
    renderOllamaList();
    renderOllamaDownloadProgress();
  }

  // ---------- data loading ----------

  function loadCatalog() {
    return fetch(MODELS_URL)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("models fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        catalog = body.data;
        renderAll();
      })
      .catch(function () {
        whisperTbody.innerHTML =
          '<tr><td colspan="4">Elenco non disponibile: usa Riprova qui sopra.</td></tr>';
        whisperStatusEl.hidden = false;
        whisperStatusEl.innerHTML =
          '<div class="queue__error"><span>Impossibile caricare l\'elenco dei modelli.</span>' +
          '<button type="button" class="btn btn--secondary" id="models-retry">Riprova</button></div>';
        document.getElementById("models-retry").addEventListener("click", loadCatalog);
      });
  }

  function loadSystem() {
    fetch(SYSTEM_URL)
      .then(function (response) {
        return response.json();
      })
      .then(function (body) {
        activeWhisperModel = body.data.whisper_model;
        renderWhisper();
      })
      .catch(function () {
        // Not critical: the table still works without the "in use" tag.
      });
  }

  // ---------- downloads ----------

  function startDownload(source, name) {
    fetch(DOWNLOADS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: source, name: name }),
    })
      .then(function (response) {
        return response.json().then(function (body) {
          return { status: response.status, body: body };
        });
      })
      .then(function (result) {
        if (result.status === 202) {
          var startKey = downloadKey(source, name);
          downloads[startKey] = result.body.data;
          trackFraction(startKey, result.body.data);
          renderAll();
          return;
        }
        var message =
          (result.body.error && result.body.error.message) ||
          "Impossibile avviare il download.";
        if (source === "ollama") {
          ollamaNameError.hidden = false;
          ollamaNameError.textContent = message;
        } else {
          whisperStatusEl.hidden = false;
          whisperStatusEl.innerHTML = '<div class="banner banner--warning">' + escapeHtml(message) + "</div>";
        }
      })
      .catch(function () {
        whisperStatusEl.hidden = false;
        whisperStatusEl.innerHTML =
          '<div class="banner banner--warning">Impossibile contattare il server.</div>';
      });
  }

  ollamaForm.addEventListener("submit", function (event) {
    event.preventDefault();
    ollamaNameError.hidden = true;
    var name = ollamaNameInput.value.trim();
    if (!name) {
      ollamaNameError.hidden = false;
      ollamaNameError.textContent = "Scrivi il nome di un modello Ollama.";
      return;
    }
    startDownload("ollama", name);
  });

  function attachDownloadEvents() {
    eventSource = new EventSource(DOWNLOADS_URL + "/events");
    eventSource.addEventListener("progress", function (event) {
      var state = JSON.parse(event.data);
      var key = downloadKey(state.source, state.name);
      downloads[key] = state;
      trackFraction(key, state);
      renderAll();
    });
    eventSource.addEventListener("end", function (event) {
      var state = JSON.parse(event.data);
      var key = downloadKey(state.source, state.name);
      downloads[key] = state;
      delete lowFractionSince[key];
      if (state.status === "done") {
        loadCatalog().then(function () {
          delete downloads[key];
          renderAll();
        });
      } else {
        renderAll();
      }
    });
  }

  // Terminal statuses only arrive via SSE events; a download whose fraction
  // crosses the stall threshold between two events still needs a re-render
  // so the bar flips to indeterminate without waiting on backend activity.
  function pollStalledDownloads() {
    var hasRunning = Object.keys(downloads).some(function (key) {
      return downloads[key].status === "running";
    });
    if (hasRunning) {
      renderAll();
    }
  }

  loadCatalog();
  loadSystem();
  attachDownloadEvents();
  setInterval(pollStalledDownloads, RERENDER_POLL_MS);
})();

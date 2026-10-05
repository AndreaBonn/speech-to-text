// sbobina · synchronised reader: word-level transcript, highlight driven by
// the audio bar in reader-audio.js.
// Vanilla JS, no build step, no CDN. Builds the DOM once per transcript load
// (DocumentFragment) and uses event delegation: a 2-hour lecture is ~15-20k
// words, one listener per word would be the slow path.
(function () {
  "use strict";

  var readerRoot = document.querySelector(".reader");
  if (!readerRoot) {
    // not_found state: base.html's inline script still ran, reader.js has
    // nothing to attach to.
    return;
  }

  var JOB_ID = readerRoot.dataset.jobId;
  var TRANSCRIPT_URL = "/api/v1/jobs/" + JOB_ID + "/transcript";

  var statusEl = document.getElementById("reader-status");
  var textEl = document.getElementById("reader-text");
  var pointsEl = document.getElementById("reader-points");
  var variantSwitch = document.getElementById("variant-switch");
  var downloadCorrectedMd = document.getElementById("download-corrected-md");
  var downloadReport = document.getElementById("download-report");
  var exportDocx = document.getElementById("export-docx");
  var exportTxt = document.getElementById("export-txt");

  var currentVariant = "original";
  var currentRevision = null; // of the text on screen; edits must quote it
  var highlighter = window.SbobinaReaderHighlight.create();

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

  function formatTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) {
      seconds = 0;
    }
    var total = Math.floor(seconds);
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    var mm = h > 0 ? String(m).padStart(2, "0") : String(m);
    var ss = String(s).padStart(2, "0");
    return h > 0 ? h + ":" + mm + ":" + ss : mm + ":" + ss;
  }

  function showStatus(message, kind) {
    statusEl.className = "reader__status banner banner--" + (kind || "warning");
    statusEl.textContent = message;
  }

  function clearStatus() {
    statusEl.className = "reader__status";
    statusEl.textContent = "";
  }

  function showTranscriptError(message) {
    textEl.innerHTML =
      '<div class="empty-state" role="alert">' +
      '<p class="empty-state__text">' + escapeHtml(message) + "</p>" +
      '<a class="btn btn--secondary" href="/storico">Vai allo storico</a>' +
      "</div>";
    pointsEl.innerHTML = "";
    audio.hide();
  }

  function showSkeleton() {
    textEl.innerHTML =
      '<div class="skeleton-row"></div>' +
      '<div class="skeleton-row"></div>' +
      '<div class="skeleton-row"></div>';
  }

  function fetchJSON(url) {
    return fetch(url).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) {
          var message =
            (body && body.error && body.error.message) || "Errore imprevisto.";
          var error = new Error(message);
          error.status = response.status;
          throw error;
        }
        return body;
      });
    });
  }

  // ---------- transcript DOM ----------

  var buildWordSpan = window.SbobinaReaderWords.buildWordSpan;

  function buildParagraph(paragraph) {
    var row = document.createElement("div");
    row.className = "reader__paragraph";

    var time = document.createElement("span");
    time.className = "reader__paragraph-time";
    time.textContent = paragraph.length ? formatTime(paragraph[0].start) : "";
    row.appendChild(time);

    var textWrap = document.createElement("div");
    textWrap.className = "reader__paragraph-text";
    paragraph.forEach(function (word) {
      // word.text carries its own leading space ("teorema" -> " teorema").
      // Keep that space as a plain text node outside the span, otherwise the
      // uncertain marker and the corrected underline bleed into the gap
      // before the word.
      var leadingSpace = /^\s+/.exec(word.text);
      if (leadingSpace) {
        textWrap.appendChild(document.createTextNode(leadingSpace[0]));
      }
      var displayText = leadingSpace
        ? word.text.slice(leadingSpace[0].length)
        : word.text;
      var span = buildWordSpan(word, displayText);
      highlighter.add({ start: word.start, end: word.end, el: span });
      textWrap.appendChild(span);
    });
    row.appendChild(textWrap);
    return row;
  }

  function renderTranscript(paragraphs) {
    highlighter.reset();
    var fragment = document.createDocumentFragment();
    if (paragraphs.length === 0) {
      var empty = document.createElement("div");
      empty.className = "empty-state";
      empty.innerHTML =
        '<p class="empty-state__text">La trascrizione non contiene testo.</p>';
      fragment.appendChild(empty);
    } else {
      paragraphs.forEach(function (paragraph) {
        fragment.appendChild(buildParagraph(paragraph));
      });
    }
    textEl.replaceChildren(fragment);
  }

  // ---------- transcript loading ----------

  function loadTranscript(variant) {
    showSkeleton();
    pointsEl.innerHTML = "";
    return fetchJSON(TRANSCRIPT_URL + "?variant=" + variant).then(function (body) {
      currentVariant = variant;
      setActiveVariantButton(variant);
      updateExportLinks(variant);
      applyPayload(body);
      readerRoot.dispatchEvent(
        new CustomEvent("reader:variant", { detail: { variant: variant } })
      );
    });
  }

  function applyPayload(body) {
    currentRevision = body.meta.revision;
    renderTranscript(body.data.paragraphs);
    window.SbobinaReaderPoints.render(pointsEl, body.data.review_points, formatTime);
  }

  // DOCX and TXT follow the version on screen: what you read is what you get.
  function updateExportLinks(variant) {
    var base = "/api/v1/jobs/" + JOB_ID + "/export/";
    exportDocx.href = base + "docx?variant=" + variant;
    exportTxt.href = base + "txt?variant=" + variant;
  }

  function showCorrectedControls() {
    variantSwitch.hidden = false;
    downloadCorrectedMd.hidden = false;
  }

  function checkCorrectedAvailable() {
    fetchJSON(TRANSCRIPT_URL + "?variant=corrected")
      .then(function () {
        showCorrectedControls();
        downloadReport.hidden = false;
      })
      .catch(function () {
        // No corrected variant on disk: the switch and its downloads stay
        // hidden, original is the only thing there is to read.
      });
  }

  function setActiveVariantButton(variant) {
    variantSwitch.querySelectorAll(".segmented__option").forEach(function (button) {
      button.classList.toggle("is-active", button.dataset.variant === variant);
    });
  }

  function switchVariant(variant) {
    setActiveVariantButton(variant);
    return loadTranscript(variant).catch(function (error) {
      showTranscriptError(error.message || "Impossibile caricare la correzione.");
      throw error;
    });
  }

  variantSwitch.addEventListener("click", function (event) {
    var button = event.target.closest(".segmented__option");
    if (!button || button.dataset.variant === currentVariant) {
      return;
    }
    switchVariant(button.dataset.variant).catch(function () {
      // Already shown by switchVariant.
    });
  });

  var audio = window.SbobinaReaderAudio.attach({
    formatTime: formatTime,
    onTime: highlighter.highlight,
    showStatus: showStatus,
  });
  var seekTo = audio.seekTo;
  var seekAndPlay = audio.seekAndPlay;

  // ---------- word + review-point activation (event delegation) ----------

  // In edit mode a click selects words: reader-edit.js owns it.
  function isEditing() {
    return readerRoot.classList.contains("is-editing");
  }

  textEl.addEventListener("click", function (event) {
    if (isEditing()) {
      return;
    }
    var span = event.target.closest(".word");
    if (span) {
      seekAndPlay(parseFloat(span.dataset.start));
    }
  });

  textEl.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" || isEditing()) {
      return;
    }
    var span = event.target.closest(".word");
    if (span) {
      event.preventDefault();
      seekAndPlay(parseFloat(span.dataset.start));
    }
  });

  pointsEl.addEventListener("click", function (event) {
    var button = event.target.closest(".reader__point");
    if (button) {
      seekAndPlay(parseFloat(button.dataset.start));
    }
  });

  // ---------- API for reader-edit.js ----------

  window.sbobinaReader = {
    variant: function () {
      return currentVariant;
    },
    revision: function () {
      return currentRevision;
    },
    switchVariant: switchVariant,
    applyPayload: applyPayload,
    showCorrectedControls: showCorrectedControls,
    seekTo: seekTo,
    seekAndPlay: seekAndPlay,
    showStatus: showStatus,
  };

  // ---------- init ----------

  clearStatus();
  loadTranscript("original")
    .then(function () {
      audio.show();
      checkCorrectedAvailable();
    })
    .catch(function (error) {
      var message =
        error.status === 404
          ? "La trascrizione non è ancora pronta per questo job."
          : error.message || "Impossibile caricare la trascrizione.";
      showTranscriptError(message);
    });
})();

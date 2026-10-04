// sbobina · synchronised reader: word-level transcript + sticky audio bar.
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
  var MANUAL_SCROLL_QUIET_MS = 1200;

  var statusEl = document.getElementById("reader-status");
  var textEl = document.getElementById("reader-text");
  var pointsEl = document.getElementById("reader-points");
  var variantSwitch = document.getElementById("variant-switch");
  var downloadCorrectedMd = document.getElementById("download-corrected-md");
  var downloadReport = document.getElementById("download-report");
  var exportDocx = document.getElementById("export-docx");
  var exportTxt = document.getElementById("export-txt");
  var audioBar = document.getElementById("audio-bar");
  var player = document.getElementById("audio-player");
  var playButton = document.getElementById("audio-playpause");
  var playIcon = document.getElementById("audio-playpause-icon");
  var backButton = document.getElementById("audio-back");
  var forwardButton = document.getElementById("audio-forward");
  var timeEl = document.getElementById("audio-time");
  var seekInput = document.getElementById("audio-seek");
  var speedSelect = document.getElementById("audio-speed");

  var SEEK_STEPS = 1000;
  var SKIP_SECONDS = 10;

  var currentVariant = "original";
  var currentRevision = null; // of the text on screen; edits must quote it
  var words = []; // flat, chronological: [{start, end, el}]
  var currentWordEl = null;
  var lastManualScrollAt = 0;
  var isSeekDragging = false;

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
    audioBar.hidden = true;
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

  function wordClassName(word) {
    var classes = ["word"];
    if (word.uncertain) {
      classes.push("word--uncertain");
    }
    if (word.corrected_from) {
      classes.push("word--corrected");
    }
    return classes.join(" ");
  }

  function buildWordSpan(word, displayText) {
    var span = document.createElement("span");
    span.className = wordClassName(word);
    span.dataset.start = String(word.start);
    span.dataset.end = String(word.end);
    span.dataset.index = String(word.index);
    span.dataset.segment = String(word.segment);
    // Raw text with its leading space: the edit module sends it back as the
    // text the user saw, and textContent would include the sr-only note.
    span.dataset.text = word.text;
    span.tabIndex = 0;
    span.textContent = displayText;
    if (word.corrected_from) {
      span.title = "prima: " + word.corrected_from;
      var srNote = document.createElement("span");
      srNote.className = "sr-only";
      srNote.textContent = " (prima: " + word.corrected_from + ")";
      span.appendChild(srNote);
    }
    return span;
  }

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
      words.push({ start: word.start, end: word.end, el: span });
      textWrap.appendChild(span);
    });
    row.appendChild(textWrap);
    return row;
  }

  function renderTranscript(paragraphs) {
    words = [];
    currentWordEl = null;
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

  function renderPoints(points) {
    if (points.length === 0) {
      pointsEl.innerHTML =
        '<p class="reader__points-empty">Nessun punto incerto da riascoltare.</p>';
      return;
    }
    var fragment = document.createDocumentFragment();
    var list = document.createElement("ul");
    list.className = "reader__points-list";
    points.forEach(function (point, index) {
      var li = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "reader__point";
      button.dataset.start = String(point.start);
      button.innerHTML =
        '<span class="reader__point-time">' + formatTime(point.start) + "</span>" +
        '<span class="reader__point-text">' +
        escapeHtml(point.before ? point.before + " " : "") +
        "<mark>" + escapeHtml(point.text) + "</mark>" +
        escapeHtml(point.after ? " " + point.after : "") +
        "</span>";
      li.appendChild(button);
      list.appendChild(li);
      void index;
    });
    fragment.appendChild(list);
    pointsEl.replaceChildren(fragment);
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
    renderPoints(body.data.review_points);
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

  // ---------- audio bar ----------

  function clampTime(seconds) {
    var duration = isFinite(player.duration) ? player.duration : seconds;
    return Math.max(0, Math.min(seconds, duration));
  }

  function seekTo(seconds) {
    player.currentTime = clampTime(seconds);
  }

  function seekAndPlay(seconds) {
    player.currentTime = clampTime(seconds);
    player.play().catch(function () {
      // Autoplay can still be refused by the browser; the transport stays
      // paused and the user can press play again.
    });
  }

  function updatePlayIcon() {
    playIcon.innerHTML = player.paused ? "&#9654;" : "&#10073;&#10073;";
    playButton.setAttribute(
      "aria-label",
      player.paused ? "Riproduci" : "Metti in pausa"
    );
  }

  playButton.addEventListener("click", function () {
    if (player.paused) {
      player.play().catch(function () {
        showStatus("Impossibile avviare la riproduzione.", "warning");
      });
    } else {
      player.pause();
    }
  });

  backButton.addEventListener("click", function () {
    seekAndPlay(player.currentTime - SKIP_SECONDS);
  });

  forwardButton.addEventListener("click", function () {
    seekAndPlay(player.currentTime + SKIP_SECONDS);
  });

  speedSelect.addEventListener("change", function () {
    player.playbackRate = parseFloat(speedSelect.value) || 1;
  });

  seekInput.addEventListener("input", function () {
    isSeekDragging = true;
    if (isFinite(player.duration)) {
      player.currentTime = (seekInput.value / SEEK_STEPS) * player.duration;
    }
  });

  seekInput.addEventListener("change", function () {
    isSeekDragging = false;
  });

  player.addEventListener("play", updatePlayIcon);
  player.addEventListener("pause", updatePlayIcon);

  player.addEventListener("loadedmetadata", function () {
    timeEl.textContent = formatTime(0) + " / " + formatTime(player.duration);
  });

  player.addEventListener("error", function () {
    showStatus(
      "Impossibile decodificare l'audio di questa lezione. Il testo resta leggibile.",
      "danger"
    );
    audioBar.hidden = true;
  });

  function findCurrentWordIndex(time) {
    var lo = 0;
    var hi = words.length - 1;
    var result = -1;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1;
      if (words[mid].start <= time) {
        result = mid;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    return result;
  }

  function highlightCurrentWord(time) {
    var index = findCurrentWordIndex(time);
    var match = index >= 0 && time <= words[index].end ? words[index] : null;
    var nextEl = match ? match.el : null;
    if (nextEl === currentWordEl) {
      return;
    }
    if (currentWordEl) {
      currentWordEl.classList.remove("word--current");
    }
    if (nextEl) {
      nextEl.classList.add("word--current");
      var recentManualScroll =
        Date.now() - lastManualScrollAt < MANUAL_SCROLL_QUIET_MS;
      if (!recentManualScroll) {
        var rect = nextEl.getBoundingClientRect();
        var outOfView = rect.top < 72 || rect.bottom > window.innerHeight - 96;
        if (outOfView) {
          nextEl.scrollIntoView({ block: "center", behavior: "smooth" });
        }
      }
    }
    currentWordEl = nextEl;
  }

  player.addEventListener("timeupdate", function () {
    if (!isSeekDragging && isFinite(player.duration) && player.duration > 0) {
      seekInput.value = String(
        Math.round((player.currentTime / player.duration) * SEEK_STEPS)
      );
    }
    timeEl.textContent =
      formatTime(player.currentTime) + " / " + formatTime(player.duration || 0);
    highlightCurrentWord(player.currentTime);
  });

  ["wheel", "touchmove"].forEach(function (eventName) {
    window.addEventListener(
      eventName,
      function () {
        lastManualScrollAt = Date.now();
      },
      { passive: true }
    );
  });

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
      audioBar.hidden = false;
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

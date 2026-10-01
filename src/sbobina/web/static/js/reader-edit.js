// sbobina · manual correction of the corrected transcript, on top of reader.js.
// Selection is a flat word range [start, end); each save sends the text the
// user saw, so the server can refuse a stale edit instead of overwriting.
(function () {
  "use strict";

  var reader = window.sbobinaReader;
  var readerRoot = document.querySelector(".reader");
  if (!reader || !readerRoot) {
    return;
  }

  var CORRECTED_URL =
    "/api/v1/jobs/" + readerRoot.dataset.jobId + "/transcript/corrected";
  var HINT =
    "Clicca una parola o trascina su una frase da correggere. " +
    "Maiuscolo+clic estende la selezione.";
  var SAVED_MESSAGE_MS = 2500;

  var textEl = document.getElementById("reader-text");
  var toggle = document.getElementById("edit-toggle");
  var panel = document.getElementById("edit-panel");
  var selectionEl = document.getElementById("edit-selection");
  var input = document.getElementById("edit-input");
  var saveButton = document.getElementById("edit-save");
  var replayButton = document.getElementById("edit-replay");
  var cancelButton = document.getElementById("edit-cancel");
  var errorEl = document.getElementById("edit-error");
  var statusEl = document.getElementById("edit-status");
  var statusTimer = null;

  var isEditing = false;
  var isSaving = false;
  var selection = null; // {start, end, expected, time}
  var anchorIndex = null;

  function request(method) {
    return function (body) {
      return fetch(CORRECTED_URL, {
        method: method,
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      }).then(function (response) {
        return response.json().then(function (payload) {
          if (!response.ok) {
            var error = new Error(
              (payload && payload.error && payload.error.message) ||
                "Errore imprevisto."
            );
            error.code = payload && payload.error && payload.error.code;
            throw error;
          }
          return payload;
        });
      });
    };
  }
  var createCorrected = request("POST");
  var saveEdit = request("PATCH");

  function setControlsEnabled(enabled) {
    input.disabled = !enabled;
    saveButton.disabled = !enabled;
    replayButton.disabled = !enabled;
    cancelButton.disabled = !enabled;
  }

  function clearSelection() {
    textEl.querySelectorAll(".word--selected").forEach(function (span) {
      span.classList.remove("word--selected");
    });
    selection = null;
    anchorIndex = null;
    input.value = "";
    selectionEl.textContent = HINT;
    errorEl.textContent = "";
    setControlsEnabled(false);
  }

  // Word spans in document order: data-index is the position in this list,
  // so a range is a slice instead of one querySelector per word.
  function spansBetween(first, last) {
    var start = Math.min(first, last);
    var end = Math.max(first, last) + 1;
    return Array.prototype.slice.call(
      textEl.querySelectorAll(".word"),
      start,
      end
    );
  }

  function markSpans(spans) {
    textEl.querySelectorAll(".word--selected").forEach(function (span) {
      span.classList.remove("word--selected");
    });
    spans.forEach(function (span) {
      span.classList.add("word--selected");
    });
  }

  function selectRange(first, last) {
    var spans = spansBetween(first, last);
    if (spans.length === 0) {
      return;
    }
    markSpans(spans);
    var start = parseInt(spans[0].dataset.index, 10);
    var end = parseInt(spans[spans.length - 1].dataset.index, 10) + 1;
    var expected = spans
      .map(function (span) {
        return span.dataset.text;
      })
      .join("")
      .trim();
    selection = {
      start: start,
      end: end,
      expected: expected,
      time: parseFloat(spans[0].dataset.start),
    };
    selectionEl.textContent = "Selezione: «" + expected + "»";
    errorEl.textContent = "";
    input.value = expected;
    setControlsEnabled(true);
    reader.seekTo(selection.time);
    input.focus();
    input.select();
  }

  function selectFromWord(span, extend) {
    var index = parseInt(span.dataset.index, 10);
    if (extend && anchorIndex !== null) {
      selectRange(anchorIndex, index);
      return;
    }
    anchorIndex = index;
    selectRange(index, index);
  }

  // Drag selection is handled on the words themselves: the spans are
  // focusable (tabindex) for keyboard users, and Chrome does not start a
  // native text selection from a focusable element.
  var dragAnchor = null;
  var dragLast = null;

  function wordIndex(event) {
    var span = event.target.closest(".word");
    return span ? parseInt(span.dataset.index, 10) : null;
  }

  textEl.addEventListener("mousedown", function (event) {
    var index = wordIndex(event);
    if (!isEditing || isSaving || event.button !== 0 || index === null) {
      return;
    }
    event.preventDefault();
    if (event.shiftKey && anchorIndex !== null) {
      dragAnchor = anchorIndex;
    } else {
      dragAnchor = index;
      anchorIndex = index;
    }
    dragLast = index;
    markSpans(spansBetween(dragAnchor, dragLast));
  });

  textEl.addEventListener("mouseover", function (event) {
    var index = wordIndex(event);
    if (dragAnchor === null || index === null || index === dragLast) {
      return;
    }
    dragLast = index;
    markSpans(spansBetween(dragAnchor, dragLast));
  });

  document.addEventListener("mouseup", function () {
    if (dragAnchor === null) {
      return;
    }
    var first = dragAnchor;
    dragAnchor = null;
    selectRange(first, dragLast);
  });

  textEl.addEventListener("keydown", function (event) {
    if (!isEditing || event.key !== "Enter") {
      return;
    }
    var span = event.target.closest(".word");
    if (span) {
      event.preventDefault();
      selectFromWord(span, event.shiftKey);
    }
  });

  function showSaved() {
    statusEl.textContent = "Correzione salvata.";
    window.clearTimeout(statusTimer);
    statusTimer = window.setTimeout(function () {
      statusEl.textContent = "";
    }, SAVED_MESSAGE_MS);
  }

  function setSaving(saving) {
    isSaving = saving;
    saveButton.setAttribute("aria-busy", String(saving));
    saveButton.innerHTML = saving
      ? '<span class="btn__spinner" aria-hidden="true"></span><span class="btn__label">Salvo…</span>'
      : '<span class="btn__label">Salva</span>';
    setControlsEnabled(!saving && selection !== null);
  }

  function reloadAfterConflict(message) {
    var typed = input.value;
    reader.switchVariant("corrected").then(function () {
      clearSelection();
      // Keep what the user typed: the next selection would overwrite it.
      errorEl.textContent = message + " Testo digitato: «" + typed + "».";
    });
  }

  panel.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!selection || isSaving) {
      return;
    }
    var scrollY = window.scrollY;
    setSaving(true);
    saveEdit({
      start: selection.start,
      end: selection.end,
      expected: selection.expected,
      text: input.value,
      revision: reader.revision(),
    })
      .then(function (body) {
        setSaving(false);
        reader.applyPayload(body);
        window.scrollTo(0, scrollY);
        clearSelection();
        showSaved();
      })
      .catch(function (error) {
        setSaving(false);
        if (error.code === "EDIT_CONFLICT") {
          reloadAfterConflict(
            "Il testo era cambiato (forse in un'altra scheda): ho ricaricato la versione salvata."
          );
          return;
        }
        errorEl.textContent = error.message || "Salvataggio non riuscito.";
      });
  });

  input.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      event.preventDefault();
      clearSelection();
    }
  });

  cancelButton.addEventListener("click", clearSelection);

  replayButton.addEventListener("click", function () {
    if (selection) {
      reader.seekAndPlay(selection.time);
    }
  });

  function setEditing(editing) {
    isEditing = editing;
    readerRoot.classList.toggle("is-editing", editing);
    panel.hidden = !editing;
    toggle.setAttribute("aria-pressed", String(editing));
    toggle.textContent = editing ? "Fine correzioni" : "Correggi a mano";
    clearSelection();
  }

  function startEditing() {
    toggle.disabled = true;
    createCorrected()
      .then(function () {
        reader.showCorrectedControls();
        return reader.variant() === "corrected"
          ? null
          : reader.switchVariant("corrected");
      })
      .then(function () {
        setEditing(true);
      })
      .catch(function (error) {
        reader.showStatus(
          error.message || "Impossibile aprire la versione corretta.",
          "danger"
        );
      })
      .finally(function () {
        toggle.disabled = false;
      });
  }

  toggle.addEventListener("click", function () {
    if (isEditing) {
      setEditing(false);
    } else {
      startEditing();
    }
  });

  // Edits only apply to the corrected text: leaving it ends edit mode.
  readerRoot.addEventListener("reader:variant", function (event) {
    if (isEditing && event.detail.variant !== "corrected") {
      setEditing(false);
    }
  });
})();

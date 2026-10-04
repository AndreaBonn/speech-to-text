// sbobina · create a flashcard from a text selection in the reader. The
// selection model mirrors reader-edit.js: word spans carry data-index (flat
// position in the transcript), data-start and data-text (raw text with its
// leading space); job_id comes from readerRoot.dataset.jobId and the
// revision from window.sbobinaReader.revision(), same two sources
// reader-edit.js reads. Unlike reader-edit.js this does not require edit
// mode: it watches the browser's own text selection instead of a click/drag
// word range, so "Crea carta" works on the plain reading view too.
(function () {
  "use strict";

  var readerRoot = document.querySelector(".reader");
  var textEl = document.getElementById("reader-text");
  var trigger = document.getElementById("reader-card-trigger");
  var dialog = document.getElementById("reader-card-dialog");
  var reader = window.sbobinaReader;
  if (!readerRoot || !textEl || !trigger || !dialog || !reader) {
    return;
  }

  var JOB_ID = readerRoot.dataset.jobId;
  var COURSES_URL = "/api/v1/courses?per_page=100";
  var FAILED_MESSAGE =
    "Creazione non riuscita. Controlla che il server sia attivo e riprova.";
  var NO_COURSE_MESSAGE =
    "Nessun corso associato a questa lezione: imposta un corso per creare carte.";
  var SOURCE_CHANGED_MESSAGE = "Il testo è cambiato: ricarica la pagina.";
  var TRIGGER_MARGIN = 8;
  var TRIGGER_GAP = 4;

  var form = document.getElementById("reader-card-form");
  var frontInput = document.getElementById("reader-card-front");
  var backInput = document.getElementById("reader-card-back");
  var frontError = document.getElementById("reader-card-front-error");
  var backError = document.getElementById("reader-card-back-error");
  var errorEl = document.getElementById("reader-card-error");
  var successBanner = document.getElementById("reader-card-success");
  var cancelButton = document.getElementById("reader-card-cancel");
  var submitButton = document.getElementById("reader-card-submit");
  var courseInput = document.getElementById("course-input");

  var pendingSelection = null; // {segmentIndex, quote}
  var isSaving = false;

  function isEditing() {
    return readerRoot.classList.contains("is-editing");
  }

  // ---------- field errors ----------

  function clearErrors() {
    frontError.hidden = true;
    frontError.textContent = "";
    backError.hidden = true;
    backError.textContent = "";
    errorEl.textContent = "";
    frontInput.classList.remove("is-invalid");
    backInput.classList.remove("is-invalid");
  }

  function showFieldError(field, message) {
    var el = field === "back" ? backError : frontError;
    var input = field === "back" ? backInput : frontInput;
    el.textContent = message;
    el.hidden = false;
    input.classList.add("is-invalid");
  }

  function showSavedMessage() {
    successBanner.textContent = "";
    successBanner.appendChild(
      document.createTextNode("Carta aggiunta al ripasso. ")
    );
    var link = document.createElement("a");
    link.href = "/ripasso";
    link.textContent = "Vai al ripasso";
    successBanner.appendChild(link);
    successBanner.hidden = false;
  }

  function applyServerError(body) {
    var error = (body && body.error) || {};
    if (error.code === "SOURCE_CHANGED") {
      errorEl.textContent = SOURCE_CHANGED_MESSAGE;
      return;
    }
    var handled = false;
    (error.details || []).forEach(function (detail) {
      if (/front$/.test(detail.field || "")) {
        showFieldError("front", detail.message);
        handled = true;
      } else if (/back$/.test(detail.field || "")) {
        showFieldError("back", detail.message);
        handled = true;
      }
    });
    if (!handled) {
      errorEl.textContent = error.message || FAILED_MESSAGE;
    }
  }

  // ---------- selection -> trigger button ----------

  function wordsInSelection(range) {
    var spans = textEl.querySelectorAll(".word");
    var result = [];
    for (var i = 0; i < spans.length; i++) {
      if (range.intersectsNode(spans[i])) {
        result.push(spans[i]);
      }
    }
    return result;
  }

  function hideTrigger() {
    trigger.hidden = true;
    pendingSelection = null;
  }

  function placeTrigger(range) {
    var rect = range.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) {
      hideTrigger();
      return;
    }
    // Shown first so its real size can keep it inside the viewport.
    trigger.hidden = false;
    var maxLeft = window.innerWidth - trigger.offsetWidth - TRIGGER_MARGIN;
    trigger.style.top =
      Math.max(TRIGGER_MARGIN, rect.top - trigger.offsetHeight - TRIGGER_GAP) + "px";
    trigger.style.left =
      Math.max(TRIGGER_MARGIN, Math.min(rect.left, maxLeft)) + "px";
  }

  // The transcript range the user selected, or null when it is not one.
  function transcriptRange() {
    var selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
      return null;
    }
    var range = selection.getRangeAt(0);
    var inside =
      textEl.contains(range.startContainer) && textEl.contains(range.endContainer);
    return inside ? range : null;
  }

  // Segment of the first selected word (data-segment, a real index into the
  // transcript segments) and the selected text as the card's quote.
  function selectionAnchor(range) {
    var spans = wordsInSelection(range);
    if (spans.length === 0) return null;
    var quote = spans
      .map(function (span) {
        return span.dataset.text;
      })
      .join("")
      .trim();
    if (!quote) return null;
    return { segmentIndex: parseInt(spans[0].dataset.segment, 10), quote: quote };
  }

  function onSelectionChange() {
    if (isEditing() || dialog.open) return;
    var range = transcriptRange();
    var anchor = range && selectionAnchor(range);
    if (!anchor) {
      hideTrigger();
      return;
    }
    pendingSelection = anchor;
    placeTrigger(range);
  }

  document.addEventListener("selectionchange", onSelectionChange);
  // The trigger is position:fixed: re-anchor it when the selection moves on screen.
  window.addEventListener("scroll", onSelectionChange, { passive: true });
  window.addEventListener("resize", onSelectionChange);

  // ---------- dialog ----------

  function findCourseKey() {
    var label = (courseInput && courseInput.value.trim()) || "";
    if (!label) {
      return Promise.resolve(null);
    }
    return fetch(COURSES_URL)
      .then(function (response) {
        return response.ok ? response.json() : { data: [] };
      })
      .then(function (body) {
        var match = (body.data || []).filter(function (course) {
          return course.label === label;
        })[0];
        return match ? match.key : null;
      })
      .catch(function () {
        return null;
      });
  }

  function openDialog() {
    if (!pendingSelection) {
      return;
    }
    clearErrors();
    frontInput.value = "";
    backInput.value = pendingSelection.quote;
    successBanner.hidden = true;
    dialog.showModal();
    frontInput.focus();
  }

  trigger.addEventListener("click", openDialog);
  cancelButton.addEventListener("click", function () {
    dialog.close();
  });
  dialog.addEventListener("close", function () {
    trigger.focus();
  });

  function setSaving(saving) {
    isSaving = saving;
    submitButton.disabled = saving;
    submitButton.setAttribute("aria-busy", String(saving));
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (isSaving || !pendingSelection) {
      return;
    }
    clearErrors();
    var front = frontInput.value.trim();
    if (!front) {
      showFieldError("front", "Il fronte non può essere vuoto.");
      return;
    }
    var segmentIndex = pendingSelection.segmentIndex;
    var quote = pendingSelection.quote;
    setSaving(true);
    findCourseKey()
      .then(function (key) {
        if (!key) {
          setSaving(false);
          errorEl.textContent = NO_COURSE_MESSAGE;
          return null;
        }
        return fetch("/api/v1/courses/" + encodeURIComponent(key) + "/cards", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            front: front,
            back: backInput.value.trim() || front,
            anchor: {
              kind: "lecture",
              job_id: JOB_ID,
              revision: reader.revision(),
              segment_index: segmentIndex,
              quote: quote,
            },
          }),
        });
      })
      .then(function (response) {
        if (!response) {
          return;
        }
        setSaving(false);
        return response.json().then(function (body) {
          if (!response.ok) {
            applyServerError(body);
            return;
          }
          dialog.close();
          hideTrigger();
          showSavedMessage();
        });
      })
      .catch(function () {
        setSaving(false);
        errorEl.textContent = FAILED_MESSAGE;
      });
  });
})();

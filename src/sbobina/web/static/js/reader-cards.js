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
  var reader = window.sbobinaReader;
  var cardDialog = window.SbobinaCardDialog;
  if (!readerRoot || !textEl || !trigger || !reader || !cardDialog) {
    return;
  }

  var JOB_ID = readerRoot.dataset.jobId;
  var COURSES_URL = "/api/v1/courses?per_page=100";
  var NO_COURSE_MESSAGE =
    "Nessun corso associato a questa lezione: imposta un corso per creare carte.";
  var TRIGGER_MARGIN = 8;
  var TRIGGER_GAP = 4;

  var courseInput = document.getElementById("course-input");

  var pendingSelection = null; // {segmentIndex, quote}
  var openedSelection = null; // the selection the open dialog was made from

  function isEditing() {
    return readerRoot.classList.contains("is-editing");
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
    if (isEditing() || cardForm.dialog.open) return;
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
      .catch(function (error) {
        console.error(error);
        return null;
      });
  }

  var cardForm = cardDialog.create("reader-card", {
    resolveCourseKey: findCourseKey,
    buildAnchor: function () {
      return {
        kind: "lecture",
        job_id: JOB_ID,
        revision: reader.revision(),
        segment_index: openedSelection.segmentIndex,
        quote: openedSelection.quote,
      };
    },
    noCourseMessage: NO_COURSE_MESSAGE,
    onSaved: hideTrigger,
  });

  trigger.addEventListener("click", function () {
    if (!pendingSelection) {
      return;
    }
    openedSelection = pendingSelection;
    cardForm.open(openedSelection.quote);
  });
  cardForm.dialog.addEventListener("close", function () {
    trigger.focus();
  });
})();

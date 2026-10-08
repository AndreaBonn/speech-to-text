// sbobina · reader word spans: one <span class="word"> per transcript word,
// carrying the data-* handles other reader modules read (data-index for edits,
// data-segment for card anchors, data-start for seeking, data-text raw text).
// Split out of reader.js to keep that file from growing.
(function () {
  "use strict";

  function wordClassName(word) {
    var classes = ["word"];
    if (word.uncertain) {
      classes.push("word--uncertain");
    }
    if (word.most_uncertain) {
      classes.push("word--most-uncertain");
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

  window.SbobinaReaderWords = { buildWordSpan: buildWordSpan };
})();

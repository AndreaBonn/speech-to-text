// sbobina · course detail: "Crea carta" on an exam-signal quote. Retro is
// pre-filled with the quote, Fronte empty. job_id/segment_index/quote/revision
// travel as data-* attributes set by corso-frasi-esame.js's cardButton(); this
// module listens via event delegation and never fetches the cues itself. The
// dialog itself is card-dialog.js.
(function () {
  "use strict";

  var listEl = document.getElementById("examcues-list");
  var examCues = window.SbobinaCourseExamCues;
  var cardDialog = window.SbobinaCardDialog;
  if (!listEl || !examCues || !cardDialog) {
    return;
  }

  var anchor = null;
  var dialog = cardDialog.create("examcue-card", {
    resolveCourseKey: function () {
      return Promise.resolve(examCues.currentKey());
    },
    buildAnchor: function () {
      return anchor;
    },
  });

  listEl.addEventListener("click", function (event) {
    var button = event.target.closest(".examcues__card-btn");
    if (!button) {
      return;
    }
    anchor = {
      kind: "lecture",
      job_id: button.dataset.jobId,
      revision: button.dataset.revision || null,
      segment_index: parseInt(button.dataset.segmentIndex, 10),
      quote: button.dataset.quote,
    };
    dialog.open(anchor.quote);
  });
})();

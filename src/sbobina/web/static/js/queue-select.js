// sbobina · N3: which jobs the home queue shows. Pure logic, no DOM: active
// jobs (queued, running) and jobs that need the user's attention
// (interrupted, failed) always show; completed jobs show only the most
// recent few. Everything else (older completed, cancelled, ...) is counted
// but left to the full history page.
(function () {
  "use strict";

  var ALWAYS_VISIBLE = ["queued", "running", "interrupted", "failed"];
  var COMPLETED_STATUS = "done";
  var MAX_COMPLETED = 3;

  // jobs: array of {id, status, ...}, newest first (as the API returns them).
  // Returns the ids to render, in the same order.
  function selectVisible(jobs) {
    var visibleIds = [];
    var completedShown = 0;
    jobs.forEach(function (job) {
      if (ALWAYS_VISIBLE.indexOf(job.status) !== -1) {
        visibleIds.push(job.id);
        return;
      }
      if (job.status === COMPLETED_STATUS && completedShown < MAX_COMPLETED) {
        visibleIds.push(job.id);
        completedShown += 1;
      }
    });
    return visibleIds;
  }

  window.SbobinaQueueSelect = { selectVisible: selectVisible };
})();

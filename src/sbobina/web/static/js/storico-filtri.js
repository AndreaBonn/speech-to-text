// sbobina · history filters (T1): the three status groups a student thinks
// in, mapped to the jobs API, and their counts from meta.status_counts.
(function () {
  "use strict";

  var UNFINISHED = ["cancelled", "interrupted", "failed"];
  var STATUSES = { all: [], done: ["done"], unfinished: UNFINISHED };

  function statusQuery(filter) {
    var statuses = STATUSES[filter] || [];
    return statuses
      .map(function (status) {
        return "&status=" + status;
      })
      .join("");
  }

  function counts(statusCounts) {
    var all = 0;
    Object.keys(statusCounts).forEach(function (status) {
      all += statusCounts[status];
    });
    var unfinished = 0;
    UNFINISHED.forEach(function (status) {
      unfinished += statusCounts[status] || 0;
    });
    return { all: all, done: statusCounts.done || 0, unfinished: unfinished };
  }

  window.SbobinaHistoryFilters = {
    statusQuery: statusQuery,
    counts: counts,
    unfinished: UNFINISHED,
  };
})();

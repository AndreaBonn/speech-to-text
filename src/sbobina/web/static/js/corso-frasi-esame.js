// sbobina · course detail: "Frasi da esame" section. Lists the exam-signal
// quotes found by GET /api/v1/courses/<key>/exam-cues, grouped by lecture,
// strong by default with a toggle for the weaker signals. Quotes come from
// the transcript (user speech), so they reach the DOM only via textContent,
// same discipline as the reader (see dom.js).
(function () {
  "use strict";

  var dom = window.SbobinaDom;
  var render = window.SbobinaExamCueRender;
  var clearChildren = dom && dom.clearChildren;
  var clearStatus = dom && dom.clearStatus;
  var showRetryStatus = dom && dom.showRetryStatus;
  var renderPagination = dom && dom.renderPagination;

  var PER_PAGE = 20;
  var JOBS_PER_PAGE = 200;
  var SLOW_MS = 15000;
  var STRONG_LEVEL = "strong";
  var ALL_LEVELS = "all";

  var sectionEl = document.getElementById("corsi-examcues");
  var toggleEl = document.getElementById("examcues-toggle");
  var statusEl = document.getElementById("examcues-status");
  var listEl = document.getElementById("examcues-list");
  var emptyEl = document.getElementById("examcues-empty");
  var emptyTextEl = document.getElementById("examcues-empty-text");
  var paginationEl = document.getElementById("examcues-pagination");
  var unavailableEl = document.getElementById("examcues-unavailable");

  if (!sectionEl || !dom || !render) {
    return;
  }

  var currentKey = null;
  var currentPage = 1;
  var titlesByJob = {};
  var slowTimer = null;
  var latestRequest = 0;

  var jobTitle = dom && dom.jobTitle;

  function currentLevel() {
    return toggleEl.checked ? ALL_LEVELS : STRONG_LEVEL;
  }

  function cuesUrl(key, level, page) {
    return (
      "/api/v1/courses/" +
      encodeURIComponent(key) +
      "/exam-cues?level=" +
      level +
      "&page=" +
      page +
      "&per_page=" +
      PER_PAGE
    );
  }

  function titlesUrl(key, page) {
    return (
      "/api/v1/jobs?course=" +
      encodeURIComponent(key) +
      "&page=" +
      page +
      "&per_page=" +
      JOBS_PER_PAGE
    );
  }

  // Every page, so a course past JOBS_PER_PAGE lectures keeps real titles.
  function fetchTitles(key, page, map) {
    return fetch(titlesUrl(key, page))
      .then(function (response) {
        return response.ok ? response.json() : { data: [], meta: {} };
      })
      .then(function (body) {
        body.data.forEach(function (job) {
          map[job.id] = jobTitle(job);
        });
        var pages = (body.meta && body.meta.total_pages) || 1;
        // Another course was opened meanwhile: its own show() loads titles.
        if (currentKey !== key) {
          return map;
        }
        return page < pages ? fetchTitles(key, page + 1, map) : map;
      });
  }

  function loadTitles(key) {
    var map = {};
    return fetchTitles(key, 1, map).catch(function (error) {
      console.error(error);
      return map;
    });
  }

  function lectureTitle(jobId) {
    return titlesByJob[jobId] || "Lezione " + jobId.slice(0, 8);
  }

  function startSlowTimer(request) {
    clearTimeout(slowTimer);
    slowTimer = setTimeout(function () {
      if (request === latestRequest) {
        statusEl.hidden = false;
        statusEl.textContent = "Ci sta mettendo più del previsto.";
      }
    }, SLOW_MS);
  }

  function hideList() {
    clearChildren(listEl);
    listEl.hidden = true;
    paginationEl.hidden = true;
  }

  function showCues(key, page, level, body) {
    clearTimeout(slowTimer);
    clearStatus(statusEl);
    render.showUnavailable(unavailableEl, body.meta);
    if (body.data.length > 0) {
      emptyEl.hidden = true;
      listEl.hidden = false;
      render.renderGroups(listEl, body.data, lectureTitle);
      renderPagination(paginationEl, body.meta, function (nextPage) {
        load(key, nextPage);
      });
      return;
    }
    hideList();
    if (page > 1) {
      // Fewer cues than when the page was chosen (e.g. after a correction).
      load(key, 1);
      return;
    }
    emptyTextEl.textContent = render.emptyMessage(level, body.meta);
    emptyEl.hidden = false;
  }

  function showLoadError(key) {
    clearTimeout(slowTimer);
    hideList();
    showRetryStatus(statusEl, "Impossibile caricare le frasi da esame.", function () {
      load(key, currentPage);
    });
  }

  function load(key, page) {
    currentKey = key;
    currentPage = page;
    var level = currentLevel();
    var request = ++latestRequest;
    clearStatus(statusEl);
    emptyEl.hidden = true;
    unavailableEl.hidden = true;
    render.showSkeleton(listEl);
    startSlowTimer(request);
    fetch(cuesUrl(key, level, page))
      .then(function (response) {
        if (!response.ok) {
          throw new Error("exam cues fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (request === latestRequest) {
          showCues(key, page, level, body);
        }
      })
      .catch(function (error) {
        console.error(error);
        if (request === latestRequest) {
          showLoadError(key);
        }
      });
  }

  toggleEl.addEventListener("change", function () {
    if (currentKey !== null) {
      load(currentKey, 1);
    }
  });

  // ---------- public API ----------

  function show(key) {
    toggleEl.checked = false;
    currentKey = key;
    titlesByJob = {};
    render.showSkeleton(listEl);
    emptyEl.hidden = true;
    clearStatus(statusEl);
    // Lecture titles come from the same API the lecture table already uses.
    // Cues load after them; a failed title fetch falls back to short job ids.
    loadTitles(key).then(function (map) {
      if (currentKey !== key) {
        return;
      }
      titlesByJob = map;
      load(key, 1);
    });
  }

  function hide() {
    currentKey = null;
    clearTimeout(slowTimer);
  }

  window.SbobinaCourseExamCues = {
    show: show,
    hide: hide,
    currentKey: function () {
      return currentKey;
    },
  };
})();

// sbobina · course detail: "Frasi da esame" section. Lists the exam-signal
// quotes found by GET /api/v1/courses/<key>/exam-cues, grouped by lecture,
// strong by default with a toggle for the weaker signals. Quotes come from
// the transcript (user speech), so they reach the DOM only via textContent,
// same discipline as the reader (see dom.js).
(function () {
  "use strict";

  var dom = window.SbobinaDom;
  var clearChildren = dom && dom.clearChildren;
  var clearStatus = dom && dom.clearStatus;
  var showRetryStatus = dom && dom.showRetryStatus;
  var renderPagination = dom && dom.renderPagination;

  var PER_PAGE = 20;
  var JOBS_PER_PAGE = 200;
  var SLOW_MS = 15000;
  var STRONG_LEVEL = "strong";
  var ALL_LEVELS = "all";
  var LEVEL_LABELS = { strong: "forte", weak: "debole" };

  var sectionEl = document.getElementById("corsi-examcues");
  var toggleEl = document.getElementById("examcues-toggle");
  var statusEl = document.getElementById("examcues-status");
  var listEl = document.getElementById("examcues-list");
  var emptyEl = document.getElementById("examcues-empty");
  var emptyTextEl = document.getElementById("examcues-empty-text");
  var paginationEl = document.getElementById("examcues-pagination");
  var unavailableEl = document.getElementById("examcues-unavailable");

  if (!sectionEl || !dom) {
    return;
  }

  var currentKey = null;
  var currentPage = 1;
  var titlesByJob = {};
  var slowTimer = null;
  var latestRequest = 0;

  var jobTitle = dom && dom.jobTitle;
  var formatTime = dom && dom.formatTime;

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

  function loadTitles(key) {
    return fetch(
      "/api/v1/jobs?course=" + encodeURIComponent(key) + "&per_page=" + JOBS_PER_PAGE
    )
      .then(function (response) {
        return response.ok ? response.json() : { data: [] };
      })
      .then(function (body) {
        var map = {};
        body.data.forEach(function (job) {
          map[job.id] = jobTitle(job);
        });
        return map;
      })
      .catch(function (error) {
        console.error(error);
        return {};
      });
  }

  function lectureTitle(jobId) {
    return titlesByJob[jobId] || "Lezione " + jobId.slice(0, 8);
  }

  function levelBadge(level) {
    var badge = document.createElement("span");
    badge.className = "badge badge--" + level;
    badge.textContent = LEVEL_LABELS[level] || level;
    return badge;
  }

  // job_id/segment_index/quote/revision as data-*: exam-cue-cards.js reads
  // them via event delegation and never fetches the cues itself.
  function cardButton(cue) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--ghost examcues__card-btn";
    button.textContent = "Crea carta";
    button.dataset.jobId = cue.job_id;
    button.dataset.segmentIndex = cue.segment_index;
    button.dataset.quote = cue.quote;
    button.dataset.revision = cue.revision || "";
    return button;
  }

  function cueNode(cue) {
    var li = document.createElement("li");
    li.className = "examcues__cue";
    var link = document.createElement("a");
    link.className = "table__link examcues__time";
    link.href = cue.href;
    link.textContent = formatTime(cue.start);
    link.setAttribute("aria-label", "Ascolta da " + formatTime(cue.start));
    li.appendChild(link);
    li.appendChild(levelBadge(cue.level));
    var quote = document.createElement("p");
    quote.className = "examcues__quote";
    quote.textContent = cue.quote;
    li.appendChild(quote);
    li.appendChild(cardButton(cue));
    return li;
  }

  function groupNode(jobId, cues) {
    var group = document.createElement("li");
    group.className = "examcues__group";
    var heading = document.createElement("h4");
    heading.className = "examcues__group-title";
    heading.textContent = lectureTitle(jobId);
    group.appendChild(heading);
    var cuesList = document.createElement("ul");
    cuesList.className = "examcues__cues";
    cues.forEach(function (cue) {
      cuesList.appendChild(cueNode(cue));
    });
    group.appendChild(cuesList);
    return group;
  }

  function renderGroups(data) {
    clearChildren(listEl);
    var order = [];
    var byJob = {};
    data.forEach(function (cue) {
      if (!byJob[cue.job_id]) {
        byJob[cue.job_id] = [];
        order.push(cue.job_id);
      }
      byJob[cue.job_id].push(cue);
    });
    order.forEach(function (jobId) {
      listEl.appendChild(groupNode(jobId, byJob[jobId]));
    });
  }

  function showSkeleton() {
    clearChildren(listEl);
    listEl.hidden = false;
    for (var i = 0; i < 3; i++) {
      var li = document.createElement("li");
      li.className = "examcues__skeleton skeleton-row";
      listEl.appendChild(li);
    }
  }

  function emptyMessage(level) {
    if (level === ALL_LEVELS) {
      return (
        "In queste lezioni non trovo frasi in cui il docente parla " +
        "dell'esame, nemmeno fra i segnali deboli (per esempio «importante», " +
        "«attenzione»)."
      );
    }
    return (
      "In queste lezioni non trovo frasi in cui il docente parla " +
      "chiaramente dell'esame (per esempio «all'esame vi chiederò» o " +
      "«ricordatevi»). Con i segnali deboli attivi se ne vedono di più, " +
      "anche se meno affidabili."
    );
  }

  function finish() {
    clearTimeout(slowTimer);
  }

  // Lessons the server could not read are listed in meta, not silently dropped.
  function showUnavailable(meta) {
    var count = (meta && meta.unavailable_jobs ? meta.unavailable_jobs : []).length;
    unavailableEl.hidden = count === 0;
    unavailableEl.textContent = count === 1
      ? "Una lezione non è leggibile ora: le sue frasi non compaiono."
      : count + " lezioni non sono leggibili ora: le loro frasi non compaiono.";
  }

  function load(key, page) {
    currentKey = key;
    currentPage = page;
    var level = currentLevel();
    var request = ++latestRequest;
    clearStatus(statusEl);
    emptyEl.hidden = true;
    unavailableEl.hidden = true;
    showSkeleton();
    clearTimeout(slowTimer);
    slowTimer = setTimeout(function () {
      if (request === latestRequest) {
        statusEl.hidden = false;
        statusEl.textContent = "Ci sta mettendo più del previsto.";
      }
    }, SLOW_MS);
    fetch(cuesUrl(key, level, page))
      .then(function (response) {
        if (!response.ok) {
          throw new Error("exam cues fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (request !== latestRequest) {
          return;
        }
        finish();
        clearStatus(statusEl);
        showUnavailable(body.meta);
        if (body.data.length === 0) {
          clearChildren(listEl);
          listEl.hidden = true;
          paginationEl.hidden = true;
          if (page === 1) {
            emptyTextEl.textContent = emptyMessage(level);
            emptyEl.hidden = false;
          }
          return;
        }
        emptyEl.hidden = true;
        listEl.hidden = false;
        renderGroups(body.data);
        renderPagination(paginationEl, body.meta, function (nextPage) {
          load(key, nextPage);
        });
      })
      .catch(function (error) {
        console.error(error);
        if (request !== latestRequest) {
          return;
        }
        finish();
        clearChildren(listEl);
        listEl.hidden = true;
        paginationEl.hidden = true;
        showRetryStatus(statusEl, "Impossibile caricare le frasi da esame.", function () {
          load(key, currentPage);
        });
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
    showSkeleton();
    emptyEl.hidden = true;
    clearStatus(statusEl);
    // Lecture titles come from the same API the lecture table already uses;
    // cues render with a short job-id fallback until they arrive.
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

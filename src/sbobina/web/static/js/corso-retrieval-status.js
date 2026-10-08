// sbobina · course detail: semantic-search status line ("ricerca per
// significato" vs "solo parole chiave: <motivo>"), T053. Reuses the shared
// phrasing from retrieval-mode.js. The status endpoint reads every course's
// text (expensive, see semantic_index_status.py): fetched once per course
// open by corso-dettaglio.js, never polled.
(function () {
  "use strict";

  var STATUS_URL = "/api/v1/semantic-index/status";
  var el = document.getElementById("corsi-detail-retrieval");
  var textEl = document.getElementById("corsi-detail-retrieval-text");
  var mode = window.SbobinaRetrievalMode;

  function courseEntry(data, key) {
    var courses = data.courses || [];
    for (var i = 0; i < courses.length; i++) {
      if (courses[i].key === key) {
        return courses[i];
      }
    }
    return null;
  }

  // Mirrors the reason priority dense_retrieval.DenseRanker.rank applies at
  // query time, from data the status endpoint already exposes per course.
  function reportFor(data, key) {
    if (data.semantic_search === false) {
      return { mode: "bm25", reason: "disabled", coverage: null };
    }
    if (data.installed === false) {
      return { mode: "bm25", reason: data.reason || "unreachable", coverage: null };
    }
    var course = courseEntry(data, key);
    var coverage = course ? course.coverage : null;
    if (data.rebuild_needed) {
      return { mode: "bm25", reason: "rebuild_needed", coverage: coverage };
    }
    if (!coverage || coverage.total === 0) {
      return { mode: "bm25", reason: "not_indexed", coverage: coverage };
    }
    if (coverage.embedded < coverage.total) {
      return { mode: "bm25", reason: "partial", coverage: coverage };
    }
    return { mode: "dense", reason: null, coverage: coverage };
  }

  // The course shown when the last status request started: a slower answer
  // for a course the user already left must not overwrite the current one.
  var currentKey = null;

  function show(key) {
    if (!el) {
      return;
    }
    currentKey = key;
    el.hidden = false;
    el.dataset.mode = "checking";
    textEl.textContent = "Verifica della ricerca semantica…";
    fetch(STATUS_URL)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("semantic status fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (currentKey === key) {
          // C7: a state with a word, not a loose grey label.
          var report = reportFor(body.data, key);
          el.dataset.mode = report.mode;
          textEl.textContent =
            report.mode === "dense" ? "Ricerca per significato attiva" : mode.phrase(report);
        }
      })
      .catch(function () {
        if (currentKey === key) {
          el.dataset.mode = "bm25";
          textEl.textContent = "Solo parole chiave: stato della ricerca semantica non verificabile ora.";
        }
      });
  }

  function hide() {
    if (!el) {
      return;
    }
    currentKey = null;
    el.hidden = true;
    textEl.textContent = "";
  }

  window.SbobinaCourseRetrievalStatus = { show: show, hide: hide };
})();

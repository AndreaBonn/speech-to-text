// sbobina · full-text search over every lecture ("dove ha spiegato X?").
// Each result links into the reader at the passage's time. Snippets arrive as
// {text, match} parts and are built node by node: a transcript containing
// markup must show it as text, never run it.
(function () {
  "use strict";

  var SEARCH_URL = "/api/v1/search";
  var COURSES_URL = "/api/v1/courses?per_page=100";
  var ALL_COURSES = "*";
  var PER_PAGE = 10;
  var SLOW_MS = 15000;
  var MESSAGES = {
    empty: "Scrivi almeno una parola da cercare.",
    loading: "Cerco nelle lezioni…",
    slow: "La ricerca sta richiedendo più del previsto: la prima volta indicizza tutte le lezioni.",
    unavailable:
      "La ricerca non è disponibile su questo computer: SQLite non ha il modulo FTS5. Corsi e lettore funzionano.",
    failed: "Ricerca non riuscita. Controlla che il server sia attivo e riprova.",
  };

  var dom = window.SbobinaDom;
  var form = document.getElementById("search-form");
  var input = document.getElementById("search-input");
  var courseSelect = document.getElementById("search-course");
  var statusEl = document.getElementById("search-status");
  var resultsEl = document.getElementById("search-results");
  var paginationEl = document.getElementById("search-pagination");
  if (!form || !dom) {
    return;
  }
  var slowTimer = null;
  // Only the latest search may paint: an older, slower answer is dropped.
  var latestRequest = 0;

  function formatTime(seconds) {
    var total = Math.floor(seconds);
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = String(total % 60).padStart(2, "0");
    return h > 0 ? h + ":" + String(m).padStart(2, "0") + ":" + s : m + ":" + s;
  }

  function showMessage(text) {
    dom.clearChildren(statusEl);
    statusEl.textContent = text;
    statusEl.hidden = false;
  }

  function resetResults() {
    dom.clearChildren(resultsEl);
    resultsEl.hidden = true;
    paginationEl.hidden = true;
  }

  function snippetNode(parts) {
    var p = document.createElement("p");
    p.className = "search__snippet";
    parts.forEach(function (part) {
      var node = part.match ? document.createElement("mark") : document.createTextNode(part.text);
      if (part.match) {
        node.textContent = part.text;
      }
      p.appendChild(node);
    });
    return p;
  }

  function passageNode(passage) {
    var li = document.createElement("li");
    li.className = "search__passage";
    var link = document.createElement("a");
    link.className = "table__link search__time";
    link.href = passage.href;
    link.textContent = formatTime(passage.start);
    link.setAttribute("aria-label", "Ascolta da " + formatTime(passage.start));
    li.appendChild(link);
    li.appendChild(snippetNode(passage.snippet));
    return li;
  }

  function documentNode(doc) {
    var li = document.createElement("li");
    li.className = "search__lecture";
    var link = document.createElement("a");
    link.className = "search__title table__link";
    link.href = doc.href;
    link.textContent = doc.filename;
    var meta = document.createElement("p");
    meta.className = "field__helper";
    meta.textContent = (doc.course || "Senza corso") + " · pagina " + doc.page;
    li.appendChild(link);
    li.appendChild(meta);
    li.appendChild(snippetNode(doc.snippet));
    return li;
  }

  function resultsMessage(lectureCount, documentCount) {
    var parts = [];
    if (lectureCount > 0) {
      parts.push(lectureCount + (lectureCount === 1 ? " lezione trovata" : " lezioni trovate"));
    }
    if (documentCount > 0) {
      parts.push(documentCount + (documentCount === 1 ? " documento trovato" : " documenti trovati"));
    }
    return parts.join(" · ") + ".";
  }

  function lectureNode(lecture) {
    var li = document.createElement("li");
    li.className = "search__lecture";
    var title = document.createElement("h3");
    title.className = "search__title";
    title.textContent = lecture.title;
    var meta = document.createElement("p");
    meta.className = "field__helper";
    meta.textContent =
      (lecture.course || "Senza corso") + " · " + lecture.passage_count +
      (lecture.passage_count === 1 ? " passaggio" : " passaggi");
    var passages = document.createElement("ol");
    passages.className = "search__passages";
    lecture.passages.forEach(function (passage) {
      passages.appendChild(passageNode(passage));
    });
    li.appendChild(title);
    li.appendChild(meta);
    li.appendChild(passages);
    var hidden = lecture.passage_count - lecture.passages.length;
    if (hidden > 0) {
      var more = document.createElement("p");
      more.className = "field__helper";
      more.textContent = "Altri " + hidden + " passaggi in questa lezione.";
      li.appendChild(more);
    }
    return li;
  }

  function renderResults(body, query, course) {
    resetResults();
    if (body.data.length === 0) {
      showMessage("Nessun risultato per «" + query + "». Prova con meno parole o con un altro corso.");
      return;
    }
    var documentCount = body.data.filter(function (item) {
      return item.kind === "document";
    }).length;
    showMessage(resultsMessage(body.meta.total, documentCount));
    body.data.forEach(function (item) {
      resultsEl.appendChild(item.kind === "document" ? documentNode(item) : lectureNode(item));
    });
    resultsEl.hidden = false;
    dom.renderPagination(paginationEl, body.meta, function (next) {
      runSearch(query, next, course);
    });
  }

  function errorMessage(response, body) {
    if (response.status === 503) {
      return MESSAGES.unavailable;
    }
    var error = body && body.error;
    var detail = error && error.details && error.details[0];
    return (detail && detail.message) || MESSAGES.failed;
  }

  function searchUrl(query, page, course) {
    var params = new URLSearchParams({ q: query, page: String(page), per_page: String(PER_PAGE) });
    if (course !== ALL_COURSES) {
      params.set("course", course);
    }
    return SEARCH_URL + "?" + params.toString();
  }

  function finish() {
    clearTimeout(slowTimer);
    form.removeAttribute("aria-busy");
  }

  function runSearch(query, page, course) {
    var request = ++latestRequest;
    var retry = function () {
      runSearch(query, page, course);
    };
    clearTimeout(slowTimer);
    resetResults();
    showMessage(MESSAGES.loading);
    form.setAttribute("aria-busy", "true");
    slowTimer = setTimeout(function () {
      showMessage(MESSAGES.slow);
    }, SLOW_MS);
    fetch(searchUrl(query, page, course))
      .then(function (response) {
        return response.json().then(function (body) {
          if (request !== latestRequest) {
            return;
          }
          finish();
          if (!response.ok) {
            dom.showRetryStatus(statusEl, errorMessage(response, body), retry);
            return;
          }
          renderResults(body, query, course);
        });
      })
      .catch(function () {
        if (request !== latestRequest) {
          return;
        }
        finish();
        dom.showRetryStatus(statusEl, MESSAGES.failed, retry);
      });
  }

  function loadCourses() {
    fetch(COURSES_URL)
      .then(function (response) {
        return response.ok ? response.json() : { data: [] };
      })
      .then(function (body) {
        body.data.forEach(function (course) {
          var option = document.createElement("option");
          option.value = course.key;
          option.textContent = course.label;
          courseSelect.appendChild(option);
        });
      })
      .catch(function () {
        // Without the list the search still covers every course.
      });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var query = input.value.trim();
    if (!query) {
      resetResults();
      showMessage(MESSAGES.empty);
      input.focus();
      return;
    }
    runSearch(query, 1, courseSelect.value);
  });

  loadCourses();
})();

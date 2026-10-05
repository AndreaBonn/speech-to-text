// sbobina · course detail (T051): the student's practice attempts and the
// mistakes to review, each with "Crea carta" for the Ripasso deck. Citations
// and outcome badges reuse esercitazione-esito.js; everything from the LLM
// reaches the DOM only via textContent (see dom.js).
(function () {
  "use strict";

  var dom = window.SbobinaDom;
  var result = window.SbobinaPracticeResult;
  var el = result.el;
  var PER_PAGE = 10;
  var FORMAT_LABELS = { multiple_choice: "Crocette", open: "Domande aperte", oral: "Orale" };

  var attemptsEl = {
    status: document.getElementById("practice-attempts-status"),
    list: document.getElementById("practice-attempts-list"),
    empty: document.getElementById("practice-attempts-empty"),
    pagination: document.getElementById("practice-attempts-pagination"),
  };
  var mistakesEl = {
    status: document.getElementById("practice-mistakes-status"),
    list: document.getElementById("practice-mistakes-list"),
    empty: document.getElementById("practice-mistakes-empty"),
    pagination: document.getElementById("practice-mistakes-pagination"),
  };
  var unavailableEl = document.getElementById("practice-unavailable");
  var successEl = document.getElementById("practice-card-success");
  var currentKey = null;

  function courseApi(key) {
    return "/api/v1/courses/" + encodeURIComponent(key);
  }

  function formatDate(iso) {
    return new Date(iso).toLocaleDateString("it-IT");
  }

  // ---------- shared list loading ----------

  function showSkeleton(parts) {
    dom.clearChildren(parts.list);
    parts.list.hidden = false;
    parts.empty.hidden = true;
    parts.pagination.hidden = true;
    for (var i = 0; i < 2; i++) {
      parts.list.appendChild(el("li", "skeleton-row"));
    }
  }

  function renderList(parts, body, renderItem, onPage) {
    dom.clearChildren(parts.list);
    var items = body.data;
    parts.list.hidden = items.length === 0;
    parts.empty.hidden = items.length !== 0;
    items.forEach(function (item) {
      parts.list.appendChild(renderItem(item));
    });
    dom.renderPagination(parts.pagination, body.meta, onPage);
  }

  function loadList(options) {
    var key = currentKey;
    dom.clearStatus(options.parts.status);
    showSkeleton(options.parts);
    fetch(options.url + "?page=" + options.page + "&per_page=" + PER_PAGE)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("list fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (key !== currentKey) {
          return;
        }
        renderList(options.parts, body, options.renderItem, options.onPage);
        if (options.onMeta) {
          options.onMeta(body.meta);
        }
      })
      .catch(function () {
        if (key !== currentKey) {
          return;
        }
        dom.clearChildren(options.parts.list);
        options.parts.list.hidden = true;
        dom.showRetryStatus(options.parts.status, options.errorText, function () {
          loadList(options);
        });
      });
  }

  // ---------- attempts ----------

  function attemptText(attempt) {
    var text =
      (FORMAT_LABELS[attempt.format] || "") +
      " · " + attempt.answered + " di " + attempt.total + " consegnate";
    if (attempt.answered > 0) {
      text += " · punteggio " + attempt.score.toLocaleString("it-IT") + " su " + attempt.total;
    }
    if (attempt.pending > 0) {
      text += " (" + attempt.pending + " da valutare)";
    }
    return text;
  }

  function renderAttempt(attempt) {
    var li = el("li", "practice-course__item");
    var info = el("p", "practice-course__text", attemptText(attempt));
    info.appendChild(
      el("span", "practice-course__meta", "Iniziato il " + formatDate(attempt.created_at))
    );
    li.appendChild(info);
    var finished = attempt.answered === attempt.total;
    var link = el("a", "btn btn--secondary", finished ? "Apri" : "Riprendi");
    link.href = attempt.href;
    li.appendChild(link);
    return li;
  }

  function showUnavailable(meta) {
    var count = (meta.unavailable_attempts || []).length;
    unavailableEl.hidden = count === 0;
    unavailableEl.textContent =
      count === 1
        ? "Un tentativo non si può leggere: il file è danneggiato."
        : count + " tentativi non si possono leggere: i file sono danneggiati.";
  }

  function loadAttempts(page) {
    loadList({
      parts: attemptsEl,
      url: courseApi(currentKey) + "/attempts",
      page: page,
      renderItem: renderAttempt,
      onPage: loadAttempts,
      onMeta: showUnavailable,
      errorText: "Impossibile caricare i tentativi.",
    });
  }

  // ---------- mistakes ----------

  function verdictLine(mistake) {
    var line = el("p", "practice-result__verdict");
    var label = mistake.self_grade ? "Il tuo voto" : "Voto del modello";
    line.appendChild(el("span", "practice-result__label", label));
    line.appendChild(result.outcomeBadge(mistake.outcome));
    return line;
  }

  function createCard(mistake, button, item) {
    var url =
      courseApi(currentKey) + "/mistakes/" + encodeURIComponent(mistake.attempt_id) +
      "/" + mistake.question_index + "/card";
    var key = currentKey;
    button.disabled = true;
    successEl.hidden = true;
    fetch(url, { method: "POST" })
      .then(function (response) {
        if (key !== currentKey) {
          return; // another course is shown now: this banner is not about it
        }
        if (response.status !== 200 && response.status !== 201) {
          throw new Error("card failed");
        }
        successEl.textContent =
          response.status === 201 ? "Carta aggiunta al Ripasso." : "La carta era già nel Ripasso.";
        successEl.hidden = false;
        button.textContent = "Nel Ripasso";
      })
      .catch(function () {
        if (key !== currentKey) {
          return;
        }
        button.disabled = false;
        var error = item.querySelector(".field__error") || el("p", "field__error");
        error.setAttribute("role", "alert");
        error.textContent = "Impossibile creare la carta: riprova.";
        item.appendChild(error);
      });
  }

  function mistakeActions(mistake, item) {
    var actions = el("div", "practice-question__actions");
    var button = el("button", "btn btn--secondary", "Crea carta");
    button.type = "button";
    button.addEventListener("click", function () {
      createCard(mistake, button, item);
    });
    actions.appendChild(button);
    var link = el("a", "table__link", "Apri l'esercitazione");
    link.href =
      "/corsi/" + encodeURIComponent(currentKey) + "/esercitazioni/" +
      encodeURIComponent(mistake.attempt_id);
    actions.appendChild(link);
    return actions;
  }

  function renderMistake(mistake) {
    var item = el("li", "practice-course__mistake");
    item.appendChild(verdictLine(mistake));
    item.appendChild(el("p", "practice-question__text", mistake.question));
    if (mistake.text) {
      item.appendChild(el("p", "practice-result__answer", mistake.text));
    }
    item.appendChild(el("p", "practice-result__solution", mistake.solution));
    if (mistake.citations && mistake.citations.length > 0) {
      var list = el("ul", "practice-result__citations");
      list.setAttribute("aria-label", "Fonti della soluzione");
      mistake.citations.forEach(function (citation) {
        list.appendChild(result.citationItem(citation));
      });
      item.appendChild(list);
    }
    item.appendChild(mistakeActions(mistake, item));
    return item;
  }

  function loadMistakes(page) {
    loadList({
      parts: mistakesEl,
      url: courseApi(currentKey) + "/mistakes",
      page: page,
      renderItem: renderMistake,
      onPage: loadMistakes,
      errorText: "Impossibile caricare gli errori.",
    });
  }

  // ---------- public ----------

  function show(key) {
    currentKey = key;
    successEl.hidden = true;
    unavailableEl.hidden = true;
    loadAttempts(1);
    loadMistakes(1);
  }

  function hide() {
    currentKey = null;
  }

  window.SbobinaCoursePractice = { show: show, hide: hide };
})();

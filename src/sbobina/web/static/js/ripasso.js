// sbobina · Ripasso: per-course summary (GET /api/v1/review/summary) and one
// FSRS session at a time (GET .../review/today, POST .../cards/<id>/review).
// Front/back render formulas via math-text.js; source is textContent (dom.js).
(function () {
  "use strict";
  var dom = window.SbobinaDom;
  if (!dom) return;
  var PER_PAGE = 100;
  var SLOW_MS = 15000;
  var ANCHOR_LABELS = {
    ok: "Fonte verificata",
    moved: "Fonte spostata",
    source_modified: "Fonte modificata",
    source_removed: "Fonte rimossa",
    unavailable: "Fonte non leggibile ora",
  };
  var summaryStatusEl = document.getElementById("ripasso-summary-status");
  var summaryListEl = document.getElementById("ripasso-summary-list");
  var summaryEmptyEl = document.getElementById("ripasso-summary-empty");
  var summaryPaginationEl = document.getElementById("ripasso-summary-pagination");
  var sessionEl = document.getElementById("ripasso-session");
  var sessionTitleEl = document.getElementById("ripasso-session-title");
  var sessionExitEl = document.getElementById("ripasso-session-exit");
  var counterEl = document.getElementById("ripasso-session-counter");
  var sessionStatusEl = document.getElementById("ripasso-session-status");
  var sessionFinishedEl = document.getElementById("ripasso-session-finished");
  var cardEl = document.getElementById("ripasso-card");
  var frontEl = document.getElementById("ripasso-card-front");
  var revealBtn = document.getElementById("ripasso-card-reveal");
  var backWrapEl = document.getElementById("ripasso-card-back-wrap");
  var backEl = document.getElementById("ripasso-card-back");
  var sourceBadgeEl = document.getElementById("ripasso-card-source-badge");
  var sourceLinkEl = document.getElementById("ripasso-card-source-link");
  var renderText = window.SbobinaMath ? window.SbobinaMath.renderMathText : function (node, text) { node.textContent = text; };
  var ratingButtons = Array.prototype.slice.call(
    document.querySelectorAll(".review-card__rating")
  );
  var summarySlowTimer = null;
  var summaryRequest = 0;
  var sessionSlowTimer = null;
  var sessionRequest = 0;
  var currentKey = null;
  var queue = [];
  var queueIndex = 0;
  var revealed = false;
  // Key repeat bypasses disabled buttons: one answer in flight at a time.
  var pendingRating = false;
  function countLabel(due) {
    return due === 1 ? "1 carta oggi" : due + " carte oggi";
  }
  function summaryItem(item) {
    var li = document.createElement("li");
    li.className = "review__summary-item";
    var label = document.createElement("span");
    label.className = "review__summary-label";
    label.textContent = item.label;
    var count = document.createElement("span");
    count.className = "review__summary-count";
    count.textContent = countLabel(item.due);
    var button = document.createElement("button");
    button.type = "button";
    if (item.due > 0) {
      button.className = "btn btn--primary";
      button.textContent = "Ripassa";
      button.addEventListener("click", function () {
        startSession(item.course_key, item.label);
      });
    } else {
      button.className = "btn btn--secondary";
      button.textContent = "Nessuna carta oggi";
      button.disabled = true;
    }
    li.appendChild(label);
    li.appendChild(count);
    li.appendChild(button);
    return li;
  }
  function loadSummary(page) {
    var request = ++summaryRequest;
    dom.clearStatus(summaryStatusEl);
    summaryEmptyEl.hidden = true;
    dom.clearChildren(summaryListEl);
    for (var i = 0; i < 3; i++) {
      var sk = document.createElement("li");
      sk.className = "skeleton-row";
      summaryListEl.appendChild(sk);
    }
    clearTimeout(summarySlowTimer);
    summarySlowTimer = setTimeout(function () {
      if (request === summaryRequest) {
        summaryStatusEl.hidden = false;
        summaryStatusEl.textContent = "Ci sta mettendo più del previsto.";
      }
    }, SLOW_MS);
    fetch("/api/v1/review/summary?page=" + page + "&per_page=" + PER_PAGE)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("review summary fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (request !== summaryRequest) return;
        clearTimeout(summarySlowTimer);
        dom.clearStatus(summaryStatusEl);
        dom.clearChildren(summaryListEl);
        if (body.data.length === 0) {
          summaryPaginationEl.hidden = true;
          summaryEmptyEl.hidden = page !== 1;
          return;
        }
        summaryEmptyEl.hidden = true;
        body.data.forEach(function (item) {
          summaryListEl.appendChild(summaryItem(item));
        });
        dom.renderPagination(summaryPaginationEl, body.meta, loadSummary);
      })
      .catch(function (error) {
        console.error(error);
        if (request !== summaryRequest) return;
        clearTimeout(summarySlowTimer);
        dom.clearChildren(summaryListEl);
        summaryPaginationEl.hidden = true;
        dom.showRetryStatus(
          summaryStatusEl,
          "Impossibile caricare il riepilogo del ripasso.",
          function () {
            loadSummary(page);
          }
        );
      });
  }
  function remaining() {
    return queue.length - queueIndex;
  }
  function showCurrentCard() {
    if (queueIndex >= queue.length) {
      cardEl.hidden = true;
      counterEl.textContent = "";
      sessionFinishedEl.hidden = false;
      return;
    }
    sessionFinishedEl.hidden = true;
    revealed = false;
    backWrapEl.hidden = true;
    revealBtn.hidden = false;
    var card = queue[queueIndex];
    renderText(frontEl, card.front);
    renderText(backEl, card.back);
    var resolution = card.anchor_resolution;
    sourceBadgeEl.className = "badge badge--anchor-" + resolution.status;
    sourceBadgeEl.textContent = ANCHOR_LABELS[resolution.status] || resolution.status;
    sourceLinkEl.href = resolution.href;
    cardEl.hidden = false;
    var left = remaining();
    counterEl.textContent = left === 1 ? "1 carta rimasta" : left + " carte rimaste";
  }
  function loadQueue() {
    var request = ++sessionRequest;
    dom.clearStatus(sessionStatusEl);
    sessionFinishedEl.hidden = true;
    cardEl.hidden = true;
    counterEl.textContent = "";
    clearTimeout(sessionSlowTimer);
    sessionSlowTimer = setTimeout(function () {
      if (request === sessionRequest) {
        sessionStatusEl.hidden = false;
        sessionStatusEl.textContent = "Ci sta mettendo più del previsto.";
      }
    }, SLOW_MS);
    fetch(
      "/api/v1/courses/" +
        encodeURIComponent(currentKey) +
        "/review/today?per_page=" +
        PER_PAGE
    )
      .then(function (response) {
        if (!response.ok) {
          throw new Error("review today fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (request !== sessionRequest) return;
        clearTimeout(sessionSlowTimer);
        dom.clearStatus(sessionStatusEl);
        queue = body.data;
        queueIndex = 0;
        showCurrentCard();
      })
      .catch(function (error) {
        console.error(error);
        if (request !== sessionRequest) return;
        clearTimeout(sessionSlowTimer);
        cardEl.hidden = true;
        dom.showRetryStatus(
          sessionStatusEl,
          "Impossibile caricare le carte di oggi.",
          loadQueue
        );
      });
  }
  function startSession(key, label) {
    currentKey = key;
    queue = [];
    queueIndex = 0;
    sessionTitleEl.textContent = label;
    sessionEl.hidden = false;
    loadQueue();
  }
  function exitSession() {
    sessionEl.hidden = true;
    clearTimeout(sessionSlowTimer);
    currentKey = null;
    loadSummary(1);
  }
  function reveal() {
    if (revealed || cardEl.hidden) return;
    revealed = true;
    backWrapEl.hidden = false;
    revealBtn.hidden = true;
  }
  function setRatingButtonsDisabled(disabled) {
    ratingButtons.forEach(function (button) {
      button.disabled = disabled;
    });
  }
  function advance() {
    queueIndex++;
    showCurrentCard();
  }
  function submitRating(rating) {
    if (pendingRating || !revealed || queueIndex >= queue.length) return;
    var card = queue[queueIndex];
    var observedDue = card.fsrs ? card.fsrs.due : null;
    pendingRating = true;
    setRatingButtonsDisabled(true);
    fetch(
      "/api/v1/courses/" +
        encodeURIComponent(currentKey) +
        "/cards/" +
        encodeURIComponent(card.id) +
        "/review",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating: rating, observed_due: observedDue }),
      }
    )
      .then(function (response) {
        pendingRating = false;
        setRatingButtonsDisabled(false);
        if (response.status === 409) {
          dom.clearChildren(sessionStatusEl);
          sessionStatusEl.hidden = false;
          sessionStatusEl.textContent = "Carta già ripassata in un'altra scheda.";
          advance();
          return;
        }
        if (!response.ok) {
          throw new Error("review post failed");
        }
        dom.clearStatus(sessionStatusEl);
        advance();
      })
      .catch(function (error) {
        console.error(error);
        pendingRating = false;
        setRatingButtonsDisabled(false);
        dom.showRetryStatus(sessionStatusEl, "Impossibile salvare la valutazione.", function () {
          submitRating(rating);
        });
      });
  }
  revealBtn.addEventListener("click", reveal);
  sessionExitEl.addEventListener("click", exitSession);
  ratingButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      submitRating(Number(button.getAttribute("data-rating")));
    });
  });
  document.addEventListener("keydown", function (event) {
    if (sessionEl.hidden) return;
    // Leave browser shortcuts (Shift+Space scrolls up) untouched.
    if (event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) return;
    var tag = event.target && event.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") return;
    if (event.code === "Space" || event.key === " ") {
      if (!cardEl.hidden && !revealed) {
        event.preventDefault();
        reveal();
      }
      return;
    }
    if (revealed && /^[1-4]$/.test(event.key)) {
      submitRating(Number(event.key));
    }
  });
  loadSummary(1);
})();

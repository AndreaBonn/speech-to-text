// sbobina · reader "punti da riascoltare": doubtful words grouped by passage
// (R2), filtered by the level the student picks for the text (R1). Split out
// of reader.js (F59). Transcript text reaches the DOM via textContent only.
(function () {
  "use strict";

  // Points closer than this to the previous one join the same passage: two
  // doubtful words a few seconds apart are one thing to re-listen, not two.
  var PASSAGE_GAP_S = 10;
  // ...but a passage never runs longer than one short listen: with a fifth of
  // the words doubtful, gap-chaining alone produced passages minutes long.
  var PASSAGE_MAX_S = 20;
  // A passage card names at most this many of its doubtful words.
  var MAX_LISTED_TEXTS = 4;
  var LEVELS = ["none", "most", "all"];
  var DEFAULT_LEVEL = "most";
  var STORAGE_KEY = "sbobina-uncertain-level";

  function wordCount(text) {
    return text.split(/\s+/).filter(Boolean).length;
  }

  function keepPoint(point, level) {
    if (level === "none") {
      return false;
    }
    return level === "all" || point.most_uncertain === true;
  }

  function groupPoints(points, level) {
    var groups = [];
    points
      .filter(function (point) {
        return keepPoint(point, level);
      })
      .forEach(function (point) {
        var last = groups[groups.length - 1];
        if (
          !last ||
          point.start - last.end > PASSAGE_GAP_S ||
          point.start - last.start > PASSAGE_MAX_S
        ) {
          last = { start: point.start, end: point.start, words: 0, texts: [] };
          groups.push(last);
        }
        last.end = point.start;
        last.words += wordCount(point.text);
        if (last.texts.indexOf(point.text) === -1) {
          last.texts.push(point.text);
        }
      });
    return groups;
  }

  // ---------- DOM ----------

  var state = { container: null, points: [], formatTime: null, level: readLevel(), current: -1 };

  function readLevel() {
    try {
      var saved = window.localStorage.getItem(STORAGE_KEY);
      return LEVELS.indexOf(saved) !== -1 ? saved : DEFAULT_LEVEL;
    } catch (error) {
      return DEFAULT_LEVEL;
    }
  }

  function saveLevel(level) {
    try {
      window.localStorage.setItem(STORAGE_KEY, level);
    } catch (error) {
      // Private windows may refuse storage: the level then resets on reload.
    }
  }

  function passageButton(group, formatTime) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "reader__point";
    button.dataset.start = String(group.start);
    var time = document.createElement("span");
    time.className = "reader__point-time";
    var range = formatTime(group.start);
    if (group.end > group.start) {
      range += " – " + formatTime(group.end);
    }
    time.textContent =
      range + " · " + group.words + (group.words === 1 ? " parola" : " parole");
    var text = document.createElement("span");
    text.className = "reader__point-text";
    var shown = group.texts.slice(0, MAX_LISTED_TEXTS).map(function (word) {
      return "«" + word + "»";
    });
    if (group.texts.length > MAX_LISTED_TEXTS) {
      shown.push("…");
    }
    text.textContent = shown.join(", ");
    button.append(time, text);
    return button;
  }

  function navButton(label, step) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--ghost reader__points-step";
    button.setAttribute("aria-label", label);
    button.textContent = step < 0 ? "‹" : "›";
    button.addEventListener("click", function () {
      move(step);
    });
    return button;
  }

  function move(step) {
    var buttons = state.container.querySelectorAll(".reader__point");
    if (buttons.length === 0) {
      return;
    }
    state.current = Math.min(Math.max(state.current + step, 0), buttons.length - 1);
    var target = buttons[state.current];
    target.scrollIntoView({ block: "nearest" });
    target.focus();
    // reader.js seeks and plays on a point click.
    target.click();
  }

  function emptyText(level, total) {
    if (level === "none") {
      return "Evidenziazione spenta: scegli «Le più dubbie» o «Tutte» per vedere i punti.";
    }
    if (total > 0) {
      return "Nessun punto molto dubbio: «Tutte» mostra anche quelli meno incerti.";
    }
    return "Nessun punto incerto da riascoltare.";
  }

  function draw() {
    var container = state.container;
    if (!container) {
      return;
    }
    state.current = -1;
    var groups = groupPoints(state.points, state.level);
    var head = document.createElement("div");
    head.className = "reader__points-head";
    var title = document.createElement("h2");
    title.className = "reader__points-title";
    title.textContent = "Punti da riascoltare";
    head.appendChild(title);
    if (groups.length === 0) {
      var empty = document.createElement("p");
      empty.className = "reader__points-empty";
      empty.textContent = emptyText(state.level, state.points.length);
      container.replaceChildren(head, empty);
      return;
    }
    var nav = document.createElement("div");
    nav.className = "reader__points-nav";
    nav.append(navButton("Punto precedente", -1), navButton("Punto successivo", 1));
    head.appendChild(nav);
    var list = document.createElement("ul");
    list.className = "reader__points-list";
    groups.forEach(function (group) {
      var li = document.createElement("li");
      li.appendChild(passageButton(group, state.formatTime));
      list.appendChild(li);
    });
    container.replaceChildren(head, list);
  }

  function render(container, points, formatTime) {
    state.container = container;
    state.points = points;
    state.formatTime = formatTime;
    draw();
  }

  function setLevel(level) {
    if (LEVELS.indexOf(level) === -1) {
      return;
    }
    state.level = level;
    saveLevel(level);
    draw();
  }

  function level() {
    return state.level;
  }

  // R1: the level picker drives the text marks (CSS on the reader root) and
  // the passages listed beside the text.
  function wireLevels() {
    var picker = document.getElementById("uncertain-level");
    var root = document.querySelector(".reader[data-job-id]");
    if (!picker || !root) {
      return;
    }
    function sync() {
      root.dataset.uncertainLevel = state.level;
      picker.querySelectorAll("[data-level]").forEach(function (button) {
        var on = button.dataset.level === state.level;
        button.classList.toggle("is-active", on);
        button.setAttribute("aria-pressed", String(on));
      });
    }
    picker.addEventListener("click", function (event) {
      var button = event.target.closest("[data-level]");
      if (button) {
        setLevel(button.dataset.level);
        sync();
      }
    });
    sync();
  }

  if (typeof document !== "undefined") {
    wireLevels();
  }

  window.SbobinaReaderPoints = {
    render: render,
    setLevel: setLevel,
    level: level,
    groupPoints: groupPoints,
  };
})();

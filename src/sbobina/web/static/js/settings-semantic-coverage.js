// sbobina · Settings page: per-course coverage list and "Indicizza ora"
// inside the "Ricerca semantica" section (T052). Split out of
// settings-semantic.js (project line limit); owns only this list, the
// toggle/model/pull/rebuild state stays in the parent module.
(function () {
  "use strict";

  // I3: the state in words; "unità" is an internal unit (a text passage), so
  // the exact count only goes to the tooltip.
  function coverageText(course) {
    var coverage = course.coverage;
    if (!coverage || coverage.total === 0) {
      return "nessun contenuto da indicizzare";
    }
    var text;
    if (coverage.embedded >= coverage.total) {
      text =
        course.missing_units > 0
          ? "pronta sul testo già indicizzato, ci sono parti nuove da indicizzare"
          : "pronta su tutte le lezioni e i materiali";
    } else {
      text =
        "pronta al " + Math.floor((coverage.embedded / coverage.total) * 100) +
        "%, il resto è da indicizzare";
    }
    if (coverage.truncated > 0) {
      text += " (alcuni passaggi molto lunghi sono stati accorciati)";
    }
    return text;
  }

  function coverageDetail(course) {
    if (!course.coverage) {
      return "";
    }
    return course.coverage.embedded + " passaggi indicizzati su " + course.coverage.total;
  }

  function create(options) {
    var Dom = window.SbobinaSettingsDom;
    var byId = Dom.byId;
    var setHidden = Dom.setHidden;
    var clearChildren = Dom.clearChildren;
    var fetchJson = Dom.fetchJson;
    var errorMessage = Dom.errorMessage;
    var onReload = options.onReload;
    var showError = options.showError;

    var el = {
      empty: byId("semantic-coverage-empty"),
      list: byId("semantic-coverage-list"),
    };

    function formatEstimate(seconds) {
      if (typeof seconds !== "number" || !(seconds >= 0)) {
        return null;
      }
      if (seconds < 60) {
        return "meno di un minuto";
      }
      return "circa " + Math.round(seconds / 60) + " min";
    }

    function buttonLabel(course) {
      if (course.queued_action !== null) {
        return "In coda…";
      }
      var estimate = formatEstimate(course.estimated_seconds);
      return "Indicizza ora" + (estimate ? " (" + estimate + ")" : "");
    }

    function indexCourse(key, button) {
      button.disabled = true;
      fetchJson("/api/v1/courses/" + encodeURIComponent(key) + "/semantic-index", {
        method: "POST",
      }).then(function (result) {
        if (result.status !== 202) {
          showError(errorMessage(result.body, "Impossibile avviare l'indicizzazione."));
          button.disabled = false;
          return;
        }
        onReload();
      });
    }

    function renderItem(course) {
      var item = document.createElement("li");
      item.className = "semantic-coverage__item";
      var title = document.createElement("span");
      title.className = "semantic-coverage__label";
      title.textContent = course.label;
      item.appendChild(title);
      var state = document.createElement("span");
      state.className = "semantic-coverage__state";
      state.textContent = " · " + coverageText(course);
      state.title = coverageDetail(course);
      item.appendChild(state);
      if (course.queued_action === null && course.missing_units === 0) {
        return item;
      }

      var button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn--secondary";
      button.disabled = course.queued_action !== null;
      button.textContent = buttonLabel(course);
      button.addEventListener("click", function () {
        indexCourse(course.key, button);
      });
      item.appendChild(button);
      return item;
    }

    function render(courses) {
      clearChildren(el.list);
      setHidden(el.empty, courses.length > 0);
      setHidden(el.list, courses.length === 0);
      courses.forEach(function (course) {
        el.list.appendChild(renderItem(course));
      });
    }

    return { render: render };
  }

  window.SbobinaSettingsSemanticCoverage = {
    create: create,
    coverageText: coverageText,
    coverageDetail: coverageDetail,
  };
})();

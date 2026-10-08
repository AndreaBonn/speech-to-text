// sbobina · Settings page: per-course coverage list and "Indicizza ora"
// inside the "Ricerca semantica" section (T052). Split out of
// settings-semantic.js (project line limit); owns only this list, the
// toggle/model/pull/rebuild state stays in the parent module.
(function () {
  "use strict";

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

    function coverageText(course) {
      if (!course.coverage) {
        return "Nessun contenuto da indicizzare.";
      }
      var text = course.coverage.embedded + "/" + course.coverage.total + " unità indicizzate";
      if (course.coverage.truncated > 0) {
        text += ", " + course.coverage.truncated + " troncate";
      }
      // The coverage counts the last synchronized manifest; text added since
      // then shows up only in missing_units.
      if (course.missing_units > 0) {
        text += ", " + course.missing_units + " da indicizzare";
      }
      return text;
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
      item.appendChild(document.createTextNode(" · " + coverageText(course)));
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

  window.SbobinaSettingsSemanticCoverage = { create: create };
})();

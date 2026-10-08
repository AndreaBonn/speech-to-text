// sbobina · course summary (C10): one line of counts, each a link to its
// section, plus the rule that tells a lecture from an unfinished attempt (C3).
// A count that fails to load is left out: a "0" there would be a claim.
(function () {
  "use strict";

  var ATTEMPT_STATUSES = ["cancelled", "interrupted", "failed"];
  var SOURCES = [
    {
      name: "lessons",
      url: function (key) {
        return "/api/v1/jobs?status=done&per_page=1&course=" + encodeURIComponent(key);
      },
    },
    {
      name: "materials",
      url: function (key) {
        return "/api/v1/courses/" + encodeURIComponent(key) + "/documents?per_page=1";
      },
    },
    {
      name: "exercises",
      url: function (key) {
        return "/api/v1/courses/" + encodeURIComponent(key) + "/generations?per_page=1";
      },
    },
    {
      name: "cards",
      url: function (key) {
        return "/api/v1/courses/" + encodeURIComponent(key) + "/review/today?per_page=1";
      },
    },
  ];
  var LABELS = {
    lessons: ["lezione", "lezioni", "#corsi-lessons"],
    materials: ["materiale", "materiali", "#corsi-materials"],
    exercises: ["esercitazione", "esercitazioni", "#corsi-generations"],
    cards: ["carta da ripassare oggi", "carte da ripassare oggi", "/ripasso"],
  };

  function isAttempt(status) {
    return ATTEMPT_STATUSES.indexOf(status) !== -1;
  }

  function items(counts) {
    return SOURCES.filter(function (source) {
      return typeof counts[source.name] === "number";
    }).map(function (source) {
      var count = counts[source.name];
      var label = LABELS[source.name];
      return { text: count + " " + (count === 1 ? label[0] : label[1]), href: label[2] };
    });
  }

  var currentKey = null;

  function fetchTotal(url) {
    return fetch(url)
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (body) {
        return body && body.meta ? body.meta.total : null;
      })
      .catch(function () {
        return null;
      });
  }

  function render(el, counts) {
    while (el.firstChild) {
      el.removeChild(el.firstChild);
    }
    items(counts).forEach(function (item) {
      var link = document.createElement("a");
      link.className = "course-summary__item";
      link.href = item.href;
      link.textContent = item.text;
      el.appendChild(link);
    });
    el.hidden = !el.firstChild;
  }

  function show(key) {
    var el = document.getElementById("corsi-summary");
    if (!el) {
      return;
    }
    currentKey = key;
    Promise.all(
      SOURCES.map(function (source) {
        return fetchTotal(source.url(key));
      })
    ).then(function (totals) {
      if (currentKey !== key) {
        return;
      }
      var counts = {};
      SOURCES.forEach(function (source, index) {
        counts[source.name] = totals[index];
      });
      render(el, counts);
    });
  }

  function hide() {
    var el = document.getElementById("corsi-summary");
    currentKey = null;
    if (el) {
      el.hidden = true;
    }
  }

  window.SbobinaCourseSummary = { items: items, isAttempt: isAttempt, show: show, hide: hide };
})();

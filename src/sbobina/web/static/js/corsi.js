// sbobina · course list: pagination, labels and URL navigation.
// The detail view follows ?corso=<key> and browser history.
(function () {
  "use strict";

  var COURSES_URL = "/api/v1/courses";
  var PER_PAGE = 20;

  var listStatusEl = document.getElementById("corsi-list-status");
  var listTbody = document.getElementById("corsi-list-tbody");
  var listEmptyEl = document.getElementById("corsi-list-empty");
  var listPaginationEl = document.getElementById("corsi-list-pagination");

  var backLink = document.getElementById("corsi-detail-back");

  var listPage = 1;
  var detail = window.SbobinaCourseDetail;
  var labelsByKey = detail.labelsByKey;

  var dom = window.SbobinaDom;
  var clearChildren = dom.clearChildren;
  var textCell = dom.textCell;
  var showSkeleton = dom.showSkeleton;
  var clearStatus = dom.clearStatus;
  var showRetryStatus = dom.showRetryStatus;
  var renderPagination = dom.renderPagination;

  // ---------- URL state ----------

  function courseKeyFromUrl() {
    var params = new URLSearchParams(window.location.search);
    return params.has("corso") ? params.get("corso") : null;
  }

  function pushCourseUrl(key) {
    var url = new URL(window.location.href);
    url.searchParams.set("corso", key);
    window.history.pushState({}, "", url.toString());
  }

  function pushListUrl() {
    window.history.pushState({}, "", "/corsi");
  }

  // ---------- list view ----------

  function renderListRow(course) {
    var row = document.createElement("tr");
    row.setAttribute("data-course-key", course.key);

    var nameCell = document.createElement("td");
    nameCell.className = "cell-name";
    nameCell.setAttribute("data-label", "Corso");
    var link = document.createElement("a");
    link.className = "table__link";
    link.href = "/corsi?corso=" + encodeURIComponent(course.key);
    link.textContent = course.label;
    link.addEventListener("click", function (event) {
      event.preventDefault();
      pushCourseUrl(course.key);
      detail.show(course.key, course.label);
    });
    nameCell.appendChild(link);
    row.appendChild(nameCell);

    row.appendChild(textCell(String(course.lecture_count), "Lezioni"));
    row.appendChild(
      textCell(
        new Date(course.last_lecture_at).toLocaleDateString("it-IT"),
        "Ultima lezione"
      )
    );
    return row;
  }

  function cacheLabels(courses) {
    courses.forEach(function (course) {
      labelsByKey[course.key] = course.label;
    });
    detail.refreshTitle();
  }

  function loadList(page) {
    listPage = page;
    clearStatus(listStatusEl);
    listEmptyEl.hidden = true;
    showSkeleton(listTbody, 3);
    fetch(COURSES_URL + "?page=" + page + "&per_page=" + PER_PAGE)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("corsi fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        cacheLabels(body.data);
        if (body.data.length === 0) {
          clearChildren(listTbody);
          listPaginationEl.hidden = true;
          if (page === 1) {
            listEmptyEl.hidden = false;
          }
          return;
        }
        clearChildren(listTbody);
        body.data.forEach(function (course) {
          listTbody.appendChild(renderListRow(course));
        });
        renderPagination(listPaginationEl, body.meta, loadList);
      })
      .catch(function () {
        clearChildren(listTbody);
        showRetryStatus(listStatusEl, "Impossibile caricare i corsi.", function () {
          loadList(listPage);
        });
      });
  }

  // ---------- wiring ----------

  backLink.addEventListener("click", function (event) {
    event.preventDefault();
    pushListUrl();
    detail.hide();
  });

  window.addEventListener("popstate", function () {
    var key = courseKeyFromUrl();
    if (key === null) {
      detail.hide();
    } else {
      detail.show(key, null);
    }
  });

  // The list is always loaded, even when the detail view opens first from a
  // shared link: it both backs the "Tutti i corsi" return and resolves the
  // course label for the heading once the fetch completes.
  loadList(1);

  var initialKey = courseKeyFromUrl();
  if (initialKey === null) {
    detail.hide();
  } else {
    detail.show(initialKey, null);
  }
})();

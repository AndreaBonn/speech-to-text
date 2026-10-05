// sbobina · course document: text per page, pagination and extraction
// polling. The filename is server-rendered (Jinja escapes it); page text
// comes from an untrusted upload, so it reaches the DOM only via
// textContent, same discipline as reader.js and studio.js (see dom.js).
(function () {
  "use strict";

  var root = document.querySelector(".document[data-doc-id]");
  var dom = window.SbobinaDom;
  if (!root || !dom) {
    return;
  }

  var courseKey = root.dataset.courseKey;
  var docId = root.dataset.docId;
  var API_BASE =
    "/api/v1/courses/" +
    encodeURIComponent(courseKey) +
    "/documents/" +
    encodeURIComponent(docId);
  var POLL_MS = 4000;
  var ERROR_MESSAGES = {
    EXTRACTION_TIMEOUT:
      "L'estrazione ha impiegato troppo tempo: ricarica il documento.",
    EXTRACTION_FAILED: "Non è stato possibile leggere il documento.",
  };

  var statusEl = document.getElementById("document-status");
  var textEl = document.getElementById("document-text");
  var paginationEl = document.getElementById("document-pagination");
  var prevButton = document.getElementById("document-prev");
  var nextButton = document.getElementById("document-next");
  var pageCountEl = document.getElementById("document-page-count");

  var currentPage = initialPage();
  var highlightQuery = initialQuery();
  var totalPages = null;
  var pollTimer = null;

  function initialPage() {
    var params = new URLSearchParams(window.location.search);
    var value = parseInt(params.get("p"), 10);
    return value > 0 ? value : 1;
  }

  function initialQuery() {
    return new URLSearchParams(window.location.search).get("q") || "";
  }

  function pushPageUrl(page) {
    var url = new URL(window.location.href);
    url.searchParams.set("p", String(page));
    window.history.pushState({}, "", url.toString());
  }

  function showMessage(message, tone) {
    dom.clearChildren(statusEl);
    statusEl.hidden = false;
    var p = document.createElement("p");
    p.className = "banner banner--" + tone;
    p.textContent = message;
    statusEl.appendChild(p);
  }

  function showSkeleton() {
    dom.clearChildren(textEl);
    for (var i = 0; i < 3; i++) {
      var row = document.createElement("div");
      row.className = "skeleton-row";
      textEl.appendChild(row);
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function schedulePoll() {
    stopPolling();
    if (document.hidden) {
      return;
    }
    pollTimer = setTimeout(loadDocument, POLL_MS);
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      stopPolling();
    } else {
      schedulePoll();
    }
  });

  function renderPage(pageData, meta) {
    dom.clearChildren(statusEl);
    statusEl.hidden = true;
    dom.clearChildren(textEl);
    if (pageData.ocr) {
      var ocrNotice = document.createElement("p");
      ocrNotice.className = "banner banner--warning document__ocr-notice";
      ocrNotice.textContent =
        "Testo riconosciuto automaticamente da una scansione: può contenere " +
        "errori, anche di significato. Controlla sul PDF originale.";
      textEl.appendChild(ocrNotice);
    }
    if (pageData.no_text) {
      var notice = document.createElement("p");
      notice.className = "document__no-text";
      notice.textContent = "Questa pagina non contiene testo estraibile.";
      textEl.appendChild(notice);
    } else {
      textEl.appendChild(window.SbobinaDocumentText.paragraph(pageData.text, highlightQuery));
    }
    totalPages = meta.total_pages;
    currentPage = meta.page;
    pageCountEl.textContent = "Pagina " + meta.page + " di " + meta.total_pages;
    prevButton.disabled = meta.page <= 1;
    nextButton.disabled = meta.page >= meta.total_pages;
    paginationEl.hidden = meta.total_pages <= 1;
  }

  function loadPage(page) {
    showSkeleton();
    fetch(API_BASE + "/pages/" + page)
      .then(function (response) {
        // A ?p= past the last page (an old link, a shorter re-upload) falls
        // back to page 1 instead of a retry that would fail forever.
        if (response.status === 404 && page !== 1) {
          var url = new URL(window.location.href);
          url.searchParams.set("p", "1");
          window.history.replaceState({}, "", url.toString());
          return null;
        }
        if (!response.ok) {
          throw new Error("document page fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (body === null) {
          loadPage(1);
          return;
        }
        renderPage(body.data, body.meta);
      })
      .catch(function () {
        dom.clearChildren(textEl);
        dom.showRetryStatus(statusEl, "Impossibile caricare la pagina.", function () {
          loadPage(currentPage);
        });
      });
  }

  function loadDocument() {
    fetch(API_BASE)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("document fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        var doc = body.data;
        if (doc.status === "extracting" || doc.status === "uploading") {
          showMessage("Estrazione del testo in corso…", "info");
          paginationEl.hidden = true;
          schedulePoll();
          return;
        }
        if (doc.status === "failed") {
          showMessage(
            ERROR_MESSAGES[doc.error] || "Non è stato possibile leggere il documento.",
            "danger"
          );
          paginationEl.hidden = true;
          return;
        }
        loadPage(currentPage);
      })
      .catch(function () {
        dom.showRetryStatus(
          statusEl,
          "Impossibile caricare il documento.",
          loadDocument
        );
      });
  }

  prevButton.addEventListener("click", function () {
    if (currentPage > 1) {
      pushPageUrl(currentPage - 1);
      loadPage(currentPage - 1);
    }
  });
  nextButton.addEventListener("click", function () {
    if (totalPages === null || currentPage < totalPages) {
      pushPageUrl(currentPage + 1);
      loadPage(currentPage + 1);
    }
  });

  loadDocument();
})();

// sbobina · course detail: "Esporta il corso" dialog (T078). One checkbox per
// course document (included with text and original, or left out), the weight
// of the chosen materials, the copyright and other-students notice. The
// package is fetched as a blob so a server error shows as a message instead
// of downloading an error file. File names reach the DOM via textContent.
(function () {
  "use strict";

  var dom = window.SbobinaDom;
  var openButton = document.getElementById("export-open");
  var dialog = document.getElementById("export-dialog");
  if (!dom || !openButton || !dialog) {
    return;
  }

  var DOCS_PER_PAGE = 100;
  var SKIPPED_HEADER = "X-Sbobina-Skipped-Lectures";
  var form = document.getElementById("export-form");
  var docsList = document.getElementById("export-docs");
  var docsStatus = document.getElementById("export-docs-status");
  var weightEl = document.getElementById("export-weight");
  var errorEl = document.getElementById("export-error");
  var resultEl = document.getElementById("export-result");
  var submitButton = document.getElementById("export-submit");
  var cancelButton = document.getElementById("export-cancel");
  var currentKey = null;
  var documents = [];

  function courseApi(key) {
    return "/api/v1/courses/" + encodeURIComponent(key);
  }

  // Every page; a course without registered materials answers 404: no documents.
  function fetchDocuments(key, page, found) {
    return fetch(courseApi(key) + "/documents?page=" + page + "&per_page=" + DOCS_PER_PAGE)
      .then(function (response) {
        if (response.status === 404) {
          return { data: [], meta: { total_pages: 0 } };
        }
        if (!response.ok) {
          throw new Error("documents fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        var all = found.concat(body.data);
        return page < (body.meta.total_pages || 0) ? fetchDocuments(key, page + 1, all) : all;
      });
  }

  function documentRow(doc) {
    var li = document.createElement("li");
    var label = document.createElement("label");
    label.className = "package__doc";
    var box = document.createElement("input");
    box.type = "checkbox";
    box.checked = true;
    box.value = doc.id;
    var name = document.createElement("span");
    name.className = "package__doc-name";
    name.textContent = doc.filename;
    var size = document.createElement("span");
    size.className = "package__doc-size";
    size.textContent = dom.formatBytes(doc.size);
    label.append(box, name, size);
    li.appendChild(label);
    return li;
  }

  function checkedIds() {
    return Array.prototype.map.call(docsList.querySelectorAll("input:checked"), function (box) {
      return box.value;
    });
  }

  function updateWeight() {
    var chosen = checkedIds();
    var bytes = documents
      .filter(function (doc) { return chosen.indexOf(doc.id) >= 0; })
      .reduce(function (sum, doc) { return sum + doc.size; }, 0);
    weightEl.hidden = documents.length === 0;
    weightEl.textContent =
      "Materiali scelti: " + chosen.length + " di " + documents.length +
      ", " + dom.formatBytes(bytes) + " oltre a lezioni ed esercitazioni.";
  }

  function showDocuments(found) {
    documents = found;
    dom.clearChildren(docsList);
    found.forEach(function (doc) {
      docsList.appendChild(documentRow(doc));
    });
    docsList.hidden = found.length === 0;
    docsStatus.hidden = found.length > 0;
    docsStatus.textContent = "Nessun materiale: il pacchetto conterrà lezioni, esercitazioni e carte.";
    updateWeight();
  }

  function openDialog() {
    var key = currentKey;
    errorEl.textContent = "";
    resultEl.hidden = true;
    cancelButton.textContent = "Annulla";
    docsList.hidden = true;
    weightEl.hidden = true;
    docsStatus.hidden = false;
    docsStatus.textContent = "Carico i materiali…";
    dialog.showModal();
    fetchDocuments(key, 1, [])
      .then(function (found) {
        if (key === currentKey) {
          showDocuments(found);
        }
      })
      .catch(function () {
        docsStatus.textContent = "Impossibile caricare i materiali: chiudi e riprova.";
      });
  }

  function packageName(response) {
    var header = response.headers.get("Content-Disposition") || "";
    var encoded = /filename\*=UTF-8''([^;]+)/i.exec(header);
    return encoded ? decodeURIComponent(encoded[1]) : "corso.sbobina.zip";
  }

  function saveBlob(blob, filename) {
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 0);
  }

  function errorMessage(response) {
    return response.json().then(
      function (body) { return (body.error && body.error.message) || "Esportazione non riuscita."; },
      function () { return "Esportazione non riuscita."; }
    );
  }

  // Lectures cancelled or stopped before transcription have only their
  // audio, which is never exported: say so instead of closing silently.
  function showSkipped(count) {
    resultEl.textContent =
      count === 1
        ? "Pacchetto scaricato. Una lezione non è inclusa: non ha una trascrizione (annullata o non conclusa)."
        : "Pacchetto scaricato. " + count +
          " lezioni non sono incluse: non hanno una trascrizione (annullate o non concluse).";
    resultEl.hidden = false;
    cancelButton.textContent = "Chiudi";
    // Esporta was disabled while exporting and lost focus: keep it in the dialog.
    cancelButton.focus();
  }

  function exportPackage() {
    var excluded = documents
      .map(function (doc) { return doc.id; })
      .filter(function (id) { return checkedIds().indexOf(id) < 0; });
    submitButton.disabled = true;
    submitButton.textContent = "Preparo il pacchetto…";
    errorEl.textContent = "";
    resultEl.hidden = true;
    fetch(courseApi(currentKey) + "/export?docs=" + encodeURIComponent(excluded.join(",")))
      .then(function (response) {
        if (!response.ok) {
          return errorMessage(response).then(function (message) { throw new Error(message); });
        }
        return response.blob().then(function (blob) {
          saveBlob(blob, packageName(response));
          var skipped = Number(response.headers.get(SKIPPED_HEADER)) || 0;
          if (skipped > 0) {
            showSkipped(skipped);
          } else {
            dialog.close();
          }
        });
      })
      .catch(function (error) {
        errorEl.textContent = error.message || "Esportazione non riuscita: verifica la connessione.";
      })
      .finally(function () {
        submitButton.disabled = false;
        submitButton.textContent = "Esporta";
      });
  }

  openButton.addEventListener("click", openDialog);
  docsList.addEventListener("change", updateWeight);
  cancelButton.addEventListener("click", function () {
    dialog.close();
  });
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    exportPackage();
  });

  window.SbobinaCourseExport = {
    show: function (key) {
      currentKey = key;
    },
    // The browser back button can leave the detail with the dialog open;
    // showModal() on an open dialog throws, so close it here.
    hide: function () {
      if (dialog.open) {
        dialog.close();
      }
      currentKey = null;
    },
  };
})();

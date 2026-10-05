// sbobina · course list: "Importa un corso" (T078). Uploads a .sbobina.zip with
// progress, then waits while the server checks and copies it. The server's
// messages (already in Italian) reach the DOM via textContent; a reimport
// warning is shown next to the result. The link to the new course uses the
// key from the course list, never one rebuilt here.
(function () {
  "use strict";

  var IMPORT_URL = "/api/v1/courses/import";
  var COURSES_URL = "/api/v1/courses";
  var COURSES_PER_PAGE = 100;

  var dropzone = document.getElementById("import-dropzone");
  var input = document.getElementById("import-input");
  if (!dropzone || !input) {
    return;
  }
  var errorEl = document.getElementById("import-error");
  var progressWrap = document.getElementById("import-progress");
  var progressBar = document.getElementById("import-bar");
  var progressRole = progressWrap.querySelector("[role=progressbar]");
  var stageEl = document.getElementById("import-stage");
  var resultEl = document.getElementById("import-result");
  var busy = false;

  function setProgress(fraction, stage) {
    progressBar.style.transform = "scaleX(" + fraction + ")";
    progressRole.setAttribute("aria-valuenow", String(Math.round(fraction * 100)));
    stageEl.textContent = stage;
  }

  function showError(message) {
    errorEl.hidden = false;
    errorEl.textContent = message;
    dropzone.classList.add("dropzone--invalid");
  }

  function resetMessages() {
    errorEl.hidden = true;
    errorEl.textContent = "";
    resultEl.hidden = true;
    dropzone.classList.remove("dropzone--invalid");
  }

  // Course keys are normalised by the server; find the new one by its label.
  function findCourseKey(label, page) {
    return fetch(COURSES_URL + "?page=" + page + "&per_page=" + COURSES_PER_PAGE)
      .then(function (response) {
        return response.ok ? response.json() : { data: [], meta: {} };
      })
      .then(function (body) {
        var match = body.data.find(function (course) { return course.label === label; });
        if (match) {
          return match.key;
        }
        return page < (body.meta.total_pages || 0) ? findCourseKey(label, page + 1) : null;
      });
  }

  function showResult(data) {
    resultEl.className = "banner " + (data.warning ? "banner--warning" : "banner--success");
    resultEl.textContent =
      "Corso «" + data.course_label + "» importato." +
      (data.warning ? " Questo pacchetto risulta " + data.warning + ": il corso nuovo ha un nome diverso." : "");
    resultEl.hidden = false;
    if (window.SbobinaCourses) {
      window.SbobinaCourses.reload();
    }
    findCourseKey(data.course_label, 1).then(function (key) {
      if (key === null) {
        return;
      }
      var link = document.createElement("a");
      link.className = "table__link";
      link.href = "/corsi?corso=" + encodeURIComponent(key);
      link.textContent = "Apri il corso";
      resultEl.append(" ", link);
    });
  }

  function serverMessage(xhr) {
    try {
      var body = JSON.parse(xhr.responseText);
      if (body && body.error && body.error.message) {
        return body.error.message;
      }
    } catch (error) {
      // Not a JSON envelope: keep the generic message below.
    }
    return "Importazione non riuscita.";
  }

  function finish(xhr) {
    busy = false;
    progressWrap.hidden = true;
    input.value = "";
    if (xhr.status === 201) {
      showResult(JSON.parse(xhr.responseText).data);
      return;
    }
    showError(serverMessage(xhr));
  }

  function importFile(file) {
    if (busy) {
      return;
    }
    busy = true;
    resetMessages();
    progressWrap.hidden = false;
    setProgress(0, "Invio del pacchetto…");
    var formData = new FormData();
    formData.append("file", file);
    var xhr = new XMLHttpRequest();
    xhr.open("POST", IMPORT_URL);
    xhr.upload.addEventListener("progress", function (event) {
      if (event.lengthComputable) {
        setProgress(event.loaded / event.total, "Invio del pacchetto…");
      }
    });
    xhr.upload.addEventListener("load", function () {
      setProgress(1, "Controllo e copia del pacchetto: può richiedere qualche minuto.");
    });
    xhr.addEventListener("load", function () { finish(xhr); });
    xhr.addEventListener("error", function () {
      busy = false;
      progressWrap.hidden = true;
      showError("Importazione non riuscita: verifica la connessione.");
    });
    xhr.send(formData);
  }

  input.addEventListener("change", function () {
    if (input.files && input.files.length > 0) {
      importFile(input.files[0]);
    }
  });
  ["dragenter", "dragover"].forEach(function (name) {
    dropzone.addEventListener(name, function (event) {
      event.preventDefault();
      dropzone.classList.add("dropzone--dragover");
    });
  });
  ["dragleave", "dragend"].forEach(function (name) {
    dropzone.addEventListener(name, function () {
      dropzone.classList.remove("dropzone--dragover");
    });
  });
  dropzone.addEventListener("drop", function (event) {
    event.preventDefault();
    dropzone.classList.remove("dropzone--dragover");
    var files = event.dataTransfer.files;
    if (files && files.length > 0) {
      importFile(files[0]);
    }
  });
})();

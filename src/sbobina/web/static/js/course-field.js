// sbobina · reader course field: suggests existing courses and saves the
// lecture's course to its user-owned meta.json. The typed text is never
// cleared on an error, so a rejected value can be fixed instead of retyped.
(function () {
  "use strict";

  var COURSES_URL = "/api/v1/courses?per_page=100";
  var MESSAGES = {
    failed: "Salvataggio non riuscito. Controlla che il server sia attivo e riprova.",
    saved: "Corso salvato.",
    cleared: "Corso personalizzato rimosso: vale la materia indicata al caricamento.",
    saving: "Salvo…",
  };

  var form = document.getElementById("course-form");
  var root = document.querySelector(".reader[data-job-id]");
  if (!form || !root) {
    return;
  }
  var input = document.getElementById("course-input");
  var errorEl = document.getElementById("course-error");
  var statusEl = document.getElementById("course-status");
  var options = document.getElementById("course-options");
  var submit = form.querySelector("button[type=submit]");
  var subject = form.getAttribute("data-subject") || "";
  var metaUrl = "/api/v1/jobs/" + root.getAttribute("data-job-id") + "/meta";

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
    input.classList.add("is-invalid");
    input.setAttribute("aria-invalid", "true");
    statusEl.textContent = "";
  }

  function clearError() {
    errorEl.textContent = "";
    errorEl.hidden = true;
    input.classList.remove("is-invalid");
    input.removeAttribute("aria-invalid");
  }

  function serverMessage(body) {
    var error = body && body.error;
    var detail = error && error.details && error.details[0];
    return (detail && detail.message) || (error && error.message) || MESSAGES.failed;
  }

  function setBusy(busy) {
    submit.disabled = busy;
    input.readOnly = busy;
    statusEl.textContent = busy ? MESSAGES.saving : "";
  }

  function save(event) {
    event.preventDefault();
    clearError();
    setBusy(true);
    fetch(metaUrl, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course: input.value.trim() || null }),
    })
      .then(function (response) {
        return response.json().then(function (body) {
          setBusy(false);
          if (!response.ok) {
            showError(serverMessage(body));
            return;
          }
          var course = body.data.course;
          input.value = course || subject;
          statusEl.textContent = course ? MESSAGES.saved : MESSAGES.cleared;
          loadOptions();
        });
      })
      .catch(function () {
        setBusy(false);
        showError(MESSAGES.failed);
      });
  }

  function loadOptions() {
    fetch(COURSES_URL)
      .then(function (response) {
        return response.ok ? response.json() : { data: [] };
      })
      .then(function (body) {
        while (options.firstChild) {
          options.removeChild(options.firstChild);
        }
        body.data.forEach(function (course) {
          if (!course.key) {
            return;
          }
          var option = document.createElement("option");
          option.value = course.label;
          options.appendChild(option);
        });
      })
      .catch(function () {
        // Suggestions are optional: the field still works without them.
      });
  }

  // The server is the only judge of length: NFKC can expand a typed label
  // past the limit that maxlength enforces on the raw characters.
  input.addEventListener("input", clearError);
  form.addEventListener("submit", save);
  loadOptions();
})();

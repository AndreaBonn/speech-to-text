// sbobina · course generations: the request form (format/count/topic/
// sources) and its field-error handling. Split out of corso-generazioni.js
// to stay under the file size limit. Submitting notifies the caller via the
// onSubmitted hook passed to bind(); the list module owns reloading.
(function () {
  "use strict";

  var dom = window.SbobinaDom;
  var clearChildren = dom.clearChildren;

  var OPENABLE_DOC_STATUSES = ["ready", "ready_no_text"];
  var FIELD_ERROR_IDS = {
    count: "generations-count-error",
    topic: "generations-topic-error",
  };
  // Pydantic messages are English; the bounds mirror generation_models.py.
  var FIELD_MESSAGES = {
    count: "Scegli un numero di domande tra 1 e 20.",
    topic: "L'argomento può avere al massimo 200 caratteri.",
  };

  var form = document.getElementById("generations-form");
  var formatSelect = document.getElementById("generations-format");
  var countField = document.getElementById("generations-count-field");
  var countInput = document.getElementById("generations-count");
  var topicInput = document.getElementById("generations-topic");
  var docsSelect = document.getElementById("generations-sources-docs");
  var lecturesSelect = document.getElementById("generations-sources-lectures");
  var formErrorEl = document.getElementById("generations-form-error");
  var submitButton = document.getElementById("generations-submit");

  var currentKey = null;
  var onSubmitted = function () {};

  function apiBase(key) {
    return "/api/v1/courses/" + encodeURIComponent(key) + "/generations";
  }

  // Mirrors jobTitle() in corso-dettaglio.js/storico.js/jobs.js.
  function jobTitle(job) {
    if (job.source_name) {
      return job.source_name;
    }
    var subject = job.config && job.config.subject;
    if (subject) {
      return subject;
    }
    var created = new Date(job.created_at).toLocaleDateString("it-IT");
    return "Lezione del " + created;
  }

  function resetErrors() {
    formErrorEl.hidden = true;
    formErrorEl.textContent = "";
    Object.keys(FIELD_ERROR_IDS).forEach(function (field) {
      var errorEl = document.getElementById(FIELD_ERROR_IDS[field]);
      errorEl.hidden = true;
      errorEl.textContent = "";
    });
  }

  function showFormError(message) {
    formErrorEl.hidden = false;
    formErrorEl.textContent = message;
  }

  function showFieldError(field, message) {
    var bare = field.replace(/^body\./, "").replace(/^sources\./, "");
    var errorId = FIELD_ERROR_IDS[bare];
    if (!errorId) {
      showFormError(message);
      return;
    }
    var errorEl = document.getElementById(errorId);
    errorEl.hidden = false;
    errorEl.textContent = FIELD_MESSAGES[bare] || message;
  }

  function applyServerErrors(body) {
    var error = body && body.error;
    if (!error) {
      showFormError("Impossibile avviare la generazione.");
      return;
    }
    if (error.details && error.details.length > 0) {
      error.details.forEach(function (detail) {
        showFieldError(detail.field, detail.message);
      });
      return;
    }
    showFormError(error.message || "Impossibile avviare la generazione.");
  }

  function toggleCountField() {
    countField.hidden = formatSelect.value === "summary";
  }

  function selectedValues(select) {
    return Array.prototype.slice.call(select.selectedOptions).map(function (option) {
      return option.value;
    });
  }

  function populateSelect(select, items, textFn) {
    clearChildren(select);
    items.forEach(function (item) {
      var option = document.createElement("option");
      option.value = item.id;
      option.textContent = textFn(item);
      select.appendChild(option);
    });
  }

  function fillWhenCurrent(key, url, select, pick) {
    fetch(url)
      .then(function (response) {
        return response.ok ? response.json() : { data: [] };
      })
      .then(function (body) {
        // A late reply for a course the user already left must not fill the form.
        if (key === currentKey) {
          pick(body.data);
        }
      })
      .catch(function () {
        clearChildren(select);
      });
  }

  function loadSources(key) {
    clearChildren(docsSelect);
    clearChildren(lecturesSelect);
    var encoded = encodeURIComponent(key);
    fillWhenCurrent(
      key,
      "/api/v1/courses/" + encoded + "/documents?page=1&per_page=100",
      docsSelect,
      function (docs) {
        var ready = docs.filter(function (doc) {
          return OPENABLE_DOC_STATUSES.indexOf(doc.status) !== -1;
        });
        populateSelect(docsSelect, ready, function (doc) {
          return doc.filename;
        });
      }
    );
    fillWhenCurrent(
      key,
      "/api/v1/jobs?course=" + encoded + "&page=1&per_page=100",
      lecturesSelect,
      function (jobs) {
        var done = jobs.filter(function (job) {
          return job.status === "done";
        });
        populateSelect(lecturesSelect, done, jobTitle);
      }
    );
  }

  function submit(event) {
    event.preventDefault();
    resetErrors();
    submitButton.disabled = true;
    var payload = {
      format: formatSelect.value,
      count: Number(countInput.value) || 1,
      topic: topicInput.value,
      sources: {
        doc_ids: selectedValues(docsSelect),
        job_ids: selectedValues(lecturesSelect),
      },
    };
    fetch(apiBase(currentKey), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (response) {
        return response.json().then(function (body) {
          return { status: response.status, body: body };
        });
      })
      .then(function (result) {
        submitButton.disabled = false;
        if (result.status !== 202) {
          applyServerErrors(result.body);
          return;
        }
        topicInput.value = "";
        onSubmitted();
      })
      .catch(function () {
        submitButton.disabled = false;
        showFormError("Il server non risponde: riprova tra poco.");
      });
  }

  function show(key, hooks) {
    currentKey = key;
    onSubmitted = hooks.onSubmitted;
    resetErrors();
    loadSources(key);
  }

  formatSelect.addEventListener("change", toggleCountField);
  form.addEventListener("submit", submit);
  toggleCountField();

  window.SbobinaGenerationForm = { show: show };
})();

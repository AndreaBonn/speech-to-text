// sbobina · WER comparison: a reference .txt against a job transcript or
// another .txt.
(function () {
  "use strict";

  var JOBS_URL = "/api/v1/jobs";
  var WER_URL = "/api/v1/wer";

  var form = document.getElementById("wer-form");
  var referenceInput = document.getElementById("wer-reference");
  var sourceSwitch = document.getElementById("wer-source-switch");
  var jobFields = document.getElementById("wer-job-fields");
  var fileFields = document.getElementById("wer-file-fields");
  var jobSelect = document.getElementById("wer-job");
  var variantSelect = document.getElementById("wer-variant");
  var hypothesisInput = document.getElementById("wer-hypothesis");
  var formError = document.getElementById("wer-form-error");
  var submitButton = document.getElementById("wer-submit");
  var resultEl = document.getElementById("wer-result");

  var FIELD_ERROR_IDS = {
    reference: "wer-reference-error",
    hypothesis: "wer-hypothesis-error",
    job_id: "wer-job-error",
  };

  var currentSource = "job";

  // ---------- helpers ----------

  // Safe in text and in quoted attributes: textContent/innerHTML would leave
  // double quotes unescaped and break out of an attribute value.
  function escapeHtml(value) {
    return (value == null ? "" : String(value))
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

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

  function clearErrors() {
    formError.hidden = true;
    formError.textContent = "";
    Object.keys(FIELD_ERROR_IDS).forEach(function (field) {
      var el = document.getElementById(FIELD_ERROR_IDS[field]);
      el.hidden = true;
      el.textContent = "";
    });
  }

  function showFieldError(field, message) {
    var errorId = FIELD_ERROR_IDS[field];
    if (!errorId) {
      formError.hidden = false;
      formError.textContent = message;
      return;
    }
    var el = document.getElementById(errorId);
    el.hidden = false;
    el.textContent = message;
  }

  function applyServerErrors(body) {
    var error = body && body.error;
    if (!error) {
      formError.hidden = false;
      formError.textContent = "Errore durante il confronto.";
      return;
    }
    if (error.details && error.details.length > 0) {
      error.details.forEach(function (detail) {
        showFieldError(detail.field, detail.message);
      });
      return;
    }
    formError.hidden = false;
    formError.textContent = error.message || "Errore durante il confronto.";
  }

  // ---------- source toggle ----------

  sourceSwitch.addEventListener("click", function (event) {
    var button = event.target.closest(".segmented__option");
    if (!button) {
      return;
    }
    currentSource = button.getAttribute("data-source");
    sourceSwitch.querySelectorAll(".segmented__option").forEach(function (option) {
      option.classList.toggle("is-active", option === button);
    });
    jobFields.hidden = currentSource !== "job";
    fileFields.hidden = currentSource !== "file";
  });

  // ---------- job list ----------

  function loadJobs() {
    fetch(JOBS_URL + "?page=1&per_page=50")
      .then(function (response) {
        return response.json();
      })
      .then(function (body) {
        var done = body.data.filter(function (job) {
          return job.status === "done";
        });
        if (done.length === 0) {
          jobSelect.innerHTML = '<option value="">Nessuna trascrizione completata</option>';
          jobSelect.disabled = true;
          return;
        }
        jobSelect.innerHTML = done
          .map(function (job) {
            return (
              '<option value="' + job.id + '">' + escapeHtml(jobTitle(job)) + "</option>"
            );
          })
          .join("");
      })
      .catch(function () {
        jobSelect.innerHTML = '<option value="">Impossibile caricare le trascrizioni</option>';
        jobSelect.disabled = true;
      });
  }

  // ---------- result ----------

  function renderResult(data) {
    resultEl.hidden = false;
    document.getElementById("wer-score-value").textContent =
      (data.wer * 100).toLocaleString("it-IT", { maximumFractionDigits: 1 }) + "%";
    document.getElementById("wer-reference-words").textContent = data.reference_words;
    document.getElementById("wer-substitutions").textContent = data.substitutions;
    document.getElementById("wer-deletions").textContent = data.deletions;
    document.getElementById("wer-insertions").textContent = data.insertions;
  }

  // ---------- submit ----------

  function setLoading(isLoading) {
    submitButton.disabled = isLoading;
    submitButton.setAttribute("aria-busy", String(isLoading));
    submitButton.innerHTML = isLoading
      ? '<span class="btn__spinner" aria-hidden="true"></span><span class="btn__label">Confronto…</span>'
      : '<span class="btn__label">Confronta</span>';
  }

  function buildFormData() {
    var data = new FormData();
    data.append("reference", referenceInput.files[0]);
    if (currentSource === "job") {
      data.append("job_id", jobSelect.value);
      data.append("variant", variantSelect.value);
    } else {
      data.append("hypothesis", hypothesisInput.files[0]);
    }
    return data;
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    clearErrors();
    resultEl.hidden = true;
    if (!referenceInput.files[0]) {
      showFieldError("reference", "Scegli un file di testo di riferimento.");
      return;
    }
    if (currentSource === "job" && !jobSelect.value) {
      showFieldError("job_id", "Scegli una trascrizione completata.");
      return;
    }
    if (currentSource === "file" && !hypothesisInput.files[0]) {
      showFieldError("hypothesis", "Scegli il file di testo da confrontare.");
      return;
    }
    setLoading(true);
    fetch(WER_URL, { method: "POST", body: buildFormData() })
      .then(function (response) {
        return response.json().then(function (body) {
          return { status: response.status, body: body };
        });
      })
      .then(function (result) {
        setLoading(false);
        if (result.status === 200) {
          renderResult(result.body.data);
        } else {
          applyServerErrors(result.body);
        }
      })
      .catch(function () {
        setLoading(false);
        formError.hidden = false;
        formError.textContent = "Impossibile contattare il server. Riprova.";
      });
  });

  loadJobs();
})();

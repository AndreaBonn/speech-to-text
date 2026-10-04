// sbobina · study page: "Aggiungi i concetti al mazzo" imports the generated
// concept cards into the course's spaced-repetition deck. job_id comes from
// root.dataset.jobId, the same source studio.js reads.
(function () {
  "use strict";

  var root = document.querySelector(".study[data-job-id]");
  var button = document.getElementById("study-cards-add");
  var statusEl = document.getElementById("study-cards-status");
  if (!root || !button || !statusEl) {
    return;
  }

  var JOB_ID = root.dataset.jobId;
  var URL = "/api/v1/jobs/" + JOB_ID + "/cards/from-concepts";
  var COURSE_REQUIRED_MESSAGE = "Imposta un corso per la lezione per creare carte.";
  var FAILED_MESSAGE = "Creazione non riuscita. Controlla che il server sia attivo e riprova.";

  function element(tag, className, text) {
    var el = document.createElement(tag);
    if (className) {
      el.className = className;
    }
    if (text !== undefined) {
      el.textContent = text;
    }
    return el;
  }

  function showMessage(text, tone) {
    statusEl.textContent = "";
    statusEl.hidden = false;
    statusEl.appendChild(element("p", "banner banner--" + tone, text));
  }

  function showCreated(created) {
    if (created === 0) {
      showMessage("Nessuna carta nuova: i concetti sono già nel mazzo.", "info");
      return;
    }
    statusEl.textContent = "";
    statusEl.hidden = false;
    var banner = element("p", "banner banner--success");
    banner.appendChild(
      document.createTextNode(created + " carte aggiunte al ripasso. ")
    );
    var link = document.createElement("a");
    link.href = "/ripasso";
    link.textContent = "Vai al ripasso";
    banner.appendChild(link);
    statusEl.appendChild(banner);
  }

  function setBusy(busy) {
    button.disabled = busy;
    button.setAttribute("aria-busy", String(busy));
  }

  button.addEventListener("click", function () {
    setBusy(true);
    statusEl.hidden = true;
    fetch(URL, { method: "POST" })
      .then(function (response) {
        return response.json().then(function (body) {
          return { status: response.status, body: body };
        });
      })
      .then(function (result) {
        setBusy(false);
        if (result.status === 201) {
          showCreated(result.body.data.created);
          return;
        }
        var error = result.body.error || {};
        if (error.code === "COURSE_REQUIRED") {
          showMessage(COURSE_REQUIRED_MESSAGE, "danger");
          return;
        }
        showMessage(error.message || FAILED_MESSAGE, "danger");
      })
      .catch(function () {
        setBusy(false);
        showMessage(FAILED_MESSAGE, "danger");
      });
  });
})();

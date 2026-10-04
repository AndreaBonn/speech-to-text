// sbobina · practice page: requests and per-question feedback (busy buttons,
// inline errors, locked forms). Split out of esercitazione.js to stay under
// the file size limit.
(function () {
  "use strict";

  var dom = window.SbobinaDom;
  var el = window.SbobinaPracticeResult.el;
  // web/errors codes the student can act on; anything else gets a generic retry.
  var ERROR_MESSAGES = {
    ANSWER_ALREADY_SUBMITTED: "Questa domanda risulta già consegnata: mostro la risposta salvata.",
    VALIDATION_ERROR: "La risposta non è valida: controllala e riprova.",
  };
  var NETWORK_MESSAGE = "Connessione al server persa: la risposta è ancora qui, riprova.";
  var GENERIC_MESSAGE = "Il server non ha accettato la richiesta: riprova.";

  // ---------- requests ----------

  function requestError(status, payload) {
    var code = payload && payload.error && payload.error.code;
    var message = ERROR_MESSAGES[code] || (status === 422 ? ERROR_MESSAGES.VALIDATION_ERROR : GENERIC_MESSAGE);
    var error = new Error(message);
    error.code = code;
    return error;
  }

  function postJson(url, body) {
    var options = { method: "POST", headers: { "Content-Type": "application/json" } };
    if (body) {
      options.body = JSON.stringify(body);
    }
    return fetch(url, options).then(
      function (response) {
        return response
          .json()
          .catch(function () {
            return {};
          })
          .then(function (payload) {
            if (!response.ok) {
              throw requestError(response.status, payload);
            }
            return payload.data;
          });
      },
      function () {
        throw new Error(NETWORK_MESSAGE);
      }
    );
  }

  function getJson(url) {
    return fetch(url).then(function (response) {
      if (!response.ok) {
        throw new Error("fetch failed: " + response.status);
      }
      return response.json();
    });
  }

  // ---------- busy and error feedback ----------

  function setBusy(button, busy, label) {
    button.disabled = busy;
    button.setAttribute("aria-busy", String(busy));
    dom.clearChildren(button);
    if (busy) {
      button.appendChild(el("span", "btn__spinner"));
    }
    button.appendChild(document.createTextNode(label));
  }

  function showError(container, message) {
    var errorEl = container.querySelector(".practice-question__error");
    if (!errorEl) {
      errorEl = el("p", "field__error practice-question__message practice-question__error");
      errorEl.setAttribute("role", "alert");
      container.appendChild(errorEl);
    }
    errorEl.textContent = message;
  }

  function clearError(container) {
    var errorEl = container.querySelector(".practice-question__error");
    if (errorEl) {
      errorEl.remove();
    }
  }

  function setLocked(form, locked) {
    form.querySelectorAll("input").forEach(function (input) {
      input.disabled = locked;
    });
    form.querySelectorAll("textarea").forEach(function (textarea) {
      textarea.readOnly = locked;
    });
  }

  window.SbobinaPracticeUi = {
    getJson: getJson,
    postJson: postJson,
    setBusy: setBusy,
    showError: showError,
    clearError: clearError,
    setLocked: setLocked,
  };
})();

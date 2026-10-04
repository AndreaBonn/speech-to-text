// sbobina · course generations: the "Svolgi" button that starts a practice
// attempt on a finished generation and opens it (T049).
(function () {
  "use strict";

  var START_ERRORS = {
    GENERATION_FAILED: "La generazione è fallita: non si può svolgere.",
  };

  function start(generationUrl, key, statusEl, button) {
    button.disabled = true;
    fetch(generationUrl + "/attempts", { method: "POST" })
      .then(function (response) {
        return response.json().then(function (body) {
          if (!response.ok) {
            var code = body && body.error && body.error.code;
            throw new Error(START_ERRORS[code] || "Impossibile avviare l'esercitazione: riprova.");
          }
          return body.data;
        });
      })
      .then(function (attempt) {
        window.location.href =
          "/corsi/" + encodeURIComponent(key) + "/esercitazioni/" + encodeURIComponent(attempt.id);
      })
      .catch(function (error) {
        button.disabled = false;
        statusEl.hidden = false;
        statusEl.textContent =
          error instanceof SyntaxError ? "Impossibile avviare l'esercitazione: riprova." : error.message;
      });
  }

  function startButton(generationUrl, key, statusEl) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--primary";
    button.textContent = "Svolgi";
    button.addEventListener("click", function () {
      start(generationUrl, key, statusEl, button);
    });
    return button;
  }

  window.SbobinaPracticeStart = { button: startButton };
})();

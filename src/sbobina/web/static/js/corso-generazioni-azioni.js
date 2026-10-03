// sbobina · course generations: cancel and delete requests with their
// user-facing outcome. The caller passes the item URL and a reload callback.
(function () {
  "use strict";

  var showRetryStatus = window.SbobinaDom.showRetryStatus;

  function showMessage(statusEl, message) {
    statusEl.hidden = false;
    statusEl.textContent = message;
  }

  function cancel(itemUrl, statusEl, reload) {
    fetch(itemUrl + "/cancel", { method: "POST" })
      .then(function (response) {
        reload();
        if (response.status === 409) {
          showMessage(statusEl, "La generazione era già terminata.");
        } else if (!response.ok) {
          throw new Error("cancel failed");
        }
      })
      .catch(function () {
        showRetryStatus(statusEl, "Impossibile annullare la generazione.", function () {
          cancel(itemUrl, statusEl, reload);
        });
      });
  }

  function remove(itemUrl, statusEl, reload) {
    fetch(itemUrl, { method: "DELETE" })
      .then(function (response) {
        if (response.status === 204) {
          reload();
          return null;
        }
        return response.json();
      })
      .then(function (body) {
        if (body === null) {
          return;
        }
        var busy = body && body.error && body.error.code === "GENERATION_BUSY";
        showMessage(
          statusEl,
          busy
            ? "La generazione è in corso: annullala prima di eliminarla."
            : "Impossibile eliminare la generazione."
        );
      })
      .catch(function () {
        showMessage(statusEl, "Impossibile eliminare la generazione.");
      });
  }

  window.SbobinaGenerationActions = { cancel: cancel, remove: remove };
})();

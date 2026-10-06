// sbobina · generation page (/corsi/<key>/generazioni/<id>), the target of a
// card made from a generation: that generation's detail and its exports.
(function () {
  "use strict";
  var root = document.getElementById("generazione-root");
  var detail = window.SbobinaGenerationDetail;
  if (!root || !detail) return;
  var container = document.getElementById("generazione-detail");
  var apiBase = "/api/v1/courses/" + encodeURIComponent(root.dataset.courseKey) + "/generations";

  function showError(text) {
    container.appendChild(detail.el("p", "banner banner--danger", text));
  }

  function show(record) {
    // A rendering bug is not a missing generation: its own message and trace (A26).
    try {
      detail.render(container, record);
      container.appendChild(detail.downloadLinks(apiBase, record));
    } catch (error) {
      console.error("generation render failed", error);
      showError("Impossibile mostrare la generazione.");
    }
  }

  fetch(apiBase + "/" + encodeURIComponent(root.dataset.generationId))
    .then(function (response) {
      if (!response.ok) {
        throw new Error("generation fetch failed: HTTP " + response.status);
      }
      return response.json();
    })
    .then(function (body) {
      show(body.data);
    })
    .catch(function (error) {
      console.error(error);
      showError("Impossibile caricare la generazione.");
    });
})();

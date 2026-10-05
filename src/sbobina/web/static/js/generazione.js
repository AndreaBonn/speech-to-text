// sbobina · generation page (/corsi/<key>/generazioni/<id>), the target of a
// card made from a generation: that generation's detail and its exports.
(function () {
  "use strict";
  var root = document.getElementById("generazione-root");
  var detail = window.SbobinaGenerationDetail;
  if (!root || !detail) return;
  var container = document.getElementById("generazione-detail");
  var apiBase = "/api/v1/courses/" + encodeURIComponent(root.dataset.courseKey) + "/generations";

  fetch(apiBase + "/" + encodeURIComponent(root.dataset.generationId))
    .then(function (response) {
      if (!response.ok) {
        throw new Error("generation fetch failed");
      }
      return response.json();
    })
    .then(function (body) {
      detail.render(container, body.data);
      container.appendChild(detail.downloadLinks(apiBase, body.data));
    })
    .catch(function () {
      container.appendChild(
        detail.el("p", "banner banner--danger", "Impossibile caricare la generazione.")
      );
    });
})();

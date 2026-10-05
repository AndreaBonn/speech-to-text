// sbobina · system banner: CPU fallback and Ollama status from /api/v1/system,
// otherwise the device and model in the rail. Moved out of base.html so the
// Content-Security-Policy can forbid inline scripts (T091).
(function () {
  var region = document.getElementById("system-banner");
  var indicator = document.getElementById("rail-indicator");

  function bannerMarkup(kind, message) {
    var el = document.createElement("div");
    el.className = "banner banner--" + kind;
    el.textContent = message;
    return el;
  }

  fetch("/api/v1/system")
    .then(function (response) {
      if (!response.ok) {
        throw new Error("system info non disponibile");
      }
      return response.json();
    })
    .then(function (body) {
      var data = body.data;
      var ollama = data.ollama || {};
      var banners = [];
      if (data.device === "cpu") {
        banners.push(
          bannerMarkup(
            "warning",
            "Trascrizione su CPU: sarà più lenta. " + data.reason + "."
          )
        );
      }
      if (ollama.status && ollama.status !== "ready") {
        banners.push(bannerMarkup("warning", ollama.message));
      }
      if (banners.length > 0) {
        region.replaceChildren.apply(region, banners);
        return;
      }
      region.replaceChildren();
      if (indicator) {
        indicator.textContent =
          data.device.toUpperCase() + " · " + data.whisper_model;
      }
    })
    .catch(function () {
      // Non critico: se /api/v1/system non risponde il resto della
      // pagina funziona comunque, il banner resta semplicemente vuoto.
    });
})();

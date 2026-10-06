// sbobina · engine warning banner: shown on every page (slot in base.html)
// when the configured LLM/transcription engine is "api" but required API
// keys or chain entries are missing. Fails silently if /api/v1/settings is
// unreachable: the banner is advisory, not load-bearing.
(function () {
  var region = document.getElementById("engine-warning-banner");
  if (!region) {
    return;
  }

  var PROVIDER_LABELS = {
    groq: "Groq",
    openai: "OpenAI",
    gemini: "Gemini",
    anthropic: "Anthropic",
    assemblyai: "AssemblyAI",
  };

  function providerLabel(provider) {
    return PROVIDER_LABELS[provider] || provider;
  }

  function banner(message) {
    var el = document.createElement("div");
    el.className = "banner banner--warning";
    el.setAttribute("role", "status");
    el.appendChild(document.createTextNode(message + " "));
    var link = document.createElement("a");
    link.href = "/impostazioni";
    link.textContent = "Impostazioni";
    el.appendChild(link);
    el.appendChild(document.createTextNode("."));
    return el;
  }

  // The settings page shows the same warnings in its own banner.
  if (window.location.pathname === "/impostazioni") {
    return;
  }

  fetch("/api/v1/settings")
    .then(function (response) {
      if (!response.ok) {
        throw new Error("impostazioni non disponibili");
      }
      return response.json();
    })
    .then(function (body) {
      var warnings = (body.data && body.data.warnings) || {};
      var banners = [];
      if (warnings.empty_chain) {
        banners.push(
          banner("Nessun modello nell'ordine dei modelli: aggiungine uno nelle")
        );
      }
      if (warnings.missing_keys && warnings.missing_keys.length > 0) {
        var labels = warnings.missing_keys.map(providerLabel).join(", ");
        banners.push(
          banner("Mancano le chiavi API per: " + labels + ". Aggiungile nelle")
        );
      }
      region.replaceChildren.apply(region, banners);
    })
    .catch(function (error) {
      console.warn("engine-warning: impossibile leggere /api/v1/settings", error);
    });
})();

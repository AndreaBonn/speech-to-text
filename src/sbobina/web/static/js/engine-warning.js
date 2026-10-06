// sbobina · engine warning banner: shown on every page (slot in base.html)
// when the saved engine settings need the user's attention (missing keys,
// empty chain, unconfirmed cloud engine, unreadable keys file, unsafe
// config dir). Fails silently if /api/v1/settings is unreachable: the
// banner is advisory. The sentences are shared with the Settings page
// through window.SbobinaEngineWarnings.
(function () {
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

  // Most urgent first: an unsafe config dir means every saved choice is
  // ignored, an unreadable keys file means saved keys are lost.
  function messages(warnings) {
    var out = [];
    if (warnings.config_dir_unsafe) {
      out.push(
        "La cartella delle impostazioni si trova dentro i dati o il progetto: " +
          "motore, modelli e chiavi salvati vengono ignorati. Imposta " +
          "SBOBINA_CONFIG_DIR su un'altra cartella."
      );
    }
    if (warnings.credentials_unreadable) {
      out.push(
        "Il file delle chiavi salvate non è leggibile: le chiavi inserite " +
          "finora non vengono usate. Reinseriscile."
      );
    }
    if (warnings.consent_missing && warnings.consent_missing.length > 0) {
      out.push(
        "Un motore cloud salvato non è stato confermato: finché non lo " +
          "confermi resta attivo quello locale."
      );
    }
    if (warnings.empty_chain) {
      out.push("Nessun modello nell'ordine dei modelli: aggiungine uno.");
    }
    if (warnings.missing_keys && warnings.missing_keys.length > 0) {
      out.push(
        "Mancano le chiavi API per: " +
          warnings.missing_keys.map(providerLabel).join(", ") +
          "."
      );
    }
    return out;
  }

  window.SbobinaEngineWarnings = { messages: messages, providerLabel: providerLabel };

  var region = document.getElementById("engine-warning-banner");
  // The settings page shows the same warnings in its own banner.
  if (!region || window.location.pathname === "/impostazioni") {
    return;
  }

  function banner(message) {
    var el = document.createElement("div");
    el.className = "banner banner--warning";
    el.setAttribute("role", "status");
    el.appendChild(document.createTextNode(message + " "));
    var link = document.createElement("a");
    link.href = "/impostazioni";
    link.textContent = "Apri le Impostazioni";
    el.appendChild(link);
    return el;
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
      region.replaceChildren.apply(region, messages(warnings).map(banner));
    })
    .catch(function (error) {
      console.warn("engine-warning: impossibile leggere /api/v1/settings", error);
    });
})();

// sbobina · job form engine awareness: relabels the Ollama fallback field
// and the Whisper model field when the active engine is cloud-based. Kept
// in its own module so jobs.js (602 lines) does not grow (T038).
(function () {
  var form = document.getElementById("upload-form");
  if (!form) {
    return;
  }

  function applyLlmEngine(prefs) {
    if (prefs.llm_engine !== "api") {
      return;
    }
    var label = document.querySelector('label[for="ollama_model"]');
    if (label) {
      label.textContent = "Modello locale di riserva";
    }
    var correctLabel = document.querySelector('label[for="correct"]');
    if (correctLabel) {
      correctLabel.textContent = "Correggi con i modelli API dopo la trascrizione";
    }
    var select = document.getElementById("ollama_model");
    var field = select ? select.closest(".field") : null;
    if (!field) {
      return;
    }
    var parts = (prefs.llm_chain || []).map(function (entry) {
      return entry.provider + "/" + entry.model;
    });
    if (prefs.llm_ollama_fallback) {
      parts.push("Ollama");
    }
    if (parts.length === 0) {
      return;
    }
    var line = document.createElement("p");
    line.className = "field__helper";
    line.id = "llm-chain-line";
    line.textContent = "Catena attiva: " + parts.join(" → ");
    field.appendChild(line);
  }

  function applyTranscriptionEngine(prefs) {
    if (prefs.transcription_engine !== "assemblyai") {
      return;
    }
    var select = document.getElementById("whisper_model");
    var field = select ? select.closest(".field") : null;
    if (!field) {
      return;
    }
    field.hidden = true;
    var notice = document.createElement("p");
    notice.className = "field__helper";
    notice.id = "assemblyai-notice";
    notice.textContent =
      "Trascrizione con AssemblyAI (l'audio viene caricato sul servizio).";
    field.insertAdjacentElement("afterend", notice);
  }

  fetch("/api/v1/settings")
    .then(function (response) {
      if (!response.ok) {
        throw new Error("impostazioni non disponibili");
      }
      return response.json();
    })
    .then(function (body) {
      var prefs = (body.data && body.data.preferences) || {};
      applyLlmEngine(prefs);
      applyTranscriptionEngine(prefs);
    })
    .catch(function (error) {
      console.warn("engine-form: impossibile leggere /api/v1/settings", error);
    });
})();

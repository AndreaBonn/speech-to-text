// sbobina · Settings page: engine, model chain, API keys, transcription engine.
// All DOM built with createElement/textContent: no innerHTML with data (CSP,
// anti-XSS). Each mutation hits the API immediately or on an explicit Save;
// there is no separate "draft saved to localStorage" step.
// The chain (section 2) and keys (section 3) sections live in
// settings-chain.js / settings-keys.js (project line limit); settings-dom.js
// holds the shared, stateless DOM helpers both of them and this file use.
(function () {
  "use strict";

  var Dom = window.SbobinaSettingsDom;
  var byId = Dom.byId;
  var setHidden = Dom.setHidden;
  var clearChildren = Dom.clearChildren;
  var fetchJson = Dom.fetchJson;
  var errorMessage = Dom.errorMessage;

  var SETTINGS_URL = "/api/v1/settings";
  var LLM_URL = SETTINGS_URL + "/llm";
  var TRANSCRIPTION_URL = SETTINGS_URL + "/transcription";

  var PROVIDER_LABELS = {
    groq: "Groq",
    gemini: "Gemini",
    openai: "OpenAI",
    anthropic: "Anthropic",
    assemblyai: "AssemblyAI",
  };

  var el = {
    banner: byId("settings-banner"),
    engineSkeleton: byId("engine-skeleton"),
    engineFieldset: byId("engine-fieldset"),
    engineLocal: byId("engine-local"),
    engineApi: byId("engine-api"),
    engineLockedNote: byId("engine-locked-note"),
    engineError: byId("engine-error"),
    transcriptionSkeleton: byId("transcription-skeleton"),
    transcriptionFieldset: byId("transcription-fieldset"),
    transcriptionWhisper: byId("transcription-whisper"),
    transcriptionAssemblyai: byId("transcription-assemblyai"),
    transcriptionKeyWarning: byId("transcription-key-warning"),
    transcriptionLockedNote: byId("transcription-locked-note"),
    transcriptionError: byId("transcription-error"),
    cloudAckDialog: byId("cloud-ack-dialog"),
    cloudAckCancel: byId("cloud-ack-cancel"),
    cloudAckConfirm: byId("cloud-ack-confirm"),
    audioAckDialog: byId("audio-ack-dialog"),
    audioAckCancel: byId("audio-ack-cancel"),
    audioAckConfirm: byId("audio-ack-confirm"),
  };

  var chainModule = window.SbobinaSettingsChain.create({
    providerLabels: PROVIDER_LABELS,
    onSave: function (ollamaFallback) {
      saveLlm({ llm_ollama_fallback: ollamaFallback });
    },
  });

  var keysModule = window.SbobinaSettingsKeys.create({
    providerLabels: PROVIDER_LABELS,
    onChange: renderBanner,
  });

  // Server-confirmed view (null while loading or on error). The chain draft
  // and key rows the user is still editing live inside chainModule/keysModule.
  var settingsState = null;
  var pendingEngineValue = null;

  // ---------- loading ----------

  function loadSettings() {
    [el.engineSkeleton, el.transcriptionSkeleton].forEach(function (node) {
      node.className = "skeleton-row";
      clearChildren(node);
      setHidden(node, false);
    });
    setHidden(el.engineFieldset, true);
    setHidden(el.transcriptionFieldset, true);
    chainModule.showLoading();
    keysModule.showLoading();
    return fetchJson(SETTINGS_URL)
      .then(function (result) {
        if (result.status !== 200) {
          throw new Error("settings fetch failed");
        }
        applyState(result.body.data);
      })
      .catch(function () {
        [el.engineSkeleton, el.transcriptionSkeleton].forEach(function (node) {
          Dom.renderLoadError(node, loadSettings);
        });
        chainModule.showLoadError(loadSettings);
        keysModule.showLoadError(loadSettings);
      });
  }

  function applyState(data) {
    settingsState = data;
    chainModule.setState(data.preferences);
    keysModule.setKeys(data.keys);
    renderAll();
  }

  function renderAll() {
    renderBanner();
    renderEngine();
    chainModule.render();
    keysModule.render();
    renderTranscription();
  }

  // ---------- banner ----------

  function renderBanner() {
    clearChildren(el.banner);
    var warnings = settingsState.warnings;
    var missing = warnings.missing_keys;
    if (missing.length > 0) {
      var labels = missing.map(function (provider) {
        return PROVIDER_LABELS[provider] || provider;
      });
      el.banner.appendChild(
        Dom.makeBanner("Aggiungi le chiavi per: " + labels.join(", "))
      );
    }
    if (warnings.empty_chain) {
      el.banner.appendChild(
        Dom.makeBanner("Nessun modello configurato nella catena API.")
      );
    }
  }

  // ---------- section 1: engine ----------

  function renderEngine() {
    setHidden(el.engineSkeleton, true);
    setHidden(el.engineFieldset, false);
    var prefs = settingsState.preferences;
    var locked = settingsState.locked_by_env.indexOf("llm_engine") !== -1;
    el.engineLocal.checked = prefs.llm_engine === "local";
    el.engineApi.checked = prefs.llm_engine === "api";
    el.engineLocal.disabled = locked;
    el.engineApi.disabled = locked;
    setHidden(el.engineLockedNote, !locked);
    setHidden(el.engineError, true);
  }

  function handleEngineChange(event) {
    var value = event.target.value;
    if (value === "api" && settingsState.preferences.cloud_ack === null) {
      pendingEngineValue = value;
      el.cloudAckDialog.showModal();
      return;
    }
    saveLlm({ llm_engine: value, cloud_ack: true });
  }

  function saveLlm(overrides) {
    var prefs = settingsState.preferences;
    var body = {
      llm_engine: prefs.llm_engine,
      llm_chain: chainModule.getDraft(),
      llm_ollama_fallback: prefs.llm_ollama_fallback,
      cloud_ack: true,
    };
    Object.keys(overrides).forEach(function (key) {
      body[key] = overrides[key];
    });
    return fetchJson(LLM_URL, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (result) {
      if (result.status !== 200) {
        showEngineError(errorMessage(result.body, "Impossibile salvare."));
        renderEngine();
        return;
      }
      applyState(result.body.data);
    });
  }

  function showEngineError(message) {
    el.engineError.textContent = message;
    setHidden(el.engineError, false);
  }

  // ---------- cloud-ack dialog (section 1) ----------

  function onCloudAckConfirm() {
    el.cloudAckDialog.close();
    var value = pendingEngineValue;
    pendingEngineValue = null;
    saveLlm({ llm_engine: value, cloud_ack: true });
  }

  function onCloudAckCancel() {
    pendingEngineValue = null;
    el.cloudAckDialog.close();
    renderEngine();
  }

  // ---------- section 4: transcription ----------

  function renderTranscription() {
    setHidden(el.transcriptionSkeleton, true);
    setHidden(el.transcriptionFieldset, false);
    var prefs = settingsState.preferences;
    var locked = settingsState.locked_by_env.indexOf("transcription_engine") !== -1;
    el.transcriptionWhisper.checked = prefs.transcription_engine === "whisper";
    el.transcriptionAssemblyai.checked = prefs.transcription_engine === "assemblyai";
    el.transcriptionWhisper.disabled = locked;
    el.transcriptionAssemblyai.disabled = locked;
    setHidden(el.transcriptionLockedNote, !locked);
    setHidden(el.transcriptionError, true);
    var missingAssemblyai =
      prefs.transcription_engine === "assemblyai" &&
      settingsState.warnings.missing_keys.indexOf("assemblyai") !== -1;
    if (missingAssemblyai) {
      el.transcriptionKeyWarning.textContent =
        "Manca la chiave AssemblyAI: aggiungila nella sezione Chiavi API qui sopra.";
    }
    setHidden(el.transcriptionKeyWarning, !missingAssemblyai);
  }

  function handleTranscriptionChange(event) {
    var value = event.target.value;
    if (value === "assemblyai" && settingsState.preferences.cloud_ack_audio === null) {
      el.audioAckDialog.showModal();
      return;
    }
    saveTranscription(value, true);
  }

  function saveTranscription(value, cloudAckAudio) {
    return fetchJson(TRANSCRIPTION_URL, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transcription_engine: value,
        cloud_ack_audio: cloudAckAudio,
      }),
    }).then(function (result) {
      if (result.status !== 200) {
        el.transcriptionError.textContent = errorMessage(
          result.body,
          "Impossibile salvare."
        );
        setHidden(el.transcriptionError, false);
        renderTranscription();
        return;
      }
      applyState(result.body.data);
    });
  }

  function onAudioAckConfirm() {
    el.audioAckDialog.close();
    saveTranscription("assemblyai", true);
  }

  function onAudioAckCancel() {
    el.audioAckDialog.close();
    renderTranscription();
  }

  // ---------- wiring ----------

  el.engineLocal.addEventListener("change", handleEngineChange);
  el.engineApi.addEventListener("change", handleEngineChange);
  el.cloudAckConfirm.addEventListener("click", onCloudAckConfirm);
  el.cloudAckCancel.addEventListener("click", onCloudAckCancel);
  el.transcriptionWhisper.addEventListener("change", handleTranscriptionChange);
  el.transcriptionAssemblyai.addEventListener("change", handleTranscriptionChange);
  el.audioAckConfirm.addEventListener("click", onAudioAckConfirm);
  el.audioAckCancel.addEventListener("click", onAudioAckCancel);
  // Escape closes a native dialog without a click: revert the radio too.
  el.cloudAckDialog.addEventListener("cancel", onCloudAckCancel);
  el.audioAckDialog.addEventListener("cancel", onAudioAckCancel);

  loadSettings();
})();

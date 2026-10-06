// sbobina · Settings page: engine, model chain, API keys, transcription engine.
// All DOM built with createElement/textContent: no innerHTML with data (CSP,
// anti-XSS). Each mutation hits the API immediately or on an explicit Save;
// there is no separate "draft saved to localStorage" step.
(function () {
  "use strict";

  var SETTINGS_URL = "/api/v1/settings";
  var LLM_URL = SETTINGS_URL + "/llm";
  var TRANSCRIPTION_URL = SETTINGS_URL + "/transcription";
  var KEYS_URL = SETTINGS_URL + "/keys/";
  var MAX_CHAIN_LINKS = 8;

  var CHAIN_PROVIDERS = ["groq", "gemini", "openai", "anthropic"];
  var KEY_PROVIDERS = ["groq", "gemini", "openai", "anthropic", "assemblyai"];
  var PROVIDER_LABELS = {
    groq: "Groq",
    gemini: "Gemini",
    openai: "OpenAI",
    anthropic: "Anthropic",
    assemblyai: "AssemblyAI",
  };
  var MODEL_PLACEHOLDERS = {
    groq: "es. llama-3.3-70b-versatile",
    gemini: "es. gemini-2.5-flash",
    openai: "es. gpt-4.1-mini",
    anthropic: "es. claude-sonnet-4-5",
  };
  var TEST_RESULT_LABELS = {
    ok: "Chiave valida",
    auth: "Chiave non valida",
    network: "Servizio non raggiungibile",
    limit: "Limite raggiunto",
    missing: "Nessuna chiave",
    error: "Errore del servizio",
  };

  function byId(id) {
    return document.getElementById(id);
  }

  var el = {
    banner: byId("settings-banner"),
    engineSkeleton: byId("engine-skeleton"),
    engineFieldset: byId("engine-fieldset"),
    engineLocal: byId("engine-local"),
    engineApi: byId("engine-api"),
    engineLockedNote: byId("engine-locked-note"),
    engineError: byId("engine-error"),
    chainSkeleton: byId("chain-skeleton"),
    chainForm: byId("chain-form"),
    chainList: byId("chain-list"),
    chainAdd: byId("chain-add"),
    chainOllamaFallback: byId("chain-ollama-fallback"),
    chainError: byId("chain-error"),
    chainSave: byId("chain-save"),
    keysWindowsNote: byId("keys-windows-note"),
    keysSkeleton: byId("keys-skeleton"),
    keysList: byId("keys-list"),
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

  // Server-confirmed view (null while loading or on error) plus the chain
  // the user is still editing before pressing "Salva" in section 2.
  var settingsState = null;
  var chainDraft = [];
  var pendingEngineValue = null;

  function setHidden(node, hidden) {
    if (hidden) {
      node.setAttribute("hidden", "");
    } else {
      node.removeAttribute("hidden");
    }
  }

  function clearChildren(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function fetchJson(url, options) {
    return fetch(url, options).then(function (response) {
      return response.json().then(function (body) {
        return { status: response.status, body: body };
      });
    });
  }

  function errorMessage(body, fallback) {
    return (body && body.error && body.error.message) || fallback;
  }

  function isWindows() {
    var uaData = navigator.userAgentData;
    if (uaData && typeof uaData.platform === "string") {
      return uaData.platform.indexOf("Win") !== -1;
    }
    return navigator.platform.indexOf("Win") !== -1;
  }

  // ---------- loading ----------

  function loadSettings() {
    [
      el.engineSkeleton,
      el.chainSkeleton,
      el.keysSkeleton,
      el.transcriptionSkeleton,
    ].forEach(function (node) {
      node.className = "skeleton-row";
      clearChildren(node);
      setHidden(node, false);
    });
    [el.engineFieldset, el.chainForm, el.keysList, el.transcriptionFieldset].forEach(
      function (node) {
        setHidden(node, true);
      }
    );
    return fetchJson(SETTINGS_URL)
      .then(function (result) {
        if (result.status !== 200) {
          throw new Error("settings fetch failed");
        }
        applyState(result.body.data);
      })
      .catch(function () {
        [
          el.engineSkeleton,
          el.chainSkeleton,
          el.keysSkeleton,
          el.transcriptionSkeleton,
        ].forEach(renderLoadError);
      });
  }

  function renderLoadError(skeletonNode) {
    skeletonNode.className = "queue__error";
    clearChildren(skeletonNode);
    var text = document.createElement("span");
    text.textContent = "Impossibile caricare le impostazioni.";
    var retry = document.createElement("button");
    retry.type = "button";
    retry.className = "btn btn--secondary";
    retry.textContent = "Riprova";
    retry.addEventListener("click", loadSettings);
    skeletonNode.appendChild(text);
    skeletonNode.appendChild(retry);
  }

  function applyState(data) {
    settingsState = data;
    chainDraft = data.preferences.llm_chain.map(function (entry) {
      return { provider: entry.provider, model: entry.model };
    });
    renderAll();
  }

  function renderAll() {
    renderBanner();
    renderEngine();
    renderChain();
    renderKeys();
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
        makeBanner("Aggiungi le chiavi per: " + labels.join(", "))
      );
    }
    if (warnings.empty_chain) {
      el.banner.appendChild(
        makeBanner("Nessun modello configurato nella catena API.")
      );
    }
  }

  function makeBanner(message) {
    var banner = document.createElement("div");
    banner.className = "banner banner--warning";
    banner.textContent = message;
    return banner;
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
      llm_chain: chainDraft,
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

  function showChainError(message) {
    el.chainError.textContent = message;
    setHidden(el.chainError, false);
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

  // ---------- section 2: chain ----------

  function renderChain() {
    setHidden(el.chainSkeleton, true);
    setHidden(el.chainForm, false);
    clearChildren(el.chainList);
    if (chainDraft.length === 0) {
      var empty = document.createElement("li");
      empty.className = "chain-list__empty";
      empty.textContent = "Nessun modello in catena. Aggiungi il primo modello.";
      el.chainList.appendChild(empty);
    } else {
      chainDraft.forEach(function (entry, index) {
        el.chainList.appendChild(buildChainRow(entry, index));
      });
    }
    el.chainAdd.disabled = chainDraft.length >= MAX_CHAIN_LINKS;
    el.chainOllamaFallback.checked = settingsState.preferences.llm_ollama_fallback;
    setHidden(el.chainError, true);
  }

  function buildChainRow(entry, index) {
    var row = document.createElement("li");
    row.className = "chain-row";

    var select = document.createElement("select");
    select.className = "select-input chain-row__provider-select";
    select.setAttribute("aria-label", "Provider, posizione " + (index + 1));
    CHAIN_PROVIDERS.forEach(function (provider) {
      var option = document.createElement("option");
      option.value = provider;
      option.textContent = PROVIDER_LABELS[provider];
      if (provider === entry.provider) {
        option.selected = true;
      }
      select.appendChild(option);
    });
    select.addEventListener("change", function () {
      chainDraft[index].provider = select.value;
    });

    var modelInput = document.createElement("input");
    modelInput.type = "text";
    modelInput.className = "text-input chain-row__model-input";
    modelInput.value = entry.model;
    modelInput.placeholder = MODEL_PLACEHOLDERS[entry.provider] || "Nome modello";
    modelInput.setAttribute("aria-label", "Modello, posizione " + (index + 1));
    modelInput.addEventListener("input", function () {
      chainDraft[index].model = modelInput.value;
    });

    var controls = document.createElement("div");
    controls.className = "chain-row__controls";
    controls.appendChild(
      makeChainButton("Su", index > 0, function () {
        moveChain(index, -1);
      })
    );
    controls.appendChild(
      makeChainButton("Giù", index < chainDraft.length - 1, function () {
        moveChain(index, 1);
      })
    );
    controls.appendChild(
      makeChainButton("Rimuovi", true, function () {
        removeChain(index);
      })
    );

    row.appendChild(select);
    row.appendChild(modelInput);
    row.appendChild(controls);
    return row;
  }

  function makeChainButton(label, enabled, onClick) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--ghost chain-row__btn";
    button.textContent = label;
    button.disabled = !enabled;
    button.addEventListener("click", onClick);
    return button;
  }

  function moveChain(index, delta) {
    var target = index + delta;
    if (target < 0 || target >= chainDraft.length) {
      return;
    }
    var entry = chainDraft.splice(index, 1)[0];
    chainDraft.splice(target, 0, entry);
    renderChain();
  }

  function removeChain(index) {
    chainDraft.splice(index, 1);
    renderChain();
  }

  function addChain() {
    if (chainDraft.length >= MAX_CHAIN_LINKS) {
      return;
    }
    chainDraft.push({ provider: CHAIN_PROVIDERS[0], model: "" });
    renderChain();
  }

  // saveLlm always sends the in-progress chainDraft, and its success path
  // (applyState) resets chainDraft from the server's saved copy.
  function onChainSubmit(event) {
    event.preventDefault();
    saveLlm({ llm_ollama_fallback: el.chainOllamaFallback.checked });
  }

  // ---------- section 3: keys ----------

  function renderKeys() {
    setHidden(el.keysSkeleton, true);
    setHidden(el.keysWindowsNote, !isWindows());
    clearChildren(el.keysList);
    KEY_PROVIDERS.forEach(function (provider) {
      el.keysList.appendChild(buildKeyRow(provider, settingsState.keys[provider]));
    });
  }

  function keyStatusText(entry) {
    if (entry.source === "env") {
      return "Configurata da variabile d'ambiente";
    }
    if (entry.configured) {
      return "Configurata ····" + (entry.last4 || "");
    }
    return "Non configurata";
  }

  function buildKeyRow(provider, entry) {
    var row = document.createElement("div");
    row.className = "key-row";

    var title = document.createElement("span");
    title.className = "key-row__title";
    title.textContent = PROVIDER_LABELS[provider];
    row.appendChild(title);

    var status = document.createElement("span");
    status.className = "key-row__status";
    status.textContent = keyStatusText(entry);
    row.appendChild(status);

    var fromEnv = entry.source === "env";

    var input = document.createElement("input");
    input.type = "password";
    input.autocomplete = "off";
    input.className = "text-input key-row__input";
    input.setAttribute("aria-label", "Chiave " + PROVIDER_LABELS[provider]);
    input.disabled = fromEnv;
    row.appendChild(input);

    var error = document.createElement("p");
    error.className = "field__error";
    setHidden(error, true);

    var result = document.createElement("p");
    result.className = "key-row__result";
    setHidden(result, true);

    var controls = document.createElement("div");
    controls.className = "key-row__controls";

    var saveButton = document.createElement("button");
    saveButton.type = "button";
    saveButton.className = "btn btn--primary";
    saveButton.textContent = "Salva";
    saveButton.disabled = fromEnv;
    saveButton.addEventListener("click", function () {
      saveKey(provider, input, error);
    });
    controls.appendChild(saveButton);

    var removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "btn btn--ghost";
    removeButton.textContent = "Rimuovi";
    removeButton.disabled = fromEnv || !entry.configured;
    removeButton.addEventListener("click", function () {
      removeKey(provider);
    });
    controls.appendChild(removeButton);

    var testButton = document.createElement("button");
    testButton.type = "button";
    testButton.className = "btn btn--secondary";
    testButton.textContent = "Prova";
    testButton.addEventListener("click", function () {
      testKey(provider, result);
    });
    controls.appendChild(testButton);

    row.appendChild(controls);
    row.appendChild(error);
    row.appendChild(result);
    return row;
  }

  function saveKey(provider, input, errorNode) {
    var key = input.value;
    setHidden(errorNode, true);
    fetchJson(KEYS_URL + provider, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: key }),
    }).then(function (result) {
      if (result.status !== 200) {
        errorNode.textContent = errorMessage(result.body, "Chiave non valida.");
        setHidden(errorNode, false);
        return;
      }
      input.value = "";
      settingsState.keys[provider] = {
        configured: result.body.data.configured,
        last4: result.body.data.last4,
        source: result.body.data.source,
      };
      renderKeys();
      renderBanner();
    });
  }

  function removeKey(provider) {
    fetchJson(KEYS_URL + provider, { method: "DELETE" }).then(function (result) {
      if (result.status !== 204) {
        return;
      }
      settingsState.keys[provider] = { configured: false, last4: null, source: null };
      renderKeys();
      renderBanner();
    });
  }

  function testKey(provider, resultNode) {
    resultNode.textContent = "Verifica in corso…";
    setHidden(resultNode, false);
    fetchJson(KEYS_URL + provider + "/test", { method: "POST" }).then(function (result) {
      if (result.status !== 200) {
        resultNode.textContent = errorMessage(result.body, "Errore del servizio");
        return;
      }
      var outcome = result.body.data.result;
      resultNode.textContent = TEST_RESULT_LABELS[outcome] || outcome;
    });
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
  el.chainAdd.addEventListener("click", addChain);
  el.chainForm.addEventListener("submit", onChainSubmit);
  el.transcriptionWhisper.addEventListener("change", handleTranscriptionChange);
  el.transcriptionAssemblyai.addEventListener("change", handleTranscriptionChange);
  el.audioAckConfirm.addEventListener("click", onAudioAckConfirm);
  el.audioAckCancel.addEventListener("click", onAudioAckCancel);

  loadSettings();
})();

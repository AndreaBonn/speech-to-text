// sbobina · Settings page: section 3, per-provider API key rows (save,
// remove, test). Owns its own copy of the key status map so impostazioni.js
// only needs setKeys() to feed it server data and an onChange callback to
// know when the missing-keys banner might need refreshing. Split out of
// impostazioni.js (project line limit).
(function () {
  "use strict";

  var KEYS_URL = "/api/v1/settings/keys/";
  var KEY_PROVIDERS = ["groq", "gemini", "openai", "anthropic", "assemblyai"];
  var TEST_RESULT_LABELS = {
    ok: "Chiave valida",
    auth: "Chiave non valida",
    network: "Servizio non raggiungibile",
    limit: "Limite raggiunto",
    missing: "Nessuna chiave",
    error: "Errore del servizio",
  };

  function create(options) {
    var Dom = window.SbobinaSettingsDom;
    var providerLabels = options.providerLabels;
    var onChange = options.onChange;

    var el = {
      skeleton: Dom.byId("keys-skeleton"),
      windowsNote: Dom.byId("keys-windows-note"),
      list: Dom.byId("keys-list"),
    };

    var keysState = {};
    // I2: a provider saved from its row gets tested right after the re-render.
    var testAfterRender = null;

    function setKeys(keys) {
      keysState = keys;
    }

    function showLoading() {
      el.skeleton.className = "skeleton-row";
      Dom.clearChildren(el.skeleton);
      Dom.setHidden(el.skeleton, false);
      Dom.setHidden(el.list, true);
    }

    function showLoadError(retry) {
      Dom.renderLoadError(el.skeleton, retry);
    }

    function render() {
      Dom.setHidden(el.skeleton, true);
      Dom.setHidden(el.list, false);
      Dom.setHidden(el.windowsNote, !Dom.isWindows());
      Dom.clearChildren(el.list);
      KEY_PROVIDERS.forEach(function (provider) {
        el.list.appendChild(buildKeyRow(provider, keysState[provider]));
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
      title.textContent = providerLabels[provider];
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
      input.setAttribute("aria-label", "Chiave " + providerLabels[provider]);
      input.disabled = fromEnv;
      row.appendChild(input);

      var error = document.createElement("p");
      error.className = "field__error";
      Dom.setHidden(error, true);

      var result = document.createElement("p");
      result.className = "key-row__result";
      Dom.setHidden(result, true);

      var controls = document.createElement("div");
      controls.className = "key-row__controls";

      // I2: one action at a time. Typing shows "Salva e prova"; a saved key
      // offers Prova and a quiet Rimuovi; an empty row offers nothing to click.
      var saveButton = document.createElement("button");
      saveButton.type = "button";
      saveButton.className = "btn btn--primary";
      saveButton.textContent = "Salva e prova";
      Dom.setHidden(saveButton, true);
      saveButton.addEventListener("click", function () {
        saveKey(provider, input, error);
      });
      input.addEventListener("input", function () {
        Dom.setHidden(saveButton, input.value.trim() === "");
      });
      controls.appendChild(saveButton);

      if (entry.configured || fromEnv) {
        var testButton = document.createElement("button");
        testButton.type = "button";
        testButton.className = "btn btn--secondary";
        testButton.textContent = "Prova";
        testButton.addEventListener("click", function () {
          testKey(provider, result);
        });
        controls.appendChild(testButton);
      }

      if (entry.configured && !fromEnv) {
        var removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.className = "btn btn--danger-text";
        removeButton.textContent = "Rimuovi";
        removeButton.addEventListener("click", function () {
          removeKey(provider);
        });
        controls.appendChild(removeButton);
      }

      if (testAfterRender === provider) {
        testAfterRender = null;
        testKey(provider, result);
      }

      row.appendChild(controls);
      row.appendChild(error);
      row.appendChild(result);
      return row;
    }

    function saveKey(provider, input, errorNode) {
      var key = input.value;
      Dom.setHidden(errorNode, true);
      Dom.fetchJson(KEYS_URL + provider, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: key }),
      }).then(function (result) {
        if (result.status !== 200) {
          errorNode.textContent = Dom.errorMessage(result.body, "Chiave non valida.");
          Dom.setHidden(errorNode, false);
          return;
        }
        input.value = "";
        testAfterRender = provider;
        keysState[provider] = {
          configured: result.body.data.configured,
          last4: result.body.data.last4,
          source: result.body.data.source,
        };
        render();
        onChange();
      });
    }

    function removeKey(provider) {
      Dom.fetchJson(KEYS_URL + provider, { method: "DELETE" }).then(function (result) {
        if (result.status !== 204) {
          return;
        }
        keysState[provider] = { configured: false, last4: null, source: null };
        render();
        onChange();
      });
    }

    function testKey(provider, resultNode) {
      resultNode.textContent = "Verifica in corso…";
      Dom.setHidden(resultNode, false);
      Dom.fetchJson(KEYS_URL + provider + "/test", { method: "POST" }).then(function (result) {
        if (result.status !== 200) {
          resultNode.textContent = Dom.errorMessage(result.body, "Errore del servizio");
          return;
        }
        var outcome = result.body.data.result;
        resultNode.textContent = TEST_RESULT_LABELS[outcome] || outcome;
      });
    }

    return {
      setKeys: setKeys,
      render: render,
      showLoading: showLoading,
      showLoadError: showLoadError,
    };
  }

  window.SbobinaSettingsKeys = { create: create };
})();

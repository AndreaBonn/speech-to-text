// sbobina · Settings page: "Ricerca semantica" section (T052). Loaded once
// on page open and after every action here (toggle, model change, per-course
// "Indicizza ora" via settings-semantic-coverage.js, rebuild):
// GET /api/v1/semantic-index/status reads every course's text, so it is
// never polled (see semantic_index_status.py). Independent of
// impostazioni.js/settings-dom.js's module split: this section owns its
// own state and never touches settingsState there.
(function () {
  "use strict";

  var Dom = window.SbobinaSettingsDom;
  var byId = Dom.byId;
  var setHidden = Dom.setHidden;
  var clearChildren = Dom.clearChildren;
  var fetchJson = Dom.fetchJson;
  var errorMessage = Dom.errorMessage;
  var retrievalMode = window.SbobinaRetrievalMode;

  var SETTINGS_URL = "/api/v1/settings";
  var SEMANTIC_SETTINGS_URL = SETTINGS_URL + "/semantic-index";
  var EMBEDDING_MODELS_URL = SETTINGS_URL + "/embedding-models";
  var STATUS_URL = "/api/v1/semantic-index/status";
  var BACKFILL_URL = "/api/v1/semantic-index/backfill";

  var el = {
    skeleton: byId("semantic-skeleton"),
    loadError: byId("semantic-load-error"),
    body: byId("semantic-body"),
    toggle: byId("semantic-search-toggle"),
    lockedNote: byId("semantic-locked-note"),
    modelSelect: byId("semantic-model-select"),
    modelHelper: byId("semantic-model-helper"),
    pull: byId("semantic-pull"),
    pullReason: byId("semantic-pull-reason"),
    pullCommand: byId("semantic-pull-command"),
    pullCopy: byId("semantic-pull-copy"),
    pullCopied: byId("semantic-pull-copied"),
    rebuildBanner: byId("semantic-rebuild-banner"),
    rebuildText: byId("semantic-rebuild-text"),
    rebuildButton: byId("semantic-rebuild-button"),
    actionError: byId("semantic-action-error"),
    rebuildDialog: byId("semantic-rebuild-dialog"),
    rebuildCancel: byId("semantic-rebuild-cancel"),
    rebuildConfirm: byId("semantic-rebuild-confirm"),
  };
  if (!el.body) {
    return; // page without the section (older template in a stale test)
  }

  function showActionError(message) {
    el.actionError.textContent = message;
    setHidden(el.actionError, false);
  }

  var coverage = window.SbobinaSettingsSemanticCoverage.create({
    onReload: function () {
      load();
    },
    showError: showActionError,
  });

  var state = null; // {preferences, lockedByEnv, models, modelsStatus, status}

  // ---------- loading ----------

  function load() {
    setHidden(el.skeleton, false);
    setHidden(el.loadError, true);
    setHidden(el.body, true);
    return Promise.all([
      fetchJson(SETTINGS_URL),
      fetchJson(EMBEDDING_MODELS_URL),
      fetchJson(STATUS_URL),
    ])
      .then(function (results) {
        if (results.some(function (r) { return r.status !== 200; })) {
          throw new Error("semantic settings fetch failed");
        }
        state = {
          preferences: results[0].body.data.preferences,
          lockedByEnv: results[0].body.data.locked_by_env,
          models: results[1].body.data.models,
          modelsStatus: results[1].body.data.status,
          status: results[2].body.data,
        };
        setHidden(el.skeleton, true);
        setHidden(el.body, false);
        renderAll();
      })
      .catch(function () {
        setHidden(el.skeleton, true);
        Dom.renderLoadError(el.loadError, load);
      });
  }

  function renderAll() {
    renderToggle();
    renderModelSelect();
    renderPull();
    renderRebuildBanner();
    coverage.render(state.status.courses || []);
  }

  // ---------- toggle ----------

  function renderToggle() {
    var locked = state.lockedByEnv.indexOf("semantic_search") !== -1;
    el.toggle.checked = state.preferences.semantic_search;
    el.toggle.disabled = locked;
    setHidden(el.lockedNote, !locked);
  }

  function onToggleChange() {
    save({ semantic_search: el.toggle.checked, embedding_model: state.preferences.embedding_model });
  }

  // ---------- model select ----------

  function modelOptionText(model) {
    if (model.recommended) {
      return model.model + " (consigliato)";
    }
    return model.model + (model.measured ? "" : " · non misurato");
  }

  function renderModelSelect() {
    clearChildren(el.modelSelect);
    var current = state.preferences.embedding_model;
    var models = state.models.slice();
    if (!models.some(function (m) { return m.model === current; })) {
      models.unshift({ model: current, recommended: false, measured: false });
    }
    models.forEach(function (model) {
      var option = document.createElement("option");
      option.value = model.model;
      option.textContent = modelOptionText(model);
      el.modelSelect.appendChild(option);
    });
    el.modelSelect.value = current;
    var locked = state.lockedByEnv.indexOf("embedding_model") !== -1;
    el.modelSelect.disabled = locked;
    el.modelHelper.textContent =
      state.modelsStatus === "available" ? "" : retrievalMode.reasonLabel(state.modelsStatus);
  }

  function onModelChange() {
    var model = el.modelSelect.value;
    save({ semantic_search: state.preferences.semantic_search, embedding_model: model }).then(
      function (ok) {
        if (ok) {
          checkRebuild();
        }
      }
    );
  }

  // ---------- pull command ----------

  function renderPull() {
    var status = state.status;
    if (status.installed !== false) {
      setHidden(el.pull, true);
      return;
    }
    setHidden(el.pull, false);
    el.pullReason.textContent = retrievalMode.reasonLabel(status.reason) + ".";
    el.pullCommand.textContent = "ollama pull " + status.model;
    setHidden(el.pullCopied, true);
  }

  function onPullCopy() {
    var text = el.pullCommand.textContent;
    var done = function () {
      setHidden(el.pullCopied, false);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, done);
      return;
    }
    done();
  }

  // ---------- rebuild banner + dialog ----------

  function renderRebuildBanner() {
    var pending = state.status.model_change_pending === true;
    setHidden(el.rebuildBanner, !pending);
    if (pending) {
      el.rebuildText.textContent =
        "L'indice usa ancora il modello precedente: va ricostruito.";
    }
  }

  // After a model save, ask the backfill endpoint whether it would discard
  // vectors from a different model; only then open the confirm dialog.
  function checkRebuild() {
    return postBackfill(false).then(function (result) {
      if (result && result.model_change_pending) {
        el.rebuildDialog.showModal();
      } else {
        load();
      }
    });
  }

  function postBackfill(confirmModelChange) {
    return fetchJson(BACKFILL_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm_model_change: confirmModelChange }),
    }).then(function (result) {
      if (result.status !== 202) {
        showActionError(errorMessage(result.body, "Impossibile avviare la ricostruzione."));
        return null;
      }
      return result.body.data;
    }).catch(function () {
      showActionError("Impossibile avviare la ricostruzione: il server non risponde.");
      return null;
    });
  }

  function onRebuildButton() {
    el.rebuildDialog.showModal();
  }

  function onRebuildConfirm() {
    el.rebuildDialog.close();
    postBackfill(true).then(function () {
      load();
    });
  }

  function onRebuildCancel() {
    el.rebuildDialog.close();
  }

  // ---------- save ----------

  function save(body) {
    setHidden(el.actionError, true);
    return fetchJson(SEMANTIC_SETTINGS_URL, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (result) {
      if (result.status !== 200) {
        showActionError(errorMessage(result.body, "Impossibile salvare."));
        renderToggle();
        renderModelSelect();
        return false;
      }
      state.preferences = result.body.data.preferences;
      return true;
    }).catch(function () {
      showActionError("Impossibile salvare: il server non risponde.");
      renderToggle();
      renderModelSelect();
      return false;
    });
  }

  // ---------- wiring ----------

  el.toggle.addEventListener("change", onToggleChange);
  el.modelSelect.addEventListener("change", onModelChange);
  el.pullCopy.addEventListener("click", onPullCopy);
  el.rebuildButton.addEventListener("click", onRebuildButton);
  el.rebuildConfirm.addEventListener("click", onRebuildConfirm);
  el.rebuildCancel.addEventListener("click", onRebuildCancel);
  el.rebuildDialog.addEventListener("cancel", onRebuildCancel);

  load();
})();

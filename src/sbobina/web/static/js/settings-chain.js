// sbobina · Settings page: section 2, the ordered LLM provider chain the
// user edits before pressing "Salva". Owns its own draft state (chain
// entries + the server-confirmed Ollama-fallback flag) so impostazioni.js
// only needs getState()/setState() to fold it into the save payload. Split
// out of impostazioni.js (project line limit).
(function () {
  "use strict";

  var MAX_CHAIN_LINKS = 8;
  var CHAIN_PROVIDERS = ["groq", "gemini", "openai", "anthropic"];
  var MODEL_PLACEHOLDERS = {
    groq: "es. llama-3.3-70b-versatile",
    gemini: "es. gemini-2.5-flash",
    openai: "es. gpt-4.1-mini",
    anthropic: "es. claude-sonnet-4-5",
  };

  function create(options) {
    var Dom = window.SbobinaSettingsDom;
    var providerLabels = options.providerLabels;
    var onSave = options.onSave;

    var el = {
      skeleton: Dom.byId("chain-skeleton"),
      form: Dom.byId("chain-form"),
      list: Dom.byId("chain-list"),
      add: Dom.byId("chain-add"),
      ollamaFallback: Dom.byId("chain-ollama-fallback"),
      error: Dom.byId("chain-error"),
    };

    // draft: entries the user is still editing. ollamaFallback: the last
    // server-confirmed value, re-applied on every render (matches the
    // pre-split behaviour, including the reset-on-reorder quirk).
    var draft = [];
    var ollamaFallback = false;

    function setState(prefs) {
      draft = prefs.llm_chain.map(function (entry) {
        return { provider: entry.provider, model: entry.model };
      });
      ollamaFallback = prefs.llm_ollama_fallback;
    }

    function getDraft() {
      return draft;
    }

    function showLoading() {
      el.skeleton.className = "skeleton-row";
      Dom.clearChildren(el.skeleton);
      Dom.setHidden(el.skeleton, false);
      Dom.setHidden(el.form, true);
    }

    function showLoadError(retry) {
      Dom.renderLoadError(el.skeleton, retry);
    }

    function showError(message) {
      el.error.textContent = message;
      Dom.setHidden(el.error, false);
    }

    function render() {
      Dom.setHidden(el.skeleton, true);
      Dom.setHidden(el.form, false);
      Dom.clearChildren(el.list);
      if (draft.length === 0) {
        var empty = document.createElement("li");
        empty.className = "chain-list__empty";
        empty.textContent = "Nessun modello in catena. Aggiungi il primo modello.";
        el.list.appendChild(empty);
      } else {
        draft.forEach(function (entry, index) {
          el.list.appendChild(buildChainRow(entry, index));
        });
      }
      el.add.disabled = draft.length >= MAX_CHAIN_LINKS;
      el.ollamaFallback.checked = ollamaFallback;
      Dom.setHidden(el.error, true);
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
        option.textContent = providerLabels[provider];
        if (provider === entry.provider) {
          option.selected = true;
        }
        select.appendChild(option);
      });
      select.addEventListener("change", function () {
        draft[index].provider = select.value;
      });

      var modelInput = document.createElement("input");
      modelInput.type = "text";
      modelInput.className = "text-input chain-row__model-input";
      modelInput.value = entry.model;
      modelInput.placeholder = MODEL_PLACEHOLDERS[entry.provider] || "Nome modello";
      modelInput.setAttribute("aria-label", "Modello, posizione " + (index + 1));
      modelInput.addEventListener("input", function () {
        draft[index].model = modelInput.value;
      });

      var controls = document.createElement("div");
      controls.className = "chain-row__controls";
      controls.appendChild(
        makeChainButton("Su", index > 0, function () {
          moveChain(index, -1);
        })
      );
      controls.appendChild(
        makeChainButton("Giù", index < draft.length - 1, function () {
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
      if (target < 0 || target >= draft.length) {
        return;
      }
      var entry = draft.splice(index, 1)[0];
      draft.splice(target, 0, entry);
      render();
    }

    function removeChain(index) {
      draft.splice(index, 1);
      render();
    }

    function addChain() {
      if (draft.length >= MAX_CHAIN_LINKS) {
        return;
      }
      draft.push({ provider: CHAIN_PROVIDERS[0], model: "" });
      render();
    }

    // onSave always receives the checkbox's current state; the caller
    // folds the in-progress draft (getDraft()) into the save payload itself.
    function onSubmit(event) {
      event.preventDefault();
      onSave(el.ollamaFallback.checked);
    }

    el.add.addEventListener("click", addChain);
    el.form.addEventListener("submit", onSubmit);

    return {
      setState: setState,
      getDraft: getDraft,
      render: render,
      showLoading: showLoading,
      showLoadError: showLoadError,
      showError: showError,
    };
  }

  window.SbobinaSettingsChain = { create: create };
})();

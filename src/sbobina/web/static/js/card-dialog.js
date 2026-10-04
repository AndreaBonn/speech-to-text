// sbobina · shared "Crea carta" dialog. Element ids follow one prefix
// (<prefix>-dialog, -form, -front, -back, -front-error, -back-error, -error,
// -success, -cancel, -submit); callers only say how to find the course and
// how to build the anchor. Card text reaches the DOM via textContent only.
(function () {
  "use strict";

  var FAILED_MESSAGE =
    "Creazione non riuscita. Controlla che il server sia attivo e riprova.";
  var SOURCE_CHANGED_MESSAGE = "Il testo è cambiato: ricarica la pagina.";
  var EMPTY_FRONT_MESSAGE = "Il fronte non può essere vuoto.";

  function elements(prefix) {
    var byId = function (suffix) {
      return document.getElementById(prefix + "-" + suffix);
    };
    return {
      dialog: byId("dialog"),
      form: byId("form"),
      front: byId("front"),
      back: byId("back"),
      frontError: byId("front-error"),
      backError: byId("back-error"),
      error: byId("error"),
      success: byId("success"),
      cancel: byId("cancel"),
      submit: byId("submit"),
    };
  }

  function clearErrors(el) {
    [el.frontError, el.backError].forEach(function (node) {
      node.hidden = true;
      node.textContent = "";
    });
    el.error.textContent = "";
    el.front.classList.remove("is-invalid");
    el.back.classList.remove("is-invalid");
  }

  function showFieldError(el, field, message) {
    var node = field === "back" ? el.backError : el.frontError;
    node.textContent = message;
    node.hidden = false;
    (field === "back" ? el.back : el.front).classList.add("is-invalid");
  }

  function showSavedMessage(el) {
    el.success.textContent = "";
    el.success.appendChild(document.createTextNode("Carta aggiunta al ripasso. "));
    var link = document.createElement("a");
    link.href = "/ripasso";
    link.textContent = "Vai al ripasso";
    el.success.appendChild(link);
    el.success.hidden = false;
  }

  function applyServerError(el, body) {
    var error = (body && body.error) || {};
    if (error.code === "SOURCE_CHANGED") {
      el.error.textContent = SOURCE_CHANGED_MESSAGE;
      return;
    }
    var handled = false;
    (error.details || []).forEach(function (detail) {
      var field = /front$/.test(detail.field || "")
        ? "front"
        : /back$/.test(detail.field || "")
          ? "back"
          : null;
      if (field) {
        showFieldError(el, field, detail.message);
        handled = true;
      }
    });
    if (!handled) {
      el.error.textContent = error.message || FAILED_MESSAGE;
    }
  }

  function postCard(key, payload) {
    return fetch("/api/v1/courses/" + encodeURIComponent(key) + "/cards", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  // options: resolveCourseKey() -> Promise<key|null>, buildAnchor() -> anchor,
  // noCourseMessage (shown when no key), onSaved() (optional).
  function create(prefix, options) {
    var el = elements(prefix);
    var saving = false;

    function setSaving(value) {
      saving = value;
      el.submit.disabled = value;
      el.submit.setAttribute("aria-busy", String(value));
    }

    function finish(response) {
      setSaving(false);
      if (!response) return;
      return response.json().then(function (body) {
        if (!response.ok) {
          applyServerError(el, body);
          return;
        }
        el.dialog.close();
        if (options.onSaved) options.onSaved();
        showSavedMessage(el);
      });
    }

    function submit(event) {
      event.preventDefault();
      if (saving) return;
      clearErrors(el);
      var front = el.front.value.trim();
      if (!front) {
        showFieldError(el, "front", EMPTY_FRONT_MESSAGE);
        return;
      }
      var payload = { front: front, back: el.back.value.trim() || front, anchor: options.buildAnchor() };
      setSaving(true);
      options
        .resolveCourseKey()
        .then(function (key) {
          if (!key) {
            el.error.textContent = options.noCourseMessage || FAILED_MESSAGE;
            return null;
          }
          return postCard(key, payload);
        })
        .then(finish)
        .catch(function () {
          setSaving(false);
          el.error.textContent = FAILED_MESSAGE;
        });
    }

    el.form.addEventListener("submit", submit);
    el.cancel.addEventListener("click", function () {
      el.dialog.close();
    });

    return {
      dialog: el.dialog,
      open: function (back) {
        clearErrors(el);
        el.front.value = "";
        el.back.value = back;
        el.success.hidden = true;
        el.dialog.showModal();
        el.front.focus();
      },
    };
  }

  window.SbobinaCardDialog = { create: create };
})();

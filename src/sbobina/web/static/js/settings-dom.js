// sbobina · Settings page: shared DOM helpers. Pure functions, no state: byId,
// show/hide, clearing children, fetch-as-json, env detection, the generic
// "skeleton -> load error" swap. Split out of impostazioni.js (project line
// limit) so settings-chain.js and settings-keys.js can reuse the same helpers.
(function () {
  "use strict";

  function byId(id) {
    return document.getElementById(id);
  }

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
      // 204 (DELETE) has no body: parsing it would reject the whole chain.
      if (response.status === 204) {
        return { status: response.status, body: null };
      }
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

  function makeBanner(message) {
    var banner = document.createElement("div");
    banner.className = "banner banner--warning";
    banner.textContent = message;
    return banner;
  }

  // Swaps a skeleton placeholder for a "could not load, retry" message.
  // `retry` is called on click of the retry button.
  function renderLoadError(skeletonNode, retry) {
    skeletonNode.className = "queue__error";
    clearChildren(skeletonNode);
    var text = document.createElement("span");
    text.textContent = "Impossibile caricare le impostazioni.";
    var retryButton = document.createElement("button");
    retryButton.type = "button";
    retryButton.className = "btn btn--secondary";
    retryButton.textContent = "Riprova";
    retryButton.addEventListener("click", retry);
    skeletonNode.appendChild(text);
    skeletonNode.appendChild(retryButton);
  }

  window.SbobinaSettingsDom = {
    byId: byId,
    setHidden: setHidden,
    clearChildren: clearChildren,
    fetchJson: fetchJson,
    errorMessage: errorMessage,
    isWindows: isWindows,
    makeBanner: makeBanner,
    renderLoadError: renderLoadError,
  };
})();

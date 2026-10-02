// sbobina · light/dark theme switch.
// Loaded synchronously in <head>, before the stylesheets: the saved choice
// lands on <html> before the first paint, so a dark-mode user never sees a
// white flash. "auto" removes data-theme and lets prefers-color-scheme decide.
(function () {
  "use strict";

  var STORAGE_KEY = "sbobina-theme";
  var ORDER = ["auto", "light", "dark"];
  var LABELS = { auto: "Auto", light: "Chiaro", dark: "Scuro" };
  var root = document.documentElement;

  function readSaved() {
    try {
      var value = window.localStorage.getItem(STORAGE_KEY);
      return ORDER.indexOf(value) >= 0 ? value : "auto";
    } catch (err) {
      // Storage blocked (private window, cleared site data): follow the system.
      return "auto";
    }
  }

  function save(theme) {
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch (err) {
      // Not persisted: the choice still holds until the page is left.
    }
  }

  function apply(theme) {
    if (theme === "auto") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", theme);
    }
  }

  function render(button, theme) {
    var next = ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length];
    var prefix = document.createElement("span");
    prefix.className = "rail__theme-prefix";
    prefix.textContent = "Tema: ";
    button.replaceChildren(prefix, LABELS[theme]);
    // Starts with the visible text so voice control matches it (WCAG 2.5.3).
    var description =
      "Tema: " + LABELS[theme] +
      (theme === "auto" ? " (segue il sistema)" : "") +
      ". Passa a " + LABELS[next];
    button.setAttribute("aria-label", description);
    button.title = description;
  }

  var current = readSaved();
  apply(current);

  document.addEventListener("DOMContentLoaded", function () {
    var button = document.getElementById("theme-toggle");
    if (!button) {
      return;
    }
    render(button, current);
    button.hidden = false;
    button.addEventListener("click", function () {
      current = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];
      apply(current);
      save(current);
      render(button, current);
    });
  });
})();

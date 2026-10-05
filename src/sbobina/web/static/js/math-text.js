// sbobina · formulas in model and OCR text (ADR D5, plan C4). Only \(...\)
// (inline) and \[...\] (display) are delimiters, never $, so prices and
// dollar signs stay text. Plain text reaches the DOM via textContent; each
// formula goes to KaTeX with trust off and bounded expansion. A formula that
// is too long, unbalanced or rejected stays as its source text.
(function () {
  "use strict";

  var MAX_FORMULA_CHARS = 2000;
  var DELIMITERS = [
    { open: "\\(", close: "\\)", display: false },
    { open: "\\[", close: "\\]", display: true },
  ];
  var KATEX_OPTIONS = {
    trust: false,
    throwOnError: false,
    strict: "ignore",
    maxExpand: 1000,
    maxSize: 10,
  };

  function nextOpening(text, from) {
    var best = null;
    DELIMITERS.forEach(function (delimiter) {
      var index = text.indexOf(delimiter.open, from);
      if (index >= 0 && (best === null || index < best.index)) {
        best = { index: index, delimiter: delimiter };
      }
    });
    return best;
  }

  // The formula opened at `opening`, or null when it never closes or the
  // same delimiter opens again inside it (LaTeX does not nest \( or \[).
  function formulaAt(text, opening) {
    var start = opening.index + 2;
    var close = text.indexOf(opening.delimiter.close, start);
    if (close < 0) {
      return null;
    }
    var value = text.slice(start, close);
    if (value.indexOf(opening.delimiter.open) >= 0) {
      return null;
    }
    return {
      kind: "math",
      value: value,
      display: opening.delimiter.display,
      source: text.slice(opening.index, close + 2),
    };
  }

  // [{kind: "text", value}] and [{kind: "math", value, display, source}].
  // An opener without a valid formula stays text and scanning resumes after it.
  function splitMath(text) {
    var source = text == null ? "" : String(text);
    var parts = [];
    var pending = "";
    var position = 0;
    var opening = nextOpening(source, 0);
    while (opening) {
      var formula = formulaAt(source, opening);
      var resume = formula ? opening.index + formula.source.length : opening.index + 2;
      pending += source.slice(position, formula ? opening.index : resume);
      if (formula) {
        parts.push({ kind: "text", value: pending }, formula);
        pending = "";
      }
      position = resume;
      opening = nextOpening(source, position);
    }
    parts.push({ kind: "text", value: pending + source.slice(position) });
    return parts.filter(function (part) {
      return part.kind === "math" || part.value !== "";
    });
  }

  function formulaNode(part) {
    var katex = window.katex;
    if (!katex || part.value.length > MAX_FORMULA_CHARS || part.value.trim() === "") {
      return document.createTextNode(part.source);
    }
    var span = document.createElement("span");
    span.className = part.display ? "math math--display" : "math";
    try {
      katex.render(part.value, span, Object.assign({ displayMode: part.display }, KATEX_OPTIONS));
    } catch (error) {
      return document.createTextNode(part.source);
    }
    return span;
  }

  function renderMathText(el, text) {
    var fragment = document.createDocumentFragment();
    splitMath(text).forEach(function (part) {
      fragment.appendChild(
        part.kind === "math" ? formulaNode(part) : document.createTextNode(part.value)
      );
    });
    el.replaceChildren(fragment);
  }

  window.SbobinaMath = { splitMath: splitMath, renderMathText: renderMathText };
})();

// sbobina · course document: search-term highlight and formulas in a page
// paragraph. Split out of documento.js (T065). The page text comes from an
// untrusted upload or OCR: it reaches the DOM only as text nodes, marks and
// KaTeX output (math-text.js), never as markup.
(function () {
  "use strict";

  var MIN_HIGHLIGHT_LENGTH = 3;
  var MIN_STEM_LENGTH = 5;

  // Marks every occurrence of a search term in the page text, ignoring case
  // and accents (the term arrives already normalized by the FTS prefix
  // match on the server, the page text does not). Built node by node so the
  // untrusted extracted text can never reach the DOM as markup.
  function stripDiacritics(text) {
    return text.normalize("NFD").replace(/[̀-ͯ]/g, "");
  }

  function escapeRegExp(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  // Mirrors search_text.build_match_query: words of MIN_STEM_LENGTH letters
  // or more lose their final vowels, so "bilancio" also marks "bilanci".
  function stemTerm(term) {
    return term.length >= MIN_STEM_LENGTH ? term.replace(/[aeiou]+$/, "") : term;
  }

  function queryTerms(query) {
    return stripDiacritics(query)
      .toLowerCase()
      .split(/\s+/)
      .filter(function (term) {
        // Two-letter words are articles and prepositions: marking every "di"
        // buries the terms the user searched for.
        return term.length >= MIN_HIGHLIGHT_LENGTH;
      })
      .map(stemTerm);
  }

  function mergeRanges(ranges) {
    var sorted = ranges.slice().sort(function (a, b) {
      return a[0] - b[0];
    });
    var merged = [];
    sorted.forEach(function (range) {
      var last = merged[merged.length - 1];
      if (last && range[0] <= last[1]) {
        last[1] = Math.max(last[1], range[1]);
      } else {
        merged.push(range.slice());
      }
    });
    return merged;
  }

  function matchRanges(text, terms) {
    if (!terms.length) {
      return [];
    }
    var normalized = stripDiacritics(text).toLowerCase();
    // Word-start matches only, like the server's FTS prefix query: "di" must
    // not light up inside "studi".
    var pattern = new RegExp(
      "(^|[^\\p{L}\\p{N}])((?:" +
        terms.map(escapeRegExp).join("|") +
        ")[\\p{L}\\p{N}]*)",
      "gu"
    );
    var ranges = [];
    var match;
    while ((match = pattern.exec(normalized)) !== null) {
      var start = match.index + match[1].length;
      ranges.push([start, start + match[2].length]);
    }
    return mergeRanges(ranges);
  }

  function appendHighlighted(paragraph, text, terms) {
    var cursor = 0;
    matchRanges(text, terms).forEach(function (range) {
      if (range[0] > cursor) {
        paragraph.appendChild(document.createTextNode(text.slice(cursor, range[0])));
      }
      var mark = document.createElement("mark");
      mark.textContent = text.slice(range[0], range[1]);
      paragraph.appendChild(mark);
      cursor = range[1];
    });
    if (cursor < text.length) {
      paragraph.appendChild(document.createTextNode(text.slice(cursor)));
    }
  }

  // Formulas from OCR (ocr-v2) render with KaTeX; search terms are marked in
  // the text around them only.
  function paragraph(text, query) {
    var node = document.createElement("p");
    node.className = "document__paragraph";
    var terms = queryTerms(query);
    var math = window.SbobinaMath;
    var parts = math ? math.splitMath(text) : [{ kind: "text", value: text }];
    parts.forEach(function (part) {
      if (part.kind === "math") {
        node.appendChild(math.element("span", null, part.source));
      } else {
        appendHighlighted(node, part.value, terms);
      }
    });
    return node;
  }

  window.SbobinaDocumentText = { paragraph: paragraph };
})();

// sbobina · course generations: rendering of one generation's detail
// (questions/solutions/citations or summary sections). Split out of
// corso-generazioni.js to stay under the file size limit. LLM text reaches
// the DOM as text nodes or KaTeX formulas (math-text.js), never as markup.
(function () {
  "use strict";

  var dom = window.SbobinaDom;
  var clearChildren = dom.clearChildren;
  // Discard reasons (generation_validation.DiscardReason and
  // source_citations.SourceRejectionReason) -> why the items were dropped.
  var NOT_FOUND = "la fonte citata non è stata trovata nel materiale";
  var DISCARD_REASONS = {
    QUOTE_NOT_FOUND: NOT_FOUND,
    PASSAGE_NOT_GIVEN: NOT_FOUND,
    QUOTE_LENGTH: "la citazione era troppo corta o troppo lunga",
    CITATION_COUNT: "le citazioni erano assenti o troppe",
    INVALID_OPTIONS: "le opzioni di risposta non erano valide",
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined) {
      node.textContent = text;
    }
    return node;
  }

  // Model text may hold \( \) and \[ \] formulas (T064); without math-text.js
  // it stays plain text.
  var mathEl = window.SbobinaMath ? window.SbobinaMath.element : el;

  function formatTime(seconds) {
    var total = Math.floor(seconds);
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = String(total % 60).padStart(2, "0");
    return h > 0 ? h + ":" + String(m).padStart(2, "0") + ":" + s : m + ":" + s;
  }

  function citationNode(citation) {
    var wrap = el("span", "generations__citation");
    if (citation.href) {
      var link = el("a", "generations__citation-link");
      link.href = citation.href;
      var label = citation.page
        ? citation.source + " p." + citation.page
        : citation.source + " " + formatTime(citation.timestamp);
      link.textContent = label;
      wrap.appendChild(link);
    } else {
      wrap.appendChild(el("span", "generations__citation-removed", citation.source));
    }
    // Formulas only in document quotes: lecture quotes are transcripts (D5).
    wrap.appendChild((citation.page ? mathEl : el)("span", null, " «" + citation.quote + "»"));
    if (citation.ocr) {
      wrap.appendChild(el("span", "generations__citation-ocr", " · testo da OCR"));
    }
    if (citation.changed) {
      // The source was edited after this generation: the quote may be gone.
      wrap.appendChild(
        el("span", "generations__citation-changed", " · fonte modificata dopo la generazione")
      );
    }
    return wrap;
  }

  function citationsList(citations) {
    var wrap = el("p", "generations__citations");
    citations.forEach(function (citation, index) {
      if (index > 0) {
        wrap.appendChild(document.createTextNode(" "));
      }
      wrap.appendChild(citationNode(citation));
    });
    return wrap;
  }

  function correctOption(question) {
    var letter = String.fromCharCode(97 + question.correct_index);
    return "Corretta: " + letter + ") " + question.options[question.correct_index];
  }

  function renderQuestion(question, index) {
    var li = el("li", "generations__question");
    li.appendChild(
      mathEl("p", "generations__question-text", index + 1 + ". " + question.question)
    );
    if (question.options && question.options.length > 0) {
      var options = el("ul", "generations__options");
      question.options.forEach(function (option, optIndex) {
        var letter = String.fromCharCode(97 + optIndex);
        options.appendChild(mathEl("li", "generations__option", letter + ") " + option));
      });
      li.appendChild(options);
    }
    var details = document.createElement("details");
    details.className = "disclosure generations__solution";
    details.appendChild(el("summary", null, "Soluzione"));
    var body = el("div", "disclosure__body");
    if (question.options && question.options.length > 0) {
      body.appendChild(mathEl("p", "generations__solution-answer", correctOption(question)));
    }
    if (question.solution) {
      body.appendChild(mathEl("p", "generations__solution-text", question.solution));
    }
    body.appendChild(citationsList(question.citations));
    details.appendChild(body);
    li.appendChild(details);
    return li;
  }

  function renderSection(section) {
    var wrap = el("div", "generations__section");
    wrap.appendChild(mathEl("h4", "generations__section-title", section.title));
    var sentences = el("ul", "generations__sentences");
    section.sentences.forEach(function (sentence) {
      var li = el("li", "generations__sentence");
      li.appendChild(mathEl("p", "generations__sentence-text", sentence.text));
      li.appendChild(citationsList(sentence.citations));
      sentences.appendChild(li);
    });
    wrap.appendChild(sentences);
    return wrap;
  }

  function countKept(record) {
    return (
      record.questions.length +
      record.sections.reduce(function (sum, section) {
        return sum + section.sentences.length;
      }, 0)
    );
  }

  function countDiscarded(record) {
    return record.discarded.reduce(function (sum, item) {
      return sum + item.count;
    }, 0);
  }

  function emptyMessage(record) {
    return record.topic
      ? "Nel materiale del corso non trovo questo argomento."
      : "Nessun materiale disponibile per generare: carica documenti o lezioni in questo corso.";
  }

  // Questions are measured against what was asked ("8 su 10 richieste");
  // a summary has no requested count (the form still sends 1), so against
  // what the model wrote.
  function counterText(record, kept, discarded) {
    if (record.format !== "summary" && record.requested_count) {
      return kept + " su " + record.requested_count + " richieste";
    }
    return kept + " su " + (kept + discarded) + " tenute";
  }

  function render(container, record) {
    clearChildren(container);
    var kept = countKept(record);
    var discarded = countDiscarded(record);
    if (kept === 0 && discarded === 0) {
      container.appendChild(el("p", "banner banner--warning", emptyMessage(record)));
      return;
    }
    container.appendChild(el("p", "generations__counter", counterText(record, kept, discarded)));
    record.discarded.forEach(function (item) {
      if (item.count > 0) {
        var why = DISCARD_REASONS[item.reason] || "non superavano i controlli";
        container.appendChild(
          el(
            "p",
            "generations__discarded",
            item.count + (item.count === 1 ? " scartata" : " scartate") + " perché " + why + "."
          )
        );
      }
    });
    if (record.format === "summary") {
      record.sections.forEach(function (section) {
        container.appendChild(renderSection(section));
      });
      return;
    }
    var questions = el("ol", "generations__questions");
    record.questions.forEach(function (question, index) {
      questions.appendChild(renderQuestion(question, index));
    });
    container.appendChild(questions);
  }

  function load(url, container) {
    clearChildren(container);
    container.appendChild(el("p", "generations__loading", "Carico…"));
    container.hidden = false;
    fetch(url)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("detail fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        render(container, body.data);
      })
      .catch(function () {
        clearChildren(container);
        container.appendChild(
          el("p", "banner banner--danger", "Impossibile caricare il dettaglio.")
        );
      });
  }

  var DOWNLOAD_NAMES = {
    multiple_choice: ["compito.md", "soluzioni.md", "compito.docx", "soluzioni.docx"],
    open: ["compito.md", "soluzioni.md", "compito.docx", "soluzioni.docx"],
    oral: ["compito.md", "soluzioni.md", "compito.docx", "soluzioni.docx"],
    summary: ["riassunto.md", "riassunto.docx"],
  };

  function downloadLinks(generationApiBase, record) {
    var wrap = el("div", "generations__downloads");
    (DOWNLOAD_NAMES[record.format] || []).forEach(function (name) {
      var link = el("a", "btn btn--ghost", name);
      link.href =
        generationApiBase + "/" + encodeURIComponent(record.id) + "/files/" + name;
      link.setAttribute("download", "");
      wrap.appendChild(link);
    });
    return wrap;
  }

  window.SbobinaGenerationDetail = {
    render: render,
    load: load,
    downloadLinks: downloadLinks,
    el: el,
    citationNode: citationNode,
    citationsList: citationsList,
  };
})();

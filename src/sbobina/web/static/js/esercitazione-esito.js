// sbobina · practice page: the result block of one submitted question
// (outcome, the judge's suggestion, covered and missing points, errors,
// solution with its citations). Split out of esercitazione.js to stay under
// the file size limit. Everything from the LLM reaches the DOM only via
// textContent (see dom.js).
(function () {
  "use strict";

  var OUTCOMES = ["corretta", "parziale", "errata"];
  var OUTCOME_LABELS = { corretta: "Corretta", parziale: "Parziale", errata: "Errata" };
  // practice_grading reasons for an answer still waiting for a grade.
  var REASON_MESSAGES = {
    GPU_BUSY: "GPU occupata da una trascrizione: valuta più tardi.",
    OLLAMA_UNAVAILABLE: "Ollama non risponde: avvialo e premi Valuta.",
    GRADING_FAILED:
      "Il modello non ha dato una valutazione leggibile: premi Valuta per riprovare o datti il voto.",
  };
  var NO_REASON_MESSAGE =
    "La correzione automatica non è partita: premi Valuta oppure datti il voto.";
  // card_anchors.AnchorStatus, same words as the Ripasso source line.
  var ANCHOR_LABELS = {
    ok: "Fonte verificata",
    moved: "Fonte spostata",
    source_modified: "Fonte modificata",
    source_removed: "Fonte rimossa",
    unavailable: "Fonte non leggibile ora",
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

  function outcomeBadge(outcome) {
    return el("span", "badge badge--outcome-" + outcome, OUTCOME_LABELS[outcome] || outcome);
  }

  function labelled(row, label, outcome) {
    row.appendChild(el("span", "practice-result__label", label));
    row.appendChild(outcomeBadge(outcome));
  }

  // U2: until the V6 measurement passes, the judge's outcome is a suggestion;
  // only multiple choice and the student's own grade are final.
  function verdict(answer) {
    var row = el("p", "practice-result__verdict");
    if (answer.kind === "multiple_choice") {
      labelled(row, "Esito", answer.outcome);
    } else if (answer.self_grade) {
      labelled(row, "Il tuo voto", answer.self_grade);
      if (answer.judgement) {
        labelled(row, "Suggerimento del modello", answer.judgement.outcome);
      }
    } else if (answer.judgement) {
      labelled(row, "Suggerimento", answer.judgement.outcome);
    } else {
      row.appendChild(el("span", "badge badge--pending", "Da valutare"));
    }
    return row;
  }

  function optionText(question, index) {
    return String.fromCharCode(97 + index) + ") " + question.options[index];
  }

  function choiceLines(question, answer) {
    var frag = document.createDocumentFragment();
    frag.appendChild(
      el("p", "practice-result__solution", "Hai scelto " + optionText(question, answer.chosen_index))
    );
    if (answer.chosen_index !== question.correct_index) {
      frag.appendChild(
        el(
          "p",
          "practice-result__solution",
          "Risposta corretta: " + optionText(question, question.correct_index)
        )
      );
    }
    return frag;
  }

  function listSection(title, items, renderItem) {
    var frag = document.createDocumentFragment();
    if (!items || items.length === 0) {
      return frag;
    }
    frag.appendChild(el("h3", "practice-result__heading", title));
    var list = el("ul", "practice-result__list");
    items.forEach(function (item) {
      list.appendChild(renderItem(item));
    });
    frag.appendChild(list);
    return frag;
  }

  function quotedItem(main, quote) {
    var li = el("li", null, main);
    li.appendChild(el("span", "practice-result__quote", quote));
    return li;
  }

  function judgementSections(judgement) {
    var frag = document.createDocumentFragment();
    frag.appendChild(
      listSection("Punti che hai coperto", judgement.covered_points, function (item) {
        return quotedItem(item.point, "Nella tua risposta: «" + item.evidence + "»");
      })
    );
    frag.appendChild(
      listSection("Punti che mancano", judgement.missing_points, function (point) {
        return el("li", null, point);
      })
    );
    frag.appendChild(
      listSection("In contrasto con la soluzione", judgement.errors, function (item) {
        return quotedItem("«" + item.phrase + "»", item.reason);
      })
    );
    return frag;
  }

  function pendingBlock(answer, handlers) {
    var frag = document.createDocumentFragment();
    var tone = answer.reason ? "banner banner--warning" : "practice-result__label";
    frag.appendChild(
      el("p", tone + " practice-question__message", REASON_MESSAGES[answer.reason] || NO_REASON_MESSAGE)
    );
    var actions = el("div", "practice-question__actions");
    var button = el("button", "btn btn--primary", "Valuta");
    button.type = "button";
    button.addEventListener("click", function () {
      handlers.onGrade(button);
    });
    actions.appendChild(button);
    frag.appendChild(actions);
    return frag;
  }

  function selfGradeGroup(answer, handlers, labelId) {
    var group = el("div", "practice-result__selfgrade");
    group.setAttribute("role", "group");
    group.setAttribute("aria-labelledby", labelId);
    var label = el("span", "practice-result__selfgrade-label", "Mi do il voto:");
    label.id = labelId;
    group.appendChild(label);
    OUTCOMES.forEach(function (outcome) {
      var button = el("button", "btn btn--secondary", OUTCOME_LABELS[outcome]);
      button.type = "button";
      button.setAttribute("aria-pressed", String(answer.self_grade === outcome));
      button.addEventListener("click", function () {
        handlers.onSelfGrade(outcome, button);
      });
      group.appendChild(button);
    });
    return group;
  }

  function textBody(answer, handlers, index) {
    var frag = document.createDocumentFragment();
    frag.appendChild(el("p", "practice-result__label", "La tua risposta"));
    frag.appendChild(el("p", "practice-result__answer", answer.text));
    if (answer.status === "ungraded") {
      frag.appendChild(pendingBlock(answer, handlers));
    }
    if (answer.judgement) {
      frag.appendChild(judgementSections(answer.judgement));
    }
    frag.appendChild(selfGradeGroup(answer, handlers, "voto-" + index));
    return frag;
  }

  function sourceLabel(citation) {
    if (citation.page) {
      return "Documento, pagina " + citation.page;
    }
    return "Lezione al minuto " + window.SbobinaDom.formatTime(citation.timestamp || 0);
  }

  function citationItem(citation) {
    var li = el("li");
    li.appendChild(
      el("span", "badge badge--anchor-" + citation.status, ANCHOR_LABELS[citation.status] || citation.status)
    );
    li.appendChild(document.createTextNode(" "));
    if (citation.href && citation.status !== "source_removed") {
      var link = el("a", "table__link", sourceLabel(citation));
      link.href = citation.href;
      li.appendChild(link);
    } else {
      li.appendChild(el("span", null, sourceLabel(citation)));
    }
    li.appendChild(el("span", "practice-result__quote", "«" + citation.quote + "»"));
    return li;
  }

  function solutionSection(question) {
    var frag = document.createDocumentFragment();
    frag.appendChild(el("h3", "practice-result__heading", "Soluzione"));
    frag.appendChild(el("p", "practice-result__solution", question.solution));
    if (question.citations && question.citations.length > 0) {
      var list = el("ul", "practice-result__citations");
      list.setAttribute("aria-label", "Fonti della soluzione");
      question.citations.forEach(function (citation) {
        list.appendChild(citationItem(citation));
      });
      frag.appendChild(list);
    }
    return frag;
  }

  function render(question, answer, handlers, index) {
    var section = el("section", "practice-result");
    section.tabIndex = -1;
    section.setAttribute("aria-label", "Esito della domanda " + (index + 1));
    section.appendChild(verdict(answer));
    if (answer.kind === "multiple_choice") {
      section.appendChild(choiceLines(question, answer));
    } else {
      section.appendChild(textBody(answer, handlers, index));
    }
    section.appendChild(solutionSection(question));
    return section;
  }

  window.SbobinaPracticeResult = { render: render, el: el };
})();

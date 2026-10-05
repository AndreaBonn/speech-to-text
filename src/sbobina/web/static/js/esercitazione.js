// sbobina · practice page (T049): loads one attempt and renders each question
// as a form until it is submitted, then its result (esercitazione-esito.js).
// Only the question that changed is re-rendered, so text typed in the other
// questions is never lost.
(function () {
  "use strict";

  var root = document.getElementById("esercitazione-root");
  if (!root) {
    return;
  }
  var dom = window.SbobinaDom;
  var result = window.SbobinaPracticeResult;
  var el = result.el;
  // Model text may hold formulas (T064); plain text without math-text.js.
  var mathEl = window.SbobinaMath ? window.SbobinaMath.element : el;
  var ui = window.SbobinaPracticeUi;
  var SLOW_MS = 15000;
  var FORMAT_LABELS = { multiple_choice: "Crocette", open: "Domande aperte", oral: "Orale" };

  var listEl = document.getElementById("esercitazione-questions");
  var statusEl = document.getElementById("esercitazione-status");
  var progressEl = document.getElementById("esercitazione-progress");
  var apiUrl =
    "/api/v1/courses/" +
    encodeURIComponent(root.dataset.courseKey) +
    "/generations/" +
    encodeURIComponent(root.dataset.generationId) +
    "/attempts/" +
    encodeURIComponent(root.dataset.attemptId);
  var state = { attempt: null, answerIds: {} };

  // ---------- state ----------

  function answerFor(index) {
    var answers = state.attempt.answers;
    for (var i = 0; i < answers.length; i++) {
      if (answers[i].question_index === index) {
        return answers[i];
      }
    }
    return null;
  }

  // An answer route returns the question (with its now revealed solution)
  // merged with the answer: split it back into the attempt's two lists.
  function storeAnswer(index, data) {
    var question = state.attempt.questions[index];
    question.solution = data.solution;
    question.correct_index = data.correct_index;
    question.citations = data.citations;
    state.attempt.answers = state.attempt.answers
      .filter(function (answer) {
        return answer.question_index !== index;
      })
      .concat([data]);
  }

  // Same rule as api_course_attempts.final_answers: since V6 the judge's
  // verdict is a grade, and the student's own grade replaces it.
  function isFinal(answer) {
    return (
      answer.kind === "multiple_choice" ||
      Boolean(answer.self_grade) ||
      Boolean(answer.judgement)
    );
  }

  function renderProgress() {
    var attempt = state.attempt;
    var total = attempt.questions.length;
    var text =
      (FORMAT_LABELS[attempt.format] || "") +
      " · consegnate " + attempt.answers.length + " di " + total;
    if (attempt.answers.length === total) {
      var final = attempt.answers.filter(isFinal);
      var score = final.reduce(function (sum, answer) {
        return sum + (answer.score || 0);
      }, 0);
      text += " · punteggio " + score.toLocaleString("it-IT") + " su " + total;
      if (final.length < total) {
        text += " (" + (total - final.length) + " da valutare)";
      }
    }
    progressEl.textContent = text;
  }

  // ---------- forms ----------

  function choiceFieldset(index, question) {
    var fieldset = el("fieldset", "practice-question__options");
    fieldset.appendChild(mathEl("legend", "practice-question__text", question.question));
    question.options.forEach(function (option, optIndex) {
      var label = el("label", "practice-option");
      var radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "scelta-" + index;
      radio.value = String(optIndex);
      label.appendChild(radio);
      label.appendChild(mathEl("span", null, String.fromCharCode(97 + optIndex) + ") " + option));
      fieldset.appendChild(label);
    });
    return fieldset;
  }

  function textFields(index, question) {
    var wrap = el("div", "field");
    var questionText = mathEl("p", "practice-question__text", question.question);
    questionText.id = "domanda-testo-" + index;
    wrap.appendChild(questionText);
    var oral = state.attempt.format === "oral";
    var label = el("label", "field__label", oral ? "Cosa risponderesti all'orale" : "La tua risposta");
    label.htmlFor = "risposta-" + index;
    wrap.appendChild(label);
    var textarea = el("textarea", "text-input");
    textarea.id = "risposta-" + index;
    textarea.setAttribute("aria-describedby", questionText.id);
    wrap.appendChild(textarea);
    return wrap;
  }

  function readBody(form, index) {
    if (state.attempt.format === "multiple_choice") {
      var checked = form.querySelector("input[type=radio]:checked");
      return checked ? { choice: Number(checked.value) } : null;
    }
    var text = form.querySelector("textarea").value;
    if (!text.trim()) {
      return null;
    }
    // B4: one id per question, reused on retry, so a repeated send is
    // recognised by the server instead of grading the answer twice.
    state.answerIds[index] = state.answerIds[index] || window.crypto.randomUUID();
    return { text: text, answer_id: state.answerIds[index] };
  }

  function emptyMessage() {
    return state.attempt.format === "multiple_choice"
      ? "Scegli una risposta prima di verificarla."
      : "Scrivi una risposta prima di verificarla.";
  }

  function submitAnswer(form, index, button) {
    var body = readBody(form, index);
    if (!body) {
      ui.showError(form, emptyMessage());
      return;
    }
    ui.clearError(form);
    var isChoice = state.attempt.format === "multiple_choice";
    ui.setBusy(button, true, isChoice ? "Verifico…" : "Valutazione in corso…");
    ui.setLocked(form, true);
    ui.postJson(apiUrl + "/answers/" + index, body)
      .then(function (data) {
        storeAnswer(index, data);
        refreshQuestion(index);
      })
      .catch(function (error) {
        ui.setBusy(button, false, "Verifica");
        ui.setLocked(form, false);
        ui.showError(form, error.message);
        if (error.code === "ANSWER_ALREADY_SUBMITTED") {
          reloadQuestion(index);
        }
      });
  }

  function answerForm(index, question) {
    var form = el("form", "practice-question__form");
    form.noValidate = true;
    var isChoice = state.attempt.format === "multiple_choice";
    form.appendChild(isChoice ? choiceFieldset(index, question) : textFields(index, question));
    var actions = el("div", "practice-question__actions");
    var button = el("button", "btn btn--primary", "Verifica");
    button.type = "submit";
    actions.appendChild(button);
    form.appendChild(actions);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      submitAnswer(form, index, button);
    });
    return form;
  }

  // ---------- result actions ----------

  function runAction(index, button, busyLabel, path, body) {
    var item = document.getElementById("domanda-" + (index + 1));
    var label = button.textContent;
    ui.clearError(item);
    ui.setBusy(button, true, busyLabel);
    ui.postJson(apiUrl + "/answers/" + index + path, body)
      .then(function (data) {
        storeAnswer(index, data);
        refreshQuestion(index);
      })
      .catch(function (error) {
        ui.setBusy(button, false, label);
        ui.showError(item, error.message);
      });
  }

  function handlersFor(index) {
    return {
      onGrade: function (button) {
        runAction(index, button, "Valutazione in corso…", "/grade", null);
      },
      onSelfGrade: function (outcome, button) {
        runAction(index, button, "Salvo…", "/self-grade", { outcome: outcome });
      },
    };
  }

  // ---------- rendering ----------

  function fillQuestion(item, index) {
    dom.clearChildren(item);
    var question = state.attempt.questions[index];
    var total = state.attempt.questions.length;
    item.appendChild(el("p", "practice-question__number", "Domanda " + (index + 1) + " di " + total));
    var answer = answerFor(index);
    if (!answer) {
      item.appendChild(answerForm(index, question));
      return;
    }
    item.appendChild(mathEl("p", "practice-question__text", question.question));
    item.appendChild(result.render(question, answer, handlersFor(index), index));
  }

  function refreshQuestion(index) {
    var item = document.getElementById("domanda-" + (index + 1));
    fillQuestion(item, index);
    renderProgress();
    var section = item.querySelector(".practice-result");
    if (section) {
      section.focus();
    }
  }

  // Submitted elsewhere (another tab): take the saved answer for this question
  // only, leaving what the student is typing in the others untouched.
  function reloadQuestion(index) {
    ui
      .getJson(apiUrl)
      .then(function (body) {
        state.attempt = body.data;
        refreshQuestion(index);
      })
      .catch(function () {
        dom.showRetryStatus(statusEl, "Impossibile ricaricare la domanda.", function () {
          reloadQuestion(index);
        });
      });
  }

  function renderAll() {
    dom.clearChildren(listEl);
    var questions = state.attempt.questions;
    if (questions.length === 0) {
      listEl.appendChild(el("li", "empty-state__text", "Questa esercitazione non ha domande."));
      return;
    }
    questions.forEach(function (question, index) {
      var item = el("li", "practice-question");
      item.id = "domanda-" + (index + 1);
      fillQuestion(item, index);
      listEl.appendChild(item);
    });
    renderProgress();
  }

  function load() {
    dom.clearStatus(statusEl);
    var slow = setTimeout(function () {
      progressEl.textContent = "Ci sta mettendo più del previsto…";
    }, SLOW_MS);
    ui
      .getJson(apiUrl)
      .then(function (body) {
        clearTimeout(slow);
        state.attempt = body.data;
        renderAll();
      })
      .catch(function () {
        clearTimeout(slow);
        dom.clearChildren(listEl);
        progressEl.textContent = "";
        dom.showRetryStatus(statusEl, "Impossibile caricare l'esercitazione.", load);
      });
  }

  load();
})();

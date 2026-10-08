// sbobina · course chat: thread rendering + question form. Split out of
// corso-chat.js (conversation list) to stay under the file size limit.
// Citation rendering is shared with corso-generazioni-dettaglio.js
// (SbobinaGenerationDetail.citationsList). Everything from the API/LLM
// reaches the DOM only via textContent (see dom.js), never innerHTML.
(function () {
  "use strict";

  var dom = window.SbobinaDom;
  var clearChildren = dom.clearChildren;
  var clearStatus = dom.clearStatus;
  var showRetryStatus = dom.showRetryStatus;
  var detail = window.SbobinaGenerationDetail;
  var el = detail.el;
  var citationsList = detail.citationsList;

  function apiBase(key) {
    return "/api/v1/courses/" + encodeURIComponent(key) + "/chats";
  }

  var threadWrapEl = document.getElementById("chat-thread-wrap");
  var threadStatusEl = document.getElementById("chat-thread-status");
  var threadEl = document.getElementById("chat-thread");
  var formEl = document.getElementById("chat-form");
  var questionInput = document.getElementById("chat-question");
  var questionErrorEl = document.getElementById("chat-question-error");
  var waitingEl = document.getElementById("chat-waiting");
  var submitButton = document.getElementById("chat-submit");

  var currentKey = null;
  var currentChatId = null;
  var onSent = null;

  // Answers may hold \( \) and \[ \] formulas (T065); questions stay literal.
  var mathEl = window.SbobinaMath ? window.SbobinaMath.element : el;

  // ---------- rendering ----------

  function renderUserMessage(text) {
    var li = el("li", "chat__message chat__message--user");
    li.appendChild(el("p", "chat__message-text", text));
    return li;
  }

  // "Ricerca per significato" vs "solo parole chiave: <motivo>" (T053);
  // absent on records saved before retrieval_mode existed.
  function appendRetrievalLine(li, message) {
    var retrievalMode = window.SbobinaRetrievalMode;
    if (!retrievalMode || !message.retrieval_mode) {
      return;
    }
    li.appendChild(el("p", "field__helper", retrievalMode.phrase(message.retrieval_mode)));
  }

  function renderAssistantMessage(message) {
    var li = el("li", "chat__message chat__message--assistant");
    var sentences = message.sentences || [];
    if (message.outcome !== "DONE" || sentences.length === 0) {
      li.appendChild(
        el("p", "chat__message-text", "Non trovo la risposta nel materiale di questo corso.")
      );
      appendRetrievalLine(li, message);
      return li;
    }
    sentences.forEach(function (sentence) {
      li.appendChild(mathEl("p", "chat__message-text", sentence.text));
      if (sentence.citations && sentence.citations.length > 0) {
        li.appendChild(citationsList(sentence.citations));
      }
    });
    // Which cloud model or local fallback answered (api engine only).
    if (message.served_by) {
      var models = Object.keys(message.served_by).join(", ");
      li.appendChild(el("p", "field__helper", "Risposta da " + models));
    }
    appendRetrievalLine(li, message);
    return li;
  }

  // A question whose Ollama call failed (GPU busy, timeout) is saved without
  // an answer: say so instead of leaving it bare in a reopened thread.
  function renderUnanswered() {
    return el("li", "chat__message chat__message--failed", "Risposta non riuscita: puoi rifare la domanda.");
  }

  function renderThread(record) {
    clearChildren(threadEl);
    record.messages.forEach(function (message, index) {
      if (message.role !== "user") {
        threadEl.appendChild(renderAssistantMessage(message));
        return;
      }
      threadEl.appendChild(renderUserMessage(message.text));
      var next = record.messages[index + 1];
      if (!next || next.role === "user") {
        threadEl.appendChild(renderUnanswered());
      }
    });
  }

  function scrollThreadToEnd() {
    var last = threadEl.lastElementChild;
    if (last && last.scrollIntoView) {
      last.scrollIntoView({ block: "end" });
    }
  }

  // ---------- loading ----------

  function fetchAndRender(key, chatId) {
    fetch(apiBase(key) + "/" + encodeURIComponent(chatId))
      .then(function (response) {
        if (!response.ok) {
          throw new Error("chat fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        renderThread(body.data);
        scrollThreadToEnd();
      })
      .catch(function () {
        showRetryStatus(threadStatusEl, "Impossibile caricare la conversazione.", function () {
          fetchAndRender(key, chatId);
        });
      });
  }

  function load(key, chatId, onMessageSent) {
    currentKey = key;
    currentChatId = chatId;
    onSent = onMessageSent || null;
    clearStatus(threadStatusEl);
    clearChildren(threadEl);
    clearQuestionError();
    questionInput.value = "";
    threadWrapEl.hidden = false;
    fetchAndRender(key, chatId);
  }

  function clear() {
    currentKey = null;
    currentChatId = null;
    onSent = null;
    threadWrapEl.hidden = true;
    clearChildren(threadEl);
  }

  // ---------- question form ----------

  function setWaiting(isWaiting) {
    waitingEl.hidden = !isWaiting;
    waitingEl.textContent = isWaiting ? "Sto cercando nel materiale…" : "";
    submitButton.disabled = isWaiting;
    questionInput.disabled = isWaiting;
  }

  function showQuestionError(message) {
    questionErrorEl.hidden = false;
    questionErrorEl.textContent = message;
  }

  function clearQuestionError() {
    questionErrorEl.hidden = true;
    questionErrorEl.textContent = "";
  }

  function findDetail(details, field) {
    var match = (details || []).filter(function (item) {
      return item.field === field;
    });
    return match.length > 0 ? match[0].message : null;
  }

  // The stage name is internal (e.g. "transcribing"): the user only needs
  // to know a transcription holds the GPU, and for how long when known.
  function gpuBusyMessage(details) {
    var seconds = Number(findDetail(details, "estimate_s"));
    var message = "La scheda video è occupata da una trascrizione: riprova tra poco.";
    if (!(seconds > 0)) {
      return message;
    }
    var minutes = Math.max(1, Math.round(seconds / 60));
    return message + " Tempo stimato: circa " + minutes + " min.";
  }

  function errorMessage(status, body) {
    var code = body && body.error && body.error.code;
    if (status === 409 && code === "GPU_BUSY") {
      return gpuBusyMessage(body.error.details);
    }
    if (status === 503) {
      return "Ollama non risponde: avvialo e riprova.";
    }
    if (status === 504) {
      return "La richiesta ha impiegato troppo tempo: riprova.";
    }
    if (status === 422) {
      var field = ((body && body.error && body.error.details) || [])[0];
      return field ? field.message : "Domanda non valida.";
    }
    return "Impossibile inviare la domanda: riprova.";
  }

  function appendExchange(question, assistantMessage) {
    threadEl.appendChild(renderUserMessage(question));
    threadEl.appendChild(renderAssistantMessage(assistantMessage));
    scrollThreadToEnd();
  }

  // The reply can arrive after the user moved to another course or
  // conversation: it belongs to the chat it was sent from, never the open one.
  function handleReply(sent, result) {
    setWaiting(false);
    if (sent.key !== currentKey || sent.chatId !== currentChatId) {
      return;
    }
    if (!result.ok) {
      showQuestionError(errorMessage(result.status, result.body));
      return;
    }
    appendExchange(sent.question, result.body.data);
    questionInput.value = "";
    if (onSent) {
      onSent();
    }
  }

  function postQuestion(sent) {
    var url = apiBase(sent.key) + "/" + encodeURIComponent(sent.chatId) + "/messages";
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: sent.question }),
    }).then(function (response) {
      return response.json().then(function (body) {
        return { ok: response.ok, status: response.status, body: body };
      });
    });
  }

  function onSubmit(event) {
    event.preventDefault();
    if (currentKey === null || currentChatId === null) {
      return;
    }
    var sent = { key: currentKey, chatId: currentChatId, question: questionInput.value.trim() };
    if (sent.question.length === 0) {
      showQuestionError("Scrivi una domanda prima di inviare.");
      return;
    }
    clearQuestionError();
    setWaiting(true);
    postQuestion(sent)
      .then(function (result) {
        handleReply(sent, result);
      })
      .catch(function () {
        setWaiting(false);
        if (sent.key === currentKey && sent.chatId === currentChatId) {
          showQuestionError("Impossibile inviare la domanda: riprova.");
        }
      });
  }

  formEl.addEventListener("submit", onSubmit);

  window.SbobinaCourseChatThread = { load: load, clear: clear };
})();

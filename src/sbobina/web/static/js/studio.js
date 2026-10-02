// sbobina · study page: loads the generated material of one lecture, queues a
// new generation and follows it over SSE. Every string from the LLM goes in
// through textContent (see dom.js): titles, items and quotes are untrusted.
(function () {
  "use strict";

  var root = document.querySelector(".study[data-job-id]");
  var dom = window.SbobinaDom;
  if (!root || !dom) {
    return;
  }

  var jobId = root.dataset.jobId;
  var STUDY_URL = "/api/v1/jobs/" + jobId + "/study";
  var EVENTS_URL = "/api/v1/jobs/" + jobId + "/events";
  var ACTIVE = ["queued", "running"];
  var ERROR_MESSAGES = {
    OLLAMA_UNAVAILABLE:
      "Ollama non risponde: avvialo e premi di nuovo Genera. Il materiale precedente, se c'era, è rimasto.",
    STAGE_FAILED: "La generazione si è interrotta per un errore. Riprova.",
  };
  var SECTIONS = [
    { key: "summary", label: "Riassunto" },
    { key: "concepts", label: "Concetti chiave" },
    { key: "questions", label: "Possibili domande d'esame" },
  ];

  var generateButton = document.getElementById("study-generate");
  var statusEl = document.getElementById("study-status");
  var progressEl = document.getElementById("study-progress");
  var progressBar = document.getElementById("study-progress-bar");
  var progressRole = progressEl.querySelector("[role=progressbar]");
  var summaryEl = document.getElementById("study-summary");
  var chaptersEl = document.getElementById("study-chapters");
  var emptyEl = document.getElementById("study-empty");
  var source = null;
  var hasMaterial = false;

  function formatTime(seconds) {
    var total = Math.floor(seconds);
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = String(total % 60).padStart(2, "0");
    return h > 0 ? h + ":" + String(m).padStart(2, "0") + ":" + s : m + ":" + s;
  }

  function element(tag, className, text) {
    var el = document.createElement(tag);
    if (className) {
      el.className = className;
    }
    if (text !== undefined) {
      el.textContent = text;
    }
    return el;
  }

  function showMessage(text, tone) {
    dom.clearChildren(statusEl);
    statusEl.hidden = false;
    statusEl.appendChild(element("p", "banner banner--" + tone, text));
  }

  function setBusy(busy) {
    generateButton.disabled = busy;
    generateButton.setAttribute("aria-busy", String(busy));
    generateButton.textContent = busy
      ? "Generazione in corso…"
      : hasMaterial
        ? "Rigenera"
        : "Genera";
  }

  // ---------- progress ----------

  function showProgress(data) {
    progressEl.hidden = false;
    var fraction = typeof data.progress === "number" ? data.progress : null;
    var queued = data.study_status === "queued";
    progressRole.classList.toggle("progress--indeterminate", fraction === null);
    progressBar.style.setProperty("--progress-value", fraction || 0);
    var percent = fraction === null ? null : Math.round(fraction * 100);
    if (percent === null) {
      progressRole.removeAttribute("aria-valuenow");
    } else {
      progressRole.setAttribute("aria-valuenow", String(percent));
    }
    var text = queued
      ? "In coda: parte appena la GPU è libera."
      : "Generazione in corso" + (percent === null ? "…" : ": " + percent + "%");
    if (!queued && typeof data.eta_s === "number") {
      text += " · circa " + Math.max(1, Math.round(data.eta_s / 60)) + " min";
    }
    showMessage(text, "info");
  }

  function follow() {
    if (source) {
      return;
    }
    setBusy(true);
    source = new EventSource(EVENTS_URL);
    source.addEventListener("progress", function (event) {
      showProgress(JSON.parse(event.data));
    });
    source.addEventListener("end", function () {
      stopFollowing();
      load();
    });
    source.onerror = function () {
      // The browser retries on its own; a closed stream means the job is gone.
      if (source && source.readyState === EventSource.CLOSED) {
        stopFollowing();
        load();
      }
    };
  }

  function stopFollowing() {
    if (source) {
      source.close();
      source = null;
    }
    progressEl.hidden = true;
  }

  // ---------- material ----------

  function citationLink(citation) {
    var link = element("a", "study__citation");
    link.href = citation.href;
    link.appendChild(
      element(
        "span",
        "study__citation-ref",
        "§" + citation.paragrafo + " " + formatTime(citation.timestamp)
      )
    );
    link.appendChild(document.createTextNode(" «" + citation.quote + "»"));
    return link;
  }

  function renderItem(key, item) {
    var li = element("li", "study__item");
    if (key === "concepts") {
      var term = element("p", "study__text");
      term.appendChild(element("strong", "study__term", item.term));
      term.appendChild(document.createTextNode(": " + item.explanation));
      li.appendChild(term);
    } else {
      li.appendChild(
        element("p", "study__text", key === "questions" ? item.question : item.text)
      );
    }
    var sources = element("p", "study__sources");
    item.citations.forEach(function (citation) {
      sources.appendChild(citationLink(citation));
    });
    li.appendChild(sources);
    return li;
  }

  function renderChapter(chapter, number, variant) {
    var li = element("li", "study__chapter");
    var head = element("div", "study__chapter-head");
    var titleId = "study-chapter-" + number;
    var title = element("h3", "study__chapter-title", chapter.title);
    title.id = titleId;
    var start = element("a", "study__chapter-time", formatTime(chapter.start));
    start.href =
      "/lettore/" + jobId + "?t=" + chapter.start + "&variant=" + variant;
    start.setAttribute("aria-label", "Ascolta da " + formatTime(chapter.start));
    head.appendChild(title);
    head.appendChild(start);
    li.appendChild(head);
    li.setAttribute("aria-labelledby", titleId);
    SECTIONS.forEach(function (section) {
      var items = chapter[section.key];
      if (!items.length) {
        return;
      }
      li.appendChild(element("h4", "study__section-title", section.label));
      var list = element("ul", "study__items");
      items.forEach(function (item) {
        list.appendChild(renderItem(section.key, item));
      });
      li.appendChild(list);
    });
    return li;
  }

  function countDiscarded(discarded) {
    return Object.keys(discarded).reduce(function (sum, reason) {
      return sum + discarded[reason];
    }, 0);
  }

  function renderSummary(material) {
    dom.clearChildren(summaryEl);
    var generated = new Date(material.generated_at).toLocaleString("it-IT");
    summaryEl.appendChild(
      element(
        "p",
        "study__meta",
        "Generato il " +
          generated +
          " con " +
          material.model +
          " dalla trascrizione " +
          (material.source_variant === "corrected" ? "corretta" : "originale") +
          "."
      )
    );
    if (material.stale) {
      summaryEl.appendChild(
        element(
          "p",
          "banner banner--warning",
          "Materiale generato su una versione precedente della trascrizione, " +
            material.stale_dropped +
            " voci non più verificabili: rigenera."
        )
      );
    }
    var discarded = countDiscarded(material.discarded);
    if (discarded > 0) {
      summaryEl.appendChild(
        element(
          "p",
          "study__meta",
          discarded + " voci scartate perché la citazione non è stata trovata."
        )
      );
    }
    if (material.chapters.length === 0) {
      summaryEl.appendChild(
        element(
          "p",
          "banner banner--warning",
          "Nessuna voce ha superato il controllo delle citazioni: rigenera."
        )
      );
    }
    material.failed_blocks.forEach(function (block) {
      summaryEl.appendChild(
        element(
          "p",
          "banner banner--warning",
          "Parte non elaborata " + formatTime(block.start) + "-" + formatTime(block.end) + "."
        )
      );
    });
    summaryEl.hidden = false;
  }

  function renderMaterial(material) {
    hasMaterial = material !== null;
    emptyEl.hidden = hasMaterial;
    dom.clearChildren(chaptersEl);
    if (!hasMaterial) {
      summaryEl.hidden = true;
      chaptersEl.hidden = true;
      return;
    }
    renderSummary(material);
    material.chapters.forEach(function (chapter, index) {
      chaptersEl.appendChild(renderChapter(chapter, index + 1, material.source_variant));
    });
    chaptersEl.hidden = material.chapters.length === 0;
  }

  // ---------- load and generate ----------

  function readJson(response) {
    return response.json().then(function (body) {
      return { status: response.status, body: body };
    });
  }

  function applyState(data) {
    renderMaterial(data.material);
    dom.clearStatus(statusEl);
    var study = data.study;
    if (study && ACTIVE.indexOf(study.status) >= 0) {
      showProgress({ study_status: study.status, progress: null });
      follow();
      return;
    }
    setBusy(false);
    if (study && study.status === "failed") {
      var code = study.error && study.error.code;
      showMessage(ERROR_MESSAGES[code] || ERROR_MESSAGES.STAGE_FAILED, "danger");
    } else if (study && study.status === "interrupted") {
      showMessage("La generazione è stata interrotta. Premi Genera per ripartire.", "warning");
    }
  }

  function load() {
    generateButton.disabled = true;
    showMessage("Carico i materiali…", "info");
    fetch(STUDY_URL)
      .then(readJson)
      .then(function (result) {
        if (result.status === 404 && result.body.error.code === "STUDY_NOT_FOUND") {
          applyState({ study: null, material: null });
          return;
        }
        if (result.status !== 200) {
          throw new Error(result.body.error ? result.body.error.message : "");
        }
        applyState(result.body.data);
      })
      .catch(function () {
        setBusy(false);
        dom.showRetryStatus(statusEl, "Impossibile caricare i materiali di studio.", load);
      });
  }

  function generate() {
    setBusy(true);
    fetch(STUDY_URL, { method: "POST" })
      .then(readJson)
      .then(function (result) {
        if (result.status !== 202) {
          setBusy(false);
          showMessage(
            (result.body.error && result.body.error.message) ||
              "Impossibile avviare la generazione.",
            "danger"
          );
          return;
        }
        showProgress({ study_status: result.body.data.status, progress: null });
        follow();
      })
      .catch(function () {
        setBusy(false);
        showMessage("Il server non risponde: riprova tra poco.", "danger");
      });
  }

  generateButton.addEventListener("click", generate);
  window.addEventListener("pagehide", stopFollowing);
  load();
})();

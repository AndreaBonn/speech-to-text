// sbobina · shared retrieval-mode phrasing: dense ("ricerca per significato")
// vs bm25 ("solo parole chiave: <motivo>"). Reason codes mirror
// sbobina.web.dense_retrieval / dense_factory (T052/T053): disabled,
// model_missing, unreachable, bad_response, not_indexed, partial,
// stale_vectors, rebuild_needed, gpu_busy. Used by the course page status
// line (corso-retrieval-status.js) and the chat answer badge
// (corso-chat-thread.js) so the wording never diverges between the two.
(function () {
  "use strict";

  var REASON_LABELS = {
    disabled: "ricerca semantica spenta nelle Impostazioni",
    model_missing: "modello di embedding non installato",
    unreachable: "Ollama non risponde",
    bad_response: "risposta di Ollama non valida",
    not_indexed: "corso non ancora indicizzato",
    partial: "indicizzazione incompleta",
    stale_vectors: "testo modificato dopo l'indicizzazione",
    rebuild_needed: "indice ricreato dopo un errore, va indicizzato di nuovo",
    gpu_busy: "scheda video occupata da una trascrizione",
  };

  function reasonLabel(reason) {
    return REASON_LABELS[reason] || "motivo non disponibile";
  }

  function coverageSuffix(coverage) {
    if (
      !coverage ||
      typeof coverage.embedded !== "number" ||
      typeof coverage.total !== "number"
    ) {
      return "";
    }
    return " (" + coverage.embedded + "/" + coverage.total + ")";
  }

  // report: {mode: "dense"|"bm25", reason: string|null, coverage?: {embedded,total}}
  function phrase(report) {
    if (!report || report.mode === "dense") {
      return "Ricerca per significato";
    }
    return "Solo parole chiave: " + reasonLabel(report.reason) + coverageSuffix(report.coverage);
  }

  window.SbobinaRetrievalMode = { phrase: phrase, reasonLabel: reasonLabel };
})();

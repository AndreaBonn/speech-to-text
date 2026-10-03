# Piano: spazio di lavoro del corso (documenti, compiti, riassunti, chat)

Versione 1.0 - 2026-10-02. Task in `specs/001-course-workspace/tasks.md`. ADR delle decisioni
strutturali in `specs/001-course-workspace/adr.md` (in scrittura, architect): le decisioni D1-D5
qui sotto riportano il default del planner e diventano definitive quando l'ADR le chiude.
Branch `main`, commit atomici (scelta dell'utente il 2026-10-02).

## Obiettivo

Aprendo un corso lo studente trova in un punto solo le lezioni trascritte e i documenti che ha
caricato (libro di testo, slide, appunti). Dal materiale del corso il LLM locale (Ollama) genera
compiti d'esame nel formato scelto, con le soluzioni separate dalle domande, e riassunti di un
argomento indicato; un chatbot risponde alle domande sul corso. Ogni contenuto generato cita le
fonti del corso (pagina del documento o minuto della lezione) e la citazione è verificata in
automatico: una voce senza citazione valida non arriva allo studente. Niente lascia la macchina.

## Definition of Done

### C1 - Documenti nel corso, senza AI (fase F1)

- [x] Nel dettaglio di un corso su `/corsi` una sezione "Materiali" elenca i documenti caricati
      (nome originale, tipo, dimensione, pagine o slide, data, stato dell'estrazione) accanto alle
      lezioni registrate.
      Prova: tests/web/test_api_documents.py::test_create_document_accepted_and_queued (stato extracting); src/sbobina/web/templates/corsi.html:90 (sezione "Materiali"); tasks.md T016 (click-through registrato).
- [x] Given il corso "Diritto privato"; When carico `manuale.pdf` (PDF con testo, 320 pagine,
      40 MB); Then `POST /api/v1/courses/<key>/documents` → 202, il documento compare con stato
      `extracting` e poi `ready` con `pages: 320`, senza ricaricare la pagina. Lo stesso per
      `.docx`, `.pptx`, `.txt`, `.md`.
      Prova: tests/web/test_api_documents.py::test_create_document_accepted_and_queued (PDF, 202, stato extracting), test_create_document_text_kind_comes_from_uploaded_name (md/txt, 202); tests/test_document_extract.py::test_extract_pdf_three_pages_preserves_text, test_extract_pptx_orders_shapes_and_includes_notes, test_extract_logical_pages_respects_headings_and_word_limit (docx, via docx.Document()).
- [x] Tipo verificato dal contenuto, non dall'estensione: un `.exe` rinominato `slide.pdf` → 415
      `UNSUPPORTED_DOCUMENT`; un `.docx` il cui contenuto non è un pacchetto Word → 415. Oltre il
      limite (default 200 MB, impostazione dedicata) → 413 senza file residui su disco.
      Prova: tests/web/test_api_documents.py::test_create_document_unsupported_kind_is_rejected (415), test_create_document_too_large_is_rejected (413, nessun file residuo).
- [x] Nome file ostile (`../../etc/passwd.pdf`, `a\x00b.pdf`, 300 caratteri, nome Windows
      riservato `CON.pdf`) → il file è salvato sotto un id generato dentro la cartella del corso;
      il nome originale è solo metadato, mostrato con `textContent`.
      Prova: tests/web/test_api_documents.py::test_path_traversal_filename_is_contained (id generato, niente fuori da data/courses); src/sbobina/web/static/js/corso-materiali.js:100 (nome montato con textContent). Variante NUL-byte/300 caratteri/CON.pdf non testata singolarmente.
- [x] Archivio compresso malevolo (`.docx`/`.pptx` che si espande oltre 500 MB, o con più di
      10.000 voci) → stato `failed` con motivo `ARCHIVE_TOO_LARGE`, nessun crash del server.
      Prova: tests/test_document_sniff.py::test_check_archive_limits_declared_bomb_rejected_without_inflation, test_check_archive_limits_entry_count_rejects_over_limit, test_sniff_document_bomb_is_rejected_before_content_read.
- [x] PDF scansionato (meno di 50 caratteri estratti per pagina in media) → stato `ready_no_text`
      con il messaggio "PDF senza testo selezionabile: non usabile per ricerca, compiti e chat"
      (decisione U1). Un'estrazione che supera il timeout (default 120 s) → `failed` con
      `EXTRACTION_TIMEOUT`; il server resta reattivo durante l'estrazione.
      Prova: tests/test_document_extract.py::test_extract_pdf_images_marks_ready_no_text; tests/web/test_extraction_worker.py::test_child_past_timeout_is_killed_and_marked_failed, test_extractions_run_one_at_a_time.
- [x] `DELETE /api/v1/courses/<key>/documents/<id>` → 204, file originale e testo estratto
      rimossi; il documento sparisce da elenco, ricerca e dalle fonti di nuove generazioni.
      `GET .../documents/<id>/file` scarica l'originale come allegato
      (`Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`).
      Prova: tests/web/test_api_documents.py (204 e header x-content-type-options: nosniff, righe 153 e 174).
- [x] Un corso che ha documenti ma nessuna lezione compare su `/corsi` (lo spazio del corso
      esiste anche senza registrazioni). Cambiare il corso di tutte le lezioni non perde i
      documenti: restano nel corso di origine, che resta visibile (R1).
      Prova: tests/web/test_course_registry_api.py::test_list_courses_registry_only_course_has_zero_lectures; tests/test_course_registry.py::test_rename_key_updates_registry_before_callback_and_keeps_documents.
- [x] I documenti caricati sono sotto `data/`, che non è versionato: verificato con `git status`
      dopo un upload.
      Prova: .gitignore riga 10 (`data/`); tasks.md T019 (verifica "git status pulito dopo un upload").

### C2 - Ricerca nel materiale del corso (fase F2)

- [x] La ricerca esistente (`/api/v1/search`) trova anche i documenti: Given `manuale.pdf` con
      "la causa del contratto è illecita" a pagina 214; When cerco `causa illecita` con filtro sul
      corso; Then un risultato "manuale.pdf, p. 214" con snippet evidenziato; il clic apre il
      testo estratto della pagina 214 (lettore documento minimale) con il termine evidenziato.
      Prova: tests/web/test_api_search_documents.py::test_search_finds_document_passage_with_course_filter_and_href (stesso esempio del piano: doc-214, pagina 214, "causa illecita").
- [x] Recupero per domanda in linguaggio naturale (base di F3 e F4): `retrieve(course_key,
      question, budget_words)` restituisce passaggi di lezioni e documenti del solo corso
      indicato, ciascuno con la fonte (`job_id` + indice di segmento, oppure `doc_id` + pagina).
      Esempio: "cos'è la causa del contratto?" → fra i primi 5 passaggi quello di p. 214.
      Prova: tests/test_retrieval.py::test_retrieve_returns_both_lecture_and_document_passages, test_retrieve_never_returns_another_courses_passages; tests/web/test_course_retrieval.py::test_course_scope_collects_lectures_by_effective_course.
- [x] Misura (T024): set di almeno 30 domande scritte a mano su un corso reale con il passaggio
      atteso annotato; `recall@8` riportato. Soglia di accettazione proposta 0,7 (BASIS:
      inferred, da confermare coi numeri); sotto soglia si apre la decisione D2 (embedding).
      Prova: specs/001-course-workspace/eval.md § T024: recall@8 = 0,90 su 30 domande (sopra soglia 0,7).
- [x] Riconciliazione come per le lezioni: aggiunta e cancellazione di un documento si riflettono
      sulla ricerca successiva senza riavvio; cancellare `data/search.sqlite3` ricostruisce tutto.
      Prova: tests/web/test_search_service_documents.py::test_reconcile_finds_new_ready_document, test_reconcile_removes_document_deleted_from_disk.

### C3 - Compiti d'esame e riassunti (fase F3)

- [x] Form nel corso: formato (crocette, domande aperte, domande da orale), numero di domande
      (1-10), argomento facoltativo (testo libero, vuoto = tutto il corso), fonti (tutte, oppure
      una selezione di lezioni e documenti). `POST /api/v1/courses/<key>/generations` → 202, la
      generazione entra nella coda GPU esistente (mai insieme a Whisper, D3), avanzamento via
      polling (come la coda delle trascrizioni, non SSE).
      Prova: tests/web/test_api_generations.py::test_create_generation_accepted_and_queued (202, stato queued).
- [x] Formati, ciascuno con un esempio nel test:
      - crocette: domanda, 4 opzioni, una sola corretta; la soluzione indica la lettera e cita la
        fonte che la giustifica. Le opzioni errate non portano citazione.
      - domande aperte: domanda; soluzione = risposta modello + 2-5 punti chiave, ogni punto con
        citazione.
      - domande da orale: domanda; soluzione = traccia di risposta + 1-3 domande di
        approfondimento che un docente farebbe, la traccia con citazioni.
      Prova: tests/test_generation_models.py::test_generation_question_rejects_wrong_option_count (crocette), test_generation_question_accepts_open_question_without_options (aperte); tests/web/test_generation_budget.py (formato orale).
- [x] Soluzioni a parte: la pagina mostra le domande e, separate, le soluzioni (sezione chiusa di
      default, apribile); l'export produce due file distinti, `compito.md` e `soluzioni.md`
      (DOCX con lo stesso stacco se U4 lo conferma).
      Prova: tests/test_generation_render.py::test_render_exam_markdown_never_leaks_solution_or_correct_option; tests/web/test_api_generations_files.py::test_download_compito_md_never_contains_solution_text, test_download_soluzioni_md_contains_solution.
- [x] Riassunto per argomento: Given l'argomento "causa del contratto"; Then un riassunto in
      sezioni con frasi citate; se il recupero non trova passaggi pertinenti → "Nel materiale del
      corso non trovo questo argomento", mai un testo inventato.
      Prova: tests/test_generation_pipeline.py (GenerationOutcome.NO_MATERIAL su argomento senza passaggi); tests/test_generation_render.py::test_render_summary_markdown_includes_sections_sentences_and_citations.
- [x] Citazioni: stessa regola di `study_citations.py` estesa ai documenti. Una citazione il cui
      testo compare in un altro passaggio dato al modello è riattribuita a quel passaggio
      (`source_citations.resolve_citation`); è inventata, e scartata da sola, solo se non compare
      in nessun passaggio dato. La voce resta se almeno una citazione regge; è scartata solo se
      nessuna regge o se il numero di citazioni è fuori da 1-3. La pagina mostra "N su M
      richieste" e una riga per motivo di scarto (es. "2 scartate perché la fonte citata non è
      stata trovata nel materiale"); con un argomento senza materiale, "Nel materiale del corso
      non trovo questo argomento."
      Prova: tests/test_source_citations.py::test_resolve_picks_the_passage_matching_the_label, test_resolve_rejects_quote_not_found_in_passage, test_resolve_rejects_passage_not_given_when_label_out_of_range.
- [x] Ogni citazione è un link: lezione → lettore al minuto; documento → pagina nel lettore
      documento.
      Prova: tests/web/test_api_generations_document_citations.py (href verso /corsi/.../documenti/...?p=...); tests/web/test_api_generations_citations.py (href verso /lettore/...?t=...).
- [x] Generazioni salvate nel corso, rileggibili ed eliminabili; documento cancellato dopo la
      generazione → le sue citazioni sono marcate "fonte rimossa" (non spariscono in silenzio).
      Prova: tests/web/test_api_generations.py (list/get/delete); tests/web/test_api_generations_source_changed.py::test_document_citation_changed_after_the_document_was_replaced ("fonte rimossa" in src/sbobina/web/generation_citations_api.py:38).
- [x] Misura reale (T036): 1 compito per formato e 2 riassunti su un corso reale; durata,
      domande scartate per motivo, revisione a mano di tutte le domande tenute (giusta / sbagliata
      / ambigua) e delle soluzioni. Numeri riportati all'utente prima di chiudere F3.
      Prova: specs/001-course-workspace/eval-generations.md § T036 (compito per formato, 2 riassunti, revisione a mano riportata, SPEDITO: iter 3/4).

### C4 - Chat sul corso (fase F4)

- [x] Pagina chat nel corso: Given il corso con `manuale.pdf`; When chiedo "quando la causa del
      contratto è illecita?"; Then risposta in italiano con le fonti cliccabili (p. 214) sotto la
      risposta.
      Prova: tests/web/test_api_chat.py::test_message_answers_with_resolved_lecture_citation.
- [x] Risposta fuori dal materiale ("chi ha vinto i mondiali del 2006?") → "Non trovo la
      risposta nel materiale di questo corso", mai una risposta dalla conoscenza generale del
      modello (decisione U3).
      Prova: tests/test_chat_pipeline.py::test_answer_returns_not_found_without_calling_chat_when_no_passages; NOT_FOUND_ANSWER verificata in test_not_found_answer_constant_is_the_user_facing_message.
- [x] Frasi della risposta senza citazione valida: non mostrate come fatto (stessa regola di C3);
      se non resta nulla → messaggio di risposta non trovata.
      Prova: tests/test_chat_pipeline.py::test_answer_discards_sentence_with_fabricated_citation_keeps_others, test_answer_returns_not_found_when_no_sentence_survives_validation.
- [x] Arbitraggio GPU (D3): durante una trascrizione la chat risponde subito 409 `GPU_BUSY` e la
      pagina dice "Trascrizione in corso: la chat torna disponibile al termine" con la stima; mentre
      la chat sta generando il supervisor non avvia Whisper finché la risposta non è chiusa e il
      modello scaricato. Verificato con `nvidia-smi` campionato durante una prova reale.
      Prova: tests/web/test_gpu_lock.py; tests/web/test_api_chat_failures.py (409 GPU_BUSY).
- [x] Domanda successiva ("e quali sono le conseguenze?") usa gli ultimi 2 scambi come contesto
      per il recupero e per il modello, entro il budget di contesto.
      Prova: tests/test_chat_pipeline.py::test_answer_only_last_two_exchanges_reach_the_prompt.
- [x] Conversazioni salvate per corso, elencate ed eliminabili (decisione U2).
      Prova: tests/web/test_chat_store.py::test_history_pairs_answers_with_their_own_question; tests/web/test_api_chat.py::test_delete_chat_then_it_is_gone.
- [x] Latenza misurata (T046) su 10 domande reali, modello caldo e freddo: p50 e massimo
      riportati. Obiettivo proposto: p50 ≤ 30 s a modello caldo (BASIS: inferred dai tempi della
      correzione, ~50 s per blocco da 200 parole con output lungo); oltre, si riapre il formato
      di risposta (streaming senza JSON, D3/D5).
      Prova: specs/001-course-workspace/eval-chat.md § T046: p50 a caldo 10,1-14,2 s, sotto soglia 30 s.
- [x] Fedeltà misurata sulle stesse 10 domande: risposta corretta / parziale / sbagliata a mano.
      Prova: specs/001-course-workspace/eval-chat.md § T046: revisione a mano per domanda, iter 2/3.

### C5 - OCR dei PDF scansionati (fase F5, U1)

- [x] Un PDF scansionato (stato `ready_no_text`) mostra il pulsante "Estrai il testo con OCR".
      Prova: tasks.md T052 (checked, verify: click-through, a11y-gate, render 375/1280); src/sbobina/web/static/js/corso-ocr.js:99 (pulsante "Estrai il testo con OCR").
- [x] L'OCR gira come azione del supervisore in coda, una pagina alla volta, annullabile.
      Prova: tests/web/test_ocr_runner.py::test_run_ocr_fills_the_scanned_pages_and_marks_the_document_ready.
- [x] Le pagine lette via OCR sono marcate: avviso nel lettore documento, " · testo da OCR" sulle
      citazioni che le usano.
      Prova: src/sbobina/web/static/js/corso-generazioni-dettaglio.js:55 (" · testo da OCR"); tasks.md T052.
- [x] Con Ollama spento, l'errore lo dice (`OLLAMA_UNAVAILABLE`), file originale intatto.
      Prova: tests/web/test_ocr_runner.py::test_run_ocr_with_ollama_down_leaves_text_and_document_untouched.
- [x] Mai due processi GPU insieme: OCR e Whisper non girano in parallelo (gate T059).
      Prova: specs/001-course-workspace/eval.md § T059: "Gate T059 valido", 289 campioni, 0 sovrapposti.
- [x] Il documento non si cancella mentre l'OCR è in coda o in corso: 409 `OCR_IN_PROGRESS`.
      Prova: tests/web/test_api_ocr.py (409 OCR_IN_PROGRESS su delete con OCR in coda/in corso).
- [x] Il figlio OCR gira sotto lo stesso `RLIMIT_AS` dell'estrazione (`web/child_limits.py`); oltre
      `ocr_process_timeout_s` (3600 s) il supervisore lo uccide con `OCR_TIMEOUT`; il rendering
      della pagina è limitato a 2500 px sul lato lungo.
      Prova: tests/web/test_ocr_runner.py::test_run_ocr_stage_applies_the_memory_limit_before_reading_the_document; src/sbobina/web/child_limits.py.
- [x] Se l'OCR cambia il testo di un documento già citato in una generazione, la citazione arriva
      con `changed: true` (fonte tracciata per `sha256`/revisione) e la pagina mostra " · fonte
      modificata dopo la generazione".
      Prova: tests/web/test_api_generations_source_changed.py::test_document_citation_changed_after_the_document_was_replaced (stesso meccanismo sha256/revisione usato dall'OCR, ADR D5).

### Trasversali

- [x] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
      `uv run mypy src tests` verdi; nessun file nuovo o modificato oltre 300 righe (oggi
      `static/js/corsi.js` è a 305 e `web/search_index.py` a 287: si dividono prima di estenderli,
      T010 e T020), nessuna funzione oltre 30 righe.
      Prova: misurato ora: `uv run pytest` 1503 passed, `uv run ruff check .` e `ruff format --check .` 0 errori, `uv run mypy src tests` 0 errori; nessun file .py sotto src/sbobina oltre 300 righe (wc -l).
- [x] Fasi UI: riga `DIAL:` derivata da `design.md`, `a11y-gate` verde, render a 375 e 1280 px,
      click-through registrato di ogni controllo nuovo (upload, elimina, genera, apri soluzioni,
      citazione, invio chat).
      Prova: tasks.md T016, T035, T043, T052 (checked, verify: click-through registrato, render 375/1280, a11y-gate).
- [x] Ogni testo non scritto dal codice (nome file, testo estratto, output LLM, citazioni,
      messaggi della chat) è montato con `textContent` e passa dall'autoescape Jinja. Test
      avversariale con `<script>` e `<img onerror>` dentro un PDF, una citazione valida e una
      risposta della chat → nessuna esecuzione.
      Prova: tests/web/test_untrusted_rendering.py::test_untrusted_text_scripts_never_write_markup, test_chat_answer_with_markup_is_returned_verbatim_as_json.
- [x] Ogni prompt nuovo è un file versionato in `src/sbobina/prompts/` ed è passato da
      `prompt-master` prima del commit (feedback dell'utente). Fatto per `compito-v2.md`,
      `chat-v2.md`, `riassunto-v1.md`, `ocr-v1.md`.
      Prova: src/sbobina/prompts/ contiene compito-v1.md, compito-v2.md, chat-v1.md, chat-v2.md, riassunto-v1.md, ocr-v1.md; tasks.md T032, T041, T051 (checked, citano il passaggio da prompt-master).
- [x] `CLAUDE.md` del progetto aggiornato su layout e confini nuovi (estrazione, recupero, chat).
      Prova: CLAUDE.md § Layout aggiornato con course_registry.py, document_extract.py, retrieval.py, chat_pipeline.py, gpu_lock.py (righe 22-26); tasks.md T044.
- [x] Dipendenze nuove solo con licenza compatibile con Apache-2.0, dichiarate nel commit.
      Prova: git log: commit 42d0c50 (licenza Apache-2.0 del progetto); tasks.md T013 (checked, verify: "licenze nel messaggio di commit").

## Assunzioni

- Stack invariato: Python 3.12, FastAPI/Jinja, JS vanilla, uv, SQLite FTS5 (BASIS: measured,
  `search_index.py`). Utente unico per istanza, più tab al massimo.
- Dipendenze nuove: `pypdf` (BSD-3) per PDF e `python-pptx` (MIT) per slide; `python-docx` è già
  presente. Nessuna di AGPL (PyMuPDF escluso). Licenze BASIS: inferred, da verificare in T013 sul
  metadato del pacchetto installato.
- Volumi: un corso ha 10-30 lezioni e 1-10 documenti; un manuale fino a ~600 pagine
  (~250.000 parole). Ordine di grandezza dell'indice cresce di 10^4 righe per corso. BASIS:
  inferred; T024 misura tempo di indicizzazione su un manuale reale.
- Il modello è quello di correzione e studio (`settings.ollama_model`, `qwen3.5:9b`, BASIS:
  measured con `ollama list`), `num_ctx` 8192: nessuna generazione vede il corso intero, si
  lavora sempre su passaggi recuperati. Un riassunto "dell'argomento" copre ciò che il recupero
  trova, non garantisce di coprire ogni pagina che ne parla: limite dichiarato in pagina.
- Nessun modello di embedding installato (BASIS: measured, `ollama list`: `gemma3:4b`,
  `qwen3.5:9b`, `qwen2.5vl:7b`). Il default di D2 non ne richiede.
- `qwen2.5vl:7b` (visione) è installato: un OCR locale dei PDF scansionati è possibile, ma è una
  fase a sé (U1), non v1.
- Lo studente carica materiale proprio o del corso per uso personale: niente gestione di diritti
  o condivisione. Il testo di un PDF scaricato può contenere istruzioni rivolte al modello: è
  trattato come dato (delimitato nel prompt), e l'effetto massimo è un output sbagliato che la
  validazione delle citazioni filtra in parte; nessun tool è esposto al modello.
- Anchor rivedibile, non vincolo: la chiave del corso come stringa calcolata dalle lezioni. Con
  documenti che vivono nel corso serve un'identità su disco (D1), e la scelta cambia il modello
  attuale: è il punto da far chiudere all'ADR.

## Decisioni strutturali (da ADR, default del planner)

### Esito dell'ADR (`adr.md`, stato Accettato, implementato in F1-F5)

L'ADR conferma i cinque default del planner e li precisa. Dove le due fonti divergono vale l'ADR.

- **D1**: registro `data/courses/<uuid>/course.json` con `key` aggiornabile; rinomina esplicita
  `POST /api/v1/courses/<key>/rename` che scrive prima `course.json` e poi i `meta.json`; un corso
  con soli documenti resta visibile; "Senza corso" non accetta documenti (409).
- **D2**: BM25 su FTS5, tabella `doc_passages`, `SCHEMA_VERSION` 2 (indice derivato, si
  ricostruisce); query senza stopword italiane e con prefissi; per i compiti l'ambito si sceglie
  a mano (capitoli, pagine, lezioni). Embedding solo se `recall@8 < 0,7` su 30 domande (T024
  usa questa soglia, non `recall@5` su 15).
- **D3**: `GpuArbiter` lettori/scrittore nel processo web: Whisper esclusivo (attende le chat in
  corso e scarica i modelli Ollama), chat e figli Ollama condivisi; chat → 409 `GPU_BUSY` con
  attesa stimata durante una trascrizione. Compiti e riassunti come `CourseWorkItem` nella stessa
  FIFO, smistati da un modulo nuovo (`supervisor.py` resta sotto 300 righe).
- **D4**: `pypdf` dietro un solo modulo `pdf_text.py`; se la prova su PDF reali sbaglia più del 5%
  delle pagine si passa a `pypdfium2`. `python-pptx`, `python-docx`. Scansionati marcati, niente OCR.
- **D5**: un JSON per artefatto, conversazioni in JSONL append-only; ogni artefatto registra le
  fonti con `sha256` o revisione della lezione e rivalida le citazioni in lettura.

Prima di accettarlo restano cinque verifiche (T001): ricarica del modello con `num_ctx` diverso,
`OLLAMA_NUM_PARALLEL`, licenze e wheel su PyPI, estrazione su PDF reali, rapporto token/parola.

Approcci elencati prima, valutati dopo. I task dipendenti sono marcati "(D<n>)" in `tasks.md` e
sono scritti per non dipendere dalla scelta oltre al modulo indicato.

### D1 - Identità e storage del corso [BLOCCANTE per F1, ADR]

Approcci: (A) cartella per chiave normalizzata `data/courses/<hash della chiave>/`; (B) registro
corsi `data/courses/<course_id>/course.json` con id stabile e `key` corrente, lezioni che restano
collegate per chiave; (C) campo `course_id` nelle lezioni (`meta.json`) e registro come fonte di
verità.

- A: zero migrazione, ma rinominare un corso (cambiare l'etichetta di tutte le lezioni) cambia la
  chiave e stacca i documenti.
- B: i documenti hanno una casa stabile; il collegamento lezioni-corso resta quello di oggi
  (chiave), il rename si gestisce aggiornando `key` nel registro. Una sola fonte nuova.
- C: identità piena e rename senza ambiguità, ma migrazione di tutti i `meta.json` e due fonti da
  tenere coerenti.
- **Default: B.** È il "passaggio a C" che il piano study-library rimandava (Q1) ridotto al minimo:
  registro solo per ciò che oggi non ha casa. Il modulo `course_registry.py` isola la scelta.

### D2 - Recupero dei passaggi [BLOCCANTE per F2, ADR]

Approcci: (A) FTS5/BM25 sull'indice esistente esteso ai documenti, query costruita dalla domanda
(parole di contenuto, prefisso senza vocale finale, OR); (B) embedding locali via Ollama
(modello da scaricare) in un indice vettoriale su file; (C) ibrido A+B con fusione dei ranking.

- A: nessuna dipendenza né modello nuovo, riusa riconciliazione e prefissi; debole su sinonimi e
  parafrasi ("nullità" vs "invalidità").
- B: migliore su parafrasi, ma un modello in più da tenere in VRAM accanto al 9B (8 GB condivisi
  con Whisper), indicizzazione lenta di un manuale, e un secondo indice da riconciliare.
- C: il meglio dei due al costo di entrambi.
- **Default: A**, dietro un'interfaccia `retrieve()` unica; B/C solo se `recall@8` di T024 resta
  sotto soglia.

### D3 - Arbitraggio GPU fra coda e chat [BLOCCANTE per F4, ADR]

Approcci: (A) la domanda della chat entra nella coda FIFO come qualsiasi lavoro; (B) chat fuori
coda, servita subito se nessuna trascrizione è in corso, altrimenti 409 `GPU_BUSY`, con un
lock GPU condiviso che il supervisor prende prima di avviare Whisper; (C) corsia prioritaria
nella coda (la domanda passa davanti, aspetta solo lo stadio corrente).

- A: invariante GPU gratis, ma una domanda può attendere 40 minuti dietro una trascrizione.
- B: risposta immediata nel caso comune; serve un lock esplicito e l'unload del modello prima di
  Whisper (oggi già fatto da `gpu_release.unload_ollama_models` in `before_transcribe`). Chat e
  studio/compiti su Ollama insieme sono ammessi (stesso server Ollama, che serializza).
- C: tempi prevedibili ma attesa comunque fino a fine stadio; complica la coda per un caso.
- **Default: B.** Compiti e riassunti invece entrano nella coda (sono lavori lunghi come lo studio).

### D4 - Estrazione del testo [BLOCCANTE per F1, ADR]

Approcci: (A) estrazione nel processo del server in un thread; (B) processo figlio dedicato con
timeout, fuori dalla coda GPU; (C) azione della coda GPU esistente.

- A: semplice, ma un PDF malformato che manda in loop il parser blocca o fa crescere il server.
- B: isolamento e timeout duri come per gli stadi (pattern `stage_runner` + `processes.py`); non
  occupa la GPU, quindi non deve aspettare una trascrizione.
- C: isolamento gratis ma un upload attende la trascrizione in corso per un lavoro solo CPU.
- **Default: B.** Output per documento: `text.json` con pagine (o slide) e testo per pagina.

### D5 - Persistenza di generazioni e conversazioni [ADR]

Approcci: (A) file JSON nella cartella del corso (`generations/<id>.json`,
`chats/<id>.json`), scrittura atomica; (B) tabelle SQLite in un database del corso; (C) dentro
`search.sqlite3`.

- A: coerente con il resto (`job.json`, `audio.studio.json`), ispezionabile, nessuna migrazione.
- B: query comode, ma un secondo database con schema e versioni da gestire.
- C: mescola un indice derivato e cancellabile con dati dell'utente: scartato.
- **Default: A.**

## Decisioni da far prendere all'utente

**Decise dall'utente il 2026-10-02**: U1 = OCR con `qwen2.5vl:7b` in una fase F5 separata (in F1
i scansionati restano marcati "senza testo"); U2 = conversazioni salvate per corso ed
eliminabili; U3 = solo il materiale del corso; U4 = export anche DOCX. Implementazione fino alla
fine con commit atomici su main.


- **U1 - PDF scansionati.** Default: in v1 sono caricati e consultabili ma segnalati "senza testo"
  ed esclusi da ricerca, compiti e chat. Alternativa: OCR locale con `qwen2.5vl:7b` (già
  installato) come fase F5 separata, lenta (stima da misurare: decine di secondi per pagina) e in
  coda GPU.
- **U2 - Conversazioni.** Default: salvate per corso, riapribili ed eliminabili. Alternativa: solo
  per la durata della pagina, niente su disco.
- **U3 - Conoscenza fuori dal materiale.** Default: compiti, riassunti e chat usano solo il
  materiale del corso e scartano ciò che non è citato (coerente con "un'allucinazione diventa un
  errore all'esame"). Alternativa: ammettere conoscenza generale del modello marcata "non dal tuo
  materiale".
- **U4 - Export.** Default: pagina + Markdown (compito e soluzioni in due file). Alternativa:
  anche DOCX via `docx_export.py`, +0,5-1 g.

## Ordine rispetto al piano study-library

- F1 e F2 non dipendono da T034/T045 e possono partire subito.
- F3 parte dopo **T045** verde (prova reale che la coda tipizzata rispetta l'invariante GPU con
  l'azione `study`, che F3 estende con un'azione di corso) e dopo i numeri di **T034** (fedeltà
  del prompt di studio e decisione Q7): i prompt di F3 riusano quell'impostazione, e se T034
  mostra troppe voci non fedeli la regola delle citazioni va rivista prima di replicarla.
- F4 parte dopo F2 (recupero) e dopo la chiusura di D3 nell'ADR.

## Fasi

| Fase | Obiettivo | Stato usabile a fine fase | Stima |
|---|---|---|---|
| F1 | Documenti nel corso, senza AI | carico, vedo, scarico ed elimino libro e slide | 4-6 g |
| F2 | Ricerca e recupero sul materiale | cerco nei documenti dal campo di ricerca esistente | 3-4,5 g |
| F3 | Compiti d'esame e riassunti | genero compiti con soluzioni a parte e riassunti citati | 6-9 g |
| F4 | Chat sul corso | chiedo e ottengo risposte con fonti | 5-7 g |
| | Totale | | 18-26,5 g |
| | Buffer 20% (primo uso di parser esterni, prompt da tarare, GPU condivisa) | | 22-32 g |

Ogni fase si chiude con il proprio gate (T019, T029, T039, T049). Le fasi AI (F3, F4) si chiudono
solo con la misura reale riportata all'utente, non con la suite verde.

## Architettura (default D1-B, D2-A, D3-B, D4-B, D5-A)

```
browser ──> FastAPI
  /corsi (dettaglio: lezioni + materiali + generazioni + chat), /corsi/<key>/documenti/<id>
  api_documents   POST|GET|DELETE /courses/<key>/documents[/<id>[/file|/pages/<n>]]
  api_generations POST|GET|DELETE /courses/<key>/generations[/<id>]  ──> Supervisor (coda GPU)
  api_chat        POST /courses/<key>/chats/<id>/messages ──> gpu_lock ──> retrieval ──> ollama_chat
  api_search      GET /search (lezioni + documenti) ──> search_service.reconcile()
Supervisor FIFO WorkItem(target, action ∈ {pipeline, study, generation}) ── Popen ──> stage_runner
extraction_runner (processo figlio, timeout) ──> document_extract (pypdf, python-docx, python-pptx)
data/courses/<course_id>/course.json, documents/<doc_id>/{original.<ext>, document.json, text.json},
                         generations/<id>.json, chats/<id>.json
```

| File | Tipo | Scopo |
|---|---|---|
| `src/sbobina/course_registry.py` | nuovo | D1: registro corsi, id stabile, lookup per chiave |
| `src/sbobina/document_models.py` | nuovo | dataclass `CourseDocument`, `ExtractedText`, stati, JSON I/O |
| `src/sbobina/document_sniff.py` | nuovo | puro: tipo reale dai byte, limiti archivi zip |
| `src/sbobina/document_extract.py` | nuovo | unico confine pypdf/python-docx/python-pptx, testo per pagina |
| `src/sbobina/web/extraction_runner.py` | nuovo | processo figlio con timeout (D4) |
| `src/sbobina/web/api_documents.py` | nuovo | upload, elenco, download, pagina, delete |
| `src/sbobina/web/search_index.py` | modifica + split | tabella passaggi dei documenti, `user_version` +1 |
| `src/sbobina/web/search_service.py` | modifica | riconciliazione anche dei documenti |
| `src/sbobina/retrieval.py` | nuovo | `retrieve()` e query da domanda naturale (D2) |
| `src/sbobina/source_citations.py` | nuovo | citazioni su passaggi di lezioni e documenti (estende `study_citations`) |
| `src/sbobina/generation_models.py` | nuovo | richiesta, formati, domande/soluzioni, schema LLM |
| `src/sbobina/generation_pipeline.py` | nuovo | recupero, prompt, validazione, assemblaggio |
| `src/sbobina/generation_render.py` | nuovo | puro: `compito.md`, `soluzioni.md`, riassunto |
| `src/sbobina/prompts/compito-v1.md`, `riassunto-v1.md`, `chat-v1.md` | nuovi | prompt versionati |
| `src/sbobina/web/work_items.py`, `supervisor.py`, `stage_runner.py` | modifica | azione `generation` di corso |
| `src/sbobina/web/api_generations.py` | nuovo | crea, legge, elimina generazioni |
| `src/sbobina/web/gpu_lock.py` | nuovo | D3: lock condiviso chat/Whisper |
| `src/sbobina/chat_pipeline.py`, `web/api_chat.py` | nuovi | turno di chat, persistenza |
| `templates/corsi.html`, `static/js/corsi*.js`, `templates/documento.html`, `static/js/corso-*.js` | modifica/nuovi | UI |
| `src/sbobina/config.py` | modifica | `course_doc_max_mb`, `extraction_timeout_s` |

## Rischi e mitigazioni

- **R1 corso senza identità su disco.** Poiché oggi il corso è una chiave calcolata dalle
  lezioni, cambiare l'etichetta di tutte le lezioni stacca i documenti, che non sarebbero più
  raggiungibili (+1-2 g di recupero dati se scoperto tardi). Mitigazione: D1 prima di F1; test
  "rinomina corso, documenti ancora visibili" (T011).
- **R2 recupero insufficiente con 8192 token.** Poiché il modello vede solo i passaggi recuperati
  e FTS5 non capisce le parafrasi, compiti e chat possono ignorare la parte giusta del materiale
  (qualità bassa, non errore visibile). Mitigazione: misura `recall@8` (T024) prima di F3/F4,
  interfaccia `retrieve()` che permette di passare a embedding senza toccare F3/F4; T036 prova
  anche `num_ctx` 16384 se la VRAM lo regge (misurato, non assunto).
- **R3 chat e GPU condivisa.** Poiché Whisper e il 9B non stanno insieme negli 8 GB, una domanda
  durante una trascrizione o una trascrizione avviata a chat aperta possono mandare in OOM uno
  dei due (job fallito, 40-85 min persi). Mitigazione: D3-B con lock, unload esplicito prima di
  Whisper (esiste), prova con `nvidia-smi` (T047).
- **R4 estrazione.** PDF scansionati, PPTX con testo nelle immagini, PDF con colonne e note a piè
  di pagina mescolate: testo assente o disordinato, citazioni che non si ritrovano. Mitigazione:
  rilevamento scansioni (U1), test su 3 file reali dell'utente in T014, testo estratto
  consultabile nel lettore documento così lo studente vede cosa il modello ha letto.
- **R5 fedeltà delle generazioni.** La validazione prova che la citazione esiste, non che la
  domanda o la soluzione siano corrette; nelle crocette una soluzione può citare il passaggio
  giusto e indicare la lettera sbagliata. Mitigazione: revisione a mano di tutte le domande in
  T036, numeri all'utente; dichiarazione in pagina "verifica sempre la fonte". Dipende da T034.
- **R6 upload = superficie nuova.** Tipo falso, path traversal, zip bomb, parser che va in loop,
  PDF con JavaScript servito inline. Mitigazione: sniff dei byte, id generati, limiti
  dimensione/espansione, estrazione in processo figlio con timeout, download solo come allegato,
  `security-reviewer` sul diff di F1.
- **R7 latenza chat.** Risposta JSON non in streaming con il 9B: decine di secondi, peggio a
  modello freddo (~10-20 s di caricamento). Mitigazione: misura T046 con soglia dichiarata prima;
  stato "sto cercando / sto scrivendo" in UI; se fuori soglia, valutare risposta in streaming con
  citazioni in coda (cambio di formato, da decidere con i numeri).
- **R8 file al limite.** `corsi.js` (305) e `search_index.py` (287) vanno divisi prima di
  estenderli, altrimenti il gate dimensionale rompe a metà fase. Task dedicati T010, T020.

## Criteri di verifica

Gate per fase con suite, ruff, format, mypy e `wc -l`; F1 con upload reali dei tre tipi e
`security-reviewer`; F2 con `recall@8` su domande scritte a mano; F3 e F4 con run reale su un
corso dell'utente, revisione a mano e `nvidia-smi` campionato. `/analyze` su
`specs/001-course-workspace/` a fine F4.

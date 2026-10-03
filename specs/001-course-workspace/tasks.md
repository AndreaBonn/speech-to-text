# Task: spazio di lavoro del corso (documenti, compiti, riassunti, chat)

Piano: `specs/001-course-workspace/plan.md` v1.0 (citato come "plan C<n>", "plan D<n>", "plan U<n>").
Blocchi delegabili (2-4 task per invocazione) indicati con **[B-n]**. Ogni task è TDD: test rosso
prima. Comandi via `uv run`. Mock solo ai boundary: Ollama (`ollama_chat`), processi figli (runner
fittizio come negli stadi esistenti), parser esterni solo dove serve un caso patologico; SQLite e
filesystem reali su `tmp_path`. Fixture dei documenti generate nei test (PDF con `pypdf`, DOCX con
`python-docx`, PPTX con `python-pptx`), mai file binari opachi committati senza sorgente.
Regole da F1: funzioni ≤ 30 righe, file ≤ 300, max 4 parametri, pathlib, `encoding="utf-8"`,
subprocess senza shell. I task marcati "(D<n>)" dipendono dall'ADR: se l'ADR cambia il default si
riscrivono prima di partire.

## F0 - Verifiche dell'ADR (prima di F1)

- [x] **T001** Le cinque verifiche aperte in `adr.md` (non delegabile: misura). (a) una chiamata
  con `num_ctx` diverso ricarica il modello? (`ollama ps` prima/dopo); (b) effetto di
  `OLLAMA_NUM_PARALLEL` sulla VRAM con due richieste; (c) licenza e wheel di `pypdf`,
  `python-pptx`, `pypdfium2` da PyPI; (d) estrazione `pypdf` su 3 PDF reali dell'utente, pagine
  sbagliate su totale; (e) token per parola italiana da `prompt_eval_count`. Rischio: medio.
  verify: tabella con i cinque esiti in `adr.md` e stato portato a "Accettato" o decisione rivista.

## F1 - Documenti nel corso, senza AI (plan C1)

**[B-1] T010-T012**

- [x] **T010** Dividere `static/js/corsi.js` (305 righe): elenco/ricerca corsi in `corsi.js`,
  dettaglio corso in `corso-dettaglio.js`. Nessun cambio di comportamento. Rischio: basso.
  verify: `wc -l` di entrambi < 250; click-through di `/corsi` (ricerca, apertura corso, link al
  lettore) identico a prima, registrato.
- [x] **T011** (D1) `src/sbobina/course_registry.py`: `data/courses/<course_id>/course.json`
  (`id` uuid4, `key`, `label`, `created_at`), `get_or_create(key, label)`, `find_by_key`,
  `rename_key(old, new)`; scrittura atomica (riuso `atomic_write`). `group_courses` include i
  corsi del registro senza lezioni. Rischio: medio (R1).
  verify: corso creato per chiave `diritto privato` → stesso id alla seconda chiamata; corso con
  0 lezioni presente in `GET /api/v1/courses` con `lecture_count: 0`; dopo `rename_key` la nuova
  chiave trova lo stesso id e i suoi documenti. ADR D1: `POST /api/v1/courses/<key>/rename`
  scrive prima `course.json` poi i `meta.json` (un crash a metà lascia il registro coerente);
  upload su "Senza corso" → 409.
- [x] **T012** `document_models.py` + `document_sniff.py` (puro): `sniff_document(head: bytes,
  path) -> DocumentKind | None` (PDF da `%PDF-`; DOCX/PPTX da firma zip + `[Content_Types].xml`
  con `wordprocessingml`/`presentationml`; TXT/MD decodificabili UTF-8 senza NUL),
  `check_archive_limits(path)` (somma `file_size` delle voci ≤ 500 MB, voci ≤ 10.000) senza
  estrarre; stati `uploading|extracting|ready|ready_no_text|failed`. Rischio: medio (R6).
  verify: test parametrizzati: PDF vero → `pdf`; `.exe` rinominato → None; zip qualsiasi →
  None; zip bomb sintetica (voce dichiarata 1 GB) → `ARCHIVE_TOO_LARGE`; testo con NUL → None.

**[B-2] T013-T015**

- [x] **T013** Aggiungere `pypdfium2` e `python-pptx` con `uv add` (ADR revisione D4); verificare la licenza dai
  metadati installati (`uv run python -c "import importlib.metadata as m; ..."`) e riportarla nel
  commit. `document_extract.py`: unico confine dei tre parser, `extract(path, kind) ->
  ExtractedText` (lista di pagine/slide con testo; TXT/MD in pagine logiche da ~500 parole);
  stato `ready_no_text` se oltre metà delle pagine ha meno di 20 caratteri (unica soglia, `is_scanned` rimossa). Rischio: medio.
  verify: PDF di 3 pagine generato nel test → 3 pagine col testo atteso; PPTX con 2 slide → 2
  "pagine"; PDF con sole immagini → `ready_no_text`; licenze nel messaggio di commit.
  Security (P1): PPTX con entità XML interna ed esterna (`<!ENTITY x SYSTEM "file:///etc/hostname">`)
  in `slide1.xml` → estrazione fallisce o ignora l'entità, mai il contenuto del file nel testo;
  la dipendenza si accetta solo con questo test verde (python-docx disabilita già
  `resolve_entities`, python-pptx non è verificato).
- [x] **T014** (D4) `web/extraction_runner.py`: processo figlio `extract <doc_dir>` che scrive
  `text.json` atomico; il padre (riuso `web/processes.py`) applica `extraction_timeout_s`
  (default 120), uccide e marca `EXTRACTION_TIMEOUT`; un'estrazione per volta, fuori dalla coda
  GPU; al boot gli `extracting` orfani tornano in estrazione. Prova su 3 file reali dell'utente
  (un manuale, slide, appunti). Rischio: alto (processi, timeout).
  verify: runner fittizio che dorme oltre il timeout → `failed` + `EXTRACTION_TIMEOUT`, server
  che risponde a `GET /api/v1/courses` durante l'estrazione; 3 file reali → pagine e tempi
  riportati in tabella nel report del task. Security (P2): il figlio imposta
  `resource.setrlimit(RLIMIT_AS, extraction_max_memory_mb)` (default 2048) prima di aprire il
  file, test con un runner che alloca oltre il limite → `failed` + `EXTRACTION_FAILED` e server
  vivo; test con spy che `check_archive_limits` è chiamato prima di `docx.Document`/
  `Presentation` (zip bomb mai decompressa). Su Windows `resource` non esiste: limite dichiarato
  come solo timeout. Prova non registrata: nessuna tabella di pagine/tempi sui 3 file reali
  trovata in `specs/001-course-workspace/`.
- [x] **T015** `web/api_documents.py`: `POST /api/v1/courses/<key>/documents` multipart (riuso
  `_write_upload` di `api_jobs.py` estratto in un modulo condiviso se serve per il limite di
  righe), salvataggio sotto id generato, sniff sui primi byte prima di accettare, 413/415 con
  pulizia dei file parziali; `GET` elenco paginato; `GET .../<id>/file` come allegato con
  `nosniff`; `GET .../<id>/pages/<n>` testo di una pagina; `DELETE` → 204. Impostazione
  `course_doc_max_mb` (default 200), applicata anche in `UploadLimitMiddleware` di `create_app`
  (oggi limita solo `/api/v1/jobs` e `/api/v1/wer`, `web/app.py:94`): senza, il multipart è
  illimitato prima dello sniff. Rischio: alto (R6).
  verify: test API per 202, 413, 415, 404, 204; nome `../../etc/passwd.pdf` → file in
  `data/courses/<id>/documents/<doc_id>/original.pdf`, niente fuori da `data/courses`; header del
  download controllati nel test. Security (P2): `Origin: http://evil.example` su POST e DELETE
  → 403 (OriginMiddleware di `web/app.py` ereditato, ma verificato per ogni mutazione nuova;
  stesso test in T011 rename, T034 e T042).

**[B-3] T016-T017**

- [x] **T016** UI "Materiali" nel dettaglio corso (`corso-dettaglio.js`, `corsi.html`): elenco con
  stato, upload (pulsante + trascina), avanzamento dell'upload, stato estrazione aggiornato
  (polling leggero o SSE esistente), elimina con conferma, scarica; stati loading, empty
  ("Nessun materiale: carica libro, slide o appunti"), error con causa e file preservato
  nell'input, edge (nome di 200 caratteri, 50 documenti). Pagina `/corsi/<key>/documenti/<id>`
  con il testo per pagina e navigazione `?p=`. Riga `DIAL:` da `design.md`. Rischio: medio.
  verify: click-through registrato (carica PDF, carica `.exe` rinominato → messaggio, elimina,
  scarica, apri pagina 3); render 375/1280; `a11y-gate` verde.
- [x] **T017** Test avversariale XSS: PDF il cui testo e nome contengono `<script>` e
  `<img onerror>` → elenco e lettore documento non eseguono nulla. Rischio: basso.
  verify: test Playwright o DOM che conta zero nodi `script`/`img` iniettati e zero dialog.

- [x] **T019** Gate F1. verify: suite, ruff, format, mypy; `wc -l` ≤ 300 sui file toccati;
  `security-reviewer` sul diff di F1 senza finding bloccanti; `git status` pulito dopo un upload
  (dati sotto `data/`); commit atomici.

## F2 - Ricerca e recupero sul materiale (plan C2) (D2)

**[B-4] T020-T022**

- [x] **T020** Dividere `web/search_index.py` (287): schema e connessione in
  `web/search_schema.py`. Nessun cambio di comportamento. Rischio: basso.
  verify: test esistenti della ricerca verdi senza modifiche; `wc -l` di entrambi < 220.
- [x] **T021** Tabella FTS5 `doc_passages(text, course_id, doc_id, page, chunk)` (stesso
  tokenizer) + tabella stato `documents(doc_id, mtime_ns, size)`; `SCHEMA_VERSION` +1 (il file
  vecchio si ricostruisce, comportamento già previsto); riconciliazione in `search_service.py`
  estesa a `data/courses/*/documents/*/text.json`; documenti `ready_no_text` esclusi. Passaggi da
  ~150-250 parole tagliati sui confini di frase, mai a cavallo di due pagine. Rischio: medio.
  verify: upload → la ricerca successiva trova il documento; delete → sparisce; `search.sqlite3`
  cancellato → ricostruito con lezioni e documenti; tempo di indicizzazione di un manuale reale
  misurato e riportato. Prova non registrata: nessun tempo di indicizzazione trovato nei file di
  `specs/001-course-workspace/`.
- [x] **T022** `GET /api/v1/search` restituisce anche risultati di documento (`kind: "document"`,
  `doc_id`, `page`, snippet a parti) e il link a `/corsi/<key>/documenti/<id>?p=<page>&q=`; la
  pagina dei risultati li mostra con nome file e pagina; il lettore documento evidenzia il
  termine. Rischio: medio.
  verify: esempio di plan C2 (p. 214) in un test; click-through dal risultato alla pagina con il
  termine evidenziato; filtro per corso rispettato.

**[B-5] T023-T024**

- [x] **T023** `src/sbobina/retrieval.py`: `question_to_fts(question) -> str` (stopword italiane
  in costante, parole di contenuto, prefisso senza vocali finali come la ricerca, OR, nessuna
  sintassi FTS dall'utente), `retrieve(index, course_id, question, budget_words, sources) ->
  list[Passage]` (BM25, solo il corso, filtro opzionale per lezioni/documenti scelti, taglio al
  budget di parole). `Passage` porta testo, fonte e un id stabile per la citazione. Rischio: medio.
  verify: "cos'è la causa del contratto?" → query senza `cos`, `è`, `la`, `del`; input con `"`,
  `NEAR(`, `*` → nessuna eccezione; passaggi di un altro corso mai restituiti; budget rispettato.
- [x] **T025** (ADR D2, tabella Chunking) Il recupero delle lezioni restituisce una finestra di
  ~250 parole attorno a ogni segmento trovato (segmenti adiacenti della stessa trascrizione),
  fusa se due finestre si toccano, invece del singolo segmento Whisper di 10-30 parole. La
  citazione resta ancorata al segmento trovato. Emerso dalla review di T023. Rischio: medio.
  verify: segmento di 12 parole al centro di una lezione → passaggio di 230-270 parole che lo
  contiene; due segmenti vicini → una sola finestra; budget di parole rispettato.
- [x] **T024** Misura del recupero (non delegabile: giudizio). Con l'utente: 30+ domande su un
  corso reale con il passaggio atteso annotato in `specs/001-course-workspace/eval.md`;
  `recall@8` e `recall@15`. `BUDGET: 3 iterazioni di query_builder | ranking: recall@8 > recall@15
  > numero di passaggi`. Rischio: alto (R2).
  verify: tabella dei tentativi e riga `SPEDITO:`; se recall@8 < 0,7 la decisione D2 torna
  all'architect con i numeri prima di F3.

- [x] **T029** Gate F2. verify: suite, ruff, format, mypy, `wc -l`; ricerca su lezioni invariata
  (test esistenti verdi); `a11y-gate` sulla pagina risultati se cambiata.

## F3 - Compiti d'esame e riassunti (plan C3)

Prerequisiti: T045 di `specs/study-library/tasks.md` verde, numeri di T034 disponibili, T024 sopra
soglia (o D2 rivista).

Decisione del 2026-10-03 (implementazione continua chiesta dall'utente): T024 sopra soglia (0,90).
T034/T045 di study-library restano aperti; ciò che proteggevano lo verificano qui T036 (fedeltà
misurata a mano sulle generazioni di F3) e T039 (run reale con `nvidia-smi` sull'azione
`generation` accodata dietro una trascrizione).

**[B-6] T030-T032**

- [x] **T030** `source_citations.py`: estende la validazione di `study_citations.py` a passaggi
  con fonte di documento (`doc_id`, pagina) o di lezione (indice di parola → timestamp); motivi
  `PASSAGE_NOT_GIVEN`, `QUOTE_NOT_FOUND`, `QUOTE_LENGTH`. Riuso della normalizzazione, nessuna
  copia. Rischio: medio.
  verify: esempio di plan C3 con passaggio di p. 214 → tenuta con `page: 214`; testo citato
  inesistente → `QUOTE_NOT_FOUND`; passaggio non fornito → `PASSAGE_NOT_GIVEN`; test di
  `study_citations` invariati e verdi.
- [x] **T031** `generation_models.py`: `GenerationRequest(format: multiple_choice|open|oral|
  summary, count 1-10, topic ≤ 200 caratteri, sources)`; dataclass di domande, opzioni,
  soluzioni separate, riassunto a sezioni; schema pydantic della risposta LLM per formato
  (crocette: esattamente 4 opzioni, una `correct`); JSON I/O di `generations/<id>.json` (D5).
  Rischio: medio.
  verify: crocette con 3 opzioni o due corrette → rifiutate dallo schema; `count` 0 o 11 → 422 a
  livello API (T034); round-trip JSON identico.
- [x] **T032** Prompt `compito-v1.md` (un file con sezioni per formato o un file per formato,
  scelto in `prompt-master`) e `riassunto-v1.md`: passaggi numerati come dato delimitato, regola
  "usa solo i passaggi", citazione obbligatoria per soluzioni e frasi del riassunto, opzioni
  errate senza citazione, risposta vuota se il materiale non basta. Passaggio da `prompt-master`
  prima del commit. Rischio: medio.
  verify: test che il prompt renderizzato con 12 passaggi resta sotto il budget di token stimato
  (parole × 1,6, costante nominata) con margine per l'output; esito di `prompt-master` nel report.

**[B-7] T033-T035**

- [x] **T033** `generation_pipeline.py` + `generation_render.py`: recupero per argomento (o
  campionamento distribuito sulle fonti se l'argomento è vuoto), chiamata `chat_json`, validazione
  citazioni, scarto per motivo (anche voce con 0 o più di 3 citazioni, crocetta con opzioni vuote o
  duplicate: scarto della singola voce, non della risposta), conteggio "N su M", un retry su JSON
  invalido; render puro di
  `compito.md` e `soluzioni.md` (e riassunto). Rischio: medio.
  verify: con Ollama finto: domanda con soluzione non citata → scartata e contata; argomento senza
  passaggi → `NO_MATERIAL` senza chiamare il modello; `compito.md` non contiene mai il testo delle
  soluzioni (test che cerca la risposta corretta nel file delle domande).
- [x] **T034** (D3, D5) Azione `generation` nella coda: `WorkItem` con bersaglio di corso
  (`work_items.py`, `supervisor.py`, `stage_runner.py generation <course_dir> <gen_id>`), stato
  `queued|running|done|failed|interrupted` nel file della generazione, recupero al boot come per
  `study`, cancel; `api_generations.py` POST (202, 422 per campo), GET elenco paginato e dettaglio
  con citazioni risolte (link al lettore o alla pagina, "fonte rimossa" se il documento non c'è
  più), DELETE. Le citazioni di lezione arrivano da T030 ancorate al segmento trovato (inizio
  della finestra di ~250 parole, fino a ~1 minuto prima della frase): l'API risolve il timestamp
  esatto cercando la citazione nella trascrizione (come `api_study` con `locate_quote`). Rischio: alto (coda condivisa).
  verify: runner fittizio: trascrizione A poi generazione B → mai due figli insieme; riavvio
  simulato con generazione `running` → `interrupted`; `supervisor.py` e `stage_runner.py` ≤ 300
  righe (dividere prima se serve); test esistenti della coda verdi. Implementato nel commit
  `45cca53`.
- [x] **T035** UI generazioni nel corso: form (formato, numero, argomento, fonti), avanzamento via
  polling (come la coda delle trascrizioni, non SSE), elenco generazioni, vista con domande e
  soluzioni separate (sezione chiusa di default), link delle citazioni, contatori di scarto,
  download `compito.md`/`soluzioni.md`, elimina; stati loading/empty/error/edge (Ollama non
  raggiungibile, "8 su 10", nessun materiale). Rischio: medio.
  verify: click-through registrato di ogni controllo; render 375/1280; `a11y-gate`; XSS con
  `<script>` nella risposta LLM finta → nessuna esecuzione. Prove fatte in sessione, commit
  `d3a4668`.

- [x] **T036** Misura reale (non delegabile: giudizio). `BUDGET: 4 iterazioni del prompt |
  ranking: domande sbagliate (meno) > soluzioni sbagliate (meno) > domande scartate (meno) >
  durata`. Corso reale: un compito per formato (10 domande) e 2 riassunti; durata,
  `prompt_eval_count` massimo, scarti per motivo, revisione a mano di tutte le domande tenute e
  delle soluzioni (giusta / sbagliata / ambigua). Prova di `num_ctx` 16384 con `nvidia-smi`
  (picco VRAM) solo se R2 lo richiede. Rischio: alto (R5).
  verify: `specs/001-course-workspace/eval-generations.md` con tabella dei tentativi e
  `SPEDITO:`; numeri riportati all'utente prima di T039.
- [x] **T038** (U4) Export DOCX di compito, soluzioni e riassunto riusando `docx_export.py`
  (unico confine python-docx). Rischio: basso.
  verify: DOCX generato nel test riaperto con python-docx → titoli e domande attesi; soluzioni
  in un file separato dal compito.
- [x] **T039** Gate F3. verify: suite, ruff, format, mypy, `wc -l`; run reale con generazione
  accodata dietro una trascrizione e `nvidia-smi --query-compute-apps` ogni 15 s → mai Whisper e
  Ollama insieme; export DOCX di compito e soluzioni via `docx_export.py` (U4 = DOCX, T038).

## F4 - Chat sul corso (plan C4) (D3)

**[B-8] T040-T042**

- [x] **T040** (D3) `web/gpu_lock.py`: lock condiviso nel processo server; la chat lo prende con
  `try_acquire` e risponde 409 `GPU_BUSY` (con lo stadio corrente e la stima) se il supervisor
  sta trascrivendo; il supervisor lo prende prima di `before_transcribe` (che scarica i modelli
  Ollama) e attende la fine del turno di chat in corso. Rischio: alto (R3, concorrenza).
  verify: test con thread: chat attiva → il supervisor non avvia la trascrizione finché il turno
  non rilascia; trascrizione attiva → chat 409; nessun deadlock con cancel durante l'attesa
  (timeout del test come guardia, attesa su condizione, niente sleep). Da senior-backend: la
  lease esclusiva copre l'intero stadio TRANSCRIBING e si rilascia prima di CORRECTING (test che
  una chat durante la trascrizione riceve 409 fino alla fine dello stadio, non solo all'unload);
  l'arbitro separa solo la chat del processo web dal supervisor, i figli della coda sono già
  seriali per la FIFO (ADR D3 da correggere: il diagramma fa passare i CourseWorkItem
  dall'arbitro); test di starvation: chat in arrivo continuo mentre la trascrizione aspetta →
  la trascrizione parte dopo il turno in corso (priorità allo scrittore).
- [x] **T041** `chat_pipeline.py` + prompt `chat-v1.md` (via `prompt-master`; sostituito da `chat-v2.md` in T046, vedi `eval-chat.md`): domanda + ultimi 2
  scambi → `retrieve` → risposta JSON a frasi con citazioni → validazione → frasi non citate
  rimosse; nessun passaggio o nessuna frase valida → "Non trovo la risposta nel materiale di
  questo corso" senza (o dopo) la chiamata. Rischio: medio.
  verify: con Ollama finto: domanda fuori corso → messaggio di non trovato; frase con citazione
  inventata → rimossa; storia di 10 scambi → solo gli ultimi 2 nel prompt.
- [x] **T042** `web/api_chat.py` (D5): `POST /api/v1/courses/<key>/chats` crea, `POST
  .../chats/<id>/messages` (domanda ≤ 1000 caratteri, 422 per campo), `GET` elenco e dettaglio,
  `DELETE`; persistenza `chats/<id>.jsonl` append-only come da ADR D5 (una riga per messaggio,
  append sotto lock per conversazione; niente riscrittura intera, che con due schede perde un
  messaggio), o solo in memoria se U2 sceglie così; `def` sincrona (I/O Ollama sincrono,
  threadpool). Timeout esplicito sul client Ollama della chat (`chat_timeout_s`, default 120):
  oltre → 504 `CHAT_TIMEOUT` e lease condivisa rilasciata. Accettato: una richiesta in threadpool
  non si cancella se il browser chiude, il timeout ne limita la durata. Rischio: medio.
  verify: test API per 201/200/409/422/404/204; Ollama giù → 503 `OLLAMA_UNAVAILABLE` e domanda
  dell'utente conservata nel file; Ollama finto che non risponde → 504 entro il timeout e GPU di
  nuovo disponibile per il supervisor; due POST concorrenti sulla stessa chat → entrambe le
  righe nel JSONL.

**[B-9] T043-T044**

- [x] **T043** UI chat nel corso: elenco conversazioni, thread, invio con stato "sto cercando nel
  materiale / sto scrivendo", fonti cliccabili sotto ogni risposta, messaggio GPU occupata con la
  stima, input preservato su errore, stati loading/empty/error/edge (domanda lunga, risposta
  lunga, 50 messaggi). Rischio: medio.
  verify: click-through registrato; render 375/1280; `a11y-gate`; XSS nella risposta finta.
- [x] **T044** Aggiornare `CLAUDE.md` del progetto (layout: registro corsi, estrazione, recupero,
  generazioni, chat, lock GPU). Rischio: basso.
  verify: `git diff CLAUDE.md` limitato alle sezioni Layout e Stack.

- [x] **T046** Misura reale (non delegabile: giudizio). 10 domande su un corso reale (incluse 2
  fuori dal materiale), modello caldo e freddo: latenza p50 e massima, `prompt_eval_count`,
  risposta corretta / parziale / sbagliata a mano, fuori-materiale riconosciute. `BUDGET: 3
  iterazioni del prompt | ranking: risposte sbagliate (meno) > fuori-materiale non riconosciute
  (meno) > latenza`. Rischio: alto (R7).
  verify: `specs/001-course-workspace/eval-chat.md` con tabella e `SPEDITO:`; se p50 > 30 s a
  modello caldo, la decisione sul formato in streaming va all'utente con i numeri.
- [x] **T047** Prova GPU reale: trascrizione avviata con una chat in corso e domanda inviata
  durante una trascrizione; `nvidia-smi --query-compute-apps` ogni 5 s. Rischio: alto (R3).
  verify: mai Whisper e Ollama insieme nei campioni; 409 osservato nella pagina; job di
  trascrizione completato.
- [ ] **T049** Gate finale. verify: suite, ruff, format, mypy, `wc -l`; `/analyze` su
  `specs/001-course-workspace/`; `code-reviewer` e `security-reviewer` sul diff di fase.

## F5 - OCR dei PDF scansionati (U1 = OCR)

- [x] **T050** Misura (non delegabile): 5 pagine scansionate con `qwen2.5vl:7b`, tempo per pagina,
  VRAM, qualità del testo a vista. verify: tabella in `eval.md`; decisione su risoluzione e prompt.
- [x] **T051** Azione di coda `ocr` (GPU, come lo studio): pagine renderizzate a immagine
  (`pypdfium2` o equivalente da T001c), una chiamata per pagina, testo in `text.json` con
  `source: "ocr"`; documento da `ready_no_text` a `ready`. Prompt `ocr-v1.md` via prompt-master.
  verify: Ollama finto → pagine scritte e stato `ready`; Ollama giù → `failed` con
  `OLLAMA_UNAVAILABLE`, file originale intatto.
- [x] **T052** UI: pulsante "Estrai il testo con OCR" sui documenti senza testo, avanzamento,
  testo OCR marcato come tale nel lettore. verify: click-through, a11y-gate, render 375/1280.
- [x] **T059** Gate F5. verify: suite, ruff, format, mypy; run reale su un PDF scansionato con
  `nvidia-smi` → mai Whisper e OCR insieme.
  Esito: valido al secondo run (2026-10-03, Whisper su CUDA, 0 campioni sovrapposti su 289), vedi
  `eval.md`.

## Remediation /analyze (2026-10-03)

Una riga per finding, verso i task sopra.

- [x] **A1** Test di generazione e citazioni divisi sotto le 300 righe (`test_generation_budget.py`, `test_api_generations_document_citations.py`). Commit `45343e9`.
- [x] **A2** `app.css` diviso in 10 fogli per area. Commit `f535471`.
- [x] **A3** Fonti delle generazioni registrate con `sha256` (documenti) o revisione (lezioni);
  una citazione la cui fonte è cambiata arriva con `changed: true` e la pagina mostra " · fonte
  modificata dopo la generazione" (vedi adr.md § D5). Commit `06f41ca`.
- [x] **A4** Limiti al processo OCR: figlio sotto lo stesso `RLIMIT_AS` dell'estrazione
  (`web/child_limits.py`); il supervisore lo uccide dopo `ocr_process_timeout_s` (3600 s) con
  `OCR_TIMEOUT`; rendering della pagina limitato a 2500 px sul lato lungo (vedi adr.md § D4).
  Commit `c0d0255`.
- [x] **A5** Page rifiuta pagine OCR senza testo. Commit `8164609`.
- [x] **A7** 409 `DOCUMENT_EXISTS` su upload duplicato (stesso `sha256`). Commit `faae876`.
- [x] **A8** Test che l'output del modello arriva alla pagina come testo, non eseguito. Commit
  `074dd77`.
- [x] **A10/A18** Avvisi in UI quando il polling o il cancel dell'OCR falliscono (commit
  `a39bdfa`) e warning sulla pagina OCR vuota (commit `8164609`).
- [x] **A16** Motivi degli scarti mostrati in pagina ("N su M richieste", riga per motivo).
  Commit `d36482c`.
- [x] **A19** `discarded >= 0` (mai negativo) loggato e verificato. Commit `8164609`. Seconda
  metà del finding (controllo che `question_id` esista) scartata: nessun chiamante può produrre
  una risposta senza la sua domanda, la risposta è scritta da `chat_turn.ask` subito dopo la
  domanda nello stesso turno.

# Task: biblioteca di studio (corsi, ricerca, materiali) e CI

Piano: `specs/study-library/plan.md` v1.0 (decisioni citate come "plan Q<n>" o "plan § <sezione>").
Blocchi delegabili (2-4 task) indicati con **[B-n]**. Ogni task è TDD: test rosso prima.
Tutti i comandi via `uv run`. Mock solo ai boundary: Ollama (`ollama_chat`), processo figlio
(runner fittizio come in web-ui), SQLite **reale** su `tmp_path` (non si mocka: è veloce e locale).
Regole valide da F1: funzioni ≤ 30 righe, file ≤ 300, max 4 parametri, pathlib, `encoding="utf-8"`,
niente shell. Le fasi F2, F3 e F5 dipendono dagli ADR di Q1, Q2, Q3: se l'ADR cambia il default,
i task marcati "(Q<n>)" si riscrivono prima di partire.

## F1 - CI GitHub Actions e badge (D8)

**[B-1] T001-T003**

- [x] **T001** `.github/workflows/ci.yml` secondo plan § CI: trigger `push` e `pull_request` verso
  `main`, `permissions: contents: read`, `concurrency` per ref, job `check` su `ubuntu-24.04`,
  `timeout-minutes: 15`; passi checkout (`persist-credentials: false`), `astral-sh/setup-uv` con
  `enable-cache: true` e `cache-dependency-glob: uv.lock`, `uv python install`, `uv sync --locked`,
  ruff check, ruff format --check, mypy src tests, pytest.
  **SHA da verificare in implementazione, non da scrivere a memoria**: per ogni action
  `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`, e se l'oggetto è un tag annotato
  `gh api repos/<owner>/<repo>/git/tags/<sha>` fino al commit; SHA di 40 caratteri con `# vX.Y.Z`
  in commento. Rischio: medio.
  verify: `grep -E "uses: .+@[0-9a-f]{40}" .github/workflows/ci.yml` conta tutte le righe `uses:`;
  nessuna riga `uses:` senza SHA; `permissions` e `persist-credentials: false` presenti; il file
  passa `yamllint` (hook `format-changed-file.sh`).
- [x] **T002** Prova locale dell'ambiente CI (R5): in una copia pulita del repo (`git worktree add`
  nella scratchpad) eseguire con `env -i HOME=<vuota> PATH=<uv>:/usr/bin:/bin
  CUDA_VISIBLE_DEVICES="" OLLAMA_HOST=http://127.0.0.1:9 HF_HUB_OFFLINE=1` la stessa sequenza del
  workflow, partendo da `uv sync --locked` in un venv nuovo. Rischio: basso.
  verify: tutti e cinque i passi exit 0; numero di test riportato (544 il 2026-10-02, cresce con le
  fasi successive); se un passo fallisce, causa nominata prima di toccare il workflow.
- [x] **T003** Badge: in `README.md` e `README.it.md` sostituire la riga 9
  (`![Tests](https://img.shields.io/badge/tests-478%20passed-brightgreen)`) con
  `[![CI](https://github.com/AndreaBonn/speech-to-text/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/AndreaBonn/speech-to-text/actions/workflows/ci.yml)`.
  Rischio: basso.
  verify: `git diff --stat` mostra 1 riga cambiata per README; `grep -c "tests-478" README*.md` → 0.
- [ ] **T004** Gate di fase e consegna. verify: ruff, format, mypy, pytest verdi in locale; nel
  report "push pronto, il primo run e il badge si vedono dopo il push su GitHub" (push all'utente,
  R6). Dopo il push dell'utente: run verde e log di setup-uv con cache salvata; al secondo run
  "cache restored".

## F2 - Corsi (D4, prima metà) (Q1)

**[B-2] T010-T012**

- [x] **T010** `src/sbobina/courses.py` puro: `normalize_course_label(raw) -> str | None` (strip,
  spazi compressi, NFKC, vuoto → None, max 100), `course_key(label) -> str` (casefold della
  normalizzata), `effective_course(course, subject) -> str | None`, `group_courses(records) ->
  list[CourseSummary]` (`key, label` della lezione più recente, `lecture_count`,
  `last_lecture_at`, gruppo "Senza corso" con chiave dedicata). Rischio: basso.
  verify: test parametrizzati: `"  Diritto   Privato "` → label `Diritto Privato`, key
  `diritto privato`; `""` → None; 101 caratteri → errore; due record "diritto privato" e "Diritto
  Privato" → 1 corso, count 2, label del più recente.
- [x] **T011** (ADR A1-c) `data/jobs/<id>/meta.json` di proprietà dell'utente, `LectureMeta(course:
  str | None)` validato con `normalize_course_label`; `job.json` resta del supervisor (nessun
  campo nuovo, nessuna race fra PATCH e `store.update` del supervisor). `JobStore.read_meta` /
  `write_meta` (atomic_write); `JobStore.list(..., course_key: str | None = None)` filtra sul corso
  effettivo `meta.course or config.subject`. Rischio: medio (R2). verify: job senza `meta.json`
  → corso effettivo = `subject`; `list(course_key="diritto privato")` su 5 job misti → solo i 2
  giusti con `total` 2; test: `write_meta` concorrente a `store.update` sullo stesso job → entrambi
  i dati presenti; test esistenti di `test_job_store.py` e `test_job_models.py` verdi senza modifiche.
- [x] **T012** `src/sbobina/web/api_courses.py`: `GET /api/v1/courses` (paginato, envelope),
  `PATCH /api/v1/jobs/<id>/meta` con body `{course}`; `GET /api/v1/jobs` accetta `course`.
  Ammesso anche su job in corso (file separato). 422 per campo. Rischio: basso.
  verify: test API: PATCH → 200 e `meta.json` con `course`, `job.json` byte-identico; 101
  caratteri → 422 `details[0].field == "course"`; PATCH con `Origin` estraneo → 403 (middleware
  esistente); `/courses?page=1&per_page=10` → `meta` completo.

**[B-3] T013-T015**

- [x] **T013** Pagina `/corsi` (`pages.py`, `templates/corsi.html`, `static/js/corsi.js`): elenco
  corsi, apertura di un corso → lezioni con data, durata, stato studio (quando F5 c'è) e link al
  lettore; voce nav "Corsi" in `NAV_SPECS`. Riga `DIAL:` derivata da `design.md`. Rischio: basso.
  verify: test della pagina (200, voce nav attiva); render a 375 e 1280 px.
- [x] **T014** Campo "Corso" modificabile nel lettore e nello storico (`static/js/course-field.js`,
  `<datalist>` dai corsi esistenti, salvataggio con PATCH, errore mostrato accanto al campo con
  input preservato). `reader.js` e `storico.js` cambiano solo per montarlo. Rischio: medio.
  verify: click-through: cambio corso dal lettore → `/corsi` mostra la lezione nel nuovo corso;
  valore troppo lungo → messaggio, testo non perso; job in corso → campo modificabile.
  Esito: campo solo nel lettore; lo storico non lo monta (le righe hanno già le azioni e
  `/corsi` copre il raggruppamento). Il limite di lunghezza lo giudica solo il server: NFKC può
  espandere oltre 100 un testo che `maxlength` ammette (verificato con 34 legature «ﬃ»).
- [x] **T015** Gate di fase. verify: suite, ruff, format, mypy; `a11y-gate` verde su `/corsi` e
  lettore; click-through registrato; `wc -l` dei file toccati ≤ 300 (salvo `reader.js`/`jobs.js`,
  che non crescono di più delle righe di montaggio).

## F3 - Ricerca full-text e deep link (D4, seconda metà) (Q2, Q4, Q5)

Prima di T021: la doc FTS5 (`https://www.sqlite.org/fts5.html`, sezioni tokenizer `unicode61`,
`prefix`, `highlight`, `bm25`, sintassi delle stringhe) citata nei docstring dove la scelta non è
ovvia.

**[B-4] T020-T022**

- [x] **T020** `src/sbobina/search_text.py` puro: `passages_from_transcript(transcript) ->
  list[Passage(segment_index, start, text)]` (segmenti vuoti saltati); `build_match_query(raw) ->
  str | None` (plan § Ricerca: parole `"x"*` senza vocali finali da 5 lettere, frasi esatte, max 10 termini, virgolette
  raddoppiate, None se nulla resta); `snippet_parts(highlighted) -> list[SnippetPart]`.
  Rischio: medio. verify: `contratti causa` → `"contratt"* "caus"*`; `di` → `"di"*`; `"causa illecita" x` →
  `"causa illecita"` (`x` scartato perché < 2 caratteri); `NEAR(a b)`, `col:val`, `-x`, `*`,
  `"` → stringa sicura o None; ogni output eseguito su una tabella FTS5 reale in memoria senza
  `OperationalError` (test parametrizzato, anche con input generati: 200 stringhe casuali di
  simboli).
- [x] **T021** `src/sbobina/web/search_index.py`, unico confine sqlite: `open_index(path)` (crea
  schema, verifica `user_version`, verifica FTS5 → `SearchUnavailableError`), `replace_lecture`,
  `remove_lecture`, `indexed_lectures`, `search(match, job_ids, limit, offset) -> SearchPage`.
  Parametri sempre bindati. Rischio: alto (primo indice del progetto).
  Ceiling (review DB, B1, measured): la delete per `job_id` UNINDEXED è un full scan, 54 ms a 450k
  righe. Oltre ~10^6 righe passare a external-content FTS5 su rowid di `lectures`; non prima (YAGNI).
  verify: su `tmp_path`: lezione con "la causa del contratto è illecita" a 2472,0 s → `search` di
  `"contratt"*` restituisce `start == 2472.0` e snippet con 1 parte `match`; "perche" trova
  "perché"; `replace_lecture` due volte → nessun duplicato; filtro `job_ids` rispettato; file con
  `user_version` diverso → ricostruito; file di byte casuali → ricostruito con WARNING (caplog);
  FTS5 assente simulato (connessione che solleva su `CREATE VIRTUAL TABLE`) →
  `SearchUnavailableError`.
- [x] **T022** `src/sbobina/web/search_service.py`: `reconcile(store, index)` confronta per job il
  file preferito (corretto se esiste, altrimenti originale, Q5) per `(path, mtime_ns, size)` con
  `lectures`, reindicizza i cambiati, rimuove gli assenti; lock unico per riconciliazione + query.
  Rischio: medio (R1). verify: test che scrivono i file **senza** passare dal server: nuova
  trascrizione → trovata; `audio.corretto.json` creato → la variante indicizzata diventa
  `corrected` e la parola corretta si trova, quella vecchia no; cartella del job rimossa → nessun
  risultato; nessuna modifica → zero reindicizzazioni (contatore).

**[B-5] T023-T024**

- [x] **T023** `src/sbobina/web/api_search.py`: `GET /api/v1/search?q=&course=&page=&per_page=`;
  riconcilia, interroga, raggruppa per lezione, aggiunge titolo (`_reader_title`), corso, `t`,
  `variant`, href `/lettore/<id>?t=<start>&variant=<v>`. 422 su `q` vuota dopo la pulizia, 503
  `SEARCH_UNAVAILABLE`, riconciliazione anche nel `lifespan` al boot. Rischio: medio.
  verify: test API su 3 lezioni fixture: `q=causa contratto` → prima lezione giusta, `meta`
  completo; `q=%22%22` → 422 `field: "q"`; `course=<key>` limita i risultati; indice
  indisponibile → 503 con envelope di errore; dopo `PATCH .../transcript/corrected` (edit manuale)
  la parola nuova si trova senza riavvio.
- [x] **T024** Deep link nel lettore: `static/js/reader-link.js` legge `t` e `variant` dall'URL,
  carica quella variante, a metadati audio pronti chiama `seekTo(t)`, porta in vista la parola con
  `start` più vicino e la evidenzia; `t` non numerico o fuori durata → ignorato senza errori.
  `reader.js` espone già `seekTo`: cambia solo per caricare il modulo. Rischio: medio.
  verify: click-through: `/lettore/<id>?t=2472&variant=corrected` → `audio.currentTime` 2472 ±1,
  parola evidenziata visibile; `?t=abc` → lettore normale, console senza errori.

**[B-6] T025-T026**

- [x] **T025** UI ricerca su `/corsi` (`static/js/search.js`): campo di ricerca con filtro corso,
  risultati per lezione (max 3 passaggi, "altri N"), snippet costruito con `textContent` dalle parti,
  stati loading/empty con eco della query/error con query preservata/503. Rischio: medio.
  verify: test con trascrizione che contiene `<script>alert(1)</script>` → nessuna esecuzione
  (Playwright, nessun dialog); click su un risultato apre il lettore al tempo giusto.
- [x] **T026** Gate di fase e misura su dati reali (`data/jobs` di questa macchina). verify: tempo
  di ricostruzione da indice vuoto e latenza di `GET /search` con indice allineato riportati
  (3 run, mediana); scenario "dove ha spiegato X?" su una lezione reale annotato con tempo trovato
  vs tempo ascoltato; `a11y-gate` verde, render 375/1280, click-through; suite, ruff, format, mypy.
  Esito 2026-10-02 (BASIS: measured; in `data/jobs` non c'erano job web, quindi archivio di misura
  con la lezione reale da 85 min, 5971 parole e 605 segmenti, replicata x1 e x100: testo identico
  fra le copie, misura di scala e non di varietà):
  ricostruzione da indice vuoto, mediana su 3 run: x1 0,02 s, x100 2,83 s; `search_lectures` con
  indice allineato, mediana su 3: x1 2 ms, x100 9-33 ms (33 ms su "contratto", 11 passaggi per lezione).
  "Dove ha spiegato l'interesse legittimo?" → 1:21, inizio del segmento (precisione Q4, a segmento);
  il riscontro all'ascolto spetta all'utente. axe chiaro/scuro 0 violazioni, responsive ok; il gate
  states non legge oklch() (inconcludente), sostituito da `contrast.py` sui colori renderizzati:
  minimo 6,17:1 sui testi, 4,15:1 sui bordi. Click-through ricerca 11/11, corsi 9/9.

## F4 - Motore dei materiali di studio e CLI (D5, prima metà)

Usabile da sola: `sbobina studio <json>` produce materiali validati senza il web.

**[B-7] T030-T031**

- [x] **T030** Estrarre `src/sbobina/ollama_chat.py` da `llm_corrector.py`: `chat_json(client,
  request: ChatRequest) -> str` (contenuto della risposta), mappatura errori
  (`CorrectorUnavailableError`/`InvalidResponseError` restano quelli di oggi), rimozione del fence
  markdown. `llm_corrector` lo usa; nessun cambio di comportamento. Aggiornare `CLAUDE.md`
  (§ Layout: il confine Ollama unico diventa `ollama_chat.py`). Rischio: medio.
  verify: `uv run pytest tests/test_llm_corrector.py tests/test_correction.py` verdi **senza
  modifiche ai test esistenti**; nuovi test di `ollama_chat` con client finto (fence, JSON nudo,
  `ResponseError`, `httpx.TransportError`).
- [x] **T031** `src/sbobina/study_models.py` (dominio + schema pydantic della risposta) e
  `src/sbobina/study_citations.py` puro: `normalize_tokens(text)`, `locate_quote(segments,
  segment_index, quote, allowed) -> CitationMatch | Rejection` (contiguità sul passaggio o sul
  successivo nello stesso blocco, 3-40 parole), `validate_item(...)` stretto (una citazione
  invalida scarta la voce; termine del concetto presente in una citazione), motivi
  `PASSAGE_NOT_IN_BLOCK | QUOTE_NOT_FOUND | QUOTE_TOO_SHORT | QUOTE_TOO_LONG |
  TERM_NOT_IN_QUOTE`. Rischio: alto (è la garanzia chiesta dall'utente).
  verify: gli esempi della DoD D5 come test; più: citazione che differisce solo per maiuscole,
  apostrofo tipografico e punteggiatura → valida; citazione a cavallo dei passaggi 12-13 → valida,
  12-14 → scartata; parola ripetuta nel passaggio → prima occorrenza; citazione vera presa da un
  passaggio fuori dal blocco → scartata; mutation check: invertire il confronto di contiguità fa
  fallire almeno un test (memoria progetto: rimuovere i `.pyc` stantii fra mutante e ripristino).

**[B-8] T032-T033**

- [ ] **T032** `src/sbobina/study_blocks.py` puro (blocchi da ~`study_block_words`=1200 parole
  tagliati sulla pausa più lunga nell'ultimo 20% del blocco; testo `[S<i>] mm:ss testo`),
  `src/sbobina/prompts/studio-v1.md` (contesto, compito, formato, vincoli: citare copiando
  carattere per carattere, una voce senza appoggio nel testo non si scrive, lista vuota ammessa;
  esempi illustrativi variati come in `correzione-v1.md`), `src/sbobina/study_pipeline.py`:
  `generate_study(transcript, chat, options, on_progress) -> StudyResult` (per blocco: chat, parse,
  un retry su JSON invalido, validazione, assemblaggio in ordine di tempo, conteggio scarti,
  blocchi falliti). Settings: `study_block_words`, `study_num_predict`. Rischio: alto.
  verify: test con `chat` finto che restituisce JSON fisso: voci valide tenute, inventate scartate
  con motivo e conteggio; JSON rotto due volte → blocco in `failed_blocks` con i tempi; `chat` che
  solleva `CorrectorUnavailableError` → eccezione propagata, nessun file scritto; ogni blocco
  sotto il budget di parole; progresso chiamato una volta per blocco.
- [ ] **T033** `src/sbobina/study_render.py` (Markdown: capitoli, voci, citazione con `§N mm:ss` e
  testo; paragrafo da `group_paragraphs` con le `RenderOptions`), JSON I/O di
  `audio.studio.json` con rivalidazione al caricamento contro la trascrizione corrente
  (`stale_dropped`), sottocomando `sbobina studio <json> [--model]` in `cli.py` con log di
  avanzamento. Rischio: medio.
  verify: cambio di `paragraph_gap_s` → stesso timestamp, numero di paragrafo ricalcolato; parola
  citata modificata nella trascrizione → voce assente e `stale_dropped == 1`; test CLI con
  pipeline finta → due file scritti con scrittura atomica; Ollama giù → exit code diverso da 0 e
  file precedenti intatti.
- [ ] **T034** Misura reale e taratura (non delegabile: giudizio). `BUDGET: 5 iterazioni del
  prompt | ranking: voci non fedeli (meno) > voci scartate (meno) > copertura dei capitoli >
  durata`. Su 1-2 lezioni reali da ~85 min (`audio.corretto.json` esistenti in `data/`): durata,
  `prompt_eval_count` massimo (sotto 8192), voci tenute/scartate per motivo, 20 voci tenute
  estratte a caso e giudicate "fedele / non fedele" a mano. Ogni iterazione del prompt diventa
  `studio-v<N>.md` nuovo. Rischio: alto.
  verify: tabella dei tentativi (tenuti e scartati, `performance.md` § Registra) in
  `specs/study-library/eval.md`; riga `SPEDITO:` con la versione scelta; numeri riportati
  all'utente per la decisione Q7.
- [ ] **T035** Gate di fase. verify: suite, ruff, format, mypy; `wc -l` dei moduli nuovi ≤ 300.

## F5 - Materiali di studio nell'interfaccia (D5, seconda metà) (Q3)

**[B-9] T040-T042**

- [ ] **T040** Dividere `web/supervisor.py` (291 righe): `_spawn`, `_reap`, `_child_env` in
  `web/processes.py`. Nessun cambio di comportamento. Rischio: basso.
  verify: `tests/web/test_supervisor.py` e `test_stage_runner.py` verdi senza modifiche;
  `wc -l src/sbobina/web/supervisor.py` < 240.
- [ ] **T041** Coda di `WorkItem(job_id, action)`; `JobRecord.study: StudyRun | None`
  (`status: queued|running|done|failed|interrupted`, `error`, `updated_at`); `submit_study`;
  `_execute` per `study` aggiorna `JobRecord.study` lasciando `status` del job a `done`; recupero
  al boot: `study.running` → `interrupted`, `study.queued` rientra in coda in ordine; il `cancel`
  esistente annulla anche lo studio in corso. Rischio: alto (coda condivisa con la pipeline).
  verify: test col runner fittizio: pipeline A poi studio B → mai due figli insieme (registro dei
  `Popen` attivi); studio su job `done` → resta `done` e `study.status` `done`; riavvio simulato con
  studio `running` → `interrupted`; test esistenti della coda verdi.
- [ ] **T042** `stage_runner study <job_dir>`: carica la variante preferita, `generate_study`,
  scrive `audio.studio.json/.md` atomici, progresso per blocco in `progress.json`, exit code
  `OLLAMA_UNAVAILABLE_EXIT` se Ollama non risponde (riuso del codice esistente). Rischio: medio.
  verify: test del runner con pipeline finta (file scritti, progresso 0→1); Ollama giù → exit code
  mappato a `OLLAMA_UNAVAILABLE` dal supervisore; materiale precedente intatto.

**[B-10] T043-T044**

- [ ] **T043** `src/sbobina/web/api_study.py`: `POST /api/v1/jobs/<id>/study` → 202 (`queued`),
  409 se job `queued`/`running`, se lo studio è già in coda o se manca la trascrizione;
  `GET /api/v1/jobs/<id>/study` → materiale rivalidato con paragrafo, timestamp, href al lettore,
  `discarded`, `failed_blocks`, `stale_dropped`; 404 `STUDY_NOT_FOUND` se non generato. Lo stadio
  `study` compare negli eventi SSE esistenti. Rischio: medio.
  verify: test API per ogni codice; `stale_dropped` > 0 dopo un `PATCH` della trascrizione che
  tocca una parola citata.
- [ ] **T044** Pagina `/studio/<id>` (`templates/studio.html`, `static/js/studio.js`): avviso in
  alto (materiale generato, ogni voce con la sua fonte), capitoli, voci con citazione cliccabile
  → `/lettore/<id>?t=&variant=`, contatori scarti e voci non più verificabili, blocchi non
  elaborati con i tempi, pulsante "Genera"/"Rigenera" con avanzamento SSE e stati
  loading/empty/error; link "Materiali di studio" dal lettore e da `/corsi`. Rischio: medio.
  verify: click-through di ogni controllo (genera, citazione → lettore al tempo giusto, rigenera,
  stato Ollama non raggiungibile); `a11y-gate`; render 375/1280.
- [ ] **T045** Gate finale e run reale. verify: studio accodato dietro una trascrizione di una
  lezione reale, `nvidia-smi --query-compute-apps` campionato ogni 15 s → mai Whisper e Ollama
  insieme; materiale visibile, citazioni che aprono il lettore al punto giusto (5 controllate a
  orecchio); suite, ruff, format, mypy; `/analyze` su `specs/study-library/`.

# Piano: biblioteca di studio (corsi, ricerca, materiali) e CI

Versione 1.0 - 2026-10-02. Task in `specs/study-library/tasks.md`. Branch `main` (scelta dell'utente il 2026-10-02: commit atomici su main).

## Obiettivo

Le lezioni si raggruppano per corso e si cercano a testo pieno su tutto l'archivio: un risultato
apre il lettore nel punto esatto dell'audio (D4). Per ogni lezione il LLM locale genera capitoli,
riassunto, concetti chiave e possibili domande d'esame, e ogni voce mostrata allo studente porta una
citazione verificata automaticamente contro la trascrizione (D5). Ogni push e ogni PR passano da una
CI GitHub Actions con ruff, format, mypy e pytest, e i README mostrano lo stato reale della CI (D8).
Audio e testo non lasciano la macchina: la CI gira solo sul codice.

## Definition of Done

### D8 - CI (fase F1)

- [ ] `.github/workflows/ci.yml` gira su `push` (ogni branch) e `pull_request` verso `main` ed
      esegue, nell'ordine, `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`,
      `uv run mypy src tests`, `uv run pytest`. Un file non formattato fa fallire il job al passo
      format (verificato con un commit di prova su un branch usa e getta, poi rimosso).
- [ ] Sicurezza del workflow (`security.md` § Checklist Pre-Commit): `permissions: contents: read`
      a livello di workflow, `persist-credentials: false` sul checkout, ogni `uses:` pinnato a uno
      SHA di 40 caratteri con il tag in commento, SHA ricavati in implementazione da
      `gh api` sul tag ufficiale (mai scritti a memoria), nessun `pull_request_target`.
- [ ] Cache di uv attiva (`setup-uv` con `enable-cache` e chiave su `uv.lock`): il secondo run sullo
      stesso lock mostra "cache restored" nel log di setup.
- [ ] `README.md` e `README.it.md`: il badge statico `tests-478 passed` (oggi falso: la suite conta
      544 test) è sostituito dal badge del workflow
      `https://github.com/AndreaBonn/speech-to-text/actions/workflows/ci.yml/badge.svg?branch=main`
      con link alla pagina del workflow. Nient'altro cambia nei README.
- [ ] Il primo run su GitHub è verde. Lo verifica l'utente dopo il push (il push non fa parte
      dell'implementazione, R6); fino ad allora D8 è "implementato, non osservato su GitHub".

### D4 - Corsi e ricerca (fasi F2, F3)

Corsi (F2):
- [ ] Ogni lezione ha un corso effettivo: il campo `course` se impostato, altrimenti
      `config.subject`, altrimenti nessuno. Un `job.json` scritto prima di questa feature (senza
      `course`) si legge senza errori e la lezione con `subject="Diritto privato"` compare nel
      corso "Diritto privato".
- [ ] `PATCH /api/v1/jobs/<id>` con `{"course": "Diritto Privato "}` → 200 e corso `Diritto Privato`;
      `{"course": ""}` → lezione senza corso; 101 caratteri → 422 con `details[0].field ==
      "course"`; job `queued`/`running` → 409. `config.subject` resta invariato (è il valore
      passato al prompt di correzione quando il job è girato).
- [ ] `GET /api/v1/courses` → elenco paginato `{key, label, lecture_count, last_lecture_at}`;
      "diritto privato" e "Diritto  Privato" finiscono nello stesso corso (chiave normalizzata);
      le lezioni senza corso stanno in un gruppo "Senza corso". `GET /api/v1/jobs?course=<key>`
      filtra lo storico.
- [ ] Pagina `/corsi` (voce di nav "Corsi"): corsi con numero di lezioni, apertura di un corso →
      lezioni in ordine di data con link al lettore; il corso si cambia da lettore e storico con un
      campo che suggerisce i corsi esistenti.

Ricerca (F3):
- [ ] Given tre lezioni di "Diritto privato", una delle quali dice "la causa del contratto è
      illecita" a 00:41:12; When cerco `causa contratto`; Then il primo gruppo di risultati è quella
      lezione con uno snippet che evidenzia "causa" e "contratto" e il tempo `41:12`, e il clic
      apre `/lettore/<id>?t=2472.0&variant=<variante indicizzata>` con l'audio posizionato a
      41:12 (±1 s) e la parola evidenziata e visibile senza scroll manuale.
- [ ] Senza stemmer italiano la ricerca usa il prefisso della parola privata delle vocali finali
      (parole di almeno 5 lettere): `contratti` → `contratt*` trova "contratto", "contratti" e
      "contrattuale"; `perche` trova "perché" (diacritici ignorati: verificato su SQLite 3.45.1).
      Una frase fra virgolette (`"causa illecita"`) cerca la sequenza esatta, senza prefisso.
- [ ] Input ostile non rompe la query: `NEAR(a b)`, `"`, `-x`, `col:val`, `*` → 200 con risultati o
      lista vuota, mai 500; query vuota o fatta solo di segni → 422 `field: "q"`.
- [ ] Filtro per corso: `GET /api/v1/search?q=causa&course=<key>` restituisce solo lezioni di quel
      corso; paginazione con `meta.page/per_page/total/total_pages`.
- [ ] Allineamento (R1), osservato senza riavviare il server: dopo una correzione manuale nel
      lettore la parola nuova si trova e la vecchia no; a fine correzione LLM i risultati puntano al
      testo corretto; dopo la cancellazione di un job nessun risultato lo cita; cancellando a mano
      `data/search.sqlite3` la ricerca successiva ricostruisce l'indice e risponde.
- [ ] Snippet servito come parti `{text, match}` e montato con `textContent`: una trascrizione che
      contiene `<script>` non esegue nulla nella pagina dei risultati.
- [ ] SQLite senza FTS5 (simulato nel test) → `/api/v1/search` risponde 503 `SEARCH_UNAVAILABLE` e
      la pagina lo dice; corsi, lettore e trascrizione funzionano.

### D5 - Materiali di studio (fasi F4, F5)

- [ ] `uv run sbobina studio <audio.corretto.json>` (o `audio.json`) scrive `audio.studio.json` e
      `audio.studio.md` accanto alla trascrizione: capitoli con titolo e tempo d'inizio; per
      capitolo riassunto (frasi), concetti chiave (termine + spiegazione), possibili domande d'esame.
- [ ] Ogni voce mostrata ha almeno una citazione `{paragrafo, timestamp, testo citato}`. La
      citazione è valida solo se: il passaggio indicato esiste ed era nel blocco dato al modello;
      il testo citato (3-40 parole, normalizzato per maiuscole, punteggiatura e spazi) compare come
      sequenza contigua di parole in quel passaggio o in quello successivo dello stesso blocco.
      Una voce con anche una sola citazione non valida è scartata (regola stretta); un concetto il
      cui termine non compare in nessuna delle sue citazioni è scartato.
- [ ] Esempio (test): il blocco contiene il passaggio 12 "la causa del contratto è illecita
      quando contrasta con norme imperative"; voce con citazione `{passaggio: 12, testo: "causa
      del contratto è illecita"}` → tenuta, timestamp = inizio della parola "causa"; stessa voce con
      `testo: "il contratto è nullo"` → scartata con motivo `QUOTE_NOT_FOUND`; con `passaggio: 99`
      → `PASSAGE_NOT_IN_BLOCK`.
- [ ] Le voci scartate non arrivano mai allo studente; `audio.studio.json` ne registra numero e
      motivi per l'eval. La pagina mostra "N voci scartate perché la citazione non è stata trovata".
- [ ] Paragrafo e timestamp mostrati sono calcolati al momento della visualizzazione dalla
      trascrizione corrente (indice di parola → paragrafo con le `RenderOptions` attuali): cambiare
      `paragraph_gap_s` non rende sbagliata una citazione.
- [ ] Dopo una correzione manuale della trascrizione le citazioni si rivalidano: quelle che non si
      trovano più spariscono e la pagina dice "materiale generato su una versione precedente, N voci
      non più verificabili: rigenera".
- [ ] Web: `POST /api/v1/jobs/<id>/study` → 202 e la generazione entra nella stessa coda FIFO di
      trascrizione e correzione (R4: mai Whisper e Ollama insieme, osservato con `nvidia-smi`
      durante un run reale accodato dietro una trascrizione); job senza trascrizione → 409,
      job `queued`/`running` → 409. Avanzamento per blocchi via SSE; Ollama non raggiungibile →
      stato `failed` con `OLLAMA_UNAVAILABLE` e il materiale precedente, se c'era, resta.
- [ ] Pagina `/studio/<id>`: ogni citazione è un link al lettore al suo timestamp; un blocco che il
      modello non ha elaborato (JSON invalido dopo un retry) appare come "parte non elaborata
      mm:ss-mm:ss", mai come silenzio.
- [ ] Misura su almeno una lezione reale da ~85 min (T034): durata, voci generate e scartate per
      motivo, revisione a mano di 20 voci tenute scelte a caso con l'esito "fedele / non fedele"
      registrato. Il numero di voci non fedeli è riportato all'utente: la validazione dimostra che la
      citazione esiste, non che la frase la rappresenti fedelmente (Q7).

### Trasversali

- [ ] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src tests`
      verdi in locale e in CI; nessun file Python nuovo o modificato oltre 300 righe (oggi
      `web/supervisor.py` è a 291: si divide prima di aggiungere, T040), nessuna funzione oltre 30.
- [ ] Fasi UI (F2, F3, F5): riga `DIAL:` derivata da `design.md`, `a11y-gate` verde, render osservato
      a 375 e 1280 px, click-through registrato di ogni controllo nuovo.
- [ ] `CLAUDE.md` del progetto aggiornato su layout e confine Ollama (autorizzato: cambia la
      struttura). README e `docs/` toccati solo per il badge.
- [ ] (Security review S1, S2) Ogni testo non scritto dal codice (output LLM di D5: titoli,
      riassunti, concetti, domande, citazioni; nome del corso; snippet) è montato con `textContent`
      o nodi di testo, mai `innerHTML` o concatenazione HTML, e passa dall'autoescape Jinja lato
      server. Test avversariale: trascrizione e risposta LLM finta con `<script>` e
      `<img onerror>` dentro una citazione valida → nessuna esecuzione in `/studio/<id>` e `/corsi`.

## Assunzioni

- Stack invariato: Python 3.12, uv, FastAPI/Jinja, JS vanilla senza npm, `sqlite3` della libreria
  standard. **Nessuna dipendenza nuova** (FTS5 è nella SQLite del runtime: BASIS measured qui,
  3.45.1, query con prefisso e `remove_diacritics 2` provata).
- FTS5 su Windows e macOS: presente nelle build Python di python.org e di uv (BASIS: inferred,
  UNVERIFIED). Per questo l'assenza di FTS5 è un caso gestito (503 e resto dell'app funzionante),
  e la checklist `docs/checklist-windows-macos.md` riceve una riga in più solo con OK dell'utente.
- Volumi: decine o poche centinaia di lezioni da 60-90 min (~9000 parole, ~1000 segmenti Whisper
  ciascuna). Ordine di grandezza dell'indice: 10^5 righe. BASIS: inferred; T026 misura
  ricostruzione e latenza su `data/` reale.
- Utente unico per istanza (come in web-ui): concorrenza = più tab, nessun multiutente.
- Lingua: tutto italiano, nessuno stemmer; la ricerca per prefisso è il compromesso dichiarato.
- Il modello di D5 è quello della correzione (`settings.ollama_model`, oggi `qwen3.5:9b`) con
  `num_ctx` 8192. Una lezione intera non entra: si procede per blocchi (map senza reduce, Q6).
  Durata stimata 10-20 min per 85 min di audio (BASIS: inferred dal costo della correzione,
  ~38 min per 45 blocchi da 200 parole con output corto); T034 misura.
- Nessun materiale generato è "verità": la pagina studio lo dichiara una volta, in alto, e ogni
  voce porta la sua citazione cliccabile, così lo studente controlla la fonte in un clic.
- Il repository ha un remote pubblico (`origin` = github.com/AndreaBonn/speech-to-text, BASIS:
  measured con `gh repo view`): il badge è visibile a chiunque. Push e merge li fa l'utente.
- I test girano senza GPU, senza Ollama e senza modelli scaricati: BASIS measured il 2026-10-02 con
  `env -i`, `HOME` vuota, `CUDA_VISIBLE_DEVICES=""`, `OLLAMA_HOST` su una porta morta,
  `HF_HUB_OFFLINE=1` → 544 passed in 7,6 s. Il runner GitHub parte da un'installazione pulita, e
  quella resta UNVERIFIED fino al primo run (R5).
- Anchor rivedibile, non vincolo: `config.subject` come unica nozione di corso. Il piano la
  affianca con un campo nuovo (Q1) invece di renderla modificabile, ma è una scelta, non un obbligo.

## Decisioni (ADR architect integrati il 2026-10-02)

Gli approcci sono elencati prima, valutati dopo.

### Q1 - Modello del corso [BLOCCANTE per F2, ADR]

Approcci: (A) `config.subject` diventa modificabile; (B) campo nuovo `JobRecord.course: str | None`,
corso effettivo = `course or config.subject`; (C) registro corsi separato `data/courses.json` con id,
lezioni che referenziano `course_id`.

- A: zero campi nuovi, ma `config` smette di essere la fotografia di come il job è girato: il
  subject passato al prompt di correzione non è più ricostruibile.
- B: compatibile all'indietro senza migrazione (default `None`, pydantic ignora il campo assente);
  `config` resta storico; rinominare un corso = aggiornare N `job.json` (operazione rara, N piccolo).
- C: abilita metadati per corso (docente, anno), ma due fonti da tenere coerenti e una migrazione dei
  job esistenti. Nessuna richiesta oggi giustifica metadati per corso (YAGNI).
- (D, ADR architect A1-c) `data/jobs/<id>/meta.json` scritto solo dall'utente, `job.json` solo dal
  supervisor: proprietario unico per file, nessun lock. Fallback `config.subject` se il file manca.
- **Decisione: D** (sostituisce il default B del planner). Motivo: il supervisor aggiorna `job.json`
  da una copia in memoria (`supervisor.py:206`, `:291`); con B una PATCH del corso concorrente a un
  aggiornamento del supervisor (job in corso, o stato `study` scritto su un job `done` per Q3-B)
  viene sovrascritta. B richiederebbe 409 sui job occupati e non coprirebbe lo stato `study`.
  Passaggio a C (registro corsi) quando arriva il glossario per corso (roadmap fase 2).
  Chiave di raggruppamento = NFKC + spazi compressi + casefold; etichetta mostrata = la grafia della
  lezione più recente.

### Q2 - Indice di ricerca: derivato o fonte di verità [BLOCCANTE per F3, ADR]

Approcci: (A) SQLite derivato e ricostruibile, allineato da hook nei punti di scrittura (edit
manuale, fine stadio correzione, delete); (B) SQLite derivato, allineato per **riconciliazione a
ogni ricerca** confrontando `(mtime_ns, size)` dei file trascrizione con quelli registrati; (C)
SQLite fonte di verità delle trascrizioni, file come export.

- A: aggiornamento immediato, ma ogni nuovo punto di scrittura (CLI, processo figlio, file toccato
  a mano) è un drift potenziale: R1 resta aperto per costruzione.
- B: un solo meccanismo copre tutti i punti di scrittura presenti e futuri, compresi quelli fuori
  dal server; costo per ricerca = 1 `stat` per lezione (centinaia di `stat`, ordine dei ms, BASIS:
  inferred, misurato in T026) più la reindicizzazione delle sole lezioni cambiate.
- C: riscrittura di storage, export, CLI e lettore; nessun guadagno per un utente unico.
- **Default: B**, più riconciliazione al boot. File in `data/search.sqlite3`; `PRAGMA user_version`
  diverso dallo schema atteso o database corrotto → file eliminato e ricostruito (WARNING nel log).

### Q3 - D5 nella coda: stadio o lavoro separato [BLOCCANTE per F5, ADR]

Approcci: (A) terzo stadio della pipeline (`config.study`) dopo la correzione; (B) la coda FIFO
accetta voci `(job_id, action)` con `action ∈ {pipeline, study}`, e lo studio su un job già `done`
gira come azione a sé con stato proprio `JobRecord.study`; (C) coda separata per lo studio.

- A: semplice per i job nuovi, ma lo studente genera i materiali **dopo** aver rivisto la
  trascrizione (correzioni manuali): servirebbe ri-accodare un job `done`, cambiandone lo stato
  nello storico.
- B: la generazione si chiede quando si vuole, rigenerabile, lo stato del job resta `done`;
  stessa coda = stessa garanzia GPU (R4). Costo: la coda passa da id a voci tipizzate e il recupero
  al boot copre anche `study`.
- C: due consumatori GPU in parallelo, viola R4. Scartato.
- **Default: B.** Generazione automatica a fine pipeline: fuori da v1 (Q9).

### Q4 - Granularità delle righe dell'indice

(A) un segmento Whisper per riga; (B) un paragrafo per riga; (C) finestre scorrevoli di segmenti.
A ha timestamp precisi e confini indipendenti dalle `RenderOptions`; B dipende dalle impostazioni
(citazioni e risultati si spostano se cambiano) e dà timestamp grossolani; C trova frasi a cavallo
di due segmenti al prezzo di risultati doppi. **Default: A**; limite dichiarato: una frase esatta
spezzata fra due segmenti non si trova (i termini sciolti sì).

### Q5 - Quale testo si indicizza e si usa per D5

Corretto (`audio.corretto.json`) se esiste, altrimenti originale. Il risultato porta la variante
nel link, così il lettore apre lo stesso testo in cui la parola è stata trovata. **Default** senza
alternative architetturali.

### Q6 - Capitoli: map senza reduce

(A) un passo per blocco (~1200 parole, tagliato sulla pausa più lunga vicina al limite) che
propone 1-3 capitoli con le loro voci; (B) A più un passo di riduzione LLM che fonde capitoli
adiacenti dello stesso argomento. **Default: A**: il reduce è un'altra fonte di allucinazione
(titoli inventati su voci che non ha visto) e non è chiesto. Rivalutare dopo T034 se i capitoli
spezzati ai confini di blocco disturbano.

### Q7 - Fedeltà semantica [DECISA 2026-10-02: O1/A, scelta dell'utente]

La validazione automatica richiesta dimostra che **la citazione esiste nel testo**, non che la frase
del riassunto ne segua. Opzioni: (A) v1 con validazione di esistenza + citazione visibile accanto a
ogni voce + misura a mano in T034; (B) aggiungere un secondo passaggio LLM che giudica se la
citazione sostiene la voce (stesso modello da 9B che giudica sé stesso, raddoppia i tempi, va
validato a sua volta). **Default: A**, decisione su B dopo i numeri di T034. Va confermato
dall'utente perché la sua condizione ("un'allucinazione diventa un errore all'esame") è coperta solo
in parte da qualunque validazione automatica.

### Q8 - Perimetro della CI

(A) solo `ubuntu-latest` con i quattro controlli richiesti; (B) matrice ubuntu/windows/macos con
smoke test di avvio (è il T075 aperto di `specs/web-ui/tasks.md`). **Default: A** (perimetro di D8);
B resta T075, attivabile dopo che A è verde.

### Q9 - Generazione automatica dei materiali a fine job

**Default: no in v1**, solo su richiesta (Q3). Un flag `config.study` si aggiunge se l'utente lo
chiede.

## Architettura (Q1-D, Q2-B, Q3-B)

```
browser ──> FastAPI
             pages: /corsi, /studio/<id>, /lettore/<id>?t=&variant=
             api_courses   GET /courses, PATCH /jobs/<id>/meta {course}
             api_search    GET /search ──> search_service.reconcile() ──> SearchIndex (sqlite FTS5)
             api_study     POST|GET /jobs/<id>/study
           Supervisor (FIFO di WorkItem(job_id, action)) ── Popen ──> stage_runner transcribe|correct|study
                                                                          └─ study_pipeline ──> ollama_chat
```

| File | Tipo | Scopo |
|---|---|---|
| `.github/workflows/ci.yml` | nuovo | CI D8 |
| `README.md`, `README.it.md` | modifica | solo la riga del badge |
| `src/sbobina/courses.py` | nuovo | puro: `normalize_course_label`, `course_key`, `effective_course`, aggregazione corsi |
| `src/sbobina/web/job_models.py` | modifica | `LectureMeta`, `JobRecord.study: StudyRun | None`, `StudyStatus` |
| `src/sbobina/web/job_store.py` | modifica | `read_meta`/`write_meta` su `meta.json`, filtro per corso in `list` |
| `src/sbobina/web/api_courses.py` | nuovo | `GET /api/v1/courses`, `PATCH /api/v1/jobs/<id>` |
| `src/sbobina/search_text.py` | nuovo | puro: righe da indicizzare (segmenti), costruzione sicura della query FTS5, parti dello snippet |
| `src/sbobina/web/search_index.py` | nuovo | unico confine sqlite: schema, `user_version`, upsert, delete, query, disponibilità FTS5 |
| `src/sbobina/web/search_service.py` | nuovo | riconciliazione `(mtime_ns, size)` fra `data/jobs` e indice, lock |
| `src/sbobina/web/api_search.py` | nuovo | `GET /api/v1/search` |
| `src/sbobina/ollama_chat.py` | nuovo | unico confine Ollama estratto da `llm_corrector.py`: client, errori, fence, schema |
| `src/sbobina/llm_corrector.py` | modifica | usa `ollama_chat` (comportamento invariato) |
| `src/sbobina/study_models.py` | nuovo | dataclass del dominio studio + schema della risposta LLM + JSON I/O |
| `src/sbobina/study_citations.py` | nuovo | puro: normalizzazione, validazione citazioni, motivi di scarto, rivalidazione |
| `src/sbobina/study_blocks.py` | nuovo | puro: blocchi di segmenti tagliati sulle pause, testo numerato per il prompt |
| `src/sbobina/study_pipeline.py` | nuovo | orchestrazione map per blocco, retry, assemblaggio, progresso |
| `src/sbobina/study_render.py` | nuovo | puro: `audio.studio.md`, paragrafo/timestamp dalle `RenderOptions` |
| `src/sbobina/prompts/studio-v1.md` | nuovo | prompt versionato |
| `src/sbobina/cli.py` | modifica | sottocomando `studio` |
| `src/sbobina/web/processes.py` | nuovo | `_spawn`, `_reap`, `_child_env` estratti da `supervisor.py` |
| `src/sbobina/web/supervisor.py` | modifica | coda di `WorkItem`, azione `study`, recupero al boot |
| `src/sbobina/web/stage_runner.py` | modifica | stadio `study` |
| `src/sbobina/web/api_study.py` | nuovo | `POST/GET /api/v1/jobs/<id>/study` |
| `src/sbobina/web/pages.py` | modifica | `/corsi`, `/studio/<id>`, voce nav "Corsi" |
| `src/sbobina/web/templates/{corsi,studio}.html` | nuovo | UI |
| `src/sbobina/web/static/js/{corsi,search,studio,reader-link,course-field}.js` | nuovo | UI; `reader.js` (502 righe) e `jobs.js` (602) non crescono |
| `tests/...` | nuovo | mirror di ogni modulo |

## Decisioni di dettaglio

### Ricerca
- Schema: `lectures(job_id PK, variant, path_mtime_ns, path_size, indexed_at)` e
  `passages USING fts5(text, job_id UNINDEXED, segment_index UNINDEXED, start UNINDEXED,
  tokenize="unicode61 remove_diacritics 2", prefix='3')`. Il corso **non** sta nell'indice: il
  filtro per corso passa l'insieme di `job_id` del corso dallo store (`job_id IN (...)` con
  parametri bindati), così cambiare corso non tocca l'indice.
- Query: l'input non arriva mai a `MATCH` com'è. Si estraggono parole (`\w+` Unicode) e frasi fra
  virgolette; ogni parola ≥ 2 caratteri diventa `"parola"*`, e da 5 lettere in su perde prima le
  vocali finali (`contratti` → `"contratt"*`: stemming minimo, qualità BASIS: inferred, da rivedere
  su query reali in T026); ogni frase resta `"a b c"`; massimo 10
  termini, AND implicito; virgolette interne raddoppiate. Ranking `bm25`; snippet con
  `highlight()` su marcatori nella Private Use Area convertiti in parti `{text, match}`.
- Risultati raggruppati per lezione (max 3 passaggi per lezione nella pagina), href con `t` =
  inizio del segmento.
- Concorrenza: una connessione per richiesta, `threading.Lock` intorno a riconciliazione e query
  (endpoint `def`, girano nel threadpool). Scritture atomiche dei file (`os.replace`) → la
  riconciliazione vede il file vecchio o il nuovo, mai metà.

### Materiali di studio
- Prompt (versionato `studio-v1.md`): blocco come righe `[S<indice>] mm:ss testo`. Risposta JSON
  `{capitoli: [{titolo, inizio, riassunto: [{testo, citazioni}], concetti: [{termine, spiegazione,
  citazioni}], domande: [{domanda, citazioni}]}]}`, `citazioni: [{passaggio: "S12", testo}]`.
- Parametri: `format=<schema>`, `think=False`, `temperature 0`, `num_ctx 8192`, `num_predict`
  2048 (tetto all'output: blocco ~2400 token + prompt ~800 + output 2048 < 8192, BASIS: inferred,
  T034 legge `prompt_eval_count` dalle risposte). JSON invalido → un retry, poi blocco registrato
  come non elaborato.
- Salvataggio: `audio.studio.json` con `{source_variant, source_revision, model, prompt_version,
  generated_at, chapters, discarded: [{reason, count}], failed_blocks: [{start, end}]}`; le
  citazioni salvano `{segment_index, quote}`, mai indici di parola (si rivalidano a ogni lettura
  contro la trascrizione corrente). Scrittura atomica: un run fallito non tocca il materiale precedente.
  Validazione (ADR A4-a): funzione pura, match esatto su token normalizzati (NFKC, casefold,
  apostrofi unificati, punteggiatura tolta) nel segmento citato con tolleranza di un segmento
  adiacente; scarti con i reason code del DoD D5 (`QUOTE_NOT_FOUND`, `PASSAGE_NOT_IN_BLOCK`, ...),
  lunghezza 3-40 parole. Mai fuzzy: difflib lascerebbe passare parafrasi.
- Paragrafo mostrato = indice del paragrafo di `group_paragraphs` che contiene la prima parola
  citata, con le `RenderOptions` del job al momento della lettura.

### CI
- Job unico `check` su `ubuntu-24.04`, `timeout-minutes: 15`, `concurrency` per ref con
  `cancel-in-progress`. Python da `.python-version` via `uv python install`; `uv sync --locked`
  (fallisce se `uv.lock` non è allineato a `pyproject.toml`: è il punto).
- Nessun extra `cuda`: le wheel NVIDIA non servono ai test (BASIS: measured, suite verde senza GPU).

## Stima

| Fase | Contenuto | Range |
|---|---|---|
| F1 | CI + badge | 0,5-1 g |
| F2 | Corsi | 2-3 g |
| F3 | Ricerca + deep link | 3-4,5 g |
| F4 | Motore studio + CLI + misura reale | 3,5-5,5 g |
| F5 | Studio nel web (coda, API, pagina) | 3-4,5 g |
| | Totale | 12-18,5 g |
| | Buffer imprevisti +20% | **14,5-22 g** |

Promossi di un livello: il primo indice FTS del progetto (T021) e la validazione delle citazioni
(T031, dove sta il rischio di prodotto). F4 ha il range più largo: la taratura del prompt non si
stima, si limita con un budget (T034).

## Rischi e mitigazioni

- **R1 drift indice/file**: poiché le trascrizioni si scrivono da 4 punti (stadio transcribe,
  stadio correct, edit manuale, CLI), un hook dimenticato lascerebbe risultati che puntano a testo
  che non c'è più → riconciliazione a ogni ricerca (Q2-B) e test che scrivono il file **senza**
  passare dal server e verificano il risultato.
- **R2 backward compat del corso**: `job.json` vecchi senza `course` → campo con default, test con
  un `job.json` reale di oggi copiato in fixture; nessuna migrazione dei file.
- **R3 allucinazioni D5**: poiché il modello da 9B parafrasa e inventa, una voce può citare un
  passaggio vero e dire altro → validazione stretta (scarto della voce intera), termine del concetto
  ancorato alla citazione, citazione visibile accanto a ogni voce, misura a mano in T034, Q7 aperta.
  Effetto se sottostimato: F4 +2 g di taratura del prompt.
- **R4 contesa GPU**: lo studio passa dalla stessa coda FIFO; prima di ogni `transcribe` si
  scaricano già i modelli Ollama (`gpu_release`); verifica con `nvidia-smi` in T045.
- **R5 CI rossa al primo run**: misurata in locale una suite verde senza GPU, Ollama e cache HF;
  restano ignoti l'installazione pulita di `ctranslate2`/`av` sul runner e la risoluzione di
  `--locked` → T002 simula l'ambiente in locale prima del push; se il runner fallisce, la causa si
  legge dal log del run (debugging.md), non si mette `continue-on-error`.
- **R6 badge vuoto prima del push**: il badge mostra "no status" finché non esiste un run su
  `main` → dichiarato all'utente; il merge su `main` lo fa lui.
- **R7 file oltre soglia**: `supervisor.py` a 291 righe, `reader.js` 502, `jobs.js` 602 → T040
  divide il supervisore prima di estenderlo; la logica nuova del lettore va in `reader-link.js`.
- **R8 FTS5 assente su un fallback OS**: gestito come stato 503 con app funzionante (DoD).
- **R9 tempi D5 su CPU** (colleghi senza GPU): qwen 9B su CPU è lento; la pagina mostra la stima
  dalla velocità misurata del run (come la correzione), nessun numero inventato.

## Criteri di verifica

Per fase: i `verify:` di `tasks.md`. A fine piano: suite, ruff, format, mypy verdi in locale; run
GitHub verde dopo il push dell'utente; scenario manuale "dove ha spiegato X?" su `data/` reale
(T026); run reale D5 con `nvidia-smi` campionato (T045); `/analyze` su `specs/study-library/`.

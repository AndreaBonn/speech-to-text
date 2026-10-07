# Piano: recupero semantico con embedding densi, BM25 di riserva (O1)

Versione 1.1 - 2026-10-07. Task in `specs/004-hybrid-retrieval/tasks.md`. Misure in
`specs/004-hybrid-retrieval/eval.md`, fonte unica dei numeri: questo piano li cita, non li
ricalcola. Branch `main`, commit atomici (scelta dell'utente del 2026-10-02, assunta invariata).

**Changelog v1.0 → v1.1 (2026-10-07).** Le misure di F1 (eval.md § Candidati, § Scelta) hanno
cambiato la forma del prodotto: modello `qwen3-embedding:8b`, embedding della domanda su CPU con
istruzione Qwen, ricerca **solo densa**, BM25 come percorso di riserva. Le fusioni con BM25 (RRF a
4 liste e pesata 2:1) perdono su ogni misura e sono uscite dal piano: rimossi T027 (fusione
ibrida), Dis.3 superata, T016 ridotto alla sola soglia. Aggiunti T009 (harness entro i limiti e
metrica dei giudizi nel repo), T033 (throughput reale di indicizzazione e convivenza CPU/GPU dello
stesso modello), T034 (scelta del percorso denso o BM25), T045 (indicizzazione a fette,
condizionale). Gate L sostituito da un tetto di regressione (p95 ≤ 2,5 s), perché l'utente ha
accettato 2,05 s. Nuovi rischi R11-R14, stima residua 12,5-18 g.

La decisione di prodotto è dell'utente e non si riapre. In v1.0 era "BM25 e denso nella stessa
RRF"; le misure l'hanno superata e l'utente ha scelto (eval.md § Scelta, decisioni D1a e D2a):
il recupero di chat e generazioni usa il solo ranking denso; BM25 resta quando il modello manca,
quando l'indice non copre il corso o quando Ollama non risponde, e lo stato dice quale percorso ha
servito la richiesta. Niente reranker, niente routing per tipo di domanda, niente LLM che sceglie
lo strumento. Il modello di embedding lo installa l'utente con `ollama pull`: il codice non lo
scarica mai.

Questa decisione supera `specs/001-course-workspace/adr.md` § D2 ("BM25 resta, nessun
embedding"): quel gold set misurava solo domande con una parola chiave presente nel passaggio
(R1). Sul gold di F1 (82 domande con risposta) il denso 8b ha recall@8 1,00 e MRR@10 0,908
contro 0,56 e 0,445 di BM25, e pareggia anche sulle 12 domande `exact` (eval.md § Scelta).

## Fatti verificati in Research

| Fatto | Fonte | BASIS |
| --- | --- | --- |
| Ollama 0.18.0; `/api/embed` accetta `input` stringa o lista, `truncate`, `options`, `keep_alive`, `dimensions`; vettori L2-normalizzati | eval.md § Verifiche su Ollama | measured |
| `truncate=false` oltre il contesto → 400 "the input length exceeds the context length"; `truncate` di default → 200 e troncamento silenzioso (`prompt_eval_count` 2047 con `num_ctx` 2048) | eval.md § Verifiche su Ollama | measured |
| Template di qwen3-embedding `{{ .Prompt }}`: l'istruzione `Instruct: ...\nQuery:` la mette il codice | eval.md § Verifiche; `ollama show --modelfile qwen3-embedding:8b` | measured |
| `options.num_gpu=0` rispettato da `/api/embed`: `size_vram` 0, e con la GPU libera `qwen3.5:9b` resta in VRAM con `size_vram` invariata dopo 20 query | eval.md § Verifiche (ripetuta il 2026-10-07) | measured |
| Coseno fra vettore GPU e CPU dello stesso testo 0,999572 | eval.md § Verifiche | measured |
| `generate(keep_alive=0)` scarica un modello di embedding (200, `done_reason: unload`) | eval.md § Verifiche | measured |
| `qwen3-embedding:8b` installato: 4,7 GB, Q4_K_M, 7,6B parametri, **embedding length 4096**, **context length 40960**, nessun `PARAMETER num_ctx` nel modelfile (quindi vale il `num_ctx` di default di Ollama, 2048 in T010) | `ollama show qwen3-embedding:8b`, `ollama show --parameters` (2026-10-07) | measured. Corregge il "32768" del brief: il valore del GGUF è 40960; per la politica di troncamento conta il `num_ctx` effettivo, non il massimo del modello |
| Corpus di misura con 8b: 548 vettori distinti per hash (552 unità) da 4096 float32, cache da 9,1 MB; 0 unità oltre il contesto nei run `q8b` e `x8b` | `data/eval/retrieval-hybrid/cache/qwen3-embedding_8b.npz`; `grep -c "truncated over-context" out/q8b.log out/x8b.log` = 0 | measured |
| Indicizzazione del corpus di misura con 8b su GPU: 3156 s, cioè ~5,8 s per unità (~0,17 unità/s). Condizioni del run (9B residente o no, layer su GPU) non registrate | eval.md § Candidati | measured il tempo; le condizioni sono unknown (T033) |
| Query 8b su CPU con 9B residente: p95 2,046 s; percorso GPU 10-20 s per domanda (scarica e ricarica il 9B) | eval.md § Candidati | measured |
| La configurazione misurata come "denso" sono **due** liste dense (documenti, finestre di lezione) unite da `fuse_by_rank` con punteggio `-cosine`, senza soglia; le finestre di lezione sono le partizioni da ~250 parole di `partition_lecture_segments` | `scripts/eval_hybrid.py` (`dense_branch`, `rank_question`), `src/sbobina/hybrid_eval.py` (`build_lecture_units`, `dense_scores`) | measured |
| `fuse_by_rank` spostato in `src/sbobina/rank_fusion.py` (non committato), ordina in modo crescente | `git status`, `src/sbobina/rank_fusion.py:15` | measured |
| La metrica dei giudizi (voto 2 oppure riferimento del gold) vive solo in `scratchpad/judged_metrics.py`, cioè nella scratchpad di una sessione, fuori dal repo | eval.md § Giudizi alla cieca; `find` | measured |
| Righe: `scripts/eval_hybrid.py` 651 (oltre il limite di 300), `src/sbobina/hybrid_eval.py` 283 e in modifica al momento della stesura, `retrieval.py` 275, `supervisor.py` 299, `generation_runner.py` 298, `course_retrieval.py` 208, `cli.py` 235, `gpu_release.py` 19 | `wc -l` (2026-10-07 14:37) | measured |
| La chat recupera **fuori** dalla lease GPU, che copre la sola chiamata a Ollama | `src/sbobina/web/chat_turn.py:1-5` | measured |
| T017: `data/eval/retrieval-hybrid/spot-check-T017.md` preparato, caselle "Accordo" ancora vuote | lettura del file | measured |
| Disco: 25 GB liberi su 350 (93%); RAM 38 GB, 16 core | `df -h` (2026-10-07), v1.0 | measured |

Dimensioni dell'indice vettoriale a 4096 dimensioni float32: 16 KB per unità. Un corso da
semestre ≈ 2.500-3.000 unità (stima v1.0, BASIS inferred) = 40-50 MB; tutta l'installazione
10-20k unità = 160-330 MB, il doppio per il tempo di un cambio di modello (vecchia e nuova
`model_key` convivono finché il nuovo indice non è completo). Ricerca a forza bruta in numpy:
3.000 × 4096 sta sotto i 10 ms, nessun indice ANN.

## Obiettivo

Chat e generazioni di un corso recuperano i passaggi per similarità semantica con
`qwen3-embedding:8b`, così una domanda parafrasata o in italiano su materiale in inglese trova il
passaggio giusto anche senza parole in comune. Se il modello manca, se Ollama non risponde o se
l'indice non copre il corso, il recupero torna al BM25 di oggi e lo dice (log, risposta della
chat, pagina del corso, Impostazioni), mai in silenzio. Gli embedding restano locali con
qualunque motore LLM.

## Ordine delle fasi e perché

F1 gold set e scelta del modello (quasi chiusa) → F2 ricerca densa nel codice di produzione,
indice da CLI → F3 indicizzazione automatica in coda → F4 stato e scelta del modello nelle
Impostazioni.

- **F1** resta utile da sola: gold set a 93 domande, harness, metrica dei giudizi e baseline sono
  il test di regressione di ogni futuro ritocco al recupero. Residuo: harness entro i limiti e
  metrica nel repo (T009), soglia del denso (T016), controllo a campione dell'utente (T017), gate.
- **F2** porta la ricerca densa in chat e generazioni con l'indice costruito da CLI. Dopo F2 il
  sistema è usabile: corso indicizzato = ricerca densa, corso non indicizzato o parziale = BM25
  con motivo esplicito. I vettori sono per hash del testo, quindi un passaggio modificato perde il
  proprio vettore invece di tenerne uno vecchio.
- **F3** tiene l'indice fresco senza intervento: azione `embed` in coda con lease GPU,
  accodamento dopo trascrizione, estrazione, OCR e modifica manuale, backfill. Fino a F3 un
  contenuto nuovo porta il corso a BM25 (Dis.8) finché non si lancia il comando: è un degrado
  dichiarato, non una perdita.
- **F4** espone stato, copertura e scelta del modello. Prima di F4 lo stato è già in API e nei
  log (F2).

## Definition of Done

### C1 - Gold set, harness e scelta misurata (fase F1)

Chiusi, con rimando a `eval.md`: corpus di misura (§ Corpus), gold set a 93 domande con 12
`exact` aggiunte in § Scelta (§ Gold set), giudizi per pooling alla cieca (§ Giudizi alla cieca,
§ Candidati, § Scelta), baseline BM25 (§ Baseline BM25), misura dei 5 candidati e del percorso
query su GPU (§ Candidati), regola di scelta scritta prima delle misure (§ Regola di scelta),
decisione con `SPEDITO:` (§ Scelta).

Aperti:

- [ ] Harness entro i limiti del repo: nessun file oltre 300 righe (`scripts/eval_hybrid.py` è a
      651), la metrica "rilevante = voto 2 oppure riferimento del gold" in
      `src/sbobina/retrieval_metrics.py` con test, nessun file di misura che viva solo in una
      scratchpad.
      - Given la cache `qwen3-embedding_8b.npz` e i voti di `judging/verdicts-*.json`; When si
        lancia `scripts/eval_hybrid.py --system dense --model qwen3-embedding:8b` con la metrica
        dei giudizi; Then stampa recall@8 1,00 e MRR@10 0,908 sulle 82 domande con risposta, gli
        stessi numeri di eval.md § Scelta.
- [ ] Soglia di coseno per `qwen3-embedding:8b` (Dis.4 B), dalle liste top-50 già salvate
      (`out/x8b-dense.json`): la più alta che tiene la recall@8 sulle 82 domande con risposta
      entro 1 domanda da "nessuna soglia", minimizzando i passaggi sopra soglia per le 11
      `negative`. Registrata in eval.md § Varianti e § Scelta.
- [ ] Controllo a campione dell'utente su 15 domande: accordo ≥ 13/15, altrimenti rigiudizio.

### C2 - Ricerca densa in produzione, indice da CLI (fase F2)

- [ ] Configurazione: `Settings.semantic_search: bool = True`, `Settings.embedding_model: str =
      "qwen3-embedding:8b"`. Modello, digest (da `/api/tags`), dimensioni (da `/api/show`,
      4096 per l'8b), `num_ctx` e `EMBEDDING_PROMPT_VERSION` formano la `model_key`. Nessun
      `os.getenv` nuovo.
- [ ] Confine Ollama `src/sbobina/ollama_embed.py`, unico punto che chiama `/api/embed`. Batch da
      32. Documenti su GPU con `num_ctx` 2048 esplicito (la configurazione misurata, che non
      dipende dal default di Ollama). Query con `options.num_gpu=0`, stesso `num_ctx`,
      `keep_alive` "30m". Mai `pull`. Errori → `EmbeddingUnavailableError` con `reason:
      model_missing | unreachable | bad_response`; vettore di dimensione diversa da quella
      registrata → `bad_response`.
- [ ] Politica di troncamento (Dis.9): ogni chiamata usa `truncate=false`. Un 400 "exceeds the
      context length" su un batch fa ripartire quel batch testo per testo; il solo testo oltre il
      contesto si incorpora con `truncate=true`, viene marcato `truncated` nell'indice e produce
      un WARNING con `passage_id`, caratteri e `num_ctx`. Il conteggio dei troncati compare
      nell'output della CLI e nello stato del corso. Mai troncamento silenzioso.
      - Given un corso con una tavola numerica da 3.000 token e 40 passaggi normali; When si
        indicizza; Then 41 vettori scritti, 1 con `truncated = 1`, un WARNING col suo
        `passage_id`, la CLI stampa "1 passaggio troncato".
- [ ] Prompt in `src/sbobina/embedding_prompts.py` (puro, `EMBEDDING_PROMPT_VERSION`): per la
      famiglia Qwen la domanda diventa `Instruct: Given a question, retrieve relevant passages
      that answer it\nQuery:{q}`, i documenti restano senza prefisso; soglia per modello da
      T016. Un modello non misurato non ha soglia e lo stato lo dichiara "non misurato".
- [ ] Unità di embedding in `src/sbobina/embedding_units.py` (puro), **la stessa** funzione usata
      dall'harness (oggi in `hybrid_eval.py`): passaggi documento 1:1 con quelli FTS, finestre di
      lezione da `partition_lecture_segments` (~250 parole) con primo e ultimo segmento e
      `sha256` del testo. Harness e produzione non possono divergere sulle unità.
- [ ] Indice vettoriale in un file separato `data/vectors.sqlite3` (Dis.2): tabelle `models`,
      `units`, `vectors(model_key, text_sha256, vector BLOB float32, truncated)`. WAL e
      `busy_timeout`. Mismatch di schema o corruzione: il file va in `.bak`, stato
      `rebuild_needed` con WARNING; nessuna cancellazione silenziosa.
- [ ] Comando `sbobina indicizza-semantico --corso <chiave>` (e `--tutti`): riconcilia le unità,
      calcola solo i vettori mancanti per la `model_key` attiva, scrive a batch (un'interruzione
      conserva il fatto), stampa copertura, troncati e unità al secondo.
      - Given un corso con 120 unità e 100 vettori già presenti; When si lancia il comando;
        Then partono 20 testi verso il fake embedder e la copertura passa a 120/120.
- [ ] Ramo denso `src/sbobina/dense_retrieval.py`, nella forma misurata: due liste (documenti,
      finestre di lezione) da al massimo 50 candidati sopra la soglia, unite con `fuse_by_rank`
      su punteggio `-cosine` (test che fallisce se il segno si inverte, R5). Una finestra densa è
      già una finestra: diventa un `RetrievedPassage` della finestra intera, senza passare da
      `expand_lecture_windows`.
- [ ] Scelta del percorso in `course_retrieval.retrieve_windows(..., dense: DenseRanker | None =
      None)`: denso se il modello risponde e la copertura del corso è 100%; altrimenti il BM25
      di oggi, invariato. `dense=None` dà output identico a oggi (la suite esistente è il test di
      non regressione). `RetrievalReport` con `mode: dense | bm25` (nome interno; l'etichetta mostrata all'utente si decide in C4), `reason` (`disabled`,
      `model_missing`, `unreachable`, `not_indexed`, `partial`, `stale_vectors`, `rebuild_needed`,
      `gpu_busy`) e copertura. `stale_vectors`: il manifest del corso è completo ma il testo di
      qualche unità è cambiato dopo l'indicizzazione (finding F7 della review di T026).
      - Given un corso con copertura 118/120; When lo studente fa una domanda; Then risponde il
        BM25, `retrieval_mode = {"mode": "bm25", "reason": "partial"}`, copertura 118/120.
- [ ] Chat e generazioni passano il ramo denso e registrano `retrieval_mode` (campo opzionale:
      JSONL e metadati vecchi si leggono ancora); la risposta API della chat lo espone; WARNING
      nel log a ogni degrado, una volta per processo e motivo.
      - Given il modello configurato non installato; When lo studente fa una domanda in chat;
        Then la risposta arriva dal BM25, il record ha `retrieval_mode = {"mode": "bm25",
        "reason": "model_missing"}` e il log ha un WARNING col nome del modello.
- [ ] `gpu_release.unload_ollama_models` scarica ogni modello in un `try` separato.
- [ ] Riproduzione attraverso il codice di produzione: harness `--system production` sul corpus
      di F1 dà i numeri di eval.md § Scelta (denso 8b) ±1 domanda. Embedding della domanda con
      9B residente p95 ≤ 2,5 s (tetto di regressione sui 2,05 s accettati, al posto del gate L),
      misurato anche mentre il 9B sta generando; `qwen3.5:9b` ancora in `/api/ps` con
      `size_vram` invariata.
- [ ] Throughput reale di indicizzazione dell'8b misurato in condizioni dichiarate (T033): unità
      al secondo con GPU libera e 9B scaricato, layer su GPU dal log di Ollama; comportamento di
      una query su CPU mentre lo stesso modello indicizza su GPU.

### C3 - Indicizzazione automatica (fase F3)

- [ ] Azione `embed` per corso nella FIFO del supervisor, in `web/embedding_supervisor.py`
      (`supervisor.py` è a 299 righe), sul modello di `ocr_supervisor.py`: processo figlio,
      annullabile, una sola azione in attesa per corso.
- [ ] L'azione prende la lease GPU come la trascrizione (`transcription_lease(stage="embedding")`),
      scarica prima i modelli residenti e a fine lavoro rilascia il modello (`keep_alive=0`).
      Durante l'indicizzazione la chat su motore locale risponde 409 `GPU_BUSY` con
      "indicizzazione semantica" e una stima calcolata con le unità/s di T033. Con motore API la
      chat continua; la sua query segue l'esito di T033 (CPU se le due istanze convivono,
      altrimenti BM25 con `reason="gpu_busy"`).
- [ ] Indicizzazione a fette (Dis.10, attiva solo se T033 conferma meno di 0,5 unità/s): un'azione
      `embed` lavora al massimo 10 minuti, poi rilascia la lease e riaccoda il resto in coda alla
      FIFO, così una trascrizione accodata non aspetta ore.
- [ ] Accodamento automatico, solo se `semantic_search` è attivo e il modello è installato:
      lezione completata, documento `READY` (estrazione o OCR), modifica manuale salvata. Con
      modello assente non si accoda niente e lo stato del corso dice perché.
      - Given una lezione già indicizzata; When lo studente corregge 3 parole nel lettore; Then
        si accoda un'azione `embed` e alla sua fine sono ricalcolati solo i vettori delle
        finestre il cui testo è cambiato (contatore del fake embedder).
- [ ] Backfill: pulsante (F4) e comando CLI accodano un'azione per ogni corso con copertura <
      100%; il cambio di modello dichiara l'indice da ricostruire e accoda il backfill solo dopo
      conferma. I vettori di altre `model_key` si eliminano quando il nuovo indice è completo.
- [ ] Il cambio di corso di una lezione non richiede re-embedding: le unità di lezione non
      portano il corso, lo scope si risolve a ogni query.

### C4 - Stato e scelta nelle Impostazioni (fase F4)

- [ ] `GET /api/v1/semantic-index/status`: modello configurato, installato sì/no, dimensioni,
      misurato sì/no, copertura e troncati per corso, ultima indicizzazione, azione in coda.
      `POST /api/v1/courses/{key}/semantic-index` accoda l'azione (stessi controlli `Origin` di
      `/api/v1/settings/*`).
- [ ] `embedding_model` e `semantic_search` in `UserPreferences` e in `_ENV_LOCKABLE_FIELDS`.
- [ ] Sezione "Ricerca semantica" nelle Impostazioni: modello (fra quelli installati con capacità
      `embedding`, col consigliato `qwen3-embedding:8b`), comando `ollama pull <modello>` da
      copiare quando manca, copertura, "Indicizza ora" con la durata stimata. Pagina del corso e
      risposta della chat mostrano "ricerca per significato" oppure "solo parole chiave: <motivo
      in chiaro>".
- [ ] `a11y-gate` sulla sezione, render a 375 e 1280 px, click-through registrato.

## Assunzioni

- Stack invariato: Python ≥ 3.12, un processo web, supervisor con FIFO e figli, frontend vanilla
  JS senza build, persistenza a file e SQLite. `numpy` dipendenza esplicita (già in
  `pyproject.toml` nel diff corrente).
- Embedding sempre locali, anche con `llm_engine = "api"` (Dis.6).
- Vettori float32 a 4096 dimensioni, come misurati. Ridurli (float16, `dimensions` MRL) è un
  cambio di qualità non misurato e resta fuori.
- `num_ctx` 2048 per documenti e query: è la configurazione con cui sono stati misurati i numeri
  di § Scelta, con 0 troncamenti sul corpus. Alzarlo ricarica il modello e aumenta la memoria; si
  rivede solo se T044 trova troncamenti frequenti su materiale reale.
- `keep_alive` "30m" per l'istanza CPU della query: ~5 GB di RAM su 38, prima query dopo lo scarico
  ~0,9 s in più (eval.md § Verifiche). Scelta implementativa, non misurata.
- `sample_course` (generazione senza argomento) resta com'è: non c'è una domanda da incorporare.
- Sugli altri computer (Windows/macOS, solo CPU) vale lo stesso default; l'indicizzazione su CPU
  non è misurata e la UI la dichiara "lenta senza GPU".
- Gold set e corpus di misura restano in `data/eval/`, fuori da git; in git harness, metriche e
  `eval.md`.
- Codex torna disponibile il 2026-10-12: fino ad allora si lavora sul residuo [M] di F1 e su T033.
- [BLOCCANTE per T017] il controllo a campione lo fa l'utente.

## Disambiguazione

1. **Come si sceglie il modello.** Risolta: misura su gold set con regola scritta prima (eval.md
   § Regola di scelta), decisione dell'utente su `qwen3-embedding:8b` (§ Scelta).
2. **Dove stanno i vettori.**
   - Opzione A: tabelle in `search.sqlite3` → il file si cancella a ogni bump di schema BM25
     (`search_index.py:74`), e a 0,17 unità/s una ricostruzione costa ore di GPU.
   - Opzione B: `data/vectors.sqlite3` separato, BLOB float32, cache per `text_sha256`.
   - Opzione C: `.npy` per corso → niente transazioni, scritture parziali a mano.
   - Raccomandata: B, ancora più netta a 4096 dimensioni e coi tempi dell'8b.
3. **Unità di lezione nella fusione con BM25.** Superata in v1.1: non c'è fusione con BM25, e le
   finestre dense sono già finestre.
4. **Soglia minima di similarità sul ramo denso.**
   - Opzione A: nessuna soglia → per "Chi ha vinto i mondiali del 2006?" il denso porta comunque
     i passaggi più vicini, e la chat riceve materiale a caso invece di "fuori dal materiale".
   - Opzione B: soglia per modello dalle liste salvate (T016), regola in C1.
   - Raccomandata: B. Costante accanto ai prompt, non un'impostazione dell'utente.
5. **Embedding della domanda.** Risolta: CPU con `num_gpu=0` (eval.md § Candidati e § Scelta). Il
   percorso GPU costa 10-20 s a domanda ed è scartato.
6. **Motore API.** Embedding sempre locali; senza Ollama il recupero è BM25 con `reason =
   unreachable`. Embedding cloud fuori dal piano.
7. **Quando indicizzare.** Azione `embed` in coda (C3), mai dentro la riconciliazione sincrona di
   `search_session`.
8. **Copertura parziale.**
   - Opzione A: tutto il corso a BM25 finché l'indice non è completo, `reason = partial`.
   - Opzione B: denso sulle sole unità indicizzate; le lezioni e i documenti nuovi restano
     invisibili alla chat fino all'indicizzazione.
   - Opzione C: denso sulle unità indicizzate più BM25 sulle altre, fusi.
   - Raccomandata: A (Domanda 1). B perde in silenzio proprio il contenuto più recente; C
     reintroduce la fusione che le misure hanno scartato. A degrada per un tempo limitato e lo
     dichiara.
9. **Testi oltre il contesto.**
   - Opzione A: `truncate` di default di Ollama → troncamento silenzioso.
   - Opzione B: `truncate=false` e unità scartata → la tavola numerica sparisce dalla ricerca e
     il corso resta per sempre sotto il 100%, quindi in BM25 (Dis.8).
   - Opzione C: `truncate=false`, ripiego testo per testo, troncamento esplicito, contato,
     loggato e marcato nell'indice (C2).
   - Raccomandata: C. Il passaggio patologico è di solito una tavola il cui inizio basta a
     ritrovarlo; il troncamento resta visibile in CLI e nello stato.
10. **Indicizzazione lunga.**
   - Opzione A: un'azione per corso, che tiene la GPU fino alla fine.
   - Opzione B: fette da 10 minuti riaccodate in fondo alla FIFO (T045).
   - Raccomandata: B se T033 conferma meno di 0,5 unità/s, A altrimenti (Domanda 2). A 0,17
     unità/s un corso da 2.500-3.000 unità tiene la GPU 4-5 ore, e una lezione registrata nel
     frattempo aspetterebbe tutto quel tempo.

## Domande per l'utente

Risposte dell'utente del 2026-10-07: `qwen3-embedding:8b` confermato sapendo che un corso reale
costa circa 4-5 ore di GPU (stima da T015, da misurare in T033); domanda 1 e domanda 2: default.
Le due domande restano sotto come traccia della scelta.

Solo preferenze che il codice non può dare; default raccomandato in testa.

1. **Corso indicizzato in parte (Dis.8).** Default: tutto il corso torna a parole chiave finché
   l'indice non è completo, con il motivo mostrato. Alternativa: ricerca per significato sul solo
   materiale già indicizzato, con le novità invisibili alla chat fino all'indicizzazione.
2. **Indicizzazione di un corso intero (Dis.10).** Default: a fette da 10 minuti, così le
   trascrizioni nuove passano avanti; la durata totale resta la stessa. Alternativa: tutto in
   una volta, lanciato a mano quando il computer non serve (anche ore di GPU).

## Rischi e mitigazioni

- **R1 Gold set sbilanciato verso BM25.** Chiuso da F1: riferimenti per pagina e intervallo,
  pooling alla cieca su 2.857 voti, 12 domande `exact` aggiunte. Resta aperto il controllo
  dell'utente (T017).
- **R2 Margine piccolo.** Chiuso: denso 8b +36 domande appaiate contro BM25 (eval.md §
  Candidati), ben oltre il rumore.
- **R3 Disco.** Poiché il disco è al 93% con 25 GB liberi e i vettori a 4096 dimensioni pesano 16
  KB per unità (rischio: a cambio di modello convivono due indici, fino a ~650 MB per
  un'installazione da 20k unità, più la `.bak` di un indice corrotto), un disco pieno bloccherebbe
  Ollama e la scrittura dei job (effetto: F3 ferma, +0,5 g). → dimensione di `vectors.sqlite3`
  nello stato (F4), pulizia della vecchia `model_key` a indice nuovo completo (T043), cache di
  misura ridotta alla sola 8b a fine F1 (T019). Responsabile: esecutore di T043.
- **R4 `num_gpu=0` ignorato.** Chiuso: misurato in T010 con la GPU libera. Con la GPU occupata da
  altri processi (ComfyUI) il 9B entra a layer parziali e la query lo scarica: è un caso fuori
  dal controllo di sbobina, coperto dal tetto di T032 e dichiarato nel log.
- **R5 Ordinamento invertito.** `fuse_by_rank` ordina in modo crescente; anche il solo denso passa
  da lì (due liste). → `-cosine` e test che rompe col segno sbagliato (T026).
- **R6 Unload prima di Whisper interrotto.** → `try` per modello (T029); lo scarico di un modello
  di embedding è verificato (T010).
- **R7 Indicizzazione di un corso reale.** Poiché l'8b ha indicizzato 552 unità in 3156 s (~0,17
  unità/s, condizioni non registrate), un corso da 2.500-3.000 unità chiede 4-5 ore di GPU e un
  manuale da 250-300 passaggi circa mezz'ora (rischio: chat locale in 409 e trascrizioni ferme per
  tutto quel tempo), e l'utente smetterebbe di usare la ricerca semantica o la spegnerebbe
  (effetto: F3 da riprogettare, +1-1,5 g se scoperto in T044). → T033 misura il throughput prima
  di F3 con GPU libera, 9B scaricato e due dimensioni di batch; fette riaccodate (T045) se resta
  sotto 0,5 unità/s; backfill solo su richiesta; durata stimata mostrata prima di "Indicizza
  ora". Responsabile: esecutore di T033.
- **R8 Concorrenza SQLite.** → WAL, `busy_timeout`, transazioni brevi per batch, test con lettore
  e scrittore in thread.
- **R9 Limiti dimensionali.** `eval_hybrid.py` 651 righe → T009; `supervisor.py` 299 e
  `generation_runner.py` 298 → moduli nuovi; `wc -l` nei verify (nessun `.size-baseline.json`).
- **R10 Test che chiamano Ollama.** → fake embedder iniettato; il guard httpx di
  `tests/conftest.py:50` resta senza eccezioni nuove.
- **R11 CPU occupata dalla query.** Poiché la query dell'8b su CPU occupa i core per ~2 s e il 9B,
  quando non entra tutto in VRAM (ComfyUI attivo, contesti lunghi), genera in parte su CPU
  (rischio), una domanda in chat durante una generazione in coda rallenterebbe entrambe (effetto:
  p95 sopra il tetto, risposta della chat oltre i timeout). → T032 misura la query mentre il 9B
  genera; se il p95 supera 2,5 s, `options.num_thread` fissato con una misura prima e una dopo
  (performance.md). Responsabile: esecutore di T032.
- **R12 Stesso modello su CPU e su GPU insieme.** Poiché la query chiede l'8b con `num_gpu=0`
  mentre l'azione `embed` lo tiene su GPU (con motore API la chat non è in 409), Ollama potrebbe
  scaricare l'istanza GPU per caricare quella CPU (UNVERIFIED) e l'indicizzazione
  rallenterebbe a ogni domanda (effetto: ore di backfill in più, lavoro di F3 sprecato). → T033
  lo osserva in `/api/ps`; se c'è il ricarico, durante `embed` la query va a BM25 con `reason =
  gpu_busy` (T041).
- **R13 Troncamento su materiale reale.** Sul corpus di misura 0 unità oltre i 2048 token con
  l'8b, ma tavole numeriche esistono (embeddinggemma ne ha troncate 3). Un corso con molte tavole
  avrebbe passaggi rappresentati dal solo inizio. → politica C di Dis.9, conteggio nello stato;
  T044 registra i troncati sul corso reale.
- **R14 Validità esterna della scelta.** Poiché 42 domande su 70 sono costruite contro BM25, il
  materiale inglese è sintetico e il corpus è uno solo, il denso puro potrebbe perdere su
  domande reali a termine esatto oltre le 12 misurate (effetto: risposte peggiori di oggi su
  sigle e articoli di legge, non visibili in nessun test). → BM25 resta nel codice e si riattiva
  togliendo `semantic_search`; `retrieval_mode` salvato in chat e generazioni permette di
  confrontare a posteriori; il gold set è il metro per ogni ripensamento.

## Stima

Ore di sviluppo senior con test; buffer imprevisti 20% esplicito. La parte già fatta di F1 non si
conta. Non entrano nella stima i tempi macchina (backfill di un corso reale, ore di GPU) e il
tempo dell'utente per T017 (~1 h).

| Fase | Min | Max | Nota |
| --- | --- | --- | --- |
| F1 residuo (T009, T016, T019) | 1 g | 1,5 g | split dell'harness e porting della metrica |
| F2 ricerca densa, indice da CLI | 4 g | 5,5 g | -1 g di fusione, +0,5 g di troncamento, T033 e T034 |
| F3 indicizzazione automatica | 3,5 g | 5 g | +0,5 g per T045 (condizionale) e il ripiego di R12 |
| F4 stato e Impostazioni | 2 g | 3 g | invariata |
| Subtotale | 10,5 g | 15 g | |
| Buffer 20% | 2 g | 3 g | |
| **Totale residuo** | **12,5 g** | **18 g** | v1.0: 15,5-23 g con F1 intera |

Se T045 non serve (T033 sopra 0,5 unità/s), F3 scende a 3-4,5 g.

## Delega

- Codex via `tdd-guide` (moduli puri, confine Ollama, indice) e `senior-backend` (wiring, API,
  supervisor): task **[C]**, 2-4 per invocazione, blocchi **[B-n]** in `tasks.md`. Codex torna
  disponibile il **2026-10-12**: un blocco [C] lanciato prima gira in-house (FALLBACK del
  protocollo). Ordine consigliato: fino al 12 il residuo [M] di F1 e T033, da lì F2.
- `fullstack-developer` in-house: task **[UI]**.
- Non delegabili: misure con Ollama reale e giudizi **[M]**, gate di fase **[G]**.
- `code-reviewer` a ogni gate; `silent-failure-hunter` su F2 (ogni degrado lascia stato e log, il
  troncamento compreso); `a11y-gate` su F4.

## Criteri di verifica

Per ogni fase: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
`uv run mypy src tests` verdi; nessun file nuovo oltre 300 righe e nessun file esistente oltre
300 che cresce. Per fase:

- F1: `scripts/eval_hybrid.py --system dense --model qwen3-embedding:8b` con la metrica dei
  giudizi riproduce eval.md § Scelta; `wc -l` di harness e moduli ≤ 300; eval.md ha la soglia e
  l'accordo di T017.
- F2: harness `--system production` riproduce § Scelta ±1 domanda; una domanda in chat con
  modello assente risponde con `retrieval_mode.reason = "model_missing"`; `retrieve_windows`
  senza ramo denso dà output identico a prima sulla suite esistente; T033 registrato in eval.md.
- F3: una lezione nuova e un PDF nuovo raggiungono copertura 100% senza comandi manuali; campioni
  `nvidia-smi` ogni 2 s durante indicizzazione + trascrizione accodata: mai più di un processo
  GPU.
- F4: click-through della sezione e della pagina corso registrato in `eval.md`, `a11y-gate`
  verde, render a 375 e 1280 px osservato.
- Chiusura: `/analyze` su `specs/004-hybrid-retrieval/` senza CRITICAL; nessun UNVERIFIED
  residuo per codice spedito.

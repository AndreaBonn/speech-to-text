# ADR-002: Ciclo di studio (esercitazioni, flashcard, frasi d'esame, pacchetto corso, formule)

**Stato**: Proposto, da accettare dopo le verifiche in fondo
**Data**: 2026-10-04
**Ambito**: decisioni D1-D6 per cinque funzioni: O1 esercitazioni con correzione e storico, O2
flashcard con FSRS, O3 frasi "importanti per l'esame", O8 export/import del pacchetto corso,
O9 formule KaTeX e OCR in LaTeX
**Relazione con decisioni precedenti**: estende ADR-001 (`specs/001-course-workspace/adr.md`) D1
(registro `data/courses/<uuid>/`), D3 (`GpuArbiter`, FIFO per le generazioni), D5 (file JSON e
JSONL come verità). Nessuna decisione di ADR-001 viene ribaltata.

## Contesto

Vincoli che delimitano lo spazio, tutti già vigenti:

| Vincolo | Fonte | Conseguenza qui |
|---|---|---|
| Nulla lascia la macchina, niente CDN | CLAUDE.md, `design.md` | KaTeX va vendorizzato; il pacchetto O8 viaggia a mano (chiavetta, mail dell'utente), non via rete dell'app |
| File = verità, SQLite solo derivato | ADR-001 D5, Q2-B | `search.sqlite3` viene **cancellato** su corruzione o schema diverso (`src/sbobina/web/search_index.py:74`, `:91`): ogni dato dell'utente messo lì si perde a un cambio di schema |
| Un solo processo web, un worker | `src/sbobina/web/launcher.py:100` (`uvicorn.run` senza `workers`) | un `threading.Lock` per file basta a serializzare gli append, come in `src/sbobina/web/chat_store.py:45` |
| Figli della coda scrivono i propri record | `generation_supervisor.py`, `generation_store.py` | un record con due scrittori (web e figlio) va evitato: un file, un proprietario |
| Chat sincrona sotto `GpuArbiter.chat_turn`, 409 `GPU_BUSY` durante Whisper | `src/sbobina/web/gpu_lock.py:61` | il pattern per una chiamata LLM interattiva esiste già |
| Latenza di un turno di chat a caldo p50 10-14 s, massimo 25 s | `specs/001-course-workspace/eval-chat.md:31` (BASIS: measured in quella sessione) | un giudizio LLM per risposta sta nel budget di una richiesta HTTP; dieci giudizi in fila no |
| Citazioni: token NFKC + casefold, punteggiatura (categoria Unicode P) sostituita da spazio | `src/sbobina/study_citations.py:30` | `\frac{a}{b}` diventa `frac a b`; `x^2` e `a=b` restano token unici (`^` e `=` sono simboli, non punteggiatura) |
| `revision` = sha256 troncato del JSON della trascrizione | `src/sbobina/web/api_files.py:113` | cambia a ogni correzione manuale; gli indici di parola si spostano |
| Frontend: solo `createElement`/`textContent` per testo LLM | `src/sbobina/web/static/js/dom.js:2` | qualunque rendering di formule non può passare da `innerHTML` |
| Id di job e di corso sono uuid4 | `src/sbobina/web/job_store.py:86`, `course_registry.py` | collisioni casuali trascurabili, ma reimportare lo stesso pacchetto due volte collide per costruzione |
| Appartenenza di una lezione al corso per **etichetta** (`meta.json`/`subject`), non per uuid | `courses.py`, ADR-001 D1 | un corso importato con la stessa etichetta di uno esistente fonderebbe le lezioni in silenzio (vedi D6) |
| Colleghi su CPU, multi-OS, licenza Apache-2.0 | ADR-001 | dipendenze nuove: wheel pure o per i tre OS, licenze permissive |

Fonti esterne consultate in questa sessione (context7 non era disponibile come tool: lette le
fonti primarie):

- `fsrs` su PyPI, JSON API `https://pypi.org/pypi/fsrs/json` e wheel `fsrs-6.3.2-py3-none-any.whl`
  scaricata e letta (BASIS: measured).
- KaTeX su npm, `https://registry.npmjs.org/katex/latest` e tarball `katex-0.19.0.tgz` scaricato e
  letto (BASIS: measured).

---

## D1. Persistenza di tentativi (O1), carte e log di ripasso (O2)

### Passata 1: approcci generati

1. Un file JSON per tentativo; carte e ripassi in due JSONL append-only per corso.
2. Event sourcing puro: un solo JSONL per corso con tutti gli eventi, stato delle carte ricalcolato
   rigiocando FSRS.
3. Tabelle nuove in `data/search.sqlite3`.
4. SQLite dedicato per corso (`data/courses/<uuid>/study.sqlite3`) come fonte di verità.
5. SQLite dedicato globale (`data/study.sqlite3`).
6. `cards.json` snapshot riscritto atomicamente a ogni ripasso, più log JSONL.
7. Persistenza nel browser (IndexedDB).

### Passata 2: valutazione

**Opzione 1, JSON per tentativo + JSONL per carte e ripassi (raccomandata)**

- Pro: stessa convenzione di generazioni (`generations/<id>.json`, scrittura atomica) e chat
  (JSONL + lock per file). Un tentativo ha un ciclo di vita a stati (in corso, consegnato,
  valutato) come `GenerationRecord`: un file per tentativo, riscritto per intero con replace
  atomico, un solo scrittore (il processo web). Carte e ripassi sono eventi: append di una riga,
  nessuna riscrittura, nessun rischio di perdere lo stato di 500 carte per un crash a metà scrittura.
  File separati per carte e ripassi mappano direttamente le scelte di export di D6 (le carte si
  condividono, lo storico dei ripassi è personale).
- Contro: "carte in scadenza oggi" richiede di leggere i due JSONL e piegarli in memoria. Con
  qualche migliaio di carte e decine di migliaia di righe è un costo di millisecondi
  (BASIS: inferred, non misurato: vedi verifica V3). Riga finale troncata da un crash: il lettore
  deve ignorare l'ultima riga non parsabile, come già fa per la chat (da verificare, V4).
- Costo di migrazione: nullo, sono dati nuovi.

**Opzione 4, SQLite per corso come verità**

- Pro: transazioni, query `due <= oggi` con indice, conteggi immediati.
- Contro: secondo regime di persistenza accanto ai file, contro ADR-001 D5. Per l'export O8 il
  file va copiato con l'API di backup (non per copia grezza con WAL aperto). All'import il
  pacchetto conterrebbe un database SQLite costruito da altri: aprire un file SQLite non fidato è
  una superficie d'attacco documentata da SQLite stesso (`https://www.sqlite.org/security.html`,
  sezione sui file di database non fidati), mentre un JSON validato da pydantic no.
- Giusta se: le query diventano davvero relazionali (statistiche incrociate su mesi di ripassi) e
  la piegatura in memoria supera una soglia misurata.

**Opzione 2, event sourcing puro**

- Pro: un solo file, storia completa.
- Contro: rigiocare FSRS non è deterministico con il fuzzing attivo (`Scheduler(enable_fuzzing=True)`
  usa `random()`, `fsrs/scheduler.py`): lo stato va comunque salvato nell'evento, e a quel punto è
  l'opzione 1 con carte e ripassi mescolati, che l'export deve poi separare riga per riga.

**Scartate**

- 3, tabelle in `search.sqlite3`: il file viene cancellato su corruzione o cambio di schema
  (`search_index.py:74`). Tentativi e ripassi andrebbero persi al primo bump di `SCHEMA_VERSION`.
- 5, SQLite globale: somma i contro della 4 e rende l'export per corso un'estrazione con query.
- 6, snapshot riscritto: riscrive l'intero mazzo a ogni ripasso; la piegatura dell'opzione 1 dà
  lo stesso stato senza il rischio.
- 7, browser: si perde pulendo i dati del sito, invisibile all'export, fuori dalla convenzione file.

### Decisione D1

```
data/courses/<uuid>/
  practice/<attempt_id>.json   # O1: un tentativo, stato in_progress|submitted|graded, replace atomico
  cards/cards.jsonl            # O2: eventi carta (created, edited, suspended, deleted)
  cards/reviews.jsonl          # O2: un ripasso per riga, con lo stato FSRS risultante
```

- Ogni riga di `reviews.jsonl` porta `{card_id, rating, reviewed_at, duration_ms, state, step,
  stability, difficulty, due}`: lo stato corrente di una carta è l'ultima riga che la riguarda,
  nessun replay.
- Scrittore unico: il processo web, con un `Lock` per file (stesso schema di `chat_store._lock_for`).
- "In scadenza oggi" = piega in memoria per corso a ogni richiesta. Se la verifica V3 supera
  200 ms, si aggiunge una tabella **derivata** in `search.sqlite3` ricostruibile dai JSONL, coerente
  con Q2-B; non prima.
- Il tentativo copia testo della domanda, opzioni e soluzione dalla generazione (vedi D4): resta
  leggibile anche se la generazione viene cancellata.

### Conseguenze D1

- Backup, cancellazione e export di un corso restano operazioni su una cartella.
- Due schede del browser che ripassano la stessa carta: due righe, vince l'ultima. Accettabile
  (stesso utente); il client manda `card_id` e `due` visto, il server rifiuta con 409 se la carta
  ha già un ripasso più recente, così lo stesso ripasso non viene contato due volte.

---

## D2. FSRS: libreria o implementazione propria

### Fatti sulla libreria (BASIS: measured, fonti sopra)

- `fsrs` 6.3.2, caricata il 2026-08-09, licenza MIT (Open Spaced Repetition), `requires_python
  >=3.10`, wheel `py3-none-any` (pura, gira sui tre OS). Dipendenze runtime: solo
  `typing-extensions`. `torch`, `numpy`, `pandas`, `tqdm` solo negli extra `optimizer` e `dev`.
  Fonte: `https://pypi.org/project/fsrs/6.3.2/`, repo `https://github.com/open-spaced-repetition/py-fsrs`.
- API: `Scheduler(parameters=DEFAULT_PARAMETERS, desired_retention=0.9, learning_steps=...,
  relearning_steps=..., maximum_interval=36500, enable_fuzzing=True)`;
  `Scheduler.review_card(card, rating, review_datetime=None, review_duration=None) -> tuple[Card,
  ReviewLog]`; `Scheduler.get_card_retrievability(...)`; `Card`, `Rating` (IntEnum), `State`,
  `to_dict`/`from_dict`/`to_json`.
- `DEFAULT_PARAMETERS` ha 21 pesi (FSRS-6), l'ultimo è `FSRS_DEFAULT_DECAY`.
- `Card` è `@dataclass(init=False)` mutabile; `card_id` di default sono i millisecondi epoch e il
  costruttore fa `time.sleep(0.001)` per evitare collisioni (`fsrs/card.py:76`).
- Il fuzzing chiama `random()` del modulo globale: non deterministico nei test.

### Passata 1: approcci generati

1. Dipendenza PyPI `fsrs`, pinnata alla major, dietro un modulo confine.
2. Implementazione propria delle formule FSRS-6 con i pesi di default.
3. Vendorizzare `fsrs/scheduler.py` (MIT) nel repo.
4. SM-2 (algoritmo di SuperMemo/Anki classico) implementato a mano.
5. Leitner a scatole fisse.

### Passata 2: valutazione

**Opzione 1, dipendenza `fsrs` (raccomandata)**

- Pro: implementazione di riferimento mantenuta dagli autori dell'algoritmo, zero dipendenze
  transitive reali, licenza compatibile con Apache-2.0. I casi difficili (learning e relearning
  steps, limiti dei parametri, intervallo massimo) sono già coperti dai loro test.
- Contro: tipi della libreria mutabili e `card_id` intero non adatti al dominio (dataclass frozen,
  uuid). Si risolve con un confine: `flashcard_scheduler.py` è l'unico modulo che importa `fsrs`,
  riceve e restituisce dataclass frozen del progetto, costruisce `Card(card_id=0, ...)` dai campi
  persistiti (il `card_id` della libreria non viene mai usato né salvato). Un cambio di major può
  cambiare il numero di pesi (FSRS-5 ne aveva 19: UNVERIFIED, da training data): pin `fsrs>=6.3,<7`.
- Costo: una riga in `pyproject.toml`, un modulo da ~80 righe.

**Opzione 2, implementazione propria**

- Pro: nessuna dipendenza, controllo totale, tipi nativi.
- Contro: ~20 formule con clamp e casi per stato; un errore di segno non fa fallire niente, sposta
  solo gli intervalli, e lo studente se ne accorge a settimane di distanza. Per verificarla servono
  comunque vettori di test generati dalla libreria di riferimento: si dipende da lei lo stesso, solo
  in dev.
- Giusta se: la libreria smette di essere mantenuta o cambia licenza.

**Scartate**

- 3, vendorizzare: stesso codice della 1 senza aggiornamenti; nessun guadagno rispetto a un pin.
- 4 e 5: la richiesta è FSRS; SM-2 e Leitner programmano peggio a parità di sforzo dello studente
  (UNVERIFIED nella misura, è la tesi del benchmark di open-spaced-repetition).

### Decisione D2

`fsrs>=6.3,<7` dietro `flashcard_scheduler.py`. Parametri di default, `desired_retention=0.9`,
`enable_fuzzing=True` in produzione e `False` nei test (il confine riceve lo scheduler per
iniezione). L'ottimizzatore dei pesi (`extra optimizer`, porta torch) resta fuori: con meno di
qualche centinaio di ripassi per corso non c'è materiale per ottimizzare.

### Conseguenze D2

- Persistiamo i campi FSRS con nomi nostri (D1), non `Card.to_dict()`: un cambio di formato della
  libreria non invalida i dati salvati.
- Rating esposti in italiano nella UI ("Di nuovo", "Difficile", "Bene", "Facile") mappati su
  `Rating` 1-4 nel confine.

---

## D3. Giudizio LLM delle risposte aperte e orali (O1)

### Passata 1: approcci generati

1. Sincrono per singola risposta, nel processo web, sotto `GpuArbiter.chat_turn` come la chat.
2. In coda FIFO come le generazioni, per tentativo intero.
3. Sincrono, e se la GPU è occupata la risposta resta salvata "da valutare" con un pulsante per
   riprovare.
4. Coda interna al processo web che ritenta da sola quando la GPU si libera.
5. Nessun LLM: autovalutazione dello studente con la soluzione citata accanto.
6. Punteggio deterministico per sovrapposizione di token con la soluzione.

### Passata 2: valutazione

**Opzione 1+3, sincrono per risposta, risposta salvata prima del giudizio (raccomandata)**

- Pro: un giudizio è una chiamata con input corto (domanda, soluzione, risposta), latenza dello
  stesso ordine di un turno di chat (p50 10-14 s, BASIS: inferred dalla chat, da misurare: V5).
  Il pattern esiste: lease condivisa, 409 `GPU_BUSY` immediato durante Whisper, priorità allo
  scrittore. La risposta dello studente si persiste **prima** di chiamare Ollama, quindi un 409 o un
  errore non costano niente: la voce resta `ungraded` e la UI mostra "GPU occupata da una
  trascrizione: valuta più tardi" con il pulsante "Valuta".
- Contro: un tentativo da 10 aperte valutato alla consegna sono ~10 chiamate in fila: si valuta
  risposta per risposta (alla conferma di ciascuna, o in sequenza dal client con avanzamento), mai
  in una richiesta sola. Sui PC dei colleghi su CPU la latenza è ignota e può superare il timeout
  HTTP del client (V5): lì la modalità di default è l'autovalutazione (opzione 5).
- Giusta se: si vuole feedback durante l'esercitazione, cioè il caso d'uso.

**Opzione 2, coda FIFO**

- Pro: nessun rischio di timeout, esclusività VRAM garantita dalla coda, adatta a CPU lente.
- Contro: la coda serve anche correzioni da ~38 minuti per lezione (CLAUDE.md): un'esercitazione
  aspetterebbe dietro una trascrizione. Per un uso interattivo è la scelta sbagliata.
- Giusta se: si introduce una modalità "simulazione d'esame" valutata a fine prova senza fretta.

**Opzione 5, autovalutazione**

- Pro: zero GPU, zero errori del giudice, ogni studente la capisce.
- Contro: nessun feedback su cosa manca. Resta sempre disponibile e diventa l'esito definitivo
  quando lo studente non concorda con il giudice.

**Scartate**

- 4, ritentativo automatico in background: una seconda coda nascosta nel processo web, con stato
  in memoria che si perde al riavvio. Il pulsante dell'opzione 3 dà lo stesso risultato in chiaro.
- 6, sovrapposizione di token: una risposta corretta con parole diverse prende zero, una che copia
  parole a caso dalla soluzione prende molto. Misura la copia, non la comprensione.

### Formato di output del giudice

Prompt versionato `src/sbobina/prompts/valutazione-v1.md` (passa da prompt-master prima del commit,
memoria di progetto). Schema pydantic `ProposedJudgement` separato dal dominio, come
`generation_models.py`:

```json
{
  "punti_coperti": [{"punto": "<testo copiato dalla soluzione>", "prova": "<testo copiato dalla risposta>"}],
  "punti_mancanti": ["<testo copiato dalla soluzione>"],
  "errori": [{"frase": "<testo copiato dalla risposta>", "motivo": "<una frase>"}]
}
```

- Ogni `punto` e ogni voce di `punti_mancanti` deve comparire nella soluzione, ogni `prova` e
  `frase` nella risposta dello studente: match contiguo su `normalize_tokens`. Le voci che non
  passano si scartano con un codice di motivo, come per le citazioni. Il feedback mostrato è quindi
  sempre ancorato a testo esistente.
- Esito e voto (1 / 0,5 / 0) sono sempre calcolati dal codice dai punti coperti e mancanti e
  dagli errori ancorati, per aperte e orali: il modello non dichiara l'esito e nessun numero è
  chiesto all'LLM. Nota: emendato in revisione piano (2026-10-04, decisione dell'orchestratore,
  plan.md v1.2); la versione precedente chiedeva il campo `esito` al modello per le aperte.
- Orale: la soluzione è già una lista di punti uniti da `" | "` (`generation_models.py:86`); il
  giudice valuta copertura punto per punto.
- Crocette: confronto di indice, nessun LLM.
- Lo stesso `qwen3.5:9b` ha generato la soluzione: rischio di indulgenza verso le proprie
  formulazioni. Mitigazione: il giudice confronta con la soluzione **citata**, non con la propria
  conoscenza; gate V6 prima di mostrare il giudizio come esito e non come suggerimento.

### Conseguenze D3

- Un nuovo chiamante di `chat_turn` oltre alla chat: la docstring di `gpu_lock.py` va aggiornata
  ("chat turns" diventa "interactive LLM calls").
- Testo di domanda e soluzione può arrivare da un pacchetto importato (D6): è dato non fidato dentro
  un prompt senza tool. Il danno massimo è un giudizio sbagliato, già filtrato dal match testuale.

---

## D4. Identità e ancoraggio di carte, tentativi e frasi O3 dopo le correzioni

### Passata 1: approcci generati

1. Ancora per `(job_id, revision, indici di parola)`; se la `revision` cambia, l'ancora è morta.
2. Ancora per citazione testuale + `revision` di creazione; rilocalizzazione a lettura con il
   match normalizzato, stato `ok | spostata | fonte modificata`.
3. Contenuto copiato dentro l'entità (carta autosufficiente), l'ancora è solo provenienza.
4. Id stabili per parola dentro la trascrizione, preservati da `manual_edit.py`.
5. Frasi O3 non persistite: calcolate a ogni lettura dalla trascrizione corrente.
6. Id di contenuto (hash del fronte normalizzato) come identità della carta.

### Passata 2: valutazione

**Opzioni 3 + 2 + 5 combinate (raccomandata)**

- Carta e tentativo sono autosufficienti (3): fronte, retro, testo della domanda e soluzione copiati
  al momento della creazione. Una correzione della trascrizione o la cancellazione di una
  generazione non rende mai inutilizzabile una carta con mesi di ripassi.
- La provenienza è un'ancora testuale (2): `{kind: "lecture", job_id, revision, quote,
  segment_index}` o `{kind: "document", doc_id, sha256, page, quote}` o `{kind: "generation",
  generation_id, question_index}`. Percorso rapido: `revision` uguale, indici validi. Percorso lento:
  `locate_quote` (già esistente in `study_citations.py:109`) cerca la citazione nella trascrizione
  corrente; trovata altrove = `spostata`, non trovata = `fonte modificata`, mostrato accanto al link
  "Apri nel Lettore". Nessuna scrittura per aggiornare l'ancora: si rilocalizza a lettura.
- Le frasi O3 sono derivate (5): regex sul testo corrente a ogni apertura del Lettore o della
  pagina corso, mai salvate, quindi nessun problema di ancoraggio. Lo studente che vuole tenerne
  una la trasforma in carta (con ancora testuale).
- Identità: uuid4 per carte e tentativi. L'hash di contenuto (6) serve solo come chiave di
  deduplicazione per le carte create in blocco: `sha256(origine + sorgente + termine normalizzato)`,
  così rilanciare "Crea carte dai concetti" non duplica il mazzo.

**Opzione 4, id stabili per parola**

- Pro: ancore esatte anche dopo modifiche.
- Contro: cambia lo schema della trascrizione, `manual_edit.py` (ridistribuzione delle parole in
  `_respread_words`) e ogni consumatore; nessuna funzione chiede precisione al livello di parola
  dopo una modifica. Rimandata finché un caso concreto non la chiede.

**Scartate**

- 1 da sola: ogni correzione manuale, cioè l'uso normale del Lettore, invaliderebbe tutte le carte
  della lezione.
- 6 come identità: modificare il testo di una carta ne cambierebbe l'id e staccherebbe lo storico
  dei ripassi.

### Decisione D4

Entità autosufficienti con uuid4, ancora di provenienza testuale rilocalizzata a lettura (riuso di
`revision` come percorso rapido e di `locate_quote` come lento), frasi O3 derivate e non persistite,
hash di contenuto solo per la deduplicazione.

### Conseguenze D4

- La regex O3 vive in un modulo puro (`exam_cues.py`) con elenco di pattern versionato e test su
  frasi reali delle trascrizioni ("questo all'esame lo chiedo", "segnatevelo", "è importante");
  precisione da misurare su un campione (V7) prima di evidenziarle in modo vistoso.
- Una carta da errore O1 punta alla generazione; se la generazione non esiste più, l'ancora mostra
  "fonte rimossa" e la carta funziona comunque.

---

## D5. Formule: KaTeX e OCR in LaTeX (O9)

### Fatti sulla libreria (BASIS: measured sul tarball `katex-0.19.0.tgz`)

- KaTeX 0.19.0, licenza MIT (`package/LICENSE`, Khan Academy and other contributors).
  Dipendenza npm `commander`, solo per la CLI: il bundle browser non la usa.
- `dist/katex.min.js` 272.868 B, `dist/katex.min.css` 24.793 B, 20 font `woff2` per 259.792 B
  totali. Il pacchetto contiene anche `ttf`/`woff` non necessari ai browser attuali.
- `katex.render(expr, element, options)` svuota l'elemento con `textContent = ""` e appende un nodo
  costruito dal proprio albero (`renderToDomTree(...).toNode()`, `dist/katex.mjs:16305`);
  `innerHTML` compare 0 volte in `katex.min.js` e in `katex.mjs`.
- Opzioni: `trust` (boolean o funzione; abilita `\url`, `\href`, `\htmlClass` ecc.), `maxExpand`
  default 1000, `maxSize` default `Infinity`, `throwOnError`, `strict`.
- Licenza dei font: MIT, notice separata nel repo upstream `KaTeX/katex-fonts` ("Copyright (c)
  2018 Khan Academy"), vendorizzata come `LICENSE-fonts` accanto alla `LICENSE` del pacchetto (V8).

### Passata 1: approcci generati

1. KaTeX vendorizzato, `katex.render` lato client su segmenti delimitati, testo intorno via
   `textContent`.
2. KaTeX `renderToString` lato client + `innerHTML`.
3. Conversione LaTeX → MathML lato server, albero JSON, DOM costruito dal client (MathML Core nativo).
4. Nessun rendering: LaTeX mostrato come sorgente.
5. `auto-render` di KaTeX che scansiona il DOM.
6. MathJax vendorizzato.

### Passata 2: valutazione

**Opzione 1, `katex.render` su segmenti (raccomandata)**

- Pro: la regola "solo `textContent`" resta vera nel nostro codice: il client spezza il testo in
  segmenti testo/formula con un parser proprio dei delimitatori, i segmenti testo vanno in
  `textContent`, ciascuna formula in uno `<span>` passato a `katex.render`, che costruisce DOM e
  non usa `innerHTML`. Con `trust: false` i comandi che producono link o attributi HTML non sono
  disponibili.
- Contro: ~560 KB di asset statici (js + css + woff2), serviti in locale. Il parser di KaTeX
  diventa superficie di attacco per testo LLM e OCR: si limita con `maxExpand: 1000` esplicito,
  `maxSize: 10`, `throwOnError: false`, `strict: "ignore"`, lunghezza massima per formula (2.000
  caratteri, sopra si mostra il sorgente) e la versione pinnata con controllo degli advisory a ogni
  aggiornamento (in passato KaTeX ha avuto advisory su `maxExpand` e su `\url` con `trust` attivo:
  UNVERIFIED nei dettagli, da training data).
- Costo: cartella `static/vendor/katex-0.19.0/` con LICENSE, un modulo `math-text.js`.

**Opzione 3, MathML lato server**

- Pro: nessun JS di terze parti, il browser rende nativamente.
- Contro: serve una libreria Python di conversione (es. `latex2mathml`: licenza, copertura e
  manutenzione UNVERIFIED), copertura dei comandi più povera di KaTeX, resa tipografica più
  disuguale fra browser; il DOM MathML va comunque costruito nodo per nodo dal client.
- Giusta se: un audit di sicurezza vieta JS di terze parti nel frontend.

**Scartate**

- 2, `renderToString` + `innerHTML`: rompe la regola senza guadagno, `katex.render` fa lo stesso
  costruendo DOM.
- 4, sorgente grezzo: è il ripiego (errore di parsing, formula troppo lunga), non la soluzione:
  uno studente di economia o fisica non legge `\frac{\partial U}{\partial x}` a colpo d'occhio.
- 5, `auto-render`: scansiona tutto il DOM, renderebbe anche `$` nelle trascrizioni e nei nomi file.
- 6, MathJax: più pesante e più lento a parità di funzione; nessun requisito che KaTeX non copra.

### Decisione D5

- Delimitatori: solo `\(...\)` e `\[...\]`. Niente `$`: compare in testi di economia come valuta e
  nelle trascrizioni non ha mai significato matematico. Il prompt OCR (`ocr-v2.md`) chiede
  esplicitamente quei delimitatori; il prompt dei compiti li chiede quando cita una formula.
- Dove si rende: testo dei documenti nel visualizzatore, domande e soluzioni delle generazioni,
  risposte della chat, carte. **Mai** nelle trascrizioni Whisper, che non contengono LaTeX.
- Il testo persistito resta LaTeX: il rendering è solo presentazione.

### Conseguenze D5 su citazioni e FTS5

- Citazioni: `normalize_tokens` trasforma `\(\frac{a}{b}\)` in `frac a b`; il match resta esatto
  se l'LLM copia la formula carattere per carattere, fallisce se la riformatta (`a = b` contro
  `a=b`: `=` non è punteggiatura, quindi `a=b` è un token solo e `a = b` sono tre). Decisione:
  nessuna normalizzazione speciale in v1; si misura il tasso di citazioni scartate su pagine con
  formule (V9). Se supera il 20%, si aggiunge una normalizzazione dei segmenti matematici (spazi
  tolti dentro i delimitatori) in `normalize_tokens`, con test, perché tocca tutte le citazioni.
- FTS5: il tokenizer `unicode61` spezza i comandi in parole (`frac`, `partial`): ricerche su un
  simbolo trovano rumore, ricerche testuali funzionano. Nessun cambio di schema; limite dichiarato
  nella guida.
- OCR: `qwen2.5vl:7b` che restituisce LaTeX va valutato su pagine reali con formule (V10): un
  modello vision da 7B può inventare comandi; il fallback è il testo grezzo, che `throwOnError:
  false` mostra comunque.

---

## D6. Formato e import del pacchetto corso (O8)

### Passata 1: approcci generati

1. ZIP con `manifest.json` versionato e JSON che rispecchiano il layout del corso.
2. Un unico file JSON con i binari in base64.
3. `tar.gz` con manifest.
4. Un file SQLite come pacchetto.
5. Copia manuale della cartella del corso.
6. Sincronizzazione fra colleghi via cartella condivisa o git.

### Passata 2: valutazione

**Opzione 1, ZIP con manifest (raccomandata)**

- Pro: `zipfile` è nella stdlib; su Windows e macOS lo studente può aprirlo per vedere cosa sta
  condividendo; ogni file si valida da solo con i loader di dominio esistenti
  (`load_generation`, i loader di trascrizione). Il manifest dichiara inventario e hash, quindi
  l'import controlla prima di scrivere.
- Contro: lo ZIP è il formato classico di zip slip e zip bomb: difese obbligatorie (sotto).

**Opzione 2, JSON unico**

- Pro: un solo parse, nessun path.
- Contro: originali dei documenti in base64 (+33%), file da centinaia di MB caricato intero in
  memoria per validarlo. Giusta solo se i documenti non si esportano mai.

**Scartate**

- 3, `tar.gz`: stesse difese dello zip più i link nel formato tar; meno apribile su Windows.
- 4, SQLite: superficie del file non fidato (D1) e secondo regime di persistenza.
- 5, copia di cartella: porta id che collidono, lezioni legate per etichetta, dati personali senza
  scelta, nessuna validazione.
- 6, sincronizzazione: richiede rete o infrastruttura condivisa, fuori dal perimetro locale.

### Decisione D6

**Struttura**

```
<corso>-<data>.sbobina.zip
  manifest.json        # format_version, app_version, package_id (uuid), created_at,
                       # course {label}, inventario [{path, sha256, size, kind}], opzioni incluse
  lectures/<n>/transcript.json, corrected.json, meta.json, study.json   # mai audio
  documents/<n>/document.json, text.json, [original.<ext>]
  generations/<n>.json
  cards/cards.jsonl    # senza reviews
```

- I path nel pacchetto sono indici progressivi (`<n>`), non gli id del mittente.

**Id rimappati, corso sempre nuovo (v1)**

- All'import ogni id (corso, job, documento, generazione, carta) riceve un uuid4 nuovo; una tabella
  di rimappatura riscrive i riferimenti interni (citazioni `doc_id`/`job_id`, ancore delle carte,
  `generation_id` dei tentativi). Motivo: reimportare lo stesso pacchetto o importarlo da due
  colleghi produrrebbe id identici.
- Il `package_id` e gli id originali si conservano in `imported_from` del corso: un secondo import
  dello stesso pacchetto viene segnalato ("già importato il …"), non bloccato.
- Sempre un corso nuovo, mai fusione in uno esistente. **Etichetta**: l'appartenenza delle lezioni è
  per chiave dell'etichetta, quindi se `course_key(label)` esiste già l'import assegna
  `"<label> (importato <data>)"`; senza questo le lezioni importate finirebbero nel corso esistente
  mentre i documenti andrebbero nel corso nuovo.
- Le lezioni importate entrano in `data/jobs/<uuid>/` con stato completato e flag `imported`
  senza audio: il Lettore deve disattivare la barra audio e i salti al timestamp (lavoro di UI da
  pianificare).

**Contenuto e consenso**

| Contenuto | Default | Motivo |
|---|---|---|
| Trascrizioni, correzioni, materiali di studio, `meta.json` | incluso | è lo scopo del pacchetto |
| Audio | mai | richiesta esplicita; peso |
| Testo estratto dei documenti | **incluso**, deselezionabile per documento | decisione utente U1 (2026-10-04), che sovrascrive il default proposto "escluso": il valore del pacchetto per chat e compiti del destinatario prevale; la finestra di export mostra un avviso sul diritto d'autore |
| Originali dei documenti | **incluso**, deselezionabile per documento | come sopra (U1); il peso dell'export va mostrato prima di confermare |
| Generazioni | incluse | contengono citazioni brevi; se i documenti sono esclusi le citazioni restano leggibili ma non apribili |
| Carte | incluse senza stato FSRS | il destinatario parte da zero |
| Tentativi, ripassi, chat | mai in v1 | dati personali dello studente, nessun valore per un altro |

La finestra di export mostra l'elenco con le scelte e una riga sul diritto d'autore. Le
trascrizioni possono contenere nomi e voci di altri studenti intervenuti a lezione: avviso nella
stessa finestra.

**Difese all'import**

- Nessun `extractall`: l'import legge i membri **elencati nel manifest** e scrive su path calcolati
  da noi (`data/courses/<nuovo-uuid>/...`), mai sul nome del membro. Rifiuto comunque di nomi
  assoluti, con `..`, backslash, lettere di unità, duplicati, e di membri con bit di symlink in
  `external_attr`.
- Limiti: dimensione del file caricato (stesso tetto degli upload), numero di membri (es. 5.000),
  dimensione decompressa totale e per membro, letta con un lettore che **conta i byte reali**
  (le dimensioni nell'header dello zip si possono falsificare), rapporto di compressione massimo.
  Numeri esatti da fissare nel piano.
- Hash di ogni membro confrontato con il manifest; membri non nel manifest ignorati; ZIP annidati
  non aperti.
- Validazione: manifest con modello pydantic e `format_version` noto (versione sconosciuta = 422
  con messaggio "pacchetto creato da una versione più recente"); ogni JSON caricato dai loader di
  dominio, che rifiutano record incoerenti. Originali dei documenti ripassati da `document_sniff`
  e dai limiti Office esistenti (commit `3c24eba`).
- Atomicità: tutto in `data/courses/.import-<uuid>/` e `data/jobs/.import-<uuid>/`, rename finale
  solo a validazione completa; errore = cartella di staging rimossa, niente di parziale visibile.
- Lavoro in processo figlio con `RLIMIT_AS` come l'estrazione (`web/extraction_worker.py`), fuori
  dalla coda GPU.
- Reindicizzazione: il pacchetto non contiene indici; dopo il rename si avvia la riconciliazione
  FTS5 esistente (indice derivato, ADR-001 D2).

### Conseguenze D6

- Il formato del pacchetto diventa un contratto: ogni cambio dei JSON di dominio va accompagnato da
  un bump di `format_version` e da un test di import del pacchetto della versione precedente.
- La fusione con un corso esistente resta fuori da v1: richiede regole di conflitto (stesso
  documento due volte, stessa lezione trascritta da due persone) che oggi nessuno ha chiesto.

---

## Scelte dell'utente (decise il 2026-10-04)

1. **D6, testo e originali dei documenti nell'export**: inclusi per default, deselezionabili per
   documento, con avviso sul diritto d'autore (U1=C; tabella D6 emendata).
2. **D6, fusione su corso esistente**: v1 sempre corso nuovo (assunzione del piano).
3. **D3, giudizio LLM come esito o come suggerimento**: suggerimento finché V6 non passa, poi
   esito con override dello studente (U2=A).

## Rischi

| Causa | Rischio | Effetto |
|---|---|---|
| Lo stesso modello genera e giudica | giudizio indulgente sulle proprie formulazioni | voti gonfiati; mitigato dal match testuale e da V6 |
| Latenza del giudice su CPU ignota | timeout HTTP sui PC dei colleghi | giudizio inutilizzabile lì; default autovalutazione su CPU |
| OCR in LaTeX da un VLM 7B | comandi inventati, formule sbagliate rese in modo convincente | lo studente studia una formula errata; la pagina mostra sempre "testo OCR" e il link alla pagina originale |
| Etichetta del corso come chiave di appartenenza | collisione all'import | lezioni nel corso sbagliato; mitigato dal suffisso obbligatorio |
| Regex O3 su parlato | falsi positivi ("è importante" detto di tutto) | evidenziazione rumorosa; misura di precisione V7 prima di renderla vistosa |

## Verifiche da fare prima di accettare

- **V1** `uv add "fsrs>=6.3,<7"`: lock senza dipendenze transitive oltre `typing-extensions`.
  **Esito (2026-10-04): superata.** Il diff di `uv.lock` aggiunge solo `fsrs` 6.3.2 (MIT);
  `typing-extensions` era già presente. BASIS: measured.
- **V2** Test del confine `flashcard_scheduler.py` con `enable_fuzzing=False`: sequenza
  Again/Good/Good/Easy produce stati e `due` identici a quelli della libreria chiamata direttamente.
  **Esito: superata** (`tests/test_flashcard_scheduler.py`); `fsrs` importato solo da
  `flashcard_scheduler.py`. BASIS: measured.
- **V3** Piegatura di `cards.jsonl` + `reviews.jsonl` con 3.000 carte e 30.000 ripassi sintetici:
  tempo di "in scadenza oggi" sotto 200 ms, altrimenti tabella derivata.
  **Esito (2026-10-04): al limite, non superata con margine.** `scripts/bench_review_fold.py`,
  6 esecuzioni da 10 run, cache calda, macchina di sviluppo: p50 della piega fra 177 e 223 ms
  (max fino a 275 ms); un append su `reviews.jsonl` da 30.000 righe p50 4,5-5,6 ms, quindi il
  rilievo della review B-3 sull'append non richiede interventi. Lo scenario è un limite superiore
  (circa un anno di ripasso intensivo in un solo corso), ma `/review/summary` ripete la piega per
  ogni corso. **Decisione: T032 rinviato, non scartato.** Si riapre se la latenza misurata nel
  click-through di T029 su `/review/today` o `/review/summary` supera 300 ms, o se un mazzo reale
  supera 1.000 carte. In quel caso l'ordine è: prima una memoizzazione in processo della piega
  invalidata da dimensione e mtime dei due file (un solo worker uvicorn, `launcher.py:100`), poi
  la tabella derivata solo se non basta. BASIS: measured sui tempi, inferred sulla soglia d'uso.
- **V4** Riga JSONL troncata in coda: il lettore la ignora e l'append successivo non la corrompe.
  **Esito: superata** (`tests/web/test_card_store.py`), estesa alle righe valide ma con dati
  non validi, saltate con warning. BASIS: measured.
- **V5** Latenza del giudice su 20 risposte reali, GPU e CPU.
  **Esito (2026-10-05): GPU misurata, CPU no.** 90 giudizi su GPU: p50 8,3 s, max 21,5 s. Su CPU
  (`num_gpu: 0`) Ollama non carica il modello: servono 8,0 GiB di RAM libera, ne erano
  disponibili 6,2. Dettaglio in `eval-grading.md`. BASIS: measured su GPU, unknown su CPU.
- **V6** 30 risposte etichettate a mano dall'utente (corretta, parziale, errata): accordo del
  giudice ≥ 80% per mostrare l'esito come voto e non come suggerimento.
  **Esito (2026-10-05): superata sulla soglia, provvisoria.** Accordo 25/30 (83%) in tre
  esecuzioni identiche, zero errate giudicate corrette; tutti i disaccordi sono parziali (3 a metà
  giudicate corrette, 2 con errore giudicate errate). Domande generate dal corso reale, risposte ed
  etichette di Claude (U5 delegata): il giudizio resta "Suggerimento" finché l'utente non dà il sì
  sul passaggio a voto. Dettaglio in `eval-grading.md`. BASIS: measured.
  **Aggiornamento (2026-10-05, F41): `valutazione-v2`.** Stesse 30 risposte: accordo 26/30 (87%),
  zero errate giudicate corrette, risposte a metà giudicate parziali 5/7 (erano 4/7). BASIS: measured.
  **Decisione dell'utente (2026-10-05): il giudizio diventa voto** ("passo a voto ora"), con il
  limite documentato delle risposte a metà (2 su 7 giudicate corrette); il voto dello studente lo
  sostituisce (U2). Commit `016a689`.
- **V7** Precisione della regex O3 su 3 lezioni reali, frasi marcate a mano dall'utente.
  **Esito (2026-10-05): superata sulla soglia, provvisoria.** Precisione `strong` 1,00 (5/5)
  contro 0,80, `weak` 0,63 (15/24), recall stimato sulla rete larga 0,91 (20/22), stabilità
  sul duplicato Jaccard 100% (2 cue), 2,7-3,3 ms per lezione. Etichette di Claude, non
  dell'utente (U5 delegata il 2026-10-05): con 5 rilevazioni l'intervallo di Wilson al 95%
  parte da 0,57, e la misura diventa definitiva con un sì dell'utente sui 7 `strong`.
  Dettaglio ed errori in `eval-exam-cues.md`. BASIS: measured, recall inferred.
- **V8** Notice di licenza dei font KaTeX nel repo upstream.
  **Esito: superata** (2026-10-05). `KaTeX/katex-fonts/LICENSE` è MIT, Copyright (c) 2018 Khan
  Academy; la `LICENSE` del tarball `katex@0.19.0` è MIT, Copyright (c) 2013-2020 Khan Academy e
  contributori. Entrambe in `static/vendor/katex-0.19.0/`. Tarball verificato: sha256
  `d8e49f2fea6eeed7cdae2cf4fd48e2f1d348758aa9e5740715e4533c2c96d1ee`, sha512 uguale al
  `dist.integrity` del registry npm. BASIS: measured.
- **V9** Tasso di citazioni scartate su pagine con formule, soglia 20%.
- **V10** OCR `qwen2.5vl:7b` con prompt `ocr-v2.md` su 10 pagine con formule: formule parsabili da
  KaTeX e corrette a confronto con la pagina.
- **V11** Test di import ostile: zip slip, symlink, membro con header falso sulla dimensione,
  rapporto di compressione estremo, manifest con hash sbagliato, `format_version` futuro. Ogni caso
  rifiutato senza file scritti fuori dallo staging.

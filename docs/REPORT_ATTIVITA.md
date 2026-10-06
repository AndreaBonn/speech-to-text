# Report attività: sbobina

Progetto: `speech-to-text`. Data di creazione: 2026-10-01.

## 2026-10-01 - 11:28 | Sessione #1 [REFACTOR]

### Richiesta

Implementare T001-T004 di `specs/web-ui/tasks.md` sul branch `feature/web-ui`:
estrarre la pipeline e introdurre il progresso per la futura UI, preservando la CLI.

### Azioni Eseguite

- Aggiunta a `transcribe_file` una callback opzionale eseguita per ogni segmento,
  anche senza parole. Conservato il log di avanzamento ogni 300 secondi.
- Estratte in `pipeline.py` trascrizione, correzione e scrittura dei risultati.
  `with_progress` notifica ogni 10 paragrafi e all'ultimo; `CorrectionOutcome`
  espone risultato, percorso scritto e stato di interruzione, validandone la coerenza.
- Ridotta la CLI da 228 a 169 righe, mantenendo controlli di input, messaggi ed exit code.
  Conservata la scrittura degli output parziali quando l'interruzione segue il primo
  segmento; nessun output quando Ollama è irraggiungibile dal primo blocco.
- Seguito il ciclo TDD: prima dell'implementazione i nuovi test fallivano per
  callback assente (`TypeError`) e modulo pipeline assente (`ImportError`). Anche
  i due test sugli invarianti di `CorrectionOutcome` sono passati da rosso a verde.
- Review del codice e dei tipi: APPROVE. Test preesistenti CLI/transcriber invariati.

Verifiche eseguite con `UV_CACHE_DIR=/tmp/sbobina-uv-cache` per i limiti del sandbox:

| Controllo | Risultato |
|---|---|
| `uv run pytest`, baseline | 76 passed |
| `uv run pytest`, finale | 87 passed |
| Test mirati | Transcriber: 6; pipeline: 8; CLI: 11, tutti passati |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 31 files already formatted |
| `uv run mypy src tests` | Success: no issues found in 26 source files |
| `wc -l src/sbobina/cli.py` | 169, inferiore a 228 |
| Controllo AST | Funzioni nuove o modificate entro 30 righe |

BASIS: measured. Test e controlli sopra riportati eseguiti dall'orchestratore.
Verifica runtime della CLI in un processo separato su fixture temporanea: `rendi`
produce `[?ciao?]` alla soglia predefinita 0.7 e `ciao` con `--soglia 0.4`;
la soglia 0 restituisce exit 2 con errore argparse, un file assente exit 1.
Invocando `with_progress` con totale 11, le notifiche sono `[(10, 11), (11, 11)]`.
`CorrectionOutcome` accetta uno stato coerente e solleva `ValueError` se il flag
di interruzione contraddice il risultato. Whisper e Ollama sono simulati nei test:
inferenza reale e hardware non verificati; nessuna percentuale di copertura misurata.

### File Modificati

| File | Tipo | Descrizione |
|---|---|---|
| `src/sbobina/transcriber.py` | Modificato | Callback di progresso opzionale |
| `src/sbobina/pipeline.py` | Nuovo | Servizi riutilizzabili e risultato della correzione |
| `src/sbobina/cli.py` | Modificato | Delega dei comandi alla pipeline |
| `tests/test_transcriber.py` | Modificato | Nuovi casi sul progresso |
| `tests/test_pipeline.py` | Nuovo | Successo, interruzioni, callback e invarianti |
| `docs/REPORT_ATTIVITA.md` | Nuovo | Registro della sessione |

### Note per il Cliente

Chi usa i comandi esistenti conserva gli stessi risultati. Il lavoro prepara la
futura interfaccia a mostrare l'avanzamento e mantiene i risultati già corretti
quando il servizio di correzione si interrompe. L'interfaccia web resta da costruire.

### Riepilogo (Complessità / Stato)

Complessità media; T001-T004 completati e verificati. Le firme richieste a cinque
parametri prevalgono sul limite generale di quattro. Validato `CorrectionOutcome`
su indicazione della review. Nessun branch creato, commit o push.

## 2026-10-01 - 15:59 | Sessione #2 [FEATURE]

### Richiesta

Costruire un'interfaccia web locale per sbobina: caricamento dell'audio,
configurazione della trascrizione, download dei risultati e scelta dei modelli.
Avvio con un comando unico che riconosce il sistema operativo, con Linux come
piattaforma principale e Windows e macOS come ripiego. Deve funzionare anche sui
computer dei colleghi privi di GPU, quindi su sola CPU.

### Azioni Eseguite

- Server locale FastAPI con coda dei job in cui ogni stadio della pipeline
  (trascrizione, correzione, scrittura) gira in un processo figlio separato.
- Pagine web: Nuova trascrizione, Lettore con audio sincronizzato al testo,
  Storico, Modelli (download con avanzamento), Confronto WER.
- Design system bloccato in `design.md`, riusato da tutte le pagine.
- Script di avvio `avvia.sh` per Linux/macOS e `avvia.bat` per Windows; guida di
  installazione e checklist di verifica per i colleghi su Windows e macOS.
- Supporto CUDA su Windows, con ripiego automatico su CPU solo in presenza di
  guasti CUDA specifici e avviso mostrato nella pagina.
- Correzioni emerse dalla verifica reale: avanzamento della correzione mostrato a
  ogni blocco elaborato invece che a fine processo, nome del file scaricato
  allineato al nome della lezione, numero di thread CPU allineato ai core fisici
  su Linux (non ai thread logici).

Verifiche reali eseguite su Linux:

- Lezione da 85 minuti su GPU, correzione completata senza errori: trascrizione
  in circa 6,5 minuti, correzione in circa 18 minuti. Whisper e Ollama non sono
  mai stati tenuti in VRAM contemporaneamente.
- Annullamento di un job, interruzione con Ctrl+C e crash simulato del server:
  in tutti i casi il job risulta annullato o interrotto e non restano processi
  residui.
- Confronto fra run ripetuti sulla stessa lezione su GPU: 165-169 finestre da 30
  secondi identiche su 170 totali, differenze minime attese nella trascrizione.
- Trascrizione CPU: 5 minuti di audio elaborati in circa 85 secondi con 10
  thread, contro circa 102 secondi con 16 thread; una lezione da 90 minuti
  richiede quindi circa mezz'ora su CPU.

BASIS: measured per le misure sopra, riportate nei commit della sessione
(`76e3b8d`, `d5ca7d4`, `540d30d`, `7d06001`). Windows e macOS non sono stati
verificati su macchine reali: il supporto CUDA su Windows e gli script di avvio
restano non testati fuori da Linux.

### File Modificati

| Area | Tipo | Descrizione |
|---|---|---|
| `src/sbobina/web/` | Nuovo | Server FastAPI, coda job, pagine, static CSS/JS, template |
| `tests/web/` | Nuovo | Test su coda job, stage runner, supervisor, limiti di upload |
| `avvia.sh` | Nuovo | Avvio su Linux/macOS |
| `avvia.bat` | Nuovo | Avvio su Windows |
| `design.md` | Nuovo | Design system bloccato dell'interfaccia |
| `docs/installazione-windows.md` | Nuovo | Guida di installazione per Windows |
| `docs/checklist-windows-macos.md` | Nuovo | Checklist di verifica per Windows e macOS |
| `specs/web-ui/` | Modificato | Avanzamento dei task T001-T082 |
| `src/sbobina/` (pipeline, transcriber) | Modificato | Fallback CPU su guasti CUDA, thread sui core fisici |
| `pyproject.toml`, `uv.lock` | Modificato | Dipendenze CUDA spostate in extra opzionale |

Totale: 74 file toccati nel branch rispetto al punto di partenza della sessione.

### Note per il Cliente

L'interfaccia web per sbobina è pronta e verificata su Linux: si carica un
audio, si avvia la trascrizione, si segue l'avanzamento in tempo reale e si
scaricano i risultati, tutto dal browser e in locale, senza inviare l'audio
fuori dal computer. Funziona sia con scheda video sia su soli processori, anche
se su CPU una lezione di un'ora e mezza richiede circa mezz'ora di elaborazione.

Resta da verificare su macchine Windows e macOS reali: gli script di avvio e la
guida sono scritti e pronti, ma non ancora provati sul campo (checklist in
`docs/checklist-windows-macos.md`). Non è stata configurata l'integrazione
continua perché il progetto non ha ancora un repository remoto condiviso. Il
file README non è stato aggiornato in attesa di conferma.

### Riepilogo (Complessità / Stato)

Complessità alta: 74 file toccati, nuovo server web con coda di processi,
supporto multipiattaforma. Stato completato e verificato su Linux; da
verificare su Windows e macOS.

## 2026-10-01 - 20:14 | Sessione #3 [FEATURE]

### Richiesta

Sul branch `feature/editable-corrected-exports`: permettere l'esportazione della
trascrizione (corretta o originale) in un formato leggibile come dispensa, e
introdurre nel lettore web la correzione manuale del testo, parola per parola o
su una frase intera.

### Azioni Eseguite

- Esportazione in DOCX e TXT con impaginazione da dispensa: titolo (materia del
  corso o nome del file), formato A4, carattere Cambria 12pt giustificato con
  rientro di prima riga, lingua italiana e sillabazione automatica, numeri di
  pagina. Nessun timestamp e nessun segno di incertezza o di correzione nel
  testo esportato. Una lezione di 85 minuti occupa 11 pagine A4.
- Correzione manuale nel lettore web: un interruttore "Correggi a mano" attiva
  la selezione di una parola con un clic o di una frase trascinando il mouse
  (Shift+clic estende la selezione); da lì si può riascoltare il tratto audio
  corrispondente, digitare la correzione e salvare (Invio salva, Esc annulla,
  testo vuoto elimina le parole selezionate). Il salvataggio sovrascrive la
  versione corretta memorizzata (JSON e file `.md` corretto), quindi la
  modifica resta e si riflette nelle esportazioni DOCX/TXT successive. Se non
  esiste ancora una correzione automatica via LLM, la prima modifica manuale
  avvia una copia corretta a partire dall'originale; l'originale non viene mai
  alterato.
- Protezione contro salvataggi in conflitto: ogni salvataggio dichiara la
  versione del file su cui si basa; una modifica partita da una scheda del
  browser non aggiornata viene rifiutata con un messaggio chiaro, mostrando il
  testo appena digitato per non perderlo, invece di sovrascrivere le parole
  sbagliate.
- Corretta una falla di sicurezza individuata durante il lavoro: la protezione
  dell'app web contro le richieste da altre origini copriva solo i metodi POST
  e DELETE; ora copre anche PUT e PATCH.
- Corretto un bug emerso su dati reali prima del rilascio: le elisioni
  dell'italiano ("l'impressione") venivano esportate con uno spazio in più.
- Verifica eseguita: 478 test automatici verdi, ruff e mypy puliti; percorso di
  modifica completo verificato nel browser con 30 controlli su 30 passati; gate
  di accessibilità (axe tema chiaro/scuro, responsive, contrasto degli stati)
  passati, con un limite noto del gate sul cursore audio preesistente, la cui
  traccia reale misura un contrasto di 4,37:1 contro una soglia di 3:1; render
  verificato a 375 e 1280 px.

BASIS: measured. Conteggio dei test, esito di ruff/mypy, click-through nel
browser e misure di contrasto osservati nella sessione.

### File Modificati

| File | Tipo | Descrizione |
|---|---|---|
| `src/sbobina/book.py` | Nuovo | Impaginazione da dispensa (titolo, sillabazione, numeri di pagina) |
| `src/sbobina/docx_export.py` | Nuovo | Esportazione DOCX in formato dispensa |
| `src/sbobina/manual_edit.py` | Nuovo | Applicazione delle correzioni manuali con controllo di versione |
| `src/sbobina/web/api_corrected.py` | Nuovo | Endpoint web per leggere e salvare le correzioni manuali |
| `src/sbobina/web/static/js/reader-edit.js` | Nuovo | Interazione di selezione, riascolto e salvataggio nel lettore |
| `tests/test_book.py` | Nuovo | Test sull'impaginazione da dispensa |
| `tests/test_docx_export.py` | Nuovo | Test sull'esportazione DOCX |
| `tests/test_manual_edit.py` | Nuovo | Test sulle correzioni manuali e sui conflitti di versione |
| `tests/web/test_api_corrected.py` | Nuovo | Test sull'endpoint di correzione |
| `src/sbobina/web/api_files.py` | Modificato | Esposizione delle esportazioni DOCX/TXT da dispensa |
| `src/sbobina/web/app.py` | Modificato | Registrazione delle nuove rotte |
| `src/sbobina/web/middleware.py` | Modificato | Protezione cross-origin estesa a PUT e PATCH |
| `src/sbobina/web/reader.py` | Modificato | Supporto alla correzione manuale nel lettore |
| `src/sbobina/web/job_store.py` | Modificato | Gestione della versione del file corretto |
| `src/sbobina/models.py` | Modificato | Modelli dati per la correzione manuale |
| `src/sbobina/edits.py` | Modificato | Fix dello spazio spurio sulle elisioni italiane |
| `src/sbobina/web/static/js/reader.js` | Modificato | Integrazione con la modalità di correzione manuale |
| `src/sbobina/web/static/css/app.css` | Modificato | Stili per selezione, stati e messaggi di conflitto |
| `src/sbobina/web/templates/reader.html` | Modificato | Interruttore "Correggi a mano" e markup di supporto |
| `CLAUDE.md` | Modificato | Aggiornamento alla documentazione tecnica del progetto |
| `pyproject.toml`, `uv.lock` | Modificato | Nuova dipendenza `python-docx` |
| `tests/web/test_api_files.py`, `tests/web/test_app.py`, `tests/web/test_reader.py` | Modificato | Copertura delle nuove rotte e del nuovo markup |

Totale: 24 file toccati nella sessione.

### Note per il Cliente

Due novità nel lettore web. La prima: la trascrizione, corretta o originale,
si scarica anche come dispensa pronta da leggere o stampare, in Word o in
testo semplice, con titolo, pagine numerate e senza le annotazioni tecniche
(niente timestamp, niente segni di incertezza). Una lezione di un'ora e
mezza diventa undici pagine A4.

La seconda: ora è possibile correggere a mano il testo direttamente dal
lettore, parola per parola o su una frase intera, riascoltando il tratto
audio corrispondente prima di scrivere la correzione. Le modifiche restano
salvate e compaiono anche nei file scaricati. Se due persone (o due schede
dello stesso browser) provano a correggere lo stesso punto in momenti diversi,
il sistema avvisa invece di perdere una delle due modifiche.

Nel corso del lavoro è stata chiusa anche una falla di sicurezza
sull'applicazione web, che non riguardava i dati delle trascrizioni ma un
controllo di protezione incompleto.

Limiti da segnalare: su telefono, selezionare una frase di più parole
richiede di tenere premuto Maiusc (non c'è ancora la selezione con il dito);
le correzioni manuali non compaiono nel report delle correzioni automatiche,
che resta dedicato solo a quelle fatte dal correttore LLM; non esiste un
"annulla", si corregge ridigitando (la parola originariamente riconosciuta
resta visibile come "prima: ...").

### Riepilogo (Complessità / Stato)

Complessità medio-alta: 24 file toccati tra nuova esportazione e correzione
manuale. Stato completato e verificato su Linux.

## 2026-10-02 - 12:18 | Sessione #4 [FEATURE]

### Richiesta

Implementare T010-T012 del blocco B-2 in `specs/study-library/tasks.md`, su
`main`: raggruppamento per corso, metadati separati per le lezioni e API dei
corsi. L'ADR A1-c riserva `job.json` al supervisor e `meta.json` alle modifiche
dell'utente, così gli aggiornamenti concorrenti non si sovrascrivono.

### Azioni Eseguite

- T010: normalizzazione NFKC, compressione degli spazi e chiavi con casefold;
  aggregazione con conteggio, data ed etichetta della lezione più recente.
  Il gruppo "Senza corso" usa la chiave vuota.
- T011: aggiunti `LectureMeta`, lettura e scrittura atomica di `meta.json`,
  filtro del corso effettivo e iterazione dei record. Il corso effettivo usa
  `meta.course or config.subject`. `JobRecord` resta invariato.
- T012: aggiunti `GET /api/v1/courses` paginato, `PATCH /api/v1/jobs/<id>/meta`
  e il parametro `course` su `GET /api/v1/jobs`, con validazione per campo e
  protezione Origin esistente. Nessuna modifica alla UI.
- Conservata la leggibilità delle materie preesistenti che superano 100
  caratteri dopo NFKC: `"ﬃ" * 34` diventa una stringa di 102 caratteri.
  Il limite di 100 resta valido per i nuovi corsi; regressione vista rossa e verde.
- Estratta la registrazione delle rotte (`_register_routes`) per mantenere
  `create_app` entro 30 righe dopo l'aggiunta del router corsi.
- Verificata la coerenza del blocco B-2 con la richiesta esplicita Q1-D.
  Aggiornati il layout in `CLAUDE.md` e le tre spunte dei task.

TDD, test osservati rossi prima dell'implementazione:

| Task | Test | Esito iniziale |
|---|---|---|
| T010 | `test_normalize_course_label_and_key` | Incluso nei 18 fallimenti iniziali |
| T011 | `test_read_meta_missing_file_falls_back_to_subject` | `AttributeError` |
| T012 | `test_patch_meta_preserves_job_bytes` | HTTP 404 |

Verifiche eseguite dall'orchestratore (fuori dal sandbox di esecuzione, senza
restrizioni sui socket):

| Controllo | Risultato |
|---|---|
| Suite completa, 599 test | 599 passed |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 101 files already formatted |
| `uv run mypy src tests` | Success: no issues found in 86 source files |

Nota: l'implementazione è stata delegata a Codex (flagship OpenAI) in un
sandbox con socket TCP negati; lì la suite completa risultava 1 failed,
2 errors solo su `test_launcher` (apertura di una porta reale), non
riproducibile fuori sandbox. Codex aveva anche aggiunto uno stub autouse in
`tests/test_cli.py` per "correggere" quattro test che nel suo sandbox
contattavano Ollama: nell'ambiente reale quei quattro test erano già verdi
senza la modifica (baseline confermata con `git stash`), quindi la modifica
era fuori scope e non necessaria. Rimossa prima del commit.

BASIS: measured - risultati dei comandi eseguiti dall'orchestratore e cicli
rosso-verde riportati sopra, fuori dal sandbox Codex. I test esistenti
`test_job_store.py` e `test_job_models.py` sono passati senza modifiche; il
test PATCH controlla che `job.json` resti identico byte per byte. Nessuna
percentuale di copertura misurata.

### File Modificati

| File | Tipo | Descrizione |
|---|---|---|
| `src/sbobina/courses.py` | Nuovo | Normalizzazione e aggregazione pura |
| `src/sbobina/web/job_models.py`, `src/sbobina/web/job_store.py` | Modificato | Metadati separati e filtro per corso |
| `src/sbobina/web/api_courses.py` | Nuovo | Elenco corsi e modifica metadati |
| `src/sbobina/web/api_jobs.py`, `src/sbobina/web/app.py` | Modificato | Filtro dei job e registrazione delle rotte |
| `tests/test_courses.py`, `tests/web/test_course_meta.py`, `tests/web/test_api_courses.py` | Nuovo | Test dei tre task |
| `tests/web/test_api_jobs.py` | Modificato | Test del filtro `course` su `GET /jobs` |
| `CLAUDE.md`, `specs/study-library/tasks.md` | Modificato | Layout del progetto e spunte T010-T012 |
| `docs/REPORT_ATTIVITA.md` | Modificato | Registro della sessione |

### Note per il Cliente

Il servizio può associare le lezioni a un corso anche durante la trascrizione
e restituire l'elenco dei corsi con il numero di lezioni. Queste operazioni
sono disponibili tramite API; i comandi nell'interfaccia grafica appartengono
ai task successivi.

### Riepilogo (Complessità / Stato)

Complessità media. Codice implementato, suite completa verde (599 passed),
ruff e mypy puliti. Tre commit atomici su `main`, nessun push.

## 2026-10-02 - Biblioteca studio, T030-T031 (B-7)

Implementati i due task nel working tree, senza commit. Nessuna modifica a
`src/sbobina/web/`, `tests/web/` o ai test preesistenti della correzione.
I file intermedi e i log di questa sessione sono in `/tmp/sbobina-b7/`.

### Modifiche

- Creato `src/sbobina/ollama_chat.py`: `ChatRequest` frozen, chiamata chat,
  mappatura degli errori esistenti e rimozione del fence Markdown.
- Modificato `src/sbobina/llm_corrector.py`: usa il confine condiviso;
  `parse_response` continua ad accettare autonomamente risposte fenced.
  `ensure_model` e la validazione Pydantic della correzione restano qui.
- Creato `src/sbobina/study_models.py`: dominio frozen, schema Pydantic con
  alias italiani, riferimenti `S12` parsati in indici interi, dati persistibili
  separati dai riferimenti alle parole risolti a runtime. JSON I/O resta T033.
- Creato `src/sbobina/study_citations.py`: match esatto su token normalizzati,
  finestra limitata al segmento indicato e al successivo numerico ammesso dal
  blocco, prima occorrenza, timestamp della prima parola, scarto della voce
  intera se una citazione fallisce, termine del concetto presente in una
  citazione. La mappa dei caratteri conserva le parole originali anche quando
  il trascrittore divide una parola in più elementi `Word`.
- Creati `tests/test_ollama_chat.py`, `tests/test_study_models.py` e
  `tests/test_study_citations.py`; aggiornato il layout in `CLAUDE.md`.
- Aggiornato questo report. I file Python nuovi hanno al massimo 227 righe;
  tutte le funzioni nuove sono entro 30 righe, verificato con AST.

Scelte di contratto esplicitate: una voce senza citazioni è scartata come
`QUOTE_NOT_FOUND`; il successivo è sempre `segment_index + 1`, mai il prossimo
membro arbitrario di `allowed`. Una citazione interamente nel successivo è
ammessa e restituisce l'indice effettivo della prima parola. Lo schema usa
secondi numerici per `inizio`. Gli apostrofi sono separatori nella
normalizzazione, come la punteggiatura. Nessuna verifica di fedeltà semantica.

### TDD e mutation check

Tutti i comandi uv hanno il prefisso
`UV_CACHE_DIR=/tmp/sbobina-uv-cache`: il primo tentativo senza prefisso falliva
con `Read-only file system` sulla cache `/home/bonn/.cache/uv`.

- Baseline: `uv run pytest tests/test_llm_corrector.py tests/test_correction.py -q`
  → `41 passed in 0.16s`.
- T030 RED: `uv run pytest tests/test_ollama_chat.py -q`, contenente
  `test_chat_json_returns_unfenced_content_and_preserves_options`, prima del
  nuovo modulo → `1 error in 0.19s`, `ModuleNotFoundError: sbobina.ollama_chat`.
  GREEN, includendo le regressioni preesistenti → `49 passed in 0.16s`.
- T031 RED: `uv run pytest tests/test_study_citations.py tests/test_study_models.py -q`,
  contenente `test_locate_quote_d5_resolves_cause_timestamp_and_word_indices`,
  prima dei due moduli → `2 errors in 0.09s`, moduli mancanti.
  GREEN → `36 passed in 0.07s`.
- Mutante: in `_window_tokens`, confronto
  `segment_index <= index <= segment_index + 1` sostituito con
  `segment_index <= index >= segment_index + 1`.
  Comando esatto:
  `UV_CACHE_DIR=/tmp/sbobina-uv-cache uv run pytest tests/test_study_citations.py::test_locate_quote_accepts_adjacent_passages_but_rejects_a_gap -q`
  → `1 failed in 0.07s`: il caso 12-13 restituiva `QUOTE_NOT_FOUND`.
- Pulizia eseguita PRIMA del ripristino:
  `find src/sbobina/__pycache__ -maxdepth 1 -name 'study_citations.*.pyc' -delete`.
  Ripristinato il confronto originale; `cmp` contro la copia precedente al
  mutante è uscito 0. Stesso comando di test → `1 passed in 0.05s`.

### Verifica e limiti dell'ambiente

- Review indipendente `code-reviewer`: APPROVE, nessun rilievo concreto;
  85 test mirati verdi, Ruff e mypy sui sette file assegnati verdi.
- `uv run pytest` ha raccolto 941 test, mostrato quattro fallimenti CLI ed è
  rimasto fermo al primo test di `tests/web/test_api_corrected.py`.
  Interrotto con Ctrl-C, exit 130; log `/tmp/sbobina-b7/pytest-full.log`.
- `uv run pytest --ignore=tests/web --tb=short` →
  `4 failed, 546 passed in 1.25s`. I quattro test CLI falliscono nel contatto
  reale a Ollama da `ensure_model`: `CorrectorUnavailableError: ConnectionError:
  Failed to connect to Ollama`.
- Controllo della baseline CLI: estratto il sorgente con
  `git show HEAD:src/sbobina/llm_corrector.py > /tmp/sbobina-b7/llm_corrector_baseline.py`,
  caricato come `sbobina.llm_corrector` tramite `importlib.util`, poi eseguito
  `pytest.main(['tests/test_cli.py', '-q', '--tb=short'])` via `uv run python`.
  Risultato identico: `4 failed, 20 passed in 0.75s`, stessi quattro test e
  stesso errore Ollama. Nessun test alterato per aggirare l'ambiente.
- Diagnosi limitata del blocco web:
  `timeout 15s env UV_CACHE_DIR=/tmp/sbobina-uv-cache uv run pytest tests/web/test_api_corrected.py -x -vv -o faulthandler_timeout=5`
  → exit 124. Il primo test, `test_export_docx_corrected_is_book_text_named_after_audio`,
  resta in attesa nel portale AnyIO chiamato da Starlette TestClient.
  Causa non determinata, nessuna attribuzione al lavoro parallelo e nessuna
  modifica ai file web. Log `/tmp/sbobina-b7/pytest-web-timeout.log`.

BASIS: measured per test, confronto con HEAD e controlli statici;
unknown per la causa del blocco web. Nessuna percentuale di copertura misurata.
Scostamenti funzionali: nessuno. Suite completa da rieseguire dall'orchestratore
nel proprio ambiente; il verde globale non è dichiarato.

Controlli finali dopo il ripristino del mutante (stesso prefisso UV_CACHE_DIR):

- `uv run pytest tests/test_ollama_chat.py tests/test_llm_corrector.py tests/test_correction.py tests/test_study_models.py tests/test_study_citations.py -q`
  → `85 passed in 0.19s`.
- `uv run ruff check .` → `All checks passed!`.
- `uv run ruff format --check .` → `116 files already formatted`.
- `uv run mypy src tests` → `Success: no issues found in 101 source files`.
- `git diff --check` → exit 0.

CHECKS: code-reviewer ESEGUITO; test mirati e controlli statici ESEGUITI;
suite globale NON COMPLETATA; a11y-gate N/A (nessuna UI modificata).
ESITO: review, implementazione pronta per l'orchestratore, nessun commit.

## 2026-10-03 | Sessione #5 [FEATURE] Spazio del corso (specs/001-course-workspace)

### Richiesta

Implementare l'intero piano `001-course-workspace` con commit atomici su
`main`. Scelte dell'utente raccolte prima di procedere: OCR con `qwen2.5vl` in
una fase F5 separata (U1); conversazioni di chat salvate per corso ed
eliminabili (U2); le fonti citate dalla chat vengono solo dal materiale del
corso (U3); export anche in DOCX oltre a TXT (U4). Tutto locale, incluso
Ollama.

### Azioni Eseguite

- **F1-F2**: caricamento nel corso di documenti PDF, DOCX, PPTX e TXT;
  estrazione del testo in un processo figlio con limite di memoria; ricerca
  full-text su lezioni e documenti.
- **F3**: generazione in coda, dal modello locale `qwen3.5:9b`, di compiti
  d'esame (crocette, domande aperte, orale, massimo dieci domande) e
  riassunti, con citazioni verificate testualmente sul materiale del corso e
  i motivi degli scarti mostrati in pagina; export in TXT e DOCX. Misure in
  `specs/001-course-workspace/eval-generations.md`.
- **F4**: chat sul corso con risposte composte solo da frasi citate,
  conversazioni salvate in JSONL; arbitraggio della GPU fra chat e
  trascrizione con un lock lettori-scrittori, la chat risponde 409 se la GPU
  è occupata. Misure in `specs/001-course-workspace/eval-chat.md`: 8 risposte
  corrette su 8 dopo le correzioni, p50 a caldo 10,1 s.
- **F5**: OCR dei PDF scansionati con `qwen2.5vl:7b`, circa 270 s a pagina su
  CPU, pagine marcate come testo da OCR. Gate T059 valido al secondo
  tentativo: Whisper confermato su CUDA, zero campioni GPU sovrapposti su 289
  (`specs/001-course-workspace/eval.md`).
- Problema emerso durante F5: un `uv add pillow` lanciato da un agent ha
  disinstallato le librerie CUDA (extra opzionale `cuda`), e Whisper è
  passato su CPU senza errori visibili. Ripristinato con
  `uv sync --extra cuda`; il primo run di T059, eseguito su CPU, è stato
  dichiarato non valido e rilanciato.
- Remediation dopo `/analyze` (19 finding nella prima passata, 6 nella
  seconda): divisi `app.css` e sette file di test oltre le 300 righe; fonti
  delle generazioni registrate con avviso di "fonte modificata" in lettura;
  limiti al processo OCR (memoria, timeout a un'ora, render a 2500 px); 409
  su upload duplicato; avvisi OCR in UI; test che l'output del modello arriva
  come testo; rimossi cinque `# type: ignore`.
- Review di codice e sicurezza sul diff: un bug minore corretto (contatore
  dei poll OCR); nessun finding di sicurezza bloccante.

### Aperto a fine sessione

- Nessun task del piano aperto: T049 chiuso dopo tre passate di `/analyze`, i 43 criteri della
  Definition of Done spuntati con la prova di ciascuno.
- Limiti noti, misurati: con argomenti fatti di parole comuni i compiti possono pescare
  materiale fuori tema (T036); l'OCR costa circa 270 s a pagina su CPU.
- Nessun push: i commit sono su `main` in locale.

### File Modificati

| Area | Descrizione |
|---|---|
| `src/sbobina/course_registry.py`, `document_sniff.py`, `document_extract.py`, `pdf_text.py`, `web/extraction_worker.py`, `web/document_store.py`, `document_passages.py`, `web/document_index.py`, `search_schema.py` | Nuovo: workspace del corso, documenti e indice full-text (F1-F2) |
| `src/sbobina/retrieval.py`, `lecture_windows.py`, `source_sampling.py`, `web/course_retrieval.py`, `source_citations.py` | Nuovo: retrieval e citazioni sul materiale del corso |
| `src/sbobina/generation_pipeline.py`, `generation_validation.py`, `generation_render.py`, `docx_export.py`, `web/generation_runner.py`, `web/generation_queue.py`, `generation_supervisor.py`, `web/api_generations.py` | Nuovo: compiti d'esame e riassunti in coda (F3) |
| `src/sbobina/chat_pipeline.py`, `web/chat_turn.py`, `web/chat_store.py`, `web/api_chat.py`, `web/gpu_lock.py`, `web/transcription_gate.py` | Nuovo: chat sul corso e arbitraggio GPU (F4) |
| Moduli OCR su `qwen2.5vl:7b` (F5) | Nuovo: OCR dei PDF scansionati con limiti di memoria, timeout e render |
| `app.css`, sette file di test | Modificato: divisi sotto le 300 righe in remediation post `/analyze` |
| `specs/001-course-workspace/plan.md`, `tasks.md`, `eval.md`, `eval-chat.md`, `eval-generations.md` | Modificato: piano, task e misure |
| `CLAUDE.md` | Modificato: layout del progetto aggiornato ai nuovi moduli |
| `docs/REPORT_ATTIVITA.md` | Modificato: registro della sessione |

### Note per il Cliente

Ogni corso ha ora uno spazio proprio: si possono caricare dispense e slide
oltre alle lezioni registrate, farsi preparare in automatico simulazioni
d'esame e riassunti con le fonti verificate, e chattare sul materiale del
corso ottenendo solo risposte basate su frasi realmente presenti nei
documenti. Anche le dispense scansionate (foto o scansioni senza testo
selezionabile) vengono lette automaticamente. Audio, documenti e testi restano
sul computer: i modelli di trascrizione, generazione e OCR girano in locale.

### Riepilogo (Complessità / Stato)

Complessità alta: feature completa su cinque fasi, 81 commit su `main`.
Suite a 1503+ test verdi, ruff e mypy puliti. Piano completo, gate
finale T049 chiuso.

## 2026-10-06 - 02:04 | Sessione #6 [FEATURE]

### Richiesta

Completare la fase F4 del piano `specs/002-study-loop` (formule LaTeX con
KaTeX), applicare la remediation del gate `/analyze` (A14-A21) e chiudere i
punti aperti F40, F41 e F51, arrivando alla fine del piano. Commit atomici
su `main`.

### Azioni Eseguite

- T066, verifica XSS delle superfici con formule (c51d909): payload di
  classe C4 testati su generazioni, esercitazioni, ripasso, chat, studio e
  documento. Esito positivo, poi la verifica è stata estesa anche alle
  citazioni e agli errori mostrati in console.
- Correzione delle barre LaTeX nel JSON prodotto dai modelli (5e2bd04):
  `qwen` scriveva `\(` con una sola barra, rendendo illeggibili due risposte
  su tre; `chat_json` ora le raddoppia.
- T067, aggiornati i prompt `compito-v3`, `riassunto-v2`, `chat-v3` e
  `studio-v2` con le formule racchiuse fra `\(` e `\[` (46aeccb). Tolta poi
  l'indicazione "la barra si scrive doppia", che causava un doppio
  raddoppio (0687ae7).
- T068, misura V9 (55854c0, a74e051, 5dfe761): risultato finale 20
  generazioni su 20 riuscite al primo tentativo, una citazione scartata su
  89 (1%), zero su 75 con formula. T069a giudicato non necessario.
- T069, gate di fine fase F4: `code-reviewer`, `security-reviewer` (nessun
  finding P0/P1/P2), `a11y-gate` (axe zero violazioni in tema chiaro e
  scuro, MathML presente per lo screen reader su ogni formula), render
  osservato a 375 e 1280 px, `/analyze` con remediation A14-A21 applicata
  (4b706d6, b417424, d9a086b, bceb833, cc103f1).
- Correzioni emerse durante il gate: passaggi inviati su una sola riga, che
  facevano fallire due compiti su dieci (c8a59e3); formule nelle citazioni
  da documento, mentre quelle da lezione restano testo (b9c219a); titoli
  `\section` dell'OCR ripuliti (c09973e); formula non valida mostrata come
  testo semplice invece di violare la CSP (e582e0b); formule larghe
  contenute nella colonna, raggiungibili da tastiera e leggibili in tema
  scuro (c051593).
- F70, corretto il riassunto che proponeva "3 su 1 richieste" (887210f).
  F51, risolto il 404 sulla pagina della generazione aperta dalle carte
  del ripasso (e02509f).
- F40, corretti gli orali con argomento che fallivano al limite di token:
  ora le domande scritte vengono mantenute per intero (6e45600, 132852a).
  F81, le citazioni esatte oltre le 40 parole vengono accorciate alle
  prime 40 invece di far scartare la domanda (4e61247).
- F41, soluzioni a più punti: `compito-v4` chiede ora le "punti" come
  lista (5d93a99). Misurato 12 domande su 12 con 2 punti in sonda, 9
  domande con 2-4 punti sul corso reale; l'effetto sul giudice non è
  misurato, perché il dataset V6 era costruito per soluzioni a un punto.
  Documentazione in e79481a.
- Secondo `/analyze` di chiusura di T069 (`type-design-analyzer` e
  `silent-failure-hunter`): remediation A24-A31 applicata. A24 record di
  generazione corrotto ora loggato dietro il 404 (88af373); A25 risposta
  del modello illeggibile loggata con i primi 500 caratteri (45e86b8); A26
  la pagina della generazione distingue caricamento e rendering falliti
  (a9252e2); A27 avviso in console per errori di KaTeX che non sono LaTeX
  non valido (0c86ad7); A28 domanda con soluzione vuota scartata da sola,
  A29 il separatore " | " dentro un punto orale non lo divide più
  (7d198f8).
- A30: studio su una lezione reale, 0 citazioni oltre 40 parole (scarti:
  13 non trovate, 5 senza termine, 4 troppo corte), quindi i materiali di
  studio restano invariati (a6c2541).
- A31: nuovo set di valutazione del giudice (10 domande con `compito-v4`,
  30 risposte di Claude, provvisorio): accordo 28/30 in tre esecuzioni
  identiche, risposte a metà giudicate parziali 10/10 contro 5/7 prima,
  nessuna errata giudicata corretta, 2 complete su 10 giudicate parziali
  (6ec0178, script `scripts/eval_grading.py`).

### Verifiche

| Controllo | Risultato |
|---|---|
| `uv run pytest` | 2334 passed |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | pulito |
| `uv run mypy src tests` | pulito |
| `verify_math_xss` | PASS |
| `verify_math_text` | 11/11 |
| `a11y-gate` (axe) | 0 violazioni |
| Misura V9, citazioni scartate | 1/89 |
| Giudice (A31) | accordo 28/30, metà giudicate parziali 10/10 |

### Aperto a fine sessione

- 3 blocchi falliti nello studio della lezione misurata per A30, da
  indagare.
- Le pagine V10 e V9 sono sintetiche: le pagine reali del corso non sono
  state misurate.
- Nessun push: i commit restano locali su `main`.

### Note per il Cliente

Le formule matematiche scritte nei materiali del corso vengono ora mostrate
correttamente anche nella chat, negli esercizi e nei riassunti generati,
comprese le versioni accessibili per chi usa uno screen reader. Alcuni
problemi emersi durante i controlli sono stati corretti: frasi d'esame
troncate, titoli disordinati nei documenti scansionati e link che
portavano a una pagina inesistente. Il lavoro resta sul computer locale, in
attesa di essere caricato online.

### Riepilogo (Complessità / Stato)

Complessità alta: chiusura della fase F4 del piano `002-study-loop`,
remediation `/analyze` applicata, più quattro punti aperti da sessioni
precedenti (F40, F41, F51, F81) risolti. Suite a 2327 test verdi, ruff e
mypy puliti. Piano a fine percorso; restano aperte solo la misura del
giudice su `compito-v4` e il push.

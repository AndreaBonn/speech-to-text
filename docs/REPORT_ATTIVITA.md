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
- Blocchi dello studio troncati: su una lezione reale 3 blocchi su 5 si
  fermavano al limite di 2048 token dentro un capitolo, e un budget più
  alto non entra nel contesto (prompt da 4600-5250 token per blocco). Ora
  si tengono i capitoli scritti per intero, validati uno per uno: 0
  blocchi falliti invece di 3, 58 voci tenute invece di 31 (d803e43).
- Script di misura su slide reali del corso (10175f6): `eval_math_real.py`
  e `eval_citations_real.py`, con JSONL incrementale per riprendere la
  misura dopo un'interruzione.
- V10 su 9 slide reali di macroeconomia ("Lezioni 11 29 Ottobre.pdf"), rese
  dal PDF nativo come scansione simulata: 64 formule, tutte leggibili da
  KaTeX e senza simbolo `$`; 21 formule su 2 pagine controllate a mano,
  tutte corrette; 95-184 secondi a pagina su CPU.
- Corretto l'OCR (8c0bc09): le liste LaTeX (`\begin{itemize}`/`\item`)
  venivano trascritte come testo illeggibile; `_strip_latex_structure` in
  `ocr_pipeline.py` le trasforma ora in voci con trattino. Il difetto
  compariva su 2 delle 9 pagine misurate in V10.
- V9 richiusa sulle slide reali: 18 generazioni su 18 completate, 11
  citazioni scartate su 103 (11%), sotto la soglia del 20%; T069a resta
  chiuso. Cause degli scarti: 5 formule riscritte dal modello (per
  esempio `δk` al posto di `\delta k`), 2 formule sotto le 3 parole, 3
  citazioni che saltano testo o uniscono pagine diverse, 1 dovuta alle
  liste con `\item`. La misura si è interrotta una volta per un crash
  della GPU (CUDA unspecified launch failure, con riavvio della
  macchina) ed è ripresa dalle generazioni già salvate.
- Documentazione aggiornata in `specs/002-study-loop/eval-math.md` e
  `adr.md` con gli esiti V9 e V10 (61fe682).
- Fix 0cacd8f: un riassunto con JSON illeggibile interrompeva la generazione
  con `KeyError` invece di essere ritentato, una regressione introdotta da
  d803e43 (il recupero dei capitoli per lo studio). Ora viene ritentato e,
  se fallisce di nuovo, la generazione termina FAILED. Difetto trovato
  durante la misura sulle slide reali; aggiunto il test di regressione.
- Script di misura 2a3faa8: una pausa di 60 secondi prima di ogni
  generazione, con attesa che la GPU scenda sotto i 75°C, perché il laptop
  si era spento due volte con generazioni consecutive (alle 11:15 e alle
  11:33); con le pause non si è più spento.
- Secondo run V9 su testo OCR senza `\item`: 17 generazioni su 18 concluse
  DONE, 17 citazioni scartate su 111 (15%), tutte nei riassunti, 8 da un
  solo riassunto che scriveva le formule come testo semplice; nessuno
  scarto dovuto a `\item`. L'11% e il 15% sono variabilità fra run; T069a
  resta chiuso. Specifiche aggiornate in un commit successivo (docs(specs):
  record the second real-slide V9 run).
- Commit 40b431e: un riassunto che il modello rompe a metà ora tiene le
  sezioni complete, come i compiti (F40) e lo studio. La causa del
  riassunto fallito della pagina 4 non era il limite di token, come
  scritto prima: riprodotto con le risposte salvate, il modello copia
  nella citazione `Il "miglior" stato stazionario` senza fare l'escape
  delle virgolette e il JSON si rompe nella quarta sezione, identico a
  entrambi i tentativi; ora si tengono 3 sezioni su 4. Specifiche
  corrette in d90dc42.
- Commit fc8b99e: `chat_json` ripara le virgolette non escapate dentro i
  testi JSON quando una risposta non si legge, e tiene la riparazione
  solo se la risposta diventa leggibile, quindi una risposta valida non
  viene mai toccata. Sulla risposta reale della pagina 4 il riassunto si
  legge intero (4 sezioni su 4); la quarta sezione perde comunque le
  frasi perché le citazioni riscrivono la formula, causa già nota di V9.
  Il `code-reviewer` ha trovato un caso silenzioso (un elemento di lista
  con `", "` all'interno veniva diviso in due, per esempio un punto
  mancante del giudice): ora la riparazione rinuncia quando in una
  stringa resta un numero dispari di virgolette corrette. Test con il
  caso del reviewer.
- Provata in `normalize_tokens` l'equivalenza fra lettere greche Unicode e
  comandi LaTeX (`δk` letto come `\delta k`). Misura offline sulle citazioni
  salvate: 2 scarti recuperati su 21 sulle slide reali, nessuna citazione
  tenuta persa, nessun effetto sulle sintetiche. Guadagno marginale contro
  righe in più nel tokenizer di tutte le citazioni: modifica annullata e
  registrata fra i tentativi scartati in `specs/002-study-loop/eval-math.md`
  (0eb0d56).

### Verifiche

| Controllo | Risultato |
|---|---|
| `uv run pytest` | 2339 passed |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | pulito |
| `uv run mypy src tests` | pulito |
| `verify_math_xss` | PASS |
| `verify_math_text` | 11/11 |
| `a11y-gate` (axe) | 0 violazioni |
| Misura V9, citazioni scartate | 1/89 |
| Giudice (A31) | accordo 28/30, metà giudicate parziali 10/10 |
| V10 su slide reali, formule leggibili da KaTeX | 64/64 |
| V9 richiusa su slide reali, citazioni scartate | 11/103 (11%) |
| V9 su slide reali, testo senza `\item` | 17/111 (15%) |

### Aperto a fine sessione

- Non misurato: una scansione vera (V10 usa il PDF nativo come scansione
  simulata).
- La riparazione delle virgolette non copre una virgoletta seguita da
  due punti dentro un testo (sembra la fine di una chiave): quel caso
  resta illeggibile.
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

## 2026-10-06 | Sessione #7 [FEATURE]

### Richiesta

Workflow RPI sul branch `feature/003-cloud-providers`, piano in
`specs/003-cloud-providers/`: affiancare al motore locale dei provider cloud
opzionali per il testo e la trascrizione, con consenso esplicito e chiavi
gestite in sicurezza.

### Azioni Eseguite

- Il lavoro di testo (correzione, studio, generazioni, chat, correzione delle
  esercitazioni) può ora girare su una catena ordinata di modelli Groq,
  Gemini, OpenAI e Anthropic: se una richiesta fallisce per errore, limite di
  frequenza o quota esaurita, passa al modello successivo senza ripetere i
  blocchi già completati. Ollama locale resta un ultimo anello opzionale. Ogni
  risultato registra quale provider e modello lo ha prodotto (`served_by`).
- La trascrizione può usare AssemblyAI al posto di Whisper locale: a fine
  lavoro il trascritto remoto e l'audio caricato vengono eliminati dal
  servizio cloud, e non serve più riservare la GPU.
- Nuova pagina Impostazioni (`/impostazioni`): motore e ordine dei modelli,
  chiavi API (salvate in `credentials.json` con permessi 0600 nella cartella
  di configurazione dell'utente, mai sotto `data/` o nel repository, mostrate
  sempre oscurate), motore di trascrizione; consenso esplicito prima che testo
  o audio lascino il computer; avviso di chiavi mancanti su ogni pagina.
- Sicurezza: le chiavi vengono oscurate nei log e nelle tracce di errore,
  rimosse dall'ambiente dei processi figli che leggono file non fidati; la
  scrittura delle impostazioni richiede l'Origin dell'applicazione.

### Verifiche

| Controllo | Risultato |
|---|---|
| `uv run pytest` | 2705 passed |
| `uv run ruff check .` | pulito |
| `uv run mypy src tests` | pulito |
| `code-reviewer` / `security-reviewer` | eseguiti su ogni fase |
| Click-through browser su impostazioni e home | 25/25 |
| Render osservato | 375 px e 1280 px |
| Contrasto (chiaro/scuro, riposo/hover) | 0 sotto soglia |

Difetti trovati e corretti durante la verifica: stati HTTP non mappati che
interrompevano la catena dei provider invece di passare al successivo;
richieste GET alle impostazioni rifiutate senza Origin; errori nel log di
accesso di uvicorn causati dal filtro di oscuramento delle chiavi; la cache
della chat non si ricostruiva al cambio di chiave; riquadri di errore nascosti
ma ancora visibili; il tasto Escape lasciava selezionato un motore non
salvato.

### Aperto a fine sessione

- Le prove con i provider reali e la misura del WER su AssemblyAI restano da
  fare con le chiavi dell'utente.
- README, SECURITY e guida utente non aggiornati: si toccano solo su
  richiesta esplicita.
- I punti A3-A5, A7-A9, A11, A12 del gate `/analyze` attendono una decisione
  dell'utente.

### Note per il Cliente

Oltre al motore che gira sul computer, ora si può scegliere di usare servizi
cloud (Groq, Gemini, OpenAI, Anthropic, AssemblyAI) per il lavoro sul testo e
per la trascrizione: una nuova pagina Impostazioni permette di inserire le
chiavi di questi servizi, scegliere quale motore usare e in quale ordine, e
chiede sempre una conferma esplicita prima che testo o audio lascino il
computer. Le chiavi inserite restano protette: non finiscono nei file del
progetto, non compaiono nei log né negli errori mostrati a schermo, e sono
sempre visibili solo in forma oscurata. Durante le verifiche sono stati
trovati e corretti alcuni problemi (pagine che si bloccavano su un errore
imprevisto, impostazioni non salvate in certi casi) prima che il lavoro fosse
dichiarato concluso. Restano da fare: una prova con le chiavi reali
dell'utente e l'aggiornamento della documentazione.

### Riepilogo (Complessità / Stato)

Complessità alta: nuovo sottosistema di provider cloud per testo e
trascrizione, affiancato al motore locale senza sostituirlo. Suite a 2705
test verdi, ruff e mypy puliti, gate di sicurezza e accessibilità eseguiti su
ogni fase. Restano aperte le prove con chiavi reali, la misura del WER su
AssemblyAI, l'aggiornamento della documentazione e alcuni punti del gate
`/analyze` in attesa di decisione.

## 2026-10-07 | Sessione #8 [FEATURE]

### Richiesta

Implementare T022 di `specs/004-hybrid-retrieval/tasks.md` nel progetto
speech-to-text, sul branch `feature/dense-retrieval`: confine Ollama per
l'embedding, senza download automatici di modelli né chiamate reali nei test.

### Azioni Eseguite

- Creati `src/sbobina/ollama_embed.py` (217 righe) e
  `tests/test_ollama_embed.py` (274 righe). `embed_texts` invia batch da 32
  testi con `num_ctx=2048` e `truncate=False`; le query usano CPU
  (`num_gpu=0`) e `keep_alive="30m"`.
- Solo un HTTP 400 con `exceeds the context length` attiva il ripiego
  testo per testo. Il solo testo ancora troppo lungo viene ritentato con
  `truncate=True`: il risultato lo segnala e un WARNING registra
  `passage_id`, caratteri e `num_ctx`.
- Gli identificativi passano tramite `EmbeddingInput(text, passage_id)`;
  per le stringhe semplici si usa l'indice globale. La formattazione dei
  prompt resta al chiamante. `validate_dimensions` controlla separatamente
  la dimensione attesa dei vettori.
- `model_status(host, model)` restituisce digest e dimensioni da
  `client.list()` e `client.show()`. Cerca le dimensioni tramite il suffisso
  `.embedding_length`, senza vincolare la famiglia del modello. Le costanti
  HTTP sono locali; gli errori espongono `model_missing`, `unreachable` o
  `bad_response`. Nessuna chiamata a `pull`.
- Nessuna modifica a `ollama_chat.py`, `tests/conftest.py` o
  `web/vector_store.py`; nessun import o dipendenza dal vector store.
  Nessun cambio di branch, commit o push.

### Verifiche

BASIS: measured. Verifiche eseguite con `UV_CACHE_DIR=/tmp/uv-cache-t022`,
perché la cache nella home non era scrivibile.

| Controllo | Risultato |
|---|---|
| TDD su T022 | 40 casi osservati rossi su stub con `NotImplementedError`, poi 40 passed in 0,46 s |
| Copertura del nuovo modulo | 99%, 111 statement, uno non coperto |
| `uv run ruff check .` | PASS |
| `uv run mypy src tests` | PASS, 421 file |
| `code-reviewer` | APPROVE dopo correzione dell'asserzione su `None` segnalata da mypy |
| Prova runtime con fake client iniettato | Troncamento selettivo, WARNING, opzioni query ed errori verificati; `pull_calls=0` |
| `git diff tests/conftest.py` e `git diff src/sbobina/ollama_chat.py` | Vuoti |
| Suite completa `uv run pytest` | Interrotta al 58%, exit 130; nessun riepilogo finale disponibile |

I log mirati sono in `/tmp/pytest_t022_red.log` e
`/tmp/pytest_t022_targeted.log`. La prova runtime usa un fake client senza
rete: non è stata eseguita alcuna prova contro Ollama reale.

### Aperto a fine sessione

La suite completa resta ferma su
`tests/web/test_api_cards.py::test_create_card_current_revision_accepts_without_matching`,
come già nella baseline precedente all'implementazione. Una prova isolata,
terminata per timeout dopo 25 secondi (exit 124), mostra l'attesa in Starlette TestClient/AnyIO
`future.result`; log in `/tmp/pytest_t022_web_probe.log`. La causa non è
stata accertata e il file è fuori dal perimetro della delega.
Il log completo è `/tmp/pytest_t022.log`: il grep richiesto non restituisce
righe di riepilogo. La suite completa non può quindi essere dichiarata verde.

### Note per il Cliente

È pronto il componente che converte i testi in vettori per la ricerca per
significato. Segnala quali testi sono stati accorciati e non scarica modelli
da solo. I controlli sul componente passano; per chiudere il lavoro resta
da completare la verifica dell'intera applicazione, ferma su un test già
bloccato prima di queste modifiche.

### Riepilogo (Complessità / Stato)

Complessità media. T022 implementato e verificato con client simulato;
stato `review` perché manca l'esito della suite completa. Applicate le
skill `verify` e `scrivi-italiano`. PROVENANCE: codex.

## 2026-10-07 - 17:34 | Sessione #9 [FEATURE]

### Richiesta

Implementare T025 e T028 di `specs/004-hybrid-retrieval/tasks.md`, secondo il piano § C2, nel progetto speech-to-text sul branch `feature/dense-retrieval`, preservando le modifiche degli altri task e senza commit.

### Azioni Eseguite

- Aggiunta riconciliazione da disco: documenti `READY`, trascrizioni preferite e finestre di lezione. Il manifesto viene sincronizzato prima dell'embedding; spariscono le unità rimosse e si ricalcolano solo gli hash grezzi mancanti.
- Formattazione del testo prima dell'embedding e validazione delle dimensioni su ogni batch. Scrittura atomica per batch: un errore si propaga al chiamante, mentre i batch già scritti restano disponibili.
- Una sola istanza di `VectorStore` per esecuzione CLI. Chiave riusabile `embedding_model_key(model, status)`, nel formato `modello@versione_prompt:digest:dimensioni:num_ctx`.
- Introdotte `EmbeddingConfig(model, status, embedder)`, `CourseEmbedding(store, vectors, embedding)` ed `EmbeddingProgress(processed, total, truncated, units_per_second)`; firma `embed_course(context, course_key, progress) -> EmbeddingProgress`.
- Comando `cmd_indicizza_semantico(args, embedding=None) -> int`, registrato come `sbobina indicizza-semantico --corso <chiave> | --tutti`. Mostra copertura, troncati e unità/s; modello assente: istruzione `ollama pull <modello>` ed exit 2; corso inesistente: errore chiaro ed exit 1.
- Il throughput conta le nuove unità coperte, comprese quelle con testo duplicato, sul tempo totale. Le unità già in cache contribuiscono alla copertura, senza aumentare il throughput.
- In `search_service.py` rese pubbliche solo `preferred_transcript`, `ready_document_state` e `read_document_passages`, aggiornando i chiamanti interni. Nessuna modifica agli altri componenti già pronti o al guard in `tests/conftest.py`.

### File Modificati

| File | Tipo | Righe / descrizione |
|---|---|---|
| `src/sbobina/web/vector_reconcile.py` | Nuovo | 185; riconciliazione e progresso |
| `src/sbobina/cli_semantic.py` | Nuovo | 108; comando e registrazione parser |
| `src/sbobina/cli.py` | Modificato | 237; collegamento al nuovo comando |
| `src/sbobina/web/search_service.py` | Modificato | 283; nomi pubblici delle tre funzioni |
| `tests/web/test_vector_reconcile.py` | Nuovo | 215; 9 test di riconciliazione |
| `tests/test_cli_semantic.py` | Nuovo | 121; 8 test CLI, output con `capsys` e `caplog` |
| `tests/vector_reconcile_fixtures.py` | Nuovo | 98; filesystem e embedder simulato |
| `docs/REPORT_ATTIVITA.md` | Modificato | Append della sessione; storico già a 865 righe |

### Verifiche

| Controllo | Risultato e provenienza |
|---|---|
| TDD T025 | 9 failed su stub → 9 passed. PROVENANCE: measured; `/tmp/t025-red.log`, `/tmp/t025-green.log` |
| TDD T028 | 6 failed, 2 passed → 8 passed; i due casi di errore parser erano già verdi con comando ignoto. PROVENANCE: measured; `/tmp/t028-red.log`, `/tmp/t028-green.log` |
| Test mirati e regressioni CLI/ricerca | 71 passed in 3,19 s. PROVENANCE: measured; `/tmp/t025-targeted.log` |
| Copertura dei due nuovi moduli | `vector_reconcile` 99%, `cli_semantic` 93%, totale 97%. PROVENANCE: measured; `/tmp/t025-targeted.log` |
| `uv run ruff check .` | All checks passed. PROVENANCE: measured; `/tmp/t025-ruff.log` |
| `uv run mypy src tests` | Nessun problema su 426 file. PROVENANCE: measured; `/tmp/t025-mypy.log` |
| Baseline | Ruff e mypy verdi, 421 file; pytest interrotto al 58%, exit 130. PROVENANCE: measured |
| Suite completa `uv run pytest` | Timeout a 60 s, exit 124, ancora al 58%; nessun riepilogo finale. PROVENANCE: measured; `/tmp/t025-pytest.log` |
| Runtime CLI con client simulato | Copertura 0/2 → 2/2; secondo giro senza nuove chiamate; corso ignoto exit 1; nuovo documento e modello assente: exit 2, `ollama pull`, copertura 2/3 conservata. PROVENANCE: measured; `/tmp/t025-runtime.log` |
| Review indipendente | `code-reviewer`: APPROVE; 17 passed, ruff e mypy verdi. PROVENANCE: measured |
| Dimensioni e integrità del diff | `wc -l src/sbobina/cli.py`: 237 ≤ 300; funzioni nuove entro 29 righe nel codice e 28 nei test; `git diff --check` pulito; diff di `tests/conftest.py` vuoto. PROVENANCE: measured |

I test usano un embedder simulato; nessuna chiamata reale a Ollama. I nove casi T025 comprendono cache 100/120, errore al secondo batch, testo modificato, esclusione dei documenti non pronti e conteggio dei troncamenti. PROVENANCE: measured.

### Aperto a fine sessione

La suite completa si ferma su `tests/web/test_api_cards.py::test_create_card_current_revision_accepts_without_matching`, anche nella baseline. La sonda isolata termina dopo 20 s e mostra un'attesa AnyIO/Starlette su thread; la causa non è accertata. PROVENANCE: measured; `/tmp/t025-hang-probe.log`. Per chiudere la verifica occorre risolvere questa attesa e ottenere il riepilogo della suite completa.

### Note per il Cliente

Il nuovo comando prepara i testi di un corso, o di tutti i corsi, per la ricerca per significato. Riutilizza il lavoro già salvato, mostra quanto manca e segnala i testi accorciati. Se il modello manca, indica come scaricarlo. Le prove mirate passano con un servizio simulato; resta da completare il controllo dell'intera applicazione.

### Riepilogo (Complessità / Stato)

Complessità media. T025 e T028 implementati; `ESITO: review`, perché la suite integrale non è terminata. Comandi git eseguiti che modificano il working tree: `[]`. Report aggiornato solo in append, con eccezione al limite di 300 righe per lo storico preesistente. Applicata la skill `scrivi-italiano`.

## 2026-10-07 | Sessione #10 [FEATURE]

### Richiesta

Implementare T026 e T034 di `specs/004-hybrid-retrieval/tasks.md` nel progetto
speech-to-text, sul branch `feature/dense-retrieval`: ricerca densa e instradamento
della ricerca nei corsi, con ritorno integrale a BM25 quando la copertura è incompleta.
Il contratto riprende la forma misurata in F1; questa sessione non ripete la misura
su 82 domande, prevista da T032.

### Azioni Eseguite

- Creato `DenseRanker` in `src/sbobina/web/dense_retrieval.py`. Lo spostamento sotto
  `web/`, ammesso dalla richiesta, mantiene l'I/O fuori dai moduli puri del core.
  Il client di embedding è iniettato tramite il Protocol esistente `EmbeddingClient`.
- Riutilizzata `embedding_model_key(model, status)` da `web/vector_reconcile.py`.
  L'import nel costruttore evita il ciclo con `course_retrieval`; il modulo di
  riconciliazione e `cli_semantic.py` non sono stati modificati da questo intervento.
- Documenti e lezioni hanno liste dense distinte, ciascuna limitata a 50 candidati
  con `CANDIDATE_LIMIT` riusato da `retrieval.py`. `top_k_cosine` applica la soglia
  del modello; `fuse_by_rank` riceve `(-cosine, passage)`.
- Riutilizzati i passaggi documentali FTS e le finestre complete della partizione
  delle lezioni, tramite `_document_groups`, `_lecture_groups` e `_lecture_windows`.
  Gli ID restano quelli documentali e `L{job_id}-S{segment_index}`; le finestre dense
  non crescono attorno a un hit. `selected` filtra sia documenti sia lezioni.
- Le query passano da `format_query` ed `embed_texts(mode="query")`, con CPU e
  opzioni già definite dal confine Ollama. Errori del modello, di rete o di dimensione
  producono un report BM25 e un WARNING con modello, motivo e traceback.
- `RetrievalReport.coverage` riusa `Coverage | None`. Senza ranker il report è
  `("bm25", None, None)`; con copertura piena è `("dense", None, coverage)`.
  Copertura 118/120 produce `partial`, zero vettori `not_indexed`.
- `retrieve_windows_with_report` sceglie il percorso e restituisce anche il report;
  `retrieve_windows` conserva i tre parametri posizionali e aggiunge `dense` come
  keyword-only. Senza ranker resta la sequenza BM25, espansione e taglio al budget.
  Con copertura piena, anche una domanda senza termini FTS usa il percorso denso.
  Se nessun coseno supera la soglia, il risultato denso rimane vuoto.
- Aggiunto `VectorStore.data_version() -> int`: token locale basato su
  `PRAGMA data_version`, letto dalla stessa connessione osservatrice di sola lettura
  protetta da lock. Identità del file e `close()` gestiscono sostituzione e riapertura;
  nessuna connessione SQLite viene aperta dal ranker.
- La cache delle matrici usa `(model_key, data_version, tuple(passages))` sotto lock.
  La selezione entra nella chiave; hash del testo e controlli della versione prima e
  dopo le letture evitano risultati densi con testi obsoleti o manifesti cambiati
  durante il calcolo. In entrambi i casi il report richiede BM25 con `partial`.

### Firme Pubbliche

```python
DenseRanker.__init__(self, *, vectors: VectorStore, model: str, status: ModelStatus, client: EmbeddingClient) -> None
DenseRanker.rank(self, *, course: str, passages: list[RetrievedPassage], question: str) -> tuple[list[RetrievedPassage], RetrievalReport]
RetrievalReport.__init__(self, mode: Literal["dense", "bm25"], reason: str | None, coverage: Coverage | None) -> None
retrieve_windows(store: JobStore, index: SearchIndex, query: WindowedQuery, *, dense: DenseRanker | None = None) -> list[RetrievedPassage]
retrieve_windows_with_report(store: JobStore, index: SearchIndex, query: WindowedQuery, *, dense: DenseRanker | None = None) -> tuple[list[RetrievedPassage], RetrievalReport]
```

### File Modificati

| File | Tipo | Righe (`wc -l`) |
|---|---|---:|
| `src/sbobina/web/dense_retrieval.py` | Nuovo | 171 |
| `src/sbobina/web/course_retrieval.py` | Modificato | 252 |
| `src/sbobina/web/vector_store.py` | Modificato | 290 |
| `tests/dense_retrieval_fixtures.py` | Nuovo | 64 |
| `tests/web/test_dense_retrieval.py` | Nuovo, 17 casi | 214 |
| `tests/web/test_dense_course_retrieval.py` | Nuovo, 8 casi | 236 |
| `tests/web/test_vector_store_version.py` | Nuovo, 4 casi | 72 |
| `docs/REPORT_ATTIVITA.md` | Append della sessione | Storico preesistente di 924 righe |

### Test e Ciclo Rosso-Verde

I tre file nuovi contengono 23 funzioni e 29 casi, incluse le parametrizzazioni.
Nella tabella, R indica la raccolta iniziale rossa di
`uv run pytest tests/web/test_dense_retrieval.py` per modulo assente
(`/tmp/dense-ranker-red.log`); C indica quella di
`uv run pytest tests/web/test_dense_course_retrieval.py` per export assente
(`/tmp/dense-routing-red.log`). Sono errori di raccolta, non fallimenti delle singole
asserzioni. V indica i quattro `AttributeError` osservati prima di implementare
`data_version`, poi quattro casi verdi. Tutti i casi elencati passano nel controllo finale.

| Funzione di test | Comportamento e prova rosso → verde |
|---|---|
| `test_rank_highest_cosine_is_first_after_fusion` | Coseno maggiore primo, prefisso query e opzioni CPU esatti; R → verde; ulteriore mutazione `+cosine` in memoria: 1 failed → verde col segno corretto (`/tmp/dense-sign-red.log`). |
| `test_rank_keeps_fifty_candidates_per_source_before_fusion` | Due liste di 50, fuse preservando entrambe le fonti; R → verde. |
| `test_rank_applies_only_the_model_threshold` | Soglia del modello noto e nessuna soglia per modello non misurato, 2 casi; R → verde. |
| `test_rank_incomplete_course_returns_bm25_report` | 118/120 produce `partial`, 0/120 `not_indexed`, senza chiamare il client; R → verde. |
| `test_rank_embedding_failure_returns_report` | Cinque errori diventano report senza propagazione, con diagnostica; R → verde; WARNING incompleto: 5 failed → verde dopo il fix (`/tmp/dense-diagnostics-red.log`). |
| `test_rank_bad_query_dimensions_returns_bad_response` | Dimensione query errata produce `bad_response`; R → verde. |
| `test_rank_changed_text_rejects_stale_complete_manifest` | Testo modificato invalida il risultato anche con manifesto completo; R → verde. |
| `test_rank_reuses_matrix_and_invalidates_on_external_commit` | Riusa la matrice e cambia ordinamento dopo un commit esterno; R → verde. |
| `test_rank_cache_distinguishes_selected_passages` | La cache distingue la selezione mantenendo la copertura del corso; R → verde. |
| `test_rank_manifest_commit_during_read_falls_back` | Commit concorrente sul manifesto produce `partial`; 1 failed prima del fix → verde (`/tmp/dense-concurrency-red.log`). |
| `test_rank_other_model_has_no_index_and_empty_scope_has_no_hits` | Vettori di altro modello e corso vuoto producono `not_indexed`; R → verde. |
| `test_retrieve_dense_without_fts_terms_and_budget` | Query senza termini FTS trova il passaggio denso entro budget; C → verde. |
| `test_retrieve_partial_course_preserves_bm25_results` | Copertura 118/120 restituisce gli stessi risultati BM25; C → verde. |
| `test_retrieve_no_dense_reports_plain_bm25` | Senza ranker conserva risultati e report BM25 neutro; C → verde. |
| `test_retrieve_lecture_keeps_partition_tail_without_growth` | Finestra finale di 140 parole senza segmenti precedenti; C → verde. |
| `test_retrieve_selected_filters_lectures_and_documents` | `selected` include solo le lezioni o i documenti scelti; C → verde. |
| `test_retrieve_partial_course_still_falls_back_with_complete_selection` | Selezione completa dentro corso parziale resta BM25; C → verde. |
| `test_retrieve_lecture_only_course_resolves_key_without_registry_id` | Corso di sole lezioni risolto senza UUID; test aggiunto dopo il codice, mutazione della risoluzione: rosso → verde (`/tmp/dense-routing-mutation-red.log`). |
| `test_retrieve_dense_below_threshold_does_not_fall_back_to_lexical_hits` | Risultato denso vuoto resta tale anche con hit BM25; test aggiunto dopo il codice, mutazione del ripiego: rosso → verde nello stesso log. |
| `test_data_version_stays_stable_on_reads_and_changes_after_local_write` | Token stabile sulle letture e nuovo dopo una scrittura della stessa istanza; V → verde. |
| `test_data_version_detects_other_instance_and_external_connection_writes` | Rileva commit da altra istanza e connessione SQLite esterna; V → verde. |
| `test_data_version_detects_recovery_and_reads_replacement_database` | Rileva ricostruzione del database e legge la nuova copertura; V → verde. |
| `test_data_version_supports_threads_and_close_invalidates_previous_stamp` | Letture da thread concordi, chiusura ripetibile e nuovo token alla riapertura; V → verde. |

Le mutazioni del segno e dell'instradamento sono state applicate in memoria tramite
plugin di test, senza alterare i file del repository. Filesystem e SQLite sono reali
su directory temporanee; il client di embedding è simulato e non contatta Ollama.

### Verifiche

BASIS: measured. Esiti raccolti dall'orchestratore e dai reviewer; i log in `/tmp`
sono artefatti temporanei della sessione.

| Controllo | Risultato |
|---|---|
| Test mirati finali e regressioni della ricerca | 60 passed in 8,36 s; `/tmp/dense-final-targeted.log` |
| Copertura misurata | `dense_retrieval` 100%, `course_retrieval` 99%, totale 99%; stesso log |
| Regressioni estese, prima degli ultimi fix locali | 1754 passed, 1 warning in 21,15 s; `/tmp/dense-regression.log`; dopo i fix rieseguiti i 60 test mirati |
| `uv run pytest -v`, limite 180 s | Exit 124, 1708 PASSED e nessun FAILED osservati; arresto al 58%, senza riepilogo finale (`/tmp/dense-full-pytest.log`) |
| `uv run ruff check .` | All checks passed |
| `uv run mypy src tests` | Success: no issues found in 431 source files |
| Dimensioni e integrità | File di codice entro 300 righe, funzioni nuove entro 30; `git diff --check` pulito |
| `code-reviewer` | APPROVE dopo il fix della lettura concorrente |
| `silent-failure-hunter` | PASS dopo il fix della diagnostica WARNING |
| Prova runtime dell'API di libreria | `retrieve_windows_with_report` su SQLite reale e client simulato: BM25 0/0, denso 1/1 su stopword, BM25 con modello assente e BM25 1/2; `/tmp/dense-runtime.log` |
| Opzioni runtime embedding | Prefisso query esatto, `num_gpu=0`, `num_ctx=2048`, `keep_alive="30m"`; stesso log |
| Analisi di coerenza | Perimetro T026/T034 coerente con piano e task; `spec.md` assente, requisiti della richiesta mappati ai test |

CHECKS: code-reviewer PASS; verify dell'API di libreria PASS; command-analyze sul
perimetro dei due task PASS; suite completa BLOCKED dal sandbox; a11y N/A perché
non è stata modificata l'interfaccia. Nessuna prova HTTP della UI o inferenza reale.

Rispetto al piano, il percorso sotto `web/` e il valore `mode="bm25"` al posto di
`lexical` seguono le alternative autorizzate dalla richiesta di questa sessione.

### Aperto a fine sessione

La suite completa resta ferma su
`tests/web/test_api_cards.py::test_create_card_current_revision_accepts_without_matching`,
anche nella baseline interrotta dopo diversi minuti con exit 130. Il dump della
prova isolata è in `/tmp/dense-api-hang.log` (dump a 120 s, timeout a 180 s).
La sonda `/tmp/dense-testclient-probe.py` riproduce il problema nel portale AnyIO
senza il progetto: `asyncio.selector_events._write_to_self` riceve `PermissionError`
con `EPERM` da `csock.send`. Il sandbox blocca il socket usato fra thread; non è
stato applicato un aggiramento. La suite completa non è dichiarata verde.

Il warning delle regressioni è una deprecazione Starlette relativa a httpx, con
suggerimento di passare a httpx2; non segnala un guasto attuale e non sono state
cambiate dipendenze. La sincronizzazione del manifesto appartiene a T025;
l'integrazione nelle schermate e nella chat resta a T030/T031. `tasks.md` invariato.

### Note per il Cliente

Il componente di ricerca può usare il significato della domanda quando tutti i
materiali del corso sono pronti. Se manca una parte dell'indice o il servizio non
risponde, usa la ricerca già disponibile e segnala il motivo. Le prove sul componente
passano; la verifica dell'intera applicazione resta da completare in un ambiente
che consenta le comunicazioni interne richieste dai test.

### Riepilogo (Complessità / Stato)

Complessità media. T026/T034 implementati; `ESITO: review` per la suite completa
bloccata dall'ambiente. Comandi git che modificano il working tree: zero; branch
immutato, nessun commit. Report aggiornato solo in append; applicata `scrivi-italiano`.

PROVENANCE: riusati senza modifiche partizioni e gruppi di `course_retrieval`, ID
FTS, `CANDIDATE_LIMIT`, `top_k_cosine`, `fuse_by_rank`, `format_query`, `embed_texts`,
`content_hash`, `Coverage` ed `embedding_model_key`. `hybrid_eval.dense_candidates`
è solo il riferimento del segno, non un import. Nuovi il ranker, il report, la cache,
l'instradamento, l'osservatore della versione SQLite e i test descritti sopra.

## 2026-10-07 | Sessione #11 [FEATURE]

### Richiesta

Implementare T040 e T041 di `specs/004-hybrid-retrieval/tasks.md` nel progetto speech-to-text, branch `feature/dense-retrieval`: indicizzazione semantica per corso nella coda del supervisor, annullamento e arbitraggio GPU con la chat. Nessun comando git che modifichi il working tree.

### Azioni Eseguite

- Aggiunta l'azione `embed` alle tabelle di dispatch di `course_actions`, a `WorkItem` e al dispatcher CLI. Il figlio parte tramite `processes._spawn`, scrive l'avanzamento e chiama `embed_course` con client Ollama e `VectorStore` reali in produzione. Una seconda richiesta sullo stesso corso già in coda o in esecuzione produce `EMBED_ALREADY_QUEUED`.
- Nuovo record immutabile `EmbeddingRun(status, processed, total, error)` in `courses/<course_id>/embedding.json`, salvato atomicamente. `EmbeddingStatus` distingue `QUEUED`, `RUNNING`, `DONE`, `FAILED`, `CANCELLED`; gli invarianti impongono `0 <= processed <= total` e un errore presente esattamente nello stato `FAILED`.
- L'annullamento rimuove l'azione in attesa oppure termina il figlio; conserva progresso e vettori dei batch già salvati. Al riavvio, le azioni `QUEUED` tornano in coda e quelle `RUNNING` diventano `CANCELLED`. Un `Event` conserva anche l'annullamento arrivato prima dell'ingresso nella lease.
- `execute_embed_action` prende `transcription_lease(stage="embedding")`; chiama `unload_ollama_models` prima del figlio e nel `finally` successivo. Il rilascio invia `keep_alive=0` anche al modello di embedding. `LeaseCancelledError` chiude l'azione senza avviarla.
- Stima calcolata sul corpus corrente con `count_missing_units(...) / EMBEDDING_UNITS_PER_SECOND`: la costante vale `1.7`, con riferimento a T032/T033. Include materiali aggiunti dopo l'ultima indicizzazione. Il client dei batch usa `max(settings.embedding_timeout_s, 180.0)`, perché T033 ha misurato un batch da 117,8 s con ricarico.
- Chat locale: il controllo dell'arbiter precede la ricerca e restituisce 409 `GPU_BUSY`, stage `embedding`, stima e messaggio «GPU occupata da un'indicizzazione semantica». La firma pubblica di `GpuBusyError` resta invariata.
- Chat API: `ChatServices` passa lo stesso arbiter attraverso `WindowedQuery` a `DenseRanker.rank(arbiter=...)`. Qualsiasi writer attivo o in attesa produce BM25 con `reason="gpu_busy"`, senza chiamare l'embedding della query; la risposta HTTP resta 200. La scelta segue il ricarico osservato da T033/R12.

### Firme Pubbliche

```python
submit_embed(supervisor: Supervisor, course_key: str) -> EmbeddingRun
cancel_embed(supervisor: Supervisor, course_key: str) -> None
execute_embed_action(supervisor: Supervisor, item: WorkItem, ollama_unavailable_exit: int) -> None
submit_embed_item(store: JobStore, course_key: str) -> tuple[EmbeddingRun, WorkItem]
cancel_embed_item(store: JobStore, course_key: str) -> WorkItem
create_embed(course_dir: Path) -> EmbeddingRun
load_embed(course_dir: Path) -> EmbeddingRun | None
save_embed(course_dir: Path, record: EmbeddingRun) -> None
finish_embed(course_dir: Path, status: EmbeddingStatus, error: str | None = None) -> None
run_embed(course_dir: Path, embed: Callable[..., EmbeddingProgress]) -> None
run_embed_stage(course_dir: Path) -> None
estimate_embed_seconds(course_dir: Path) -> float
```

### File Modificati

Righe misurate con `wc -l`; i percorsi raggruppati hanno lo stesso prefisso dichiarato.

| Area | File:righe |
|---|---|
| Nuovi moduli, `src/sbobina/web/` | `embedding_queue.py:40`, `embedding_runner.py:109`, `embedding_store.py:68`, `embedding_supervisor.py:189` |
| Coda e GPU, `src/sbobina/web/` | `course_actions.py:181`, `gpu_lock.py:140`, `job_models.py:169`, `stage_runner.py:295`, `supervisor.py:294` |
| Ricerca e chat, `src/sbobina/web/` | `chat_turn.py:233`, `course_retrieval.py:255`, `dense_factory.py:159`, `dense_retrieval.py:216`, `vector_reconcile.py:195` |
| Nuovi test, `tests/web/` | `embedding_fixtures.py:106`, `test_embedding_chat.py:52`, `test_embedding_dense.py:97`, `test_embedding_lifecycle.py:159`, `test_embedding_runner.py:173`, `test_embedding_stage.py:52`, `test_embedding_store.py:68`, `test_embedding_supervisor.py:160` |
| Test modificati, `tests/web/` | `test_chat_dense_turn.py:140`, `test_chat_dense_integration.py:124`, `test_chat_dense_wiring.py:74` |
| Report | `docs/REPORT_ATTIVITA.md`, sola append; storico preesistente di 1096 righe |

### Scelte Rispetto alla Sintesi Iniziale

L'arbiter vive in `app.state`, non in `dense_factory`: passa quindi per il percorso della chat fino a `rank`, senza aggiungerlo al costruttore del ranker condiviso. La modifica minima a `dense_factory` espone `vector_store_for_process`, riusando una sola istanza per processo. `vector_reconcile` espone il conteggio delle unità mancanti per una stima aggiornata. `chat_turn` anticipa il controllo locale per evitare una query di embedding prima del 409.

`supervisor.py` scende da 299 a 294 righe tramite helper di recupero e interruzione in `course_actions`; non introduce metodi `submit_embed` o `cancel_embed`. `gpu_release.py` resta invariato. Nessun endpoint, accodamento automatico, backfill o indicizzazione a fette: sono fuori dal perimetro T040/T041.

Analisi di coerenza sul perimetro dei due task: nessun rilievo critico. La verifica preesistente di T031 prevede la query densa durante un writer, mentre T041 e la richiesta corrente prescrivono BM25 dopo la misura R12; prevale questo contratto successivo. Le specifiche e le spunte dei task restano invariate, perché non incluse fra i file da modificare.

### Verifiche

BASIS: measured. L'orchestratore e gli agent incaricati hanno eseguito i controlli sotto riportati; il redattore ne registra gli esiti comunicati e le evidenze lette nei log. Nessuna chiamata reale a Ollama nei test.

| Controllo | Risultato |
|---|---|
| TDD iniziale | Raccolta rossa per `embedding_supervisor` assente, `/tmp/sbobina-embed-red.log`; errore di import, non fallimento di asserzione |
| TDD comportamentale | `test_cancel_before_lease_registration_does_not_wait_for_reader`: timeout a 5 s → verde; recupero di JSON con `processed: null` e radice `null`: due `TypeError` → verde; dispatcher: quattro `AttributeError` per `run_embed_stage` assente → verde |
| TDD ricerca e GPU | Sei casi rossi e uno già verde prima di introdurre arbiter, helper e label; indice incompleto con writer: motivo `not_indexed` invece di `gpu_busy` → verde |
| Test mirati coda e GPU | 24 passed in 3,81 s: `test_embedding_supervisor.py`, `test_embedding_lifecycle.py`, `test_gpu_lock.py`; coda unica, annullamento, lease, recupero ed errori |
| Test mirati chat e ricerca | 19 passed in 6,20 s con launcher diagnostico a 50 ms: HTTP, ranker e turno di chat |
| Test mirati runner e persistenza | 26 passed, inclusi 17 nuovi: runner, store e riconciliazione |
| Regressioni del contratto chat | Tre test preesistenti aggiornati dopo il rosso della suite: BM25 senza query durante il writer e ripresa densa dopo; 7 passed in 1,24 s nei due file di integrazione e collegamento dei componenti |
| Copertura dei nuovi moduli | 50 test passed in 5,01 s; 190 statement, 2 non coperti, totale 99%: queue 95%, runner 100%, store 100%, supervisor 99% |
| `uv run ruff check .` | PASS |
| `uv run mypy src tests` | PASS, 453 file |
| Baseline `uv run pytest`, timeout 240 s | FAIL, exit 124 prima del primo test HTTP; `/tmp/sbobina-baseline-tests.log`. `socketpair.send` riceve `EPERM` e impedisce il risveglio del loop asyncio |
| Suite completa con launcher diagnostico, prima prova | Exit 124 al 68%, nessun errore osservato; timeout 300 s, attesa `select` limitata a 50 ms, troppo lenta per i numerosi scambi fra thread. Log `/tmp/sbobina-full-tests.log` |
| Suite completa con launcher diagnostico a 1 ms, prima prova | 4 failed, 3024 passed, 2 warnings, 2 errors in 93,45 s: tre aspettative del vecchio contratto chat corrette; tre casi TCP impediti dal sandbox. Timeout 600 s, log `/tmp/sbobina-full-tests-fast-poll.log` |
| Suite completa con launcher diagnostico, prova finale | FAIL, exit 1: 1 failed, 3027 passed, 2 warnings, 2 errors in 91,52 s; timeout 600 s, nessuno skip o xfail. `/tmp/sbobina-pytest-selector.py` limita l'attesa di `select` a 1 ms senza cambiare il repository; log `/tmp/sbobina-full-tests-final.log` |
| Review | Tre rilievi corretti; analisi dei tipi senza rilievi bloccanti. Review finale APPROVE anche sui test aggiornati, senza adattamenti opportunistici; revisione di errori e fallback senza nuovi rilievi |
| Prova runtime | API pubbliche `course_actions`, vero supervisor e figlio con `run_embed`/`embed_course`, SQLite e filesystem reali; client simulato. Duplicato: `EMBED_ALREADY_QUEUED`, coda 1; avanzamento 32/33; lease `embedding`, stima 10 s, label corretta |
| Annullamento e ripresa runtime | Figlio terminato con exit -15; stato `CANCELLED`, progresso e copertura 32/33, due chiamate alla funzione di scarico simulata. Nuovo invio: `DONE`, progresso e copertura 33/33; arbiter finale `(None, None)` |
| Rilascio del modello | Nei test di ciclo di vita il fake client riceve `generate(..., keep_alive=0)`; distinto dal conteggio della funzione simulata nella prova runtime |
| Dimensioni | Controllo AST su tutti i file Python nuovi e modificati: zero violazioni dei limiti di 300 righe per file, 30 per funzione, 4 parametri |

I tre casi residui sono `test_is_port_available_free_port_returns_true`, `test_is_port_available_busy_port_returns_false` e `test_run_server_busy_port_exits_1_without_starting`, tutti in `tests/web/test_launcher.py`: la creazione del socket TCP fallisce con `PermissionError: [Errno 1] Operation not permitted` in `/usr/lib/python3.12/socket.py:233`. Test e launcher del progetto restano invariati. I due warning riguardano la fixture già importata dal launcher diagnostico e la deprecazione Starlette/httpx. La suite standard va rieseguita in un ambiente che consenta i socket; il risultato del launcher diagnostico non equivale a un PASS di `uv run pytest`.

### Note per il Cliente

L'indicizzazione di un corso può entrare in coda ed essere annullata senza perdere il lavoro già salvato. Durante l'elaborazione la chat locale segnala l'attesa prevista; quella con servizi API continua a usare la ricerca per parole. I comandi nell'interfaccia saranno aggiunti nei task successivi.

### Riepilogo (Complessità / Stato)

Complessità media. `ESITO: review`: implementazione, test mirati e prova runtime verificati; suite completa non verde per i tre casi TCP impediti dal sandbox. Comandi git che modificano il working tree eseguiti: zero. Report aggiornato solo in append, preservando lo storico preesistente; applicata la skill `scrivi-italiano`. Nessuna modifica frontend: gate a11y non applicabile.

PROVENANCE: l'orchestratore ha letto per intero `CLAUDE.md`, tutti i file guida e di contratto richiesti, `tests/conftest.py`, il registro corsi reale `src/sbobina/course_registry.py`, `plan.md` e `tasks.md`; `spec.md` è assente, di `eval.md` sono state lette le sezioni T033 pertinenti. Il redattore ha letto per intero questo report, `CLAUDE.md`, i quattro nuovi moduli e `course_actions.py`; gli esiti delle verifiche di implementazione provengono dall'orchestratore. Nessuna inferenza reale su Ollama né comunicazione HTTP reale: la prova runtime usa client simulato e processi locali.

## 2026-10-07: ripristino T031 durante la trascrizione

La chat API torna al ramo denso con query CPU durante la trascrizione. Il motivo `gpu_busy` riguarda soltanto lo stage `EMBEDDING_STAGE`. Questa correzione sostituisce l'interpretazione riportata nella sessione precedente: R12 riguarda la contesa con l'indicizzazione, non con qualsiasi writer.

In `src/sbobina/web/dense_retrieval.py:100` il controllo anticipato confronta lo stage con `EMBEDDING_STAGE`. L'helper privato `_leased_query_vector` mantiene la lease condivisa in assenza di writer, evita di richiederla per gli altri stage e usa `GpuBusyError.stage` quando il writer arriva fra il controllo e l'acquisizione. La query diretta rimane dentro la gestione degli errori di `_safe_query_vector`. Gli import locali evitano il ciclo attraverso `embedding_supervisor`, `embedding_runner`, `vector_reconcile` e `course_retrieval`. Nessuna firma pubblica modificata.

### Asserzioni e test

BASIS: measured. I tre file `tests/web/test_chat_dense_{integration,turn,wiring}.py` sono stati ripristinati da HEAD e copiati subito in `/tmp/dense-retrieval-regression-baseline/`. Il confronto dei blocchi `assert`, comprese le righe delle asserzioni multilinea e quelle nelle funzioni annidate, è vuoto per tutte le funzioni originali. Nessuna eccezione. L'intera funzione `test_api_dense_query_succeeds_during_transcription_without_lease` è identica alla copia di HEAD.

Le firme erano già compatibili. Nei due test locali è stato adattato soltanto il mock: la prima chiamata usa la lease reale per la query, la seconda usa il controllo preesistente per la chat. Nessuna asserzione originale modificata. Le nuove asserzioni sull'indicizzazione sono in funzioni aggiunte.

| File | Test aggiunto |
|---|---|
| `tests/web/test_chat_dense_integration.py` | `test_api_dense_query_during_indexing_returns_bm25_without_embedding` |
| `tests/web/test_chat_dense_turn.py` | `test_api_turn_during_indexing_returns_bm25_without_embedding` |
| `tests/web/test_chat_dense_wiring.py` | `test_api_wiring_during_indexing_returns_bm25_without_embedding` |
| `tests/web/test_embedding_dense.py` | `test_rank_non_embedding_writer_queries_cpu_without_lease`, parametrizzato con `transcribing`, `TRANSCRIBING`, `custom-stage` |
| `tests/web/test_embedding_dense.py` | `test_rank_writer_race_respects_busy_error_stage`, parametrizzato con indicizzazione e trascrizione |

Anche due parametrizzazioni in `test_embedding_dense.py` e `test_embedding_chat.py` imponevano BM25 durante la trascrizione. Sono state ristrette all'indicizzazione, conservando le asserzioni di degradazione e ripresa. La trascrizione è verificata separatamente dai test ripristinati e dai nuovi casi del ranker.

### Verifiche della sessione

BASIS: measured. Tutti gli esiti provengono dai comandi eseguiti in questa sessione; i client Ollama sono simulati. Le misure non dimostrano prestazioni o comportamento di un modello reale.

| Controllo | Esito |
|---|---|
| Diff asserzioni originali | PASS, vuoto nei tre file; verificatore in `/tmp/dense-retrieval-regression-baseline/verify_changes.py` |
| TDD prima del fix | 7 failed, 21 passed: tre test ripristinati sulla trascrizione, tre stage non embedding e una race di trascrizione falliscono; `/tmp/dense-retrieval-red-final.log` |
| Nuovi test di indicizzazione | Già verdi prima del fix; confermano il comportamento da conservare |
| TDD dopo il fix | 28 passed con launcher diagnostico; `/tmp/dense-retrieval-green.log` |
| `uv run pytest` sui test senza HTTP | PASS: 20 passed nei file turn, wiring ed embedding_dense; `/tmp/dense-retrieval-green-standard.log` |
| `uv run ruff check .` | PASS |
| `uv run mypy src tests` | PASS, 453 file |
| Limiti Python | PASS: file ≤300, classi ≤200, funzioni ≤30 righe, parametri ≤4 escluso self; controllo AST |
| Suite completa diagnostica | FAIL: 3033 passed, 1 failed, 2 errors, 2 warnings in 91,79 s; completata senza timeout, skip o interruzioni; `/tmp/dense-retrieval-full-diagnostic.log` |

La cache uv predefinita non è scrivibile nel sandbox: i comandi successivi usano `UV_CACHE_DIR=/tmp/sbobina-uv-cache`. `pytest-timeout` non è installato. Il comando standard sui tre file ripristinati resta bloccato nei test HTTP; una sonda separata conferma `PermissionError` nell'invio su `socketpair`. Questa sola esecuzione mirata è stata interrotta. I test HTTP e la suite completa sono stati eseguiti con `uv run python /tmp/sbobina-pytest-selector.py`, launcher preesistente che limita a 1 ms l'attesa del selector, senza modificare il repository. Il suo esito non equivale a un PASS della suite standard `uv run pytest`.

I tre impedimenti residui della suite completa sono `test_is_port_available_free_port_returns_true`, `test_is_port_available_busy_port_returns_false` e `test_run_server_busy_port_exits_1_without_starting` in `tests/web/test_launcher.py`: la creazione del socket TCP solleva `PermissionError: [Errno 1] Operation not permitted`. Nessuna modifica ai test delle porte o al launcher di produzione. Per verificare la suite standard completa serve un ambiente che consenta i socket locali.

### Comandi git eseguiti

Soltanto questi tre, senza commit, push o altri comandi git:

```sh
git show HEAD:tests/web/test_chat_dense_integration.py > tests/web/test_chat_dense_integration.py
git show HEAD:tests/web/test_chat_dense_turn.py > tests/web/test_chat_dense_turn.py
git show HEAD:tests/web/test_chat_dense_wiring.py > tests/web/test_chat_dense_wiring.py
```

ESITO: bloccato sulla verifica completa standard per i vincoli del sandbox; fix e regressioni mirate verificati. Report aggiornato in append, preservando le 1188 righe precedenti.

## 2026-10-08 - 01:40 | Sessione #12 [API]

### Richiesta

Implementare T050/T051 del blocco B-10 di `specs/004-hybrid-retrieval/tasks.md` nel progetto speech-to-text, branch `feature/dense-retrieval`: stato dell'indice semantico, accodamento per corso e backfill, preferenze persistenti ed elenco dei modelli di embedding installati. Aggiungere il backfill necessario alla futura conferma del cambio modello in T052. Nessun commit e soltanto comandi git in lettura.

### Azioni Eseguite

- Registrato `api_semantic_index.router` in `app.py`. Le route riusano `SettingsDep`: GET accetta Origin assente, le mutazioni richiedono l'origine dell'applicazione e altrimenti restituiscono 403. Gli errori passano dalle eccezioni del progetto e dai relativi handler.
- Lo stato espone modello effettivo, disponibilità, dimensioni, presenza in `EMBEDDING_THRESHOLDS`, ricerca semantica attiva, cambio modello pendente e dimensione di `vectors.sqlite3`. Per ogni corso riporta copertura, troncati, unità mancanti, stima, ultimo successo e azione attiva. `model_missing`, `unreachable` e `bad_response` restano dati della risposta HTTP 200; i valori non determinabili sono `null`.
- La stima usa `ESTIMATED_UNITS_PER_SECOND = 1.0`, con commento riferito alle misure di `eval.md`. Non è una nuova misura di prestazione. `VectorStore` arriva da `vector_store_for_process`, senza creare un'istanza per richiesta.
- L'indicizzazione del corso passa da `course_actions.submit_embed` al supervisor vivo. Corso assente: 404; corso già in coda: 409 `EMBED_ALREADY_QUEUED`.
- Il backfill usa `enqueue_backfill` sotto la condition del supervisor, pubblica gli item nella coda e notifica il worker. Un cambio modello senza conferma restituisce `model_change_pending: true` e `queued: 0`; un modello non disponibile produce 409 con il motivo. Se un corso successivo provoca un errore, gli item già persistiti vengono pubblicati comunque e la risposta è 503 `BACKFILL_FAILED`, senza dettagli interni.
- Aggiunti `embedding_model` e `semantic_search` a `UserPreferences`, `_ENV_LOCKABLE_FIELDS`, vista e aggiornamento delle impostazioni. La PUT conserva il controllo dei campi bloccati dall'ambiente; il nome modello viene ripulito dagli spazi esterni e deve essere non vuoto.
- Il catalogo riusa `ollama_embed.Client`: `list()` interroga `/api/tags`, `show()` legge `capabilities` e conserva i modelli con capacità `embedding`. `qwen3-embedding:8b` è consigliato; `measured` deriva dalle soglie disponibili. Ollama irraggiungibile restituisce `{"data":{"status":"unreachable","models":[]}}`.
- `EmbeddingRun.last_indexed_at` è opzionale e compatibile con i JSON precedenti. Il timestamp si aggiorna al completamento riuscito e sopravvive a un nuovo accodamento o a un fallimento. I vecchi record senza timestamp riportano `null`.
- `ModelStatus.model` è opzionale per mantenere compatibili i chiamanti precedenti. Il controllo del modello lo valorizza; il backfill web trasporta il modello risolto dalla configurazione dell'applicazione, evitando di ripiegare su impostazioni globali diverse.

### Firme Pubbliche e Risposte

Tutte le funzioni di route sono sincrone e restituiscono `dict[str, JsonValue]`.

| Metodo e percorso | File e firma |
|---|---|
| GET `/api/v1/semantic-index/status` | `web/api_semantic_index.py: read_status(services: Services)` |
| POST `/api/v1/courses/{key}/semantic-index` | `web/api_semantic_index.py: post_course_index(key: str, services: Services)`, HTTP 202 |
| POST `/api/v1/semantic-index/backfill` | `web/api_semantic_index.py: post_backfill(body: BackfillBody, services: Services)`, HTTP 202 |
| GET `/api/v1/settings/embedding-models` | `web/api_semantic_index.py: read_embedding_models(settings: SettingsDep)` |
| PUT `/api/v1/settings/semantic-index` | `web/api_settings.py: put_semantic_index(body: SemanticIndexSettingsBody, settings: SettingsDep)` |

I file della tabella sono relativi a `src/sbobina/`. Il body del backfill richiede `confirm_model_change: bool`; quello delle impostazioni richiede `embedding_model: str` e `semantic_search: bool`.

Esempio illustrativo dello schema status, con valori fittizi:

```json
{"data":{"model":"qwen3-embedding:8b","semantic_search":true,"measured":true,"installed":true,"dimensions":4096,"reason":null,"model_change_pending":false,"courses":[{"key":"diritto","label":"Diritto","coverage":{"embedded":8,"total":10,"truncated":1},"missing_units":2,"estimated_seconds":2.0,"run":null,"queued_action":null,"last_indexed_at":null}],"size_bytes":32768}}
```

La copertura descrive il manifest nell'indice; `missing_units` controlla anche le unità aggiunte su disco dopo l'ultima sincronizzazione. I due valori hanno quindi ambiti diversi.

### Percorso delle Preferenze

La PUT chiama `settings_service.update_semantic_index`, salva `preferences.json` tramite il servizio esistente e restituisce la vista aggiornata. `effective_settings` applica i due campi rispettando la precedenza ambiente, file, default. `runtime_settings` viene riletto dalle richieste web e dai processi di lavoro.

La chat e il runner di generazione passano le impostazioni risolte a `dense_for_process`. Accodamento automatico, stima, runner di embedding e CLI le leggono prima di usare modello e interruttore semantico. Il backfill usa il nome in `ModelStatus`, con risoluzione delle preferenze come compatibilità per i vecchi chiamanti. I test verificano anche cambio modello e disattivazione dopo un primo uso della cache.

### File Modificati

I percorsi raggruppati condividono il prefisso indicato; sono riportati soltanto i file del lavoro T050/T051.

| File | Tipo | Descrizione |
|---|---|---|
| `src/sbobina/web/api_semantic_index.py`, `semantic_index_status.py`, `semantic_index_queue.py` | Nuovi | Route, aggregazione dello stato e pubblicazione del backfill nella coda viva |
| `src/sbobina/web/embedding_availability.py` | Nuovo | Controllo di disponibilità estratto per non far crescere il supervisor oltre il limite |
| `src/sbobina/user_preferences.py`, `settings_service.py`, `ollama_embed.py`, `cli_semantic.py` | Modificati | Preferenze, catalogo, identità del modello e risoluzione nella CLI |
| `src/sbobina/web/api_settings.py`, `app.py` | Modificati | PUT delle preferenze e registrazione del router |
| `src/sbobina/web/embedding_backfill.py`, `embedding_runner.py`, `embedding_store.py`, `embedding_supervisor.py` | Modificati | Preferenze nei consumatori, timestamp e gestione dell'errore parziale |
| `tests/test_embedding_catalog.py`, `tests/test_semantic_preferences.py` | Nuovi | Catalogo e precedenza delle preferenze |
| `tests/web/semantic_index_fixtures.py`, `test_api_semantic_index.py`, `test_api_semantic_settings.py`, `test_embedding_timestamps.py` | Nuovi | Fixture, contratti HTTP, timestamp e compatibilità |
| `tests/web/test_semantic_backfill_failure.py`, `test_semantic_dense_preferences.py`, `test_semantic_index_live_queue.py`, `test_semantic_runtime_preferences.py` | Nuovi | Errore parziale, preferenze nei consumatori e risveglio del supervisor |
| `tests/test_ollama_embed.py`, `tests/web/test_api_settings.py`, `test_embedding_auto_queue.py` | Modificati | Regressioni del modello, delle impostazioni e dell'accodamento automatico |
| `docs/REPORT_ATTIVITA.md` | Append | Questa sessione, conservando le 453 righe di diff già presenti all'avvio |

### Verifiche

BASIS: measured. Gli esiti sotto sono stati osservati dall'orchestratore e dagli agent incaricati; il redattore ha letto i log delle prove API, backfill parziale, coda viva e suite diagnostica. I test usano client Ollama simulati: nessuna inferenza reale. Nessuna percentuale di copertura del codice è stata misurata.

| Controllo | Esito osservato |
|---|---|
| TDD catalogo e timestamp | 5 failed in `/tmp/f4-red-boundaries.log`, poi 16 passed |
| TDD API | 14 failed in `/tmp/f4-red-api.log`; gruppo finale: 63 passed, 1 warning in 1,61 s, `/tmp/f4-green-api.log` |
| TDD errore parziale backfill | 1 failed in `/tmp/f4-red-partial.log`; dopo il fix: 12 passed, 1 warning in 2,05 s, `/tmp/f4-green-partial.log` |
| Coda viva e impostazioni | 22 passed, 1 warning in 2,94 s, `/tmp/f4-live-queue.log`. Due casi avviano il supervisor e attendono `DONE` con progresso 33/33 e timestamp |
| Mutation test della coda | Disabilitando `_publish_items` con un plugin temporaneo: 1 failed, 1 deselected in 5,79 s, `/tmp/f4-red-live-queue.log`; il test rileva il mancato risveglio |
| Preferenze e consumatori | Gruppo diagnostico dell'agent: 67 passed. Due nuovi test di preferenze dense: 2 passed con pytest standard; mutazione: 2 fallimenti. Il gruppo è distinto dal totale della suite completa |
| Verifica diretta finale | `uv run pytest -q tests/web/test_semantic_dense_preferences.py tests/test_embedding_catalog.py tests/test_semantic_preferences.py tests/web/test_embedding_timestamps.py`: 11 passed in 0,97 s |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check` sui 14 sorgenti modificati | `14 files already formatted` |
| `uv run mypy src tests` | `Success: no issues found in 474 source files` |
| Dimensioni del codice | Controllo AST senza violazioni nei file modificati: file ≤300 righe, funzioni ≤30, parametri ≤4; `embedding_supervisor.py`: 292 righe |
| `git diff --check` | Output vuoto |
| Suite standard | `timeout --signal=INT --kill-after=5s 120s uv run pytest -q`: interrotta dopo 120+5 s, exit 137; avanzamento fermo al 53%, nessun riepilogo pytest |
| Suite diagnostica | 1 failed, 3109 passed, 2 warnings, 2 errors in 99,88 s. I tre problemi riguardano i socket locali negati dal sandbox |
| Prerequisito runtime HTTP | `/tmp/f4-runtime-probe.py`: `BLOCKED`, `PermissionError: [Errno 1] Operation not permitted` alla creazione del socket |
| Code review | APPROVE dopo il fix del backfill parziale; riproduzione indipendente: `BACKFILL_FAILED`, record persistito `queued` e item presente nella coda viva |
| Review sicurezza e tipi | Analisi statica senza nuovi rilievi concreti su Origin, errori, timestamp legacy e compatibilità di `ModelStatus`; non è una prova dinamica |

I comandi uv usano `UV_CACHE_DIR=/tmp/sbobina-uv-cache`, perché la cache predefinita non è scrivibile nel sandbox. I log finali sono `f4be.log` e `f4be-diagnostic.log` nella scratchpad `/tmp/claude-1000/-home-bonn-Documenti-00-Lavoro-ProgettiPersonali-speech-to-text/ac89d54a-06dc-4ffa-8495-58a0bef4da42/scratchpad/`.

Il launcher diagnostico limita l'attesa del selector senza modificare il repository; il suo risultato non equivale al superamento della suite standard. I casi residui sono `test_is_port_available_free_port_returns_true` (failed), `test_is_port_available_busy_port_returns_false` e `test_run_server_busy_port_exits_1_without_starting` (errors), in `tests/web/test_launcher.py`. La creazione del socket solleva `PermissionError`. I warning riguardano la riscrittura delle asserzioni di `chat_api_fixtures` già importato e la deprecazione Starlette/httpx.

PROVENANCE: measured per i comportamenti esercitati dai test e gli esiti dei comandi riportati. La copertura funzionale dichiarata riguarda quei casi; non dimostra l'esecuzione HTTP su socket reale, le prestazioni di Ollama o una percentuale di copertura del codice. PROVENANCE: inferred per la durata stimata, ricavata dalle unità mancanti con la costante di 1,0 unità al secondo; l'esempio JSON contiene valori illustrativi.

### Riscontri sul Codice Esistente e Perimetro

La firma reale di `submit_embed_item(store, course_key="", *, course_id=None)` supporta entrambi i nomi: il presunto disallineamento fra chiamanti non è un bug. La ricerca di rate limiter, slowapi e middleware equivalenti non ha trovato un meccanismo applicato alle impostazioni; non ne è stato introdotto uno.

La verifica di coerenza del perimetro T050/T051 con C4 non ha rilevato divergenze backend. `spec.md` è assente; `tasks.md` e `plan.md` sono i riferimenti disponibili. T052/T053 e il gate complessivo F4 restano esclusi: nessuna UI modificata e gate a11y non applicabile. Le spunte dei task restano invariate.

### Comandi Git Eseguiti

Soltanto letture: `git status --short`, `git status --short --branch`, `git diff --stat`, `git log -3 --oneline`, `git diff --staged`, `git diff -- src/sbobina`, `git diff --check`, `git diff --numstat`, `git diff --numstat -- docs/REPORT_ATTIVITA.md`. Nessun commit, push o comando git di scrittura.

### Note per il Cliente

Il server può mostrare lo stato della ricerca per significato, ricordare il modello scelto e avviare l'indicizzazione dei corsi. Il cambio modello richiede una conferma prima di accodare il lavoro. Se l'accodamento si interrompe a metà, i corsi già presi in carico continuano a essere elaborati.

I comandi nell'interfaccia saranno aggiunti nei task successivi. I test mirati passano, ma questo ambiente impedisce l'apertura delle connessioni locali necessarie alla verifica completa dell'applicazione.

### Riepilogo (Complessità / Stato)

Complessità media. Backend T050/T051 implementato, code review approvata; `ESITO: bloccato` sulla suite standard e sulla prova runtime HTTP per i limiti del sandbox. Prossimo: rieseguire la suite standard e la verifica HTTP in un ambiente che consenta i socket locali; fino ad allora la verifica completa resta aperta.

Report aggiornato in append con la skill `scrivi-italiano`, preservando lo storico e le modifiche precedenti alla sessione. Nessun file README o altro documento di progetto modificato. La memoria esterna dell'agent non è stata aggiornata perché si trova fuori dalle directory scrivibili.

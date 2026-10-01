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

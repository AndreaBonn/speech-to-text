# Task: interfaccia web per sbobina

Piano: `specs/web-ui/plan.md` v1.1 (decisioni citate come "plan §N").
Blocchi delegabili (2-4 task) indicati con **[B-n]**. Ogni task è TDD: test rosso prima.
Tutti i comandi via `uv run`. Mock solo ai boundary: faster-whisper/ctranslate2, Ollama, HF hub,
processo figlio (sostituito da un runner fittizio Python che scrive `progress.json`).
Regole cross-platform (plan § Assunzioni) valide da F1: pathlib, niente shell, niente
multiprocessing, niente `/proc`, `encoding="utf-8"` esplicito.

## F1 - Service e hook di progresso (nessuna dipendenza nuova)

**[B-1] T001-T004**

- [x] **T001** `transcribe_file(..., on_progress: ProgressCallback | None = None)`; `_collect_segments`
  la chiama a ogni segmento con `(raw_segment.end, duration)`. Log ogni 300 s invariato. Plan §1.
  File: `src/sbobina/transcriber.py`, `tests/test_transcriber.py`. Rischio: basso.
  verify: test con segmenti finti registra `[(10.0, 30.0), (30.0, 30.0)]`;
  `test_transcribe_file_passes_vad_setting_to_whisper` verde senza modifiche.
- [x] **T002** `src/sbobina/pipeline.py`: `with_progress(corrector, total, on_done)` spostato da
  `cli._with_progress`; `transcribe_to_dir(...)` e `correct_to_dir(...) -> CorrectionOutcome`
  estratti da `cmd_trascrivi`, `cmd_correggi`, `_write_correction_outputs`. Funzioni ≤ 30 righe.
  File: `src/sbobina/pipeline.py`, `tests/test_pipeline.py`. Rischio: medio (va preservata la
  scrittura degli output parziali, `src/sbobina/cli.py:143`).
  verify: `uv run pytest tests/test_pipeline.py` verde; caso "interrotto a metà" scrive gli output
  parziali come oggi.
- [x] **T003** `cli.py` delega a `pipeline`; `_with_progress` rimosso (orfano della modifica).
  Rischio: basso. verify: `uv run pytest tests/test_cli.py` verde senza toccare i test esistenti.
- [x] **T004** Gate di fase. verify: pytest, ruff, mypy verdi; `wc -l src/sbobina/cli.py` < 228.

## F2 - Piattaforma e CPU su Linux (indipendente dal web)

Prima di T005: context7 su CTranslate2 (device supportati, assenza di Metal, compute type CPU) e
citare l'URL nel docstring di `resolve_runtime`.

**[B-2] T005-T007**

- [x] **T005** `src/sbobina/platform_info.py`: `PlatformInfo`, `RuntimeChoice`,
  `resolve_runtime(info, requested)` puro secondo la tabella di plan §10. Settings: `device="auto"`,
  `compute_type="auto"`, `cpu_threads=0`, `whisper_model_cpu="large-v3-turbo"`. Rischio: medio.
  verify: test parametrizzato su tutte le righe della tabella (linux/windows/darwin/other ×
  NVIDIA+wheel / NVIDIA senza wheel / nessuna GPU / Apple Silicon), più: cpu senza `int8` →
  `float32`; `cuda` esplicito senza GPU → errore; `cpu` esplicito con GPU → cpu. Nessun test legge
  l'OS reale (`sys.platform` mai usato nei test).
- [x] **T006** `detect_platform()` (unico I/O: `sys.platform`, `platform.machine()`,
  `ctranslate2.get_cuda_device_count()`, `get_supported_compute_types("cpu")`, `find_spec` delle
  wheel NVIDIA senza caricarle). Rischio: basso.
  verify: test con ctranslate2 e `find_spec` mockati → `PlatformInfo` atteso; esecuzione reale qui
  → `system=linux, cuda_devices=1, cuda_libs_available=True`.
- [x] **T007** `transcribe_file` usa `RuntimeChoice`: `preload_cuda_libraries()` solo per cuda su
  Linux, `cpu_threads` solo su cpu, log INFO (OS, device, compute, modello, motivo), WARNING con
  `uv sync --extra cuda` per GPU senza wheel. Rischio: medio.
  verify: test con `WhisperModel` mockato: su cpu `preload_cuda_libraries` non chiamato e
  `WhisperModel(device="cpu", compute_type="int8", cpu_threads=N)`; caplog con il WARNING nel caso
  GPU-senza-wheel.

**[B-3] T008-T009**

- [x] **T008** `pyproject.toml`: wheel NVIDIA in `[project.optional-dependencies] cuda` con marker
  `sys_platform == 'linux'`; `uv.lock` rigenerato dal tool. **Richiede OK utente**. Rischio: medio.
  verify: `uv sync && uv pip list | grep -c nvidia` → 0; `uv sync --extra cuda` → wheel presenti e
  `uv run sbobina trascrivi <fixture 30 s>` di nuovo su cuda.
- [x] **T009** Verifica CPU reale su questa macchina. verify: `CUDA_VISIBLE_DEVICES="" uv run
  sbobina trascrivi <30 s wav>` completa, log `device=cpu compute_type=int8 model=large-v3-turbo`.
  Misurato 2026-10-01 (senza wheel, RTX presente): WARNING `uv sync --extra cuda`, cpu/int8/
  large-v3-turbo, 30 s di audio in 16 s su 16 core (modello già in cache).

## F3 - Server, job store, coda, SSE

Dipendenze `fastapi uvicorn jinja2 python-multipart`: **OK utente prima di `uv add`**. All'inizio di
B-4, context7 su FastAPI (lifespan, StreamingResponse/SSE, UploadFile, TrustedHostMiddleware,
FileResponse Range): URL citati nei commenti dove la scelta non è ovvia.

**[B-4] T010-T012**

- [x] **T010** Settings web (`web_host` validato loopback, `web_port=8765`, `data_dir=Path("data")`,
  `web_max_upload_mb=1024`) + `web/job_models.py` (`JobStatus`: queued, running, done, failed,
  cancelled, interrupted; `JobStage`; `JobConfig` plan §12; `JobRecord`). Rischio: basso.
  verify: `Settings(web_host="0.0.0.0")` → ValidationError; `JobConfig(beam_size=0,
  uncertain_threshold=1.5, whisper_model="xl")` → 3 errori con `loc` per campo.
- [x] **T011** `web/job_store.py`: create (uuid4), get, list paginato (`created_at` desc), update
  atomico (tmp + `os.replace`), delete, `read_progress`/`write_progress`. Rischio: basso.
  verify: 25 job su `tmp_path`, `list(page=3, per_page=10)` → 5 elementi, total 25, total_pages 3;
  id non-uuid → `NotFoundError` senza accesso al filesystem.
- [x] **T012** `web/app.py` `create_app(...)`, `web/responses.py` (envelope, 422 con
  `details[{field,message}]`), middleware host/origin plan §9, `web/api_system.py`
  (`GET /api/v1/system` da `detect_platform` + `resolve_runtime`), sottocomando
  `sbobina web [--port] [--no-browser]` plan §11. Rischio: medio.
  verify: `Host: evil.example` → 400; POST con `Origin: https://evil.example` → 403;
  `/api/v1/system` → 200 con `device`; `webbrowser.open` mockato chiamato una volta; porta
  occupata da un socket del test → exit 1 senza traceback.

**[B-5] T013-T015**

- [x] **T013** `web/stage_runner.py` (`python -m sbobina.web.stage_runner transcribe|correct
  <job_dir>`): Settings validati dagli override, chiama `pipeline`, `progress.json` al più ogni 1 s
  con `{stage, progress, audio_s, elapsed_s}`, watchdog stdin (EOF → `os._exit`), exit 0/1/2
  (ok / errore / Ollama irraggiungibile). Plan §1, §3. Rischio: medio.
  verify: `run_stage()` in-process con pipeline finta → `progress.json` finale `progress == 1.0`;
  figlio reale col runner fittizio: chiusa la stdin, esce entro 2 s.
- [x] **T014** `web/supervisor.py`: thread, FIFO, un `Popen([sys.executable, "-m", ...],
  stdin=PIPE, start_new_session=True)` alla volta; `correct` solo se richiesto e dopo `wait()` del
  transcribe; `cancel(id)`; stop pulito nel lifespan. Plan §2, §4. Rischio: alto.
  verify: due job col runner fittizio, il secondo `queued` finché il primo è terminale; cancel su
  running → `cancelled` e `poll() is not None` entro 10 s; cancel su terminale →
  `JobNotCancellableError`.
- [x] **T015** Recupero al boot: `running` → `interrupted` (`SERVER_RESTARTED`), `queued` rimessi in
  coda per `created_at`. Rischio: medio.
  verify: store con 1 running + 2 queued, avvio → running `interrupted`, queued eseguiti in ordine
  di creazione (log del runner fittizio).

**[B-6] T016-T019**

- [x] **T016** `web/gpu_release.py`: `unload_ollama_models(host)` (`ps()` + `generate(model,
  keep_alive=0)`), chiamato prima di ogni stage transcribe; Ollama giù → WARNING. Plan §2.
  Rischio: medio. verify: client finto registra `generate(model="qwen3.5:9b", keep_alive=0)`;
  manuale: dopo `sbobina correggi`, la funzione rende `ollama ps` vuoto.
- [x] **T017** `web/api_jobs.py`: `POST /api/v1/jobs` (multipart, streaming su disco plan §5),
  `GET /api/v1/jobs` paginato, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`, `DELETE /jobs/{id}`.
  Rischio: medio. verify: wav fixture → 201 queued; `.pdf` → 422 `field=file`; testo rinominato
  `.mp3` → 422; limite 1 MB e upload da 2 MB → 413 senza cartella residua; DELETE su running → 409.
- [x] **T018** `web/sse.py`: `GET /api/v1/jobs/{id}/events` plan §7, con velocità ed ETA calcolate
  da `audio_s/elapsed_s`. Rischio: medio. verify: stream su job con progress scritto dal test →
  `event: progress` crescenti, `event: end` su stato terminale, nessun duplicato senza cambio.
- [x] **T019** Pagine minime Jinja (form upload con config e default da `/api/v1/system`, coda con
  barra via EventSource, annulla). File: `web/pages.py`, `templates/{base,index}.html`,
  `static/jobs.js`. Rischio: basso. verify: `uv run sbobina web`, upload di una fixture da 30 s dal
  browser, barra fino a "completato"; `curl -N .../events` mostra gli stessi eventi.

## F3b - Avvio con un comando (richiesta utente 2026-10-01, anticipato da F9)

Script sottili per OS, logica in Python (testabile, uguale ovunque). uv crea e usa il venv da
solo: nessuna attivazione. Driver NVIDIA, Ollama e modelli NON vengono installati dallo script:
rilevati e segnalati (permessi admin / download lunghi gestiti dalla UI con avanzamento).

**[B-3b] T080-T082**

- [x] **T080** `avvia.sh` (Linux principale, macOS): installa uv se manca (installer ufficiale
  astral, verificato sulla doc al momento della scrittura), `nvidia-smi` presente su Linux →
  `uv sync --extra cuda`, altrimenti `uv sync`; poi `exec uv run sbobina web`. Idempotente.
  verify: su questa macchina, da clone pulito, `./avvia.sh` → browser aperto su `/`;
  secondo lancio senza reinstallazioni; `shellcheck avvia.sh` pulito.
- [x] **T081** `sbobina web` all'avvio: diagnosi (`platform_info`, stato Ollama, modello Whisper in
  cache) loggata in italiano e servita da `/api/v1/system`; apre il browser con `webbrowser` dopo
  che il server risponde (`--no-browser` per disattivare); porta occupata → messaggio chiaro.
  verify: test della diagnosi con boundary mockati; avvio reale apre la pagina una sola volta.
- [ ] **T082** `avvia.bat` (Windows, doppio clic): stesso flusso con installer PowerShell di uv e
  `where nvidia-smi`. Non verificabile qui: entra nella checklist T076.

## F4 - Lettore, audio, storico

**[B-7] T020-T022**

- [x] **T020** `web/reader.py` puro: `Transcript` + soglia → paragrafi (`render.group_paragraphs`)
  di `WordView(start, end, text, uncertain, corrected_from)`. Rischio: basso.
  verify: probability 0.5 con soglia 0.7 → `uncertain=True`; `corrected_from="clorofilla"` →
  prima/dopo; stessi confini di paragrafo di `render_markdown`.
- [x] **T021** `GET /api/v1/jobs/{id}/audio` (test Range per primo, fallback plan §6) e
  `GET /jobs/{id}/files/{kind}` (md, json, corrected_md, corrected_json, report). Rischio: medio.
  verify: `Range: bytes=0-1023` → 206, `Content-Range: bytes 0-1023/<size>`, 1024 byte; kind ignoto
  → 422; file non prodotto → 404.
- [x] **T022** `templates/reader.html`: parole come `<span data-start data-end>`, classi
  incerta/corretta, `<audio>` nativo. Rischio: basso. verify: HTML del job fixture ha tanti span
  quante le parole del transcript.

**[B-8] T023-T025**

- [x] **T023** `static/reader.js`: clic → `currentTime = start` + play; `timeupdate` → ricerca
  binaria, classe attiva, scroll solo se fuori viewport; errore di decodifica → messaggio visibile.
  Rischio: medio. verify: manuale su job reale: clic su una parola a 12:30 → audio a 12:30;
  l'evidenza avanza parola per parola.
- [x] **T024** Storico `templates/history.html` paginato: stato, durata, riapri, elimina (solo
  terminali). Rischio: basso. verify: 12 job fixture, per_page 10 → 2 pagine; "riapri" apre il lettore.
- [x] **T025** Gate di fase: pytest/ruff/mypy verdi, file ≤ 300 righe.

## F5 - Modelli e stato Ollama

**[B-9] T030-T032**

- [x] **T030** `web/model_service.py` Whisper: elenco `available_models()` deduplicato per repo_id,
  stato via `download_model(name, local_files_only=True)` catturando l'eccezione specifica di hub
  (tipo da verificare). Rischio: medio. verify: hub mockato → presente True / assente False;
  `large` e `large-v3` una riga con alias.
- [x] **T031** Download Whisper: `snapshot_download(repo_id, allow_patterns=...)` in thread
  `DownloadManager`, totale da `dry_run=True`, byte dalla cache, fallback indeterminato. Plan §8.
  Rischio: alto. verify: snapshot finto che scrive file progressivi → `completed/total` crescenti;
  manuale: download di `tiny` con barra e stato finale "scaricato".
- [x] **T032** Ollama: `ollama_status()` → `not_installed | not_running | ready` (anche in
  `/api/v1/system`); `list()`; `pull(stream=True)` con progresso sommato sui digest; Ollama giù →
  stato con messaggio, non 500. Rischio: medio. verify: 3 `ProgressResponse` finte → 0.33/0.66/1.0;
  (which None, host giù) → not_installed; (which ok, host giù) → not_running; (host su) → ready.

**[B-10] T033-T034**

- [x] **T033** `GET /api/v1/models`, `POST /api/v1/models/downloads`, SSE
  `/api/v1/models/downloads/events`; download duplicato → 409. Rischio: basso.
  verify: POST due volte `tiny` → 202 poi 409.
- [x] **T034** `templates/models.html` + `static/models.js`: tabelle Whisper/Ollama, badge device,
  modelli consigliati su CPU, "scarica per nome" Ollama, stato Ollama con azione. Rischio: basso.
  verify: manuale: download di `tiny` dall'UI con barra e stato finale scaricato.

## F6 - WER da browser

**[B-11] T040-T041**

- [x] **T040** `POST /api/v1/wer`: riferimento `.txt` + `job_id`/`variant` (original|corrected) o
  ipotesi `.txt`; `compute_wer`. Rischio: basso. verify: stessi valori di `uv run sbobina wer` sulle
  stesse fixture; variant corrected senza correzione → 404.
- [x] **T041** `templates/wer.html`. verify: manuale, numero identico alla CLI.

## F7 - UI finale (orchestratore con skill di design)

- [x] **T050** Riga `DIAL:` (strumento di lavoro locale, lettura lunga) e sistema visivo in
  `static/app.css`; `design.md` a root da `hallmark` prima della seconda pagina.
  verify: riga DIAL nel report, `design.md` presente.
- [x] **T051** Redesign pagine F3-F6: stati Loading/Empty/Error/Populated/Edge per coda, storico,
  modelli, lettore (edge: 10k parole, nome file da 200 caratteri, Ollama giù, device cpu).
  verify: ogni superficie mostrata nei 5 stati con fixture.
- [x] **T052** Avvisi piattaforma: banner OS/device, avviso large-v3 su CPU prima di accodare,
  avviso tempi correzione, velocità ed ETA reali. verify: con `SBOBINA_DEVICE=cpu` il form
  preseleziona `large-v3-turbo` e scegliere `large-v3` mostra l'avviso.
- [x] **T053** Gate: `a11y-gate` verde, `hallmark audit`, render osservato a 375 e 1280 px.
- [x] **T054** Click-through di ogni controllo (upload, annulla, riapri, elimina, clic parola →
  seek, download, scarica modello, calcola WER), console senza errori. verify: elenco
  `controllo -> esito` nel report.

## F8 - Verifica reale su Linux

- [x] **T060** Job GPU su lezione da 85 min con correzione: `nvidia-smi --query-compute-apps`
  durante transcribe, fra le fasi (nessun processo Whisper) e durante correct. verify: tre letture
  riportate, job `done`, output identici a quelli della CLI sullo stesso audio.
  Esito 2026-10-01: job `done` (trascrizione ~6,5 min, correzione ~18 min); Whisper e Ollama mai
  insieme in VRAM (campioni ogni 15 s). "Identici" non è raggiungibile: su GPU due run differiscono
  (finestre da 30 s identiche: CLI-CLI 169/170, web-CLI 165/170, un'altra run web 145/170), quindi
  il percorso web non introduce differenze sistematiche. Correzione: 147 applicate contro 149 della CLI.
- [x] **T061** Riavvio del server e cancellazione durante un job; misura CPU (`SBOBINA_DEVICE=cpu`,
  audio da 5 min, turbo, `cpu_threads` logici vs fisici). verify: job `interrupted`, nessun figlio
  in `ps`; rapporto audio/tempo riportato e usato nel testo dell'avviso.
  Esito 2026-10-01: annulla -> `cancelled` in 0,2 s, nessun figlio; SIGINT al gruppo del server ->
  `interrupted`; SIGKILL al server -> il figlio esce in ~1 s, al riavvio `interrupted`
  (`SERVER_RESTARTED`). CPU, 5 min di audio, i7-13620H (10 core, 16 thread): 102,1 s con 16 thread,
  85,5 s con 10 (3 run ciascuno) -> default ai core fisici su Linux, rimisurato 85,1 s. Una lezione
  da 90 min ~ mezz'ora; testo della guida Windows aggiornato.
- [ ] **T062** (solo con OK utente) README: `sbobina web`, installazione CPU vs
  `uv sync --extra cuda`. verify: un lettore non tecnico trova il comando in 60 s.

## F9 - Fallback Windows e macOS (mergiabile a sé, dopo F2 e F3)

**[B-12] T070-T072**

- [x] **T070** `cuda_libs` ramo Windows (`os.add_dll_directory` sulle cartelle delle wheel NVIDIA),
  `detect_platform` imposta `cuda_libs_available` di conseguenza; extra `cuda` esteso a
  `sys_platform == 'win32'` (**OK utente**). Plan §13. Rischio: alto (non osservabile qui).
  verify: test con `sys.platform` iniettato e `os.add_dll_directory` mockato; su Linux nessun
  cambiamento (test esistenti verdi). Verifica reale solo in T075/T076.
- [x] **T071** Ripiego a runtime cuda → cpu quando `WhisperModel(device="cuda")` solleva per
  librerie mancanti: WARNING e nota nel `job.json`. Rischio: medio. verify: `WhisperModel` mockato
  che solleva al primo tentativo → secondo tentativo con `device="cpu"`, nota presente.
- [x] **T072** Processi e file su Windows: `creationflags=CREATE_NEW_PROCESS_GROUP` su win32,
  env `PYTHONUTF8=1`, log del figlio su file UTF-8, retry di `os.replace` su `PermissionError`.
  Rischio: medio. verify: test con piattaforma iniettata controlla gli argomenti di `Popen`; test
  del retry con `os.replace` finto che fallisce due volte.

**[B-13] T073-T074**

- [x] **T073** Messaggi Ollama per OS in `/api/v1/system` e in UI (Windows/macOS: installer
  ollama.com e avvio dall'app; Linux: script e `ollama serve`). Rischio: basso.
  verify: test per i tre OS × tre stati.
- [x] **T074** `docs/installazione-windows.md` (italiano, per non tecnici, via `doc-writer` +
  `scrivi-italiano`) e `avvia-sbobina.bat`: installare uv (comando PowerShell ufficiale verificato
  sulla doc astral al momento della scrittura), scaricare il progetto, `uv sync`, installare e
  avviare Ollama, `ollama pull`, doppio clic sul lanciatore (browser aperto da solo), tempi su CPU,
  cosa fare con "Ollama non installato/non avviato". Rischio: basso.
  verify: `reader-test` con le domande del collega ("come avvio?", "perché è lento?", "Ollama non
  parte"); prova reale in T076.

**[B-14] T075-T076**

- [ ] **T075** `.github/workflows/ci.yml`, matrice `ubuntu-latest`, `windows-latest`,
  `macos-latest`: `uv sync` senza extra, pytest, ruff, mypy, smoke test (`sbobina web --no-browser`
  in background, poll di `/api/v1/system` fino a 200 entro 30 s, stop), decodifica di una fixture
  m4a con `av`. `permissions: contents: read`, `persist-credentials: false`, action pinnate a SHA.
  **Dipende dalla scelta dell'utente di creare un remote GitHub** (oggi assente); push all'utente.
  Rischio: medio. verify: run verde sui tre OS in Actions.
- [x] **T076** Checklist (scritta: `docs/checklist-windows-macos.md`; esiti da raccogliere) per un collega Windows (e macOS se disponibile): guida T074, pytest, job da
  30 s su CPU, lettore con m4a, cancellazione, stati Ollama. Ripiego se T075 non è possibile.
  verify: esiti per OS riportati; finché mancano T075 e T076, Windows/macOS non verificati.

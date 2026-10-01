# Piano: interfaccia web per sbobina

Versione 1.1 - 2026-10-01. Task in `specs/web-ui/tasks.md`.
v1.1: integrate le correzioni dell'utente (uso su CPU dei colleghi; Linux piattaforma principale,
Windows e macOS fallback supportati in una fase finale separata).

## Obiettivo

`uv run sbobina web` avvia su 127.0.0.1 un'interfaccia da cui si carica una registrazione, si
configura e si accoda il job, se ne segue l'avanzamento live, si legge la trascrizione con audio
sincronizzato, si gestiscono i modelli Whisper e Ollama e si calcola il WER. La CLI esistente
continua a funzionare con lo stesso comportamento osservabile. Il sistema rileva a runtime OS e
hardware: Linux con GPU NVIDIA resta il percorso principale e invariato; senza GPU gira su CPU;
Windows e macOS sono fallback supportati. Ognuno usa la propria istanza locale.

## Definition of Done

Percorso Linux (fasi F1-F8):

- [ ] `uv run sbobina web` risponde su `http://127.0.0.1:<porta>` e apre il browser (disattivabile
      con `--no-browser`); con `SBOBINA_WEB_HOST=0.0.0.0` rifiuta di partire (exit 1, messaggio);
      porta occupata → messaggio leggibile ed exit 1, senza traceback.
- [ ] Richiesta con `Host: evil.example` → 400; POST con `Origin: https://evil.example` → 403
      (difesa da DNS rebinding e CSRF contro un server locale senza login).
- [ ] Upload di `lezione.m4a` da 80 MB → 201 con `{"data": {"id": ..., "status": "queued"}}` e file
      in `data/jobs/<id>/audio.m4a`; upload di `note.pdf` → 422 con `details[0].field == "file"`;
      upload oltre `SBOBINA_WEB_MAX_UPLOAD_MB` → 413 e nessun file residuo in `data/jobs/`.
- [ ] Config job fuori range (`beam_size=0`, `uncertain_threshold=1.5`, `whisper_model="xl"`) →
      422 con un elemento di `details` per campo.
- [ ] Due job accodati: il secondo resta `queued` finché il primo non è terminale (mai due stage
      di inferenza contemporanei; test sul supervisore e `nvidia-smi` durante il run reale).
- [ ] Lo stream SSE `/api/v1/jobs/<id>/events` emette eventi con `stage` e `progress` crescente
      (0..1), velocità misurata (secondi di audio per secondo) e tempo residuo stimato da quella;
      a job finito emette un evento terminale e chiude.
- [ ] Fra la fase Whisper e la fase Ollama la VRAM del processo Whisper torna a zero (misurato con
      `nvidia-smi --query-compute-apps` sul job reale di 85 min); prima di ogni trascrizione i
      modelli Ollama residenti vengono scaricati (`ollama ps` vuoto).
- [ ] Cancellazione: job `queued` → `cancelled` subito; job in corso → `cancelled` entro 10 s e il
      processo figlio non esiste più.
- [ ] Riavvio del server con un job in corso: al boot il job è `interrupted`, il figlio orfano è
      uscito da solo, i job `queued` ripartono in ordine di creazione.
- [ ] Lettore: paragrafi come `render.group_paragraphs`, parole sotto soglia evidenziate, parole
      con `corrected_from` mostrate prima/dopo; clic su una parola → `audio.currentTime` = inizio
      parola; durante la riproduzione la parola corrente ha la classe attiva.
- [ ] `GET /api/v1/jobs/<id>/audio` con `Range: bytes=0-1023` → 206, `Content-Range`, 1024 byte.
- [ ] Download di `.md`, `.json`, `.correzioni.md` con `Content-Disposition: attachment`.
- [ ] Storico: `GET /api/v1/jobs?page=2&per_page=10` → `meta` con `page, per_page, total,
      total_pages`; una lezione chiusa si riapre nel lettore.
- [ ] Modelli: la pagina elenca i modelli di `faster_whisper.utils.available_models()` con stato
      scaricato/non scaricato e i modelli Ollama installati; il download mostra l'avanzamento e a
      fine download lo stato diventa "scaricato".
- [ ] Ollama: `GET /api/v1/system` riporta `ollama: not_installed | not_running | ready`; la UI
      mostra per i primi due l'azione da fare; la trascrizione senza correzione resta disponibile.
- [ ] WER: caricando un riferimento `.txt` e scegliendo una lezione (originale o corretta) la
      pagina mostra lo stesso numero di `uv run sbobina wer riferimento.txt <json>`.
- [ ] Piattaforma: `resolve_runtime` è pura e testata per ogni combinazione OS × hardware
      passando i valori (nessun test dipende dall'OS reale). Su Linux+NVIDIA con extra `cuda` il
      default resta `cuda`/`float16`/`large-v3`; con `CUDA_VISIBLE_DEVICES=""` diventa
      `cpu`/`int8`/`large-v3-turbo` e `preload_cuda_libraries` non viene chiamato. Un log INFO
      all'avvio dice OS, device, compute_type, modello di default e perché.
- [ ] GPU NVIDIA presente ma extra `cuda` non installato → WARNING con `uv sync --extra cuda`, mai
      un ripiego silenzioso sulla CPU.
- [ ] `uv sync` senza extra non installa `nvidia-cublas-cu12`/`nvidia-cudnn-cu12`;
      `uv sync --extra cuda` li installa.
- [ ] L'interfaccia mostra OS e device rilevati; su CPU preseleziona il modello leggero, avvisa
      prima di accodare large-v3, avvisa sui tempi della correzione Ollama e la lascia
      disattivabile.
- [ ] `uv run pytest`, `uv run ruff check .`, `uv run mypy src tests` verdi; nessun file nuovo
      oltre 300 righe, nessuna funzione oltre 30.
- [ ] Fase UI: riga `DIAL:` dichiarata, `a11y-gate` verde, render osservato a 375 e 1280 px,
      click-through registrato di ogni controllo.

Fallback Windows/macOS (fase F9, mergiabile a sé):

- [ ] Windows+NVIDIA: `cuda` solo se le DLL delle wheel NVIDIA si caricano, altrimenti `cpu`; un
      errore di caricamento CUDA a runtime ripiega su CPU con WARNING registrato nel job.
- [ ] macOS: sempre `cpu`, compute_type `int8` se fra quelli supportati dalla CPU, altrimenti
      `float32`.
- [ ] Suite e smoke test di avvio verdi su `windows-latest` e `macos-latest` in CI (T075), oppure,
      senza remote, checklist T076 eseguita da un collega; finché nessuno dei due è avvenuto,
      Windows e macOS sono dichiarati **non verificati**.
- [ ] `docs/installazione-windows.md` porta un non tecnico da zero a una trascrizione, con
      lanciatore a doppio clic.

## Assunzioni

- Python 3.12, uv, stesso package `sbobina`; web in un sottopacchetto `sbobina.web`.
- Dipendenze nuove: `fastapi`, `uvicorn`, `jinja2`, `python-multipart`. **[BLOCCANTE: `uv add` è
  installazione di pacchetti, serve l'OK esplicito dell'utente nel turno di implementazione]**.
  Idem per lo spostamento delle wheel NVIDIA in un extra (T008).
- Utente unico per istanza, un browser; nessuna concorrenza multi-utente oltre a più tab.
- Storico = job creati dall'interfaccia. Le trascrizioni già presenti in `data/output*` non vengono
  importate in v1 (anchor rivedibile: un import è un task a parte).
- Catalogo Ollama: il client Python non ha un endpoint di ricerca nel registry (metodi presenti:
  `list`, `pull`, `delete`, `ps`, `show`, ...; BASIS: measured su `ollama/_client.py` 0.6.3). La
  pagina mostra i modelli installati e un campo "scarica per nome" precompilato con
  `settings.ollama_model`. Nessun elenco dei modelli remoti. Cancellazione modelli: fuori da v1.
- README: aggiornare la sezione Uso richiede richiesta esplicita (`code-standards.md` §
  Documentazione). Proposto come T062, non eseguito senza OK. La guida Windows (T074) è invece
  richiesta dall'utente.
- Audio nel browser: m4a/AAC, mp3, wav, ogg/opus, flac riproducibili da Chrome e Firefox su Linux
  (BASIS: inferred). Nessuna transcodifica in v1; se il browser non riproduce, il lettore lo dice
  e il testo resta.
- **Piattaforme**: Linux principale (GPU e CPU), Windows e macOS fallback supportati. Qui c'è solo
  Linux: Windows e macOS restano non verificati finché non girano T075 o T076.
- **Regole cross-platform vincolanti da F1** (costano zero se rispettate subito, molto dopo):
  `pathlib` ovunque; nessuna shell (`subprocess` con lista di argomenti e `sys.executable -m`);
  nessun `multiprocessing` (il piano usa `subprocess`, quindi niente dipendenza da `fork`: su
  Windows il default è `spawn`); nessun `/proc`, `os.fork`, `signal.SIGKILL`; ogni lettura e
  scrittura di testo con `encoding="utf-8"` (il codice esistente lo fa già,
  `src/sbobina/models.py:44`). Le parti che richiedono **codice diverso** per OS stanno in F9.
- Default Whisper su CPU: `large-v3-turbo` (decoder più leggero di large-v3, qualità italiana
  presunta vicina). BASIS: inferred, da misurare col WER sul gold set (roadmap punto 2);
  alternative proposte nell'UI: `medium`, `small`.
- Tempi su CPU: nessun numero inventato in UI. La stima viene dalla velocità misurata sul job in
  corso; T061 misura una volta il rapporto su questa CPU per tarare il testo dell'avviso.
- Context7 non era disponibile a questo planner e FastAPI non è installato: le affermazioni su
  FastAPI/Starlette e su CTranslate2 per macOS sono da training (UNVERIFIED) e ogni task che le
  usa apre con la consultazione context7. Faster-whisper, ctranslate2, huggingface_hub, ollama,
  av e uv sono verificati sui pacchetti installati.

## Disambiguazione: dove gira l'inferenza

Approcci plausibili:
- Opzione A: thread worker dentro il processo web, chiama `transcribe_file` e `correct_transcript`.
- Opzione B: thread supervisore nel processo web che lancia **un processo figlio per stage**
  (`python -m sbobina.web.stage_runner transcribe|correct <job_dir>`), uno alla volta.

Conseguenze:
- A: meno codice, progresso via callback in memoria. Ma la VRAM si libera solo se il distruttore
  di CTranslate2 la rilascia, e il contesto CUDA del processo resta allocato (BASIS: inferred); la
  cancellazione è solo cooperativa e non interrompe il caricamento del modello; un crash nativo di
  cuDNN/CTranslate2 abbatte il server e la coda. Su CPU la RAM di large-v3 resta occupata.
- B: l'uscita del processo garantisce il rilascio di VRAM e RAM fra Whisper e Ollama;
  cancellazione dura con `terminate()`/`kill()` (cross-platform in `subprocess.Popen`); crash
  isolato al job. Costo: IPC via file di progresso, qualche secondo di avvio per stage, codice di
  supervisione.
- **Raccomandata: B**, perché la DoD chiede VRAM a zero fra le fasi e cancellazione entro 10 s: con
  A la prima dipende da un comportamento non documentato e la seconda non è garantita durante il
  caricamento del modello. Il piano è scritto su B. Se l'orchestratore sceglie A, T013 e T014
  collassano in un worker in-process e cade il watchdog di T013.

## Architettura (B)

```
browser ── HTTP/SSE ──> FastAPI (127.0.0.1)
                          routes (api_jobs, api_models, api_wer, api_system, pages, sse)
                            └─> services (job_service, model_service, sbobina.wer)
                                  └─> JobStore (data/jobs/<id>/job.json, progress.json)
                          JobSupervisor thread ── Popen ──> stage_runner transcribe
                                               └─ Popen ──> stage_runner correct
                          DownloadManager thread ── snapshot_download / ollama pull(stream)
platform_info (puro) ── usato da transcriber, stage_runner, /api/v1/system
```

| File | Scopo |
|---|---|
| `src/sbobina/transcriber.py` (mod) | kwarg `on_progress`; usa `RuntimeChoice` (device, compute, threads) |
| `src/sbobina/pipeline.py` | service estratto dalla CLI: `transcribe_to_dir`, `correct_to_dir`, `with_progress` |
| `src/sbobina/platform_info.py` | `PlatformInfo`, `detect_platform()` (unico I/O), `resolve_runtime()` puro |
| `src/sbobina/cuda_libs.py` (mod, F9) | ramo Windows: registra le DLL delle wheel NVIDIA |
| `src/sbobina/cli.py` (mod) | usa `pipeline`; sottocomando `web` (import lazy) |
| `src/sbobina/settings.py` (mod) | `device="auto"`, `compute_type="auto"`, `cpu_threads=0`, `whisper_model_cpu`, `web_host`, `web_port`, `data_dir`, `web_max_upload_mb` |
| `pyproject.toml` (mod) | wheel NVIDIA nell'extra `cuda` (marker linux; win32 aggiunto in F9) |
| `src/sbobina/web/job_models.py` | `JobConfig` (validazione per campo), `JobRecord`, `JobStatus`, `JobStage` |
| `src/sbobina/web/job_store.py` | repository filesystem: create/get/list paginato/update atomico/delete |
| `src/sbobina/web/stage_runner.py` | entrypoint figlio: uno stage, `progress.json`, watchdog stdin, exit code |
| `src/sbobina/web/supervisor.py` | coda FIFO, 1 figlio alla volta, cancel, recupero al boot |
| `src/sbobina/web/gpu_release.py` | scarica i modelli Ollama residenti (`ps` + `keep_alive=0`) |
| `src/sbobina/web/model_service.py` | stato/download modelli Whisper e Ollama, stato di Ollama |
| `src/sbobina/web/reader.py` | vista pura del lettore: paragrafi → parole con start/end/incerta/corretta |
| `src/sbobina/web/app.py` | `create_app(...)`, lifespan, middleware host/origin, error handler |
| `src/sbobina/web/responses.py` | envelope `{"data","meta"}` / `{"error"}`, handler 422 |
| `src/sbobina/web/{api_jobs,api_models,api_wer,api_system,pages,sse}.py` | router |
| `src/sbobina/web/templates/*.html`, `static/*.{css,js}` | UI |
| `tests/test_platform_info.py`, `tests/test_pipeline.py`, `tests/web/test_*.py` | mirror |
| `docs/installazione-windows.md`, `avvia-sbobina.bat` (F9) | guida e lanciatore Windows |
| `.github/workflows/ci.yml` (F9, se c'è un remote) | matrice ubuntu/windows/macos |

## Decisioni sui punti aperti

### 1. Callback di progresso senza rompere la CLI
- `transcribe_file(audio_path, config, on_progress=None)`: `ProgressCallback =
  Callable[[float, float], None]` (secondi trascritti, durata). `_collect_segments` la chiama a
  ogni segmento; il log ogni 300 s resta. Default `None` → CLI invariata. Il test esistente
  `test_transcribe_file_passes_vad_setting_to_whisper` deve restare verde senza modifiche.
- `correct_transcript` **non si tocca**: il progresso passa già dal wrapper del `Corrector`
  (`cli._with_progress`). Si sposta in `pipeline.with_progress(corrector, total, on_done)`; la CLI
  passa una callback di logging identica a oggi.
- In B la cancellazione non entra nella pipeline (il figlio viene terminato). Se si sceglie A, la
  callback solleva `JobCancelledError`, che **non** deve ereditare da `CorrectorError`:
  `correct_transcript` cattura solo `InvalidResponseError` e `CorrectorUnavailableError`
  (`src/sbobina/correction.py:83`), quindi un'eccezione diversa risale intatta.

### 2. Liberare la VRAM fra le fasi
- Whisper: lo stage `transcribe` è un processo; alla sua uscita il driver rilascia la memoria. Il
  supervisore avvia `correct` solo dopo `wait()` del primo.
- Ollama: il modello resta residente dopo l'ultima chat (il corrector non passa `keep_alive`,
  `src/sbobina/llm_corrector.py:92`; default server 5 min, BASIS: inferred, UNVERIFIED sulla
  0.18). Il job successivo caricherebbe Whisper con qwen ancora in VRAM → OOM. Prima di ogni stage
  `transcribe`, `gpu_release.unload_ollama_models(host)` elenca `client.ps()` (BASIS: measured,
  metodo presente) e per ciascuno chiama `client.generate(model=name, keep_alive=0)` (BASIS:
  inferred dalla doc Ollama; verifica osservabile `ollama ps` vuoto in T016). Ollama
  irraggiungibile → WARNING, nessuna azione. Su CPU libera RAM ed è comunque innocuo.

### 3. Riavvio con job in corso
- `job.json` porta `status`, `stage`, `pid`, `updated_at`; scritture atomiche (tmp + `os.replace`).
- Orfani senza codice per OS: il supervisore apre il figlio con `stdin=PIPE`; nel figlio un thread
  daemon legge stdin e a EOF (padre morto: la pipe si chiude su ogni OS) chiama `os._exit`.
  Niente `/proc`, niente `psutil`. BASIS: inferred (semantica standard delle pipe), coperto da un
  test che chiude la pipe di un figlio fittizio (T013).
- Al boot: ogni job `running` → `interrupted` con `error.code = "SERVER_RESTARTED"`; gli output
  già prodotti restano leggibili; i `queued` rientrano in coda per `created_at`.
- Su POSIX `start_new_session=True` perché il Ctrl-C del terminale non arrivi al figlio prima che
  il supervisore lo gestisca; l'equivalente Windows sta in F9.

### 4. Cancellazione
- `POST /api/v1/jobs/<id>/cancel`: `queued` → `cancelled` subito; `running` → `terminate()`,
  `kill()` dopo 5 s, `cancelled`; stato terminale → 409 `JOB_NOT_CANCELLABLE`.
- `DELETE /api/v1/jobs/<id>`: solo stati terminali (altrimenti 409); rimuove la cartella.

### 5. Upload: limiti e tipi
- Estensioni: `.m4a .mp3 .wav .ogg .opus .flac .webm .aac`. Limite `web_max_upload_mb`, default 1024.
- Scrittura a chunk da 1 MiB in `audio.part` con contatore; oltre il limite → cancella il parziale
  e 413. Rifiuto anticipato se `Content-Length` supera già il limite.
- Contenuto: `av.open(path)` deve trovare uno stream audio → altrimenti 422 `field: "file"`.
  FFmpeg arriva con la wheel `av` (BASIS: measured su Linux, `av.libs/libavcodec*`), nessuna
  installazione separata. Rinomina `audio.part` → `audio.<ext>` solo dopo.
- Starlette bufferizza il multipart in un file temporaneo prima dell'handler (BASIS: inferred,
  UNVERIFIED): lo spazio occupato è doppio per qualche secondo. Accettato.

### 6. Audio con Range
- `FileResponse` di Starlette gestisce `Range` nelle versioni recenti (BASIS: inferred, UNVERIFIED
  sulla versione che uv risolverà). T021 scrive per primo il test 206/`Content-Range`; se fallisce,
  handler Range minimale (singolo intervallo, 416 su range invalido).

### 7. SSE
- `StreamingResponse(media_type="text/event-stream")` con generatore async che rilegge
  `progress.json`/`job.json` ogni 1 s, emette solo al cambio, `: ping` ogni 15 s, termina su stato
  terminale o `await request.is_disconnected()`; header `Cache-Control: no-cache`. BASIS: inferred
  (UNVERIFIED: T018 consulta context7; se la versione risolta di FastAPI offre una risposta SSE
  dedicata, si usa quella).
- Client `EventSource` con riconnessione automatica; il primo evento dopo il reconnect è lo stato
  corrente, quindi nessun evento perso conta.

### 8. Modelli
- Whisper, elenco: `faster_whisper.utils.available_models()` (BASIS: measured, 19 nomi in 1.2.1;
  alias `large`→large-v3 e `turbo`→large-v3-turbo deduplicati per repo_id).
- Whisper, "già scaricato": `download_model(name, local_files_only=True)` che solleva se assente
  (BASIS: measured la firma; il tipo d'eccezione è inferred, da fissare in T030).
- Whisper, download con avanzamento: `download_model` forza `tqdm_class=disabled_tqdm` (BASIS:
  measured, `faster_whisper/utils.py:102`), quindi si chiama
  `huggingface_hub.snapshot_download(repo_id, allow_patterns=<stessi 5 pattern>)`. In hub 1.33
  `tqdm_class` "non è passato ai singoli download" (BASIS: measured, docstring): darebbe solo file
  completati su 5. Byte: totale da `snapshot_download(..., dry_run=True)` (BASIS: measured il
  parametro; campi dimensione inferred) e scaricati sommando i file della cache durante il
  download (BASIS: inferred). Fallback: barra indeterminata + file completati.
- Ollama: `Client(host).list()` → `models[].model/size` (BASIS: measured); `pull(model,
  stream=True)` → `ProgressResponse(status, completed, total, digest)` (BASIS: measured).
- Stato Ollama (tutte le piattaforme): `not_installed` (`shutil.which("ollama")` nullo e host
  irraggiungibile), `not_running` (eseguibile trovato, host giù), `ready`. Messaggi per OS in F9.
- Download in un thread `DownloadManager` separato dalla coda di inferenza (solo rete e disco),
  uno alla volta, stato in memoria via SSE. Riavvio durante un download: stato perso, si rilancia.

### 9. Sicurezza locale
- `web_host` validato: solo `127.0.0.1`, `::1`, `localhost`.
- `TrustedHostMiddleware(allowed_hosts=["127.0.0.1", "localhost", "::1"])` contro DNS rebinding.
- Middleware Origin: su POST/DELETE, `Origin` presente e diverso da `http://<host>:<port>` → 403.
  Fallimento concreto: senza login, qualunque pagina aperta nel browser può fare POST a 127.0.0.1.
- Id job UUID4, path costruiti solo da id validati.
- Nessun rate limiting: `api-design.md` lo chiede per endpoint pubblici, qui non ce ne sono.

### 10. Piattaforma, device e installazione senza GPU
- **Unico punto di rilevamento**, `platform_info.py`:
  - `PlatformInfo(system: linux|windows|darwin|other, machine, is_apple_silicon, cuda_devices,
    cuda_libs_available, cpu_compute_types, cpu_count)`.
  - `detect_platform()` è l'unica funzione con I/O: `sys.platform`/`platform.machine()`,
    `ctranslate2.get_cuda_device_count()`, `ctranslate2.get_supported_compute_types("cpu")`
    (BASIS: measured su ctranslate2 4.8.2: 1 device qui; CPU `{int8, int8_float32, int16,
    float32}`, CUDA con `float16`), disponibilità delle wheel NVIDIA via
    `importlib.util.find_spec` (senza caricarle).
  - `resolve_runtime(info, requested) -> RuntimeChoice(device, compute_type, whisper_model,
    cpu_threads, reason)` è pura. Tabella:

    | OS | Hardware | device | compute | modello default |
    |---|---|---|---|---|
    | Linux | NVIDIA + wheel | cuda | float16 | `whisper_model` (large-v3), percorso attuale |
    | Linux | NVIDIA senza wheel | cpu + WARNING extra | int8 | `whisper_model_cpu` |
    | Windows | NVIDIA + DLL caricabili (F9) | cuda | float16 | `whisper_model` |
    | Windows | NVIDIA senza DLL, o prima di F9 | cpu | int8 | `whisper_model_cpu` |
    | macOS (Intel o Apple Silicon) | qualsiasi | cpu | int8 se supportato, altrimenti float32 | `whisper_model_cpu` |
    | qualsiasi | nessuna GPU | cpu | int8 se supportato, altrimenti float32 | `whisper_model_cpu` |

  - Device esplicito vince sempre; `cuda` esplicito senza GPU → errore, non ripiego.
  - macOS: CTranslate2 non ha backend Metal/MPS, solo `cpu` e `cuda` (BASIS: inferred dalla doc
    CTranslate2 da training, UNVERIFIED: da confermare con context7 prima di T005).
- `cuda_libs.preload_cuda_libraries()` resta Linux-first e si chiama solo quando il device risolto
  è `cuda` su Linux. Già oggi non fallisce senza wheel (ritorna `[]` su `ImportError`,
  `src/sbobina/cuda_libs.py:21`) e fuori da Linux non trova `.so`; il salto evita il WARNING
  "GPU inference unavailable" a chi usa la CPU di proposito.
- `cpu_threads`: faster-whisper usa 4 thread di default su CPU (BASIS: measured, docstring di
  `WhisperModel`, `faster_whisper/transcribe.py:652`). Setting `0` = auto → `os.cpu_count()`,
  passato a `WhisperModel(cpu_threads=...)` solo su CPU. Logici o fisici: misurato in T061.
- Extra `cuda`: `[project.optional-dependencies] cuda = [<wheel>; sys_platform == 'linux']`,
  installazione GPU `uv sync --extra cuda` (BASIS: measured, `--extra` in `uv sync --help`,
  `--optional` in `uv add --help`). Chi ha già la GPU e lancia `uv sync` senza extra perde le wheel
  (uv sync rende l'ambiente esatto, BASIS: inferred): il WARNING della tabella è ciò che impedisce
  il ripiego silenzioso.
- `GET /api/v1/system` → OS, device, compute_type, motivo, modello di default, stato Ollama.

### 11. Avvio per utenti non tecnici
- `sbobina web` apre il browser (`webbrowser.open`, stdlib, cross-platform) dopo che
  `GET /api/v1/system` risponde; `--no-browser` per disattivarlo; porta occupata → messaggio in
  italiano con `--port`, exit 1.

### 12. Config per job
`JobConfig`: `whisper_model` (in `available_models()`), `beam_size` 1..10, `vad_filter`,
`condition_on_previous_text`, `uncertain_threshold` (0,1], `correct` bool, `ollama_model` non
vuota, `subject` opzionale ≤ 100 caratteri. Default da `settings` e da `RuntimeChoice`. Il figlio
costruisce `Settings.model_validate({**settings.model_dump(), **overrides})` per avere la stessa
validazione (`model_copy(update=...)` non valida).

### 13. Fallback Windows/macOS (F9)
- `cuda_libs` ramo Windows: `os.add_dll_directory` sulle cartelle `bin` delle wheel NVIDIA
  (BASIS: inferred, UNVERIFIED: layout delle wheel su Windows non osservabile qui); extra `cuda`
  esteso a `sys_platform == 'win32'`.
- Ripiego a runtime: se `WhisperModel(device="cuda")` solleva per librerie mancanti, retry su CPU
  con WARNING e nota nel job. Copre le combinazioni che la probe non intercetta.
- Processi: `creationflags=CREATE_NEW_PROCESS_GROUP` su win32; figli con `PYTHONUTF8=1` e log su
  file UTF-8 (su Windows una pipe usa la codifica di sistema: le lettere accentate possono
  sollevare `UnicodeEncodeError`, BASIS: inferred); `os.replace` con retry breve su
  `PermissionError` (Windows rifiuta il rename su un file aperto da un lettore, BASIS: inferred).
- FFmpeg: `uv.lock` risolve `av` e `ctranslate2` per `win_amd64` e `macosx_*_arm64` (BASIS:
  measured nel lock). Che la wheel Windows includa FFmpeg come quella Linux è BASIS: inferred, da
  confermare in CI con una decodifica m4a reale.
- Ollama: messaggi per OS da `platform_info` (Windows/macOS: installer da ollama.com e avvio
  dall'app; Linux: script e `ollama serve`). BASIS: inferred che l'installer Windows metta
  `ollama` nel PATH; se non lo fa, lo stato degrada a `not_installed` con lo stesso link.
- Guida `docs/installazione-windows.md` + `avvia-sbobina.bat` (doppio clic → `uv run sbobina web`).
- CI GitHub Actions su `ubuntu-latest`, `windows-latest`, `macos-latest`: suite, smoke test di
  avvio del server, decodifica m4a. **Dipende dalla scelta di creare un remote** (oggi
  `git remote -v` è vuoto, BASIS: measured); il push resta all'utente.

## Fasi (indipendentemente mergiabili)

| Fase | Stato dopo il merge | Task | Stima |
|---|---|---|---|
| F1 Service e hook di progresso | CLI identica, `pipeline.py` riusabile, progresso iniettabile | T001-T004 | 0.5-1 g |
| F2 Piattaforma e CPU su Linux | CLI gira su GPU e CPU, extra `cuda`, default per piattaforma | T005-T009 | 1-1.5 g |
| F3 Server, coda, job, SSE | `sbobina web` accoda e completa job con progresso live, pagina minima | T010-T019 | 2-3 g |
| F4 Lettore e storico | lezioni riapribili, audio sincronizzato, download | T020-T025 | 1.5-2 g |
| F5 Modelli e stato Ollama | elenco, stato, download con avanzamento | T030-T034 | 1-1.5 g |
| F6 WER | WER da browser | T040-T041 | 0.5 g |
| F7 UI finale | design, avvisi CPU, a11y, render, click-through | T050-T054 | 1.5-2.5 g |
| F8 Verifica reale Linux | job GPU da 85 min, CPU, riavvio, cancellazione | T060-T062 | 1 g |
| F9 Fallback Windows/macOS | CUDA Windows opzionale, processi, guida, CI | T070-T076 | 2-3 g |

Base 11-16 giorni; buffer imprevisti +20% (primo uso di FastAPI/SSE nel repo, supervisione
processi, download HF senza precedenti, piattaforme non osservabili qui) → **13-19 giorni**.
Il tempo macchina dei run reali non è incluso.

Dipendenze: F2 indipendente dal web (dà valore ai colleghi Linux senza GPU già da CLI). F7 dipende
da F3-F6 perché ridisegna le loro pagine; F3-F6 escono con template funzionali e CSS minimo,
usabili ma non rifiniti. F9 dipende solo da F2 e F3 e si può mergiare a sé.

## Rischi e mitigazioni

- Poiché Ollama tiene il modello in VRAM 5 min dopo l'ultima chat, un job accodato subito dopo può
  andare in OOM caricando Whisper; effetto: job fallito e coda ferma. → `gpu_release` prima di ogni
  stage transcribe, verifica `ollama ps` in T016 e T060.
- Poiché `uv sync` rimuove ciò che non è dichiarato, spostare le wheel NVIDIA nell'extra fa perdere
  la GPU a chi aggiorna senza `--extra cuda`; effetto: trascrizioni molto più lente senza errore.
  → WARNING GPU-senza-extra (T007), banner in UI, nota README (T062, su OK).
- Poiché su CPU large-v3 su 85 min di audio richiede tempi non misurati (plausibilmente ore), un
  collega può credere il sistema bloccato. → default CPU turbo, velocità ed ETA reali, avviso
  prima dell'accodamento.
- Poiché `download_model` disabilita il progresso e hub non passa `tqdm_class` ai singoli file,
  la barra dei ~3 GB di large-v3 può non avere dati byte; effetto: +0.5 g su T031 o barra
  indeterminata. → T031 parte dal calcolo dry_run, fallback dichiarato.
- Poiché le API FastAPI/Starlette (Range, SSE, multipart) e CTranslate2 su macOS non sono state
  verificate su una fonte, un dettaglio può differire; effetto: 0.5 g su F3/F4. → ogni task
  relativo apre con il test del comportamento e la consultazione context7.
- Poiché qui c'è solo Linux, processi, rename atomico, codifica dei log, DLL CUDA e wheel su
  Windows/macOS restano non osservati; effetto: primo collega Windows bloccato, 0.5-2 g di fix a
  distanza. → logica di piattaforma pura e testata per combinazioni, regole cross-platform da F1,
  CI su windows-latest/macos-latest (T075, dipende dal remote) o checklist T076.
- Poiché l'installazione di uv e Ollama è a carico del collega, un passo saltato si presenta come
  "correzione fallita"; effetto: supporto a distanza. → stati Ollama in UI, guida T074.
- Poiché l'audio arriva in m4a, un browser senza codec AAC non lo riproduce; effetto: lettore
  senza audio. → messaggio esplicito, transcodifica fuori v1.
- Poiché i limiti 300/30 righe valgono anche per JS, `reader.js` rischia di crescere. → split per
  responsabilità (sync audio, evidenza, correzioni).

## Criteri di verifica

- `uv run pytest`, `uv run ruff check .`, `uv run mypy src tests` verdi a ogni fase.
- F2: `CUDA_VISIBLE_DEVICES="" uv run sbobina trascrivi <30 s wav>` completa con log
  `device=cpu compute_type=int8`; senza la variabile torna su cuda.
- F3: `uv run sbobina web`, `curl -F file=@fixture.wav`, `curl -N .../events` mostra eventi.
- F7: `DIAL:`, `a11y-gate`, render 375/1280, click-through con esiti registrati.
- F8: lezione vera, `nvidia-smi` fra le fasi, riavvio e cancellazione durante il job.
- F9: CI verde sui tre OS o checklist eseguita; altrimenti Windows/macOS dichiarati non verificati.

# ADR-003: Provider LLM cloud con catena di fallback e trascrizione AssemblyAI

**Stato**: Proposto, da accettare dopo le verifiche in fondo
**Data**: 2026-10-06
**Ambito**: decisioni D1-D6 per due funzioni: provider LLM via API (Groq, Gemini, OpenAI,
Anthropic) accanto a Ollama, in una catena di fallback ordinata dall'utente con Ollama ultimo
anello; AssemblyAI come alternativa a faster-whisper per la trascrizione
**Relazione con decisioni precedenti**: modifica il vincolo fondativo di `CLAUDE.md` ("Audio must
never leave the machine; text correction uses a local LLM via Ollama, not a cloud API"), estende
ADR-001 D3 (`GpuArbiter`, FIFO) e lascia invariati ADR-002 D1-D6.

## Decisioni già prese dall'utente (non rivalutate qui)

- Chiavi in un file dedicato con permessi 0600 nella cartella di configurazione dell'utente; la
  variabile `SBOBINA_<PROVIDER>_API_KEY` ha la precedenza; le chiavi non tornano mai al browser.
- L'OCR resta locale (`ocr_runner.py`, `ollama_vision.py` non cambiano).
- Un'impostazione globale "motore Locale/API" più l'ordine dei modelli, nella pagina Impostazioni.

## Contesto

### Il vincolo che cambia

Fino a oggi nulla usciva dalla macchina. Con questo ADR escono, solo se l'utente sceglie "API":
il testo delle trascrizioni (correzione, studio, generazioni, chat, giudizio delle risposte),
i passaggi dei documenti del corso (retrieval nella chat e nelle generazioni) e, con AssemblyAI,
**l'audio**. I documenti del corso sono spesso materiale coperto da diritto d'autore, e le
registrazioni contengono la voce del docente e di chi interviene. Conseguenze vincolanti per
tutte le decisioni sotto:

- il default resta Locale; il passaggio ad API è un consenso esplicito, con un testo che dice
  cosa esce e verso chi;
- ogni artefatto prodotto con un provider cloud porta scritto quale provider e modello lo ha
  prodotto (D2);
- la riga di `CLAUDE.md` va riscritta quando l'ADR viene accettato: "Locale per default; audio e
  testo escono solo con il motore API scelto dall'utente".

### Fatti dal codice (BASIS: measured, letti in questa sessione)

| Fatto | Fonte | Conseguenza qui |
|---|---|---|
| `type ChatClient = Callable[[ChatRequest], str]` è il confine di chat, generazione, giudizio | `src/sbobina/chat_pipeline.py:46` | una catena può essere un `ChatClient` senza toccare le pipeline |
| Il correttore e lo studio **non** passano dal `ChatClient`: costruiscono un `ollama.Client` e chiamano `chat_json` | `src/sbobina/llm_corrector.py:103`, `src/sbobina/study_command.py:50` | vanno portati sul `ChatClient` prima di poter usare la catena |
| `ChatRequest.model` porta il modello Ollama scelto dal chiamante | `src/sbobina/ollama_chat.py:19` | con una catena il modello lo decide l'anello, non il chiamante |
| `chat_json` ripara fence, LaTeX, parentesi e virgolette sul testo grezzo | `src/sbobina/ollama_chat.py:155` | le riparazioni sono logica pura riusabile da ogni adapter |
| `CorrectorUnavailableError` = fermati; `InvalidResponseError` = salta solo questo blocco | `src/sbobina/correction.py:27` | la tassonomia della catena deve conservare queste due semantiche |
| Budget del materiale calcolato su `CONTEXT_WINDOW_TOKENS = 8192` | `src/sbobina/ollama_chat.py:14`, `src/sbobina/web/chat_turn.py:65` | il prompt costruito per un anello deve stare anche nell'anello di riserva |
| `temperature: 0`, `think=False`, `num_ctx` sono opzioni Ollama | `src/sbobina/ollama_chat.py:157` | ogni provider ha le sue capacità: niente parametri condivisi per default |
| Figli lanciati con `env = dict(os.environ)` | `src/sbobina/web/processes.py:14` | qualunque chiave messa in `os.environ` dal processo web arriva a **ogni** figlio, compresi quelli che parsano PDF e pacchetti non fidati |
| `JobConfig.ollama_model` fotografato all'accodamento in `job.json` | `src/sbobina/web/job_models.py:92` | esiste già il precedente "snapshot per job" |
| `generation_runner` legge `settings.ollama_model` dal vivo nel figlio | `src/sbobina/web/generation_runner.py:289` | per le generazioni oggi non c'è snapshot |
| `_guarded` avvolge l'intero `ChatClient` della chat in `arbiter.chat_turn()` | `src/sbobina/web/chat_turn.py:97` | con una catena la guardia va spostata sull'anello Ollama |
| `before_transcribe=unload_ollama_models` prima di ogni trascrizione | `src/sbobina/web/app.py:156` | con AssemblyAI scaricare Ollama dalla VRAM è inutile |
| Parole Whisper con spazio iniziale; `Segment.text` le concatena senza separatore | `src/sbobina/transcriber.py:39`, `src/sbobina/models.py:24` | le parole AssemblyAI vanno normalizzate allo stesso formato |
| Paragrafi del lettore raggruppati per pausa tra **segmenti** (`paragraph_gap_s`) | `src/sbobina/render.py:71` | i segmenti devono restare unità piccole, come quelli di Whisper |
| `OriginMiddleware` rifiuta le mutazioni con `Origin` diverso, lascia passare quelle senza `Origin` | `src/sbobina/web/middleware.py:27` | difesa già presente contro un sito che scrive chiavi sul server locale |
| Dipendenze: `httpx` sì, `platformdirs` e `keyring` assenti da `uv.lock` | `pyproject.toml:12`, `uv.lock` | ogni SDK o libreria di path è una dipendenza nuova |

### Dettagli delle API dei provider

Tutto ciò che questo ADR dice sulle API esterne è `UNVERIFIED: da training data, verificare
prima della produzione`, salvo dove è indicato altro. L'elenco consolidato da verificare è in
fondo (V1-V9). Fa eccezione un fatto dato dall'utente: Opus 5.5 e Sonnet 5 rispondono 400 se la
richiesta contiene `temperature`.

---

## D1. Adapter verso i provider (A1)

### Passata 1: approcci generati

1. httpx sottile con due protocolli: OpenAI-compatible (OpenAI, Groq, Gemini tramite endpoint
   compatibile) e Anthropic Messages nativo.
2. SDK ufficiali: `openai`, `anthropic`, `google-genai`, `groq`.
3. Ibrido: SDK `anthropic`, httpx per tutto il protocollo OpenAI-compatible.
4. Libreria di astrazione multi-provider (LiteLLM o simili).
5. Solo `openai` SDK puntato su base URL diverse, Anthropic compreso tramite il suo endpoint di
   compatibilità OpenAI.
6. Tutto tramite l'endpoint OpenAI-compatible di Ollama, che diventa un anello come gli altri.
7. Un adapter httpx per ciascuno dei quattro provider, con API native (anche Gemini nativo).

### Passata 2: valutazione

**Opzione 1, httpx sottile con due protocolli (raccomandata)**

- Pro: nessuna dipendenza nuova. Il bisogno è stretto: una sola chiamata non in streaming, senza
  tool, con risposta JSON. Un protocollo è una funzione pura che costruisce il corpo della
  richiesta, una che legge la risposta e una tabella di errori, sotto le 150 righe ciascuno
  (BASIS: inferred). Tipi nostri sotto mypy strict, nessun `Any` importato. Test con
  `httpx.MockTransport` sul client reale, nessun mock di SDK. Il controllo dei retry resta nostro:
  è la catena (D2) che decide quando ritentare e quando passare al successivo.
- Contro: le differenze fra provider dentro il protocollo OpenAI-compatible (chi accetta
  `response_format` con `json_schema`, chi rifiuta `temperature`, nomi dei campi di uso dei token)
  le manteniamo noi in una tabella di capacità. Un'API che cambia non ci avvisa con un upgrade di
  SDK: lo scopriamo da un errore 400, che D2 rende visibile.
- Costo di migrazione: nullo, codice nuovo accanto a `ollama_chat.py`.
- Giusta se: i bisogni restano "una chiamata, JSON in uscita". Smette di esserlo con streaming
  della chat, tool use o batch API.

**Opzione 2, SDK ufficiali**

- Pro: tipi forniti, retry e gestione errori già scritti, nuovi parametri disponibili senza
  scriverli. `openai` e `anthropic` sono costruiti su httpx e accettano un `http_client`, quindi
  anche `MockTransport` funziona (UNVERIFIED per `google-genai`).
- Contro: quattro dipendenze con le loro transitive (`google-genai` porta l'autenticazione Google
  e altro: UNVERIFIED), da tenere aggiornate su tre sistemi operativi per colleghi che spesso non
  useranno il motore API. I retry interni (due per default su `openai`/`anthropic`, UNVERIFIED)
  vanno disattivati, altrimenti sommano attesa prima che la catena passi al successivo. Quattro
  modelli di errore da tradurre nella stessa tassonomia invece di uno per codice HTTP. `groq` e
  OpenAI hanno lo stesso protocollo: due SDK per una forma sola.
- Giusta se: arriva lo streaming nella chat o il tool use, dove gli SDK fanno davvero risparmiare.

**Opzione 3, ibrido**

- Pro: Anthropic ha l'API più diversa (header `x-api-key` e `anthropic-version`, `system` fuori
  dai messaggi, `max_tokens` obbligatorio: UNVERIFIED); l'SDK ne nasconde le differenze.
- Contro: le differenze sono poche e stabili; l'SDK aggiunge una dipendenza e un secondo modo di
  fare la stessa cosa nel codice. Il guadagno è marginale e il costo è codice e dipendenze in più:
  scartata per la tabella di `code-standards.md`.

**Scartate**

- 4, LiteLLM: albero di dipendenze ampio per usare il 2% della libreria; il controllo di retry e
  fallback, che è proprio D2, passerebbe a lei.
- 5, solo SDK `openai` anche per Anthropic: l'endpoint compatibile di Anthropic perde le
  funzioni native di output strutturato (UNVERIFIED) e non toglie la dipendenza.
- 6, Ollama via endpoint OpenAI-compatible: `num_ctx` e `think` non passano da lì (UNVERIFIED),
  e tutte le misure del progetto (T036, T067, V5) sono fatte sull'adapter attuale.
- 7, quattro adapter nativi: Gemini nativo mette la chiave nella query string (`?key=`,
  UNVERIFIED), dove finisce nei log di httpx; tre protocolli invece di due senza un bisogno.

### Decisione D1

Opzione 1. Struttura:

- `llm_protocols/openai_compat.py` e `llm_protocols/anthropic_messages.py`: funzioni pure
  `build_body(request, link) -> dict` e `parse_reply(json) -> ProviderReply` (testo, motivo di
  stop, token in ingresso e uscita), più `classify_error(status, body) -> LinkFailure`.
- `llm_http.py`: l'unico confine httpx dei provider cloud (timeout, header di autenticazione).
- `ollama_chat.py` resta il confine Ollama; le riparazioni JSON (`strip_markdown_fence`,
  `escape_latex_backslashes`, `close_open_brackets`, `escape_inner_quotes`) si spostano in
  `json_repair.py`, puro, applicato al testo di ogni anello allo stesso modo.
- Tabella di capacità per **modello**, non per provider (`provider_catalog.py`): finestra di
  contesto, se accetta `temperature`, modo JSON supportato (`json_schema`, `json_object`,
  nessuno), parametro del limite di uscita (`max_tokens` o `max_completion_tokens`, UNVERIFIED per
  i modelli di ragionamento OpenAI). Default prudente per un modello non in tabella: niente
  `temperature`, `json_object`, contesto 8192.
- Lo schema viene sempre inviato dove supportato, ma la validazione resta quella di oggi, nei
  chiamanti, con pydantic. Il modo `strict` di OpenAI richiede `additionalProperties: false` e
  tutti i campi obbligatori (UNVERIFIED), che gli schemi pydantic attuali non garantiscono: si usa
  la forma non strict.

### Conseguenze D1

- Le riparazioni sono state tarate su qwen3.5:9b. Su un modello cloud con output vincolato la
  riparazione LaTeX trasforma un `\n` seguito da lettera in testo letterale, come già oggi su
  Ollama per scelta (`ollama_chat.py:32`). Accettato perché i campi sono frasi; da misurare (V7).
- I modelli di ragionamento consumano token di pensiero dentro il limite di uscita (UNVERIFIED
  per OpenAI e Gemini): i `num_predict` misurati su qwen con `think=False` troncherebbero il JSON.
  La tabella di capacità porta un moltiplicatore del limite e, dove esiste, il livello minimo di
  ragionamento (V6).

---

## D2. Catena di fallback (A2)

### Passata 1: approcci generati

1. `ChatClient` composito: una funzione che prova gli anelli in ordine, con la stessa firma
   `Callable[[ChatRequest], str]`.
2. Fallback nei chiamanti: ogni pipeline cattura l'errore e richiama con l'anello successivo.
3. Fallback a livello di job: il job fallisce sul primo provider e il supervisor lo riaccoda col
   successivo.
4. Selezione all'accodamento: si sceglie il primo anello disponibile (ping) e si usa solo quello
   per tutto il job.
5. Proxy locale (un processo che espone un endpoint unico e fa da router).
6. Router per compito: modelli diversi per correzione, chat, generazioni, giudizio.

### Passata 2: valutazione

**Opzione 1, `ChatClient` composito (raccomandata)**

- Pro: nessuna pipeline cambia firma; la catena vive in un posto e si testa da sola con anelli
  finti. Circuit breaker e registro delle chiamate stanno nell'istanza: nei figli della coda
  l'istanza dura quanto il job, quindi "per job" viene gratis; nel processo web dura quanto il
  processo e serve un raffreddamento a tempo.
- Contro: il composito restituisce solo `str`, quindi chi ha risposto va comunicato per un canale
  laterale (sotto). Il correttore e lo studio vanno portati sul `ChatClient` (oggi parlano a Ollama
  direttamente): due file, modifica meccanica.
- Costo di migrazione: basso; prima la migrazione dei due chiamanti a catena di un solo anello
  Ollama, comportamento identico, poi la catena vera.

**Opzione 4, un provider per job scelto all'accodamento**

- Pro: output omogeneo, un solo modello per artefatto, tracciabilità banale.
- Contro: un 429 a metà job (quota per minuto di Groq o Gemini gratuiti: UNVERIFIED) ferma il
  job invece di passare a Ollama; un ping al momento dell'accodamento non dice niente sulla quota
  fra un'ora. Toglie proprio la ragione della catena.
- Giusta se: l'utente vuole artefatti mono-modello a qualunque costo. Si ottiene comunque con una
  catena di un solo anello.

**Opzione 2, fallback nei chiamanti**

- Contro: sei chiamanti (`chat_pipeline`, `generation_pipeline`, `grading`, `study_pipeline`,
  `llm_corrector`, `practice_grading`) con la stessa logica duplicata e sei posti in cui la
  tassonomia può divergere.

**Scartate**

- 3, fallback per job: rifare da capo una correzione da 38 minuti per un 429 sul quarantesimo
  blocco.
- 5, proxy locale: un processo in più da avviare su tre sistemi operativi per una funzione che
  sta in 200 righe.
- 6, router per compito: utile, ma è una funzione nuova e non richiesta; la struttura della
  catena non lo impedisce più avanti (una catena per compito).

### Decisione D2

**Composizione.** `LlmChain(links, recorder, clock)` implementa `ChatClient`. Ogni anello è
`ChatLink(provider, model, call)`; il composito passa `replace(request, model=link.model)` e
applica `json_repair` al testo restituito. Se tutti gli anelli sono falliti o aperti solleva
`CorrectorUnavailableError` con l'elenco dei motivi, come oggi.

**Tassonomia.** Decide se passare all'anello successivo e per quanto tempo l'anello resta aperto:

| Esito dell'anello | Passa al successivo | Breaker sull'anello |
|---|---|---|
| Errore di rete, timeout di connessione | sì | aperto dopo 2 fallimenti consecutivi, raffreddamento 60 s |
| Timeout di lettura | sì | come sopra |
| 429 con `Retry-After` ≤ 20 s | no: attesa e **un** nuovo tentativo sullo stesso anello, poi sì | aperto per `Retry-After` |
| 429 senza `Retry-After` o oltre 20 s | sì | aperto per `Retry-After` o 120 s |
| 5xx (compreso 529 di Anthropic, UNVERIFIED) | sì | aperto dopo 2 consecutivi, 60 s |
| 401, 403, chiave assente | sì | aperto per tutto il job o fino al cambio chiave; avviso all'utente |
| 404 modello inesistente | sì | aperto per tutto il job; avviso |
| 400 | sì, con log ERROR del corpo dell'errore | aperto per tutto il job: un 400 deterministico (parametro non accettato, contesto troppo lungo) si ripeterebbe su ogni blocco |
| Risposta bloccata dal filtro di sicurezza del provider | sì | chiuso: dipende dal testo, non dall'anello |
| `GpuBusyError` sull'anello Ollama (solo processo web, D5) | è l'ultimo: l'errore finale resta 409 `GPU_BUSY` | chiuso |
| Risposta arrivata ma JSON non valido o fuori schema | **no** | chiuso |
| Risposta troncata al limite di uscita | **no** | chiuso |

Il JSON non valido non passa al successivo per tre ragioni: la validazione per schema avviene nei
chiamanti, dopo il `ChatClient`, quindi il composito non la vede; oggi `InvalidResponseError`
significa "salta questo blocco" e la semantica resta identica; un fallback silenzioso su output
scadente nasconderebbe proprio il segnale che serve per togliere un modello dalla catena. Il
registro (sotto) conta questi casi per anello.

**Registro delle chiamate.** Canale laterale, nessuna firma cambia: `CallRecorder` riceve per ogni
tentativo `(seq, provider, model, esito, latenza_ms, token_in, token_out)`. Uso:

- ogni artefatto (trascrizione corretta, generazione, studio, turno di chat, giudizio) salva nei
  suoi metadati `llm_calls`: conteggio per `(provider, model)` ed esiti;
- il report delle correzioni annota per ogni blocco `provider/model` (il correttore legge
  `recorder.last` dopo ogni chiamata, un solo thread per figlio);
- il lettore mostra "corretto con: groq/…, ollama/…" quando i modelli sono più d'uno.

Nessun testo di prompt o risposta nel registro: solo metadati.

### Conseguenze D2

- Una correzione può alternare modelli fra un blocco e l'altro. È visibile nel report, ed è il
  prezzo esplicito del non fermarsi.
- **Budget del contesto**: i budget del materiale si calcolano sulla finestra **minima** degli
  anelli della catena. Con Ollama sempre ultimo, oggi vale 8192 anche quando il primo anello
  avrebbe 128k. Alternativa scartata: budget per anello, che obbliga a ricostruire prompt e
  retrieval a ogni passaggio di anello. Si riapre se l'utente toglie Ollama dalla catena.
- Il breaker del processo web (chat, giudizio) è condiviso fra richieste: un 401 apre l'anello
  finché la chiave non cambia, non per ogni messaggio.

---

## D3. Modello dati della configurazione e propagazione ai figli (A3)

### Passata 1: approcci generati

1. `Settings` e variabili d'ambiente (`.env`), scritte dalla pagina Impostazioni.
2. File JSON di preferenze nella cartella di configurazione dell'utente, accanto ai segreti.
3. File JSON in `data/` (`data/llm.json`).
4. Lettura dal vivo nei figli a ogni chiamata o a ogni avvio.
5. Snapshot della catena nel record di lavoro all'accodamento.
6. Variabile d'ambiente serializzata passata al figlio al lancio.

Sono due assi: dove sta la preferenza (1-3) e come arriva al figlio (4-6).

### Passata 2: valutazione, dove sta la preferenza

**Opzione 2, `llm.json` nella cartella di configurazione dell'utente (raccomandata)**

- Pro: preferenza della macchina e della persona, come le chiavi; sopravvive a un cambio di
  `data_dir` e non viaggia con un pacchetto corso o con una copia di `data/`. Un solo posto per
  "come uso i provider", due file con permessi diversi (`llm.json` 0644, `secrets.json` 0600).
  Validata da un modello pydantic (`LlmPreferences`: motore, catena di `{provider, model}`, motore
  di trascrizione, consenso con data).
- Contro: un secondo regime di configurazione accanto a `Settings`. Precedenza da dichiarare:
  `SBOBINA_LLM_ENGINE` e `SBOBINA_LLM_CHAIN` (per CLI e uso senza interfaccia) vincono sul file,
  e la pagina Impostazioni mostra i campi bloccati con "impostato da variabile d'ambiente", come
  per le chiavi.
- Costo: un modulo di lettura e scrittura atomica, lo stesso di D4.

**Opzione 1, `Settings`/`.env`**

- Pro: nessun meccanismo nuovo; i figli rileggono `Settings()` già oggi.
- Contro: scrivere `.env` dall'interfaccia vuol dire riscrivere un file che l'utente edita a mano
  e che contiene altro; `.env` è relativo alla directory di lavoro (`env_file=".env"`), quindi
  dipende da dove si avvia sbobina. Una lista ordinata in una variabile d'ambiente è JSON dentro
  una stringa.
- Giusta se: la configurazione resta solo da riga di comando. Resta comunque come sovrascrittura.

**Opzione 3, `data/llm.json`**

- Contro: `data/` è il dato dei corsi, si copia e si condivide; una preferenza che dice "manda
  tutto a OpenAI" non deve arrivare con una copia della cartella sulla macchina di un collega.

### Passata 2: valutazione, come arriva al figlio

**Opzione 5, snapshot nel record di lavoro (raccomandata)**

- Pro: stesso precedente di `JobConfig.ollama_model`. Il job in coda da un'ora fa ciò che
  l'utente aveva scelto quando l'ha lanciato; `job.json` dice cosa era previsto, il registro di D2
  dice cosa è successo. Le chiavi **non** sono nello snapshot: il figlio le legge dallo store (D4)
  quando ne ha bisogno, quindi una chiave revocata nel frattempo produce un 401 gestito da D2.
- Contro: cambiare l'ordine non tocca i job già in coda. È il comportamento giusto, ma va detto
  nell'interfaccia ("vale per i prossimi lavori").
- Dove: `JobConfig` acquista `llm_chain: tuple[ChainLink, ...]` e
  `transcription_engine: Literal["local", "assemblyai"]`. Per i lavori di corso (generazioni)
  lo snapshot va nel record di generazione, che oggi legge `settings.ollama_model` dal vivo.
- Compatibilità: i `job.json` esistenti non hanno `llm_chain`; un validatore lo deriva da
  `ollama_model` (catena di un solo anello Ollama). `ollama_model` resta nel modello e viene
  scritto ancora, per i record vecchi e per l'anello Ollama.

**Opzione 4, lettura dal vivo**

- Contro: un job lanciato col motore Locale che parte dopo un cambio passa al cloud senza che
  l'utente lo abbia deciso per quel lavoro: è un'uscita di dati non consentita al momento del
  lancio.

**Scartata**

- 6, variabile d'ambiente al lancio: duplica lo snapshot già persistito e non lascia traccia nel
  record.

### Decisione D3

Preferenze in `llm.json` nella cartella di configurazione dell'utente, sovrascrivibili da
variabili d'ambiente; snapshot di catena e motore di trascrizione nel record di lavoro
all'accodamento; chiavi lette dal figlio, mai copiate nel record. Chat e giudizio nel processo web
usano le preferenze correnti: sono interazioni sincrone, la scelta è contestuale al clic.

### Conseguenze D3

- Con motore "Locale" la catena effettiva è `[ollama:<ollama_model>]` e nulla cambia rispetto a
  oggi: è il test di non regressione della migrazione.
- Il motore di trascrizione è indipendente dal motore LLM: si può trascrivere in locale e
  correggere via API, o il contrario. L'interfaccia deve mostrare i due consensi separati,
  perché il secondo fa uscire l'audio.

---

## D4. Secret store (A4)

### Passata 1: approcci generati

1. File JSON `secrets.json` 0600 nella cartella di configurazione, scrittura atomica.
2. File in formato dotenv (`secrets.env`) 0600.
3. Portachiavi del sistema (`keyring`: Credential Manager, Keychain, Secret Service).
4. File cifrato con una chiave derivata da una passphrase.
5. Un file per chiave (`keys/groq`), stile `~/.ssh`.

Per il path:

6. `platformdirs`.
7. Funzione propria su `sys.platform` (XDG su Linux, `~/Library/Application Support` su macOS,
   `%APPDATA%` su Windows).

### Passata 2: valutazione

**Opzione 1, `secrets.json` 0600 (raccomandata, nel perimetro deciso dall'utente)**

- Formato: `{"version": 1, "keys": {"groq": "…"}}`, letto in un modello pydantic con
  `SecretStr` (il valore non compare in `repr` né nei log di validazione).
- Scrittura: lock in processo (unico scrittore: il processo web), file temporaneo nella stessa
  cartella aperto con `os.open(path, O_CREAT | O_EXCL | O_WRONLY, 0o600)`, `fsync`, `os.replace`.
  La cartella si crea 0700. Mai `Path.write_text` seguito da `chmod`: fra le due chiamate il file
  esiste con i permessi dell'umask.
- Lettura: su POSIX, se il file ha permessi più larghi di 0600 si stringe con `chmod` e si scrive
  un WARNING (senza il valore). Rifiutare, come fa ssh, lascerebbe l'utente senza un messaggio
  utile nell'interfaccia.
- Windows: `chmod` agisce solo sul flag di sola lettura, quindi 0600 non significa niente
  (BASIS: measured nella documentazione di `os.chmod`, nota per Windows, da rileggere: V9).
  `%APPDATA%` è per utente e il suo ACL per default esclude gli altri utenti non amministratori
  (UNVERIFIED). Si documenta che su Windows la protezione è quella del profilo utente, senza
  un ACL esplicito in v1. `os.replace` su Windows può fallire se un antivirus tiene aperto il file:
  un nuovo tentativo dopo 100 ms, poi errore chiaro.
- Precedenza: `SBOBINA_<PROVIDER>_API_KEY` vince sul file. **Il processo web non copia mai le
  chiavi del file in `os.environ`**: `_child_env()` le passerebbe a tutti i figli, compresi
  `extraction_worker` e `package_import_worker`, che aprono file non fidati. Per lo stesso motivo
  `_child_env()` rimuove `SBOBINA_*_API_KEY` dall'ambiente dei figli di estrazione e import; i
  figli che ne hanno bisogno (pipeline, studio, generazione) leggono store ed env da soli.
- Pro: un file leggibile e cancellabile dall'utente, nessuna dipendenza, stesso comportamento sui
  tre sistemi.
- Contro: chiave in chiaro su disco, protetta solo dai permessi. Un backup della home la porta con
  sé.

**Opzione 3, portachiavi di sistema**

- Pro: cifratura a riposo gestita dal sistema, prompt di sblocco su macOS.
- Contro: su Linux senza sessione grafica o senza Secret Service non c'è backend (UNVERIFIED nel
  dettaglio), e un collega su un server o in WSL resta senza chiavi; diagnostica diversa per
  sistema; una dipendenza nuova con backend nativi. L'utente ha già scelto il file.
- Giusta se: sbobina diventa un'app desktop distribuita a utenti non tecnici. Si può aggiungere
  come secondo backend dietro la stessa interfaccia `SecretStore`.

**Scartate**

- 2, dotenv: il parsing di quote e caratteri speciali è un formato meno definito del JSON, e
  pydantic-settings lo leggerebbe come configurazione generica con il rischio di mescolarlo.
- 4, file cifrato con passphrase: una passphrase da chiedere a ogni avvio, o salvata accanto al
  file, che annulla la cifratura.
- 5, un file per chiave: quattro scritture atomiche invece di una, nessun guadagno.
- 6, `platformdirs`: una dipendenza per tre righe, e il suo default su macOS
  (`~/Library/Application Support`) è quello che scriveremmo comunque. Funzione propria
  (`config_dir()`), con `SBOBINA_CONFIG_DIR` per i test e per chi vuole altrove.

### API REST

Prefisso `/api/v1`, come le rotte esistenti (BASIS: measured, `src/sbobina/web/api_*.py`).

| Metodo e rotta | Corpo | Risposta |
|---|---|---|
| `GET /api/v1/providers` | | per provider: `configured`, `source` (`env`, `file`, `null`), `updated_at`; **mai** il valore, nemmeno le ultime cifre |
| `PUT /api/v1/providers/{provider}/key` | `{"key": "…"}` | 204; 409 `KEY_FROM_ENV` se la variabile d'ambiente è impostata (scrivere il file non cambierebbe niente); 422 se vuota o con spazi |
| `DELETE /api/v1/providers/{provider}/key` | | 204; 409 `KEY_FROM_ENV` come sopra |
| `POST /api/v1/providers/{provider}/check` | | prova la chiave con una chiamata a costo nullo (elenco modelli, UNVERIFIED per provider) e restituisce `ok` o il codice di errore |
| `GET/PUT /api/v1/llm-preferences` | catena e motori | catena validata contro il catalogo e le chiavi presenti |

Minaccia specifica: un sito aperto nel browser che fa `PUT` di una **sua** chiave e di una catena
cloud riceverebbe sul proprio account le lezioni dell'utente. `OriginMiddleware` già rifiuta le
mutazioni con `Origin` estraneo; per queste rotte si chiede in più `Origin` **presente** e uguale
all'origine dell'app, e `Content-Type: application/json` (che obbliga a un preflight CORS). Il
cambio del motore verso API richiede il consenso esplicito dalla pagina, non solo la chiamata.

### Redazione nei log

- Un filtro `logging` installato in ogni processo sostituisce con `***` ogni occorrenza esatta
  delle chiavi caricate (env e file) in messaggio e argomenti formattati.
- Nessun log di header o corpi di richiesta; degli errori dei provider si logga il corpo (serve
  per i 400), filtrato.
- Il logger `httpx` resta a WARNING: a INFO stampa l'URL di ogni richiesta (con il protocollo
  scelto in D1 la chiave non è mai nell'URL, ma è la seconda difesa).
- Test: una chiave finta attraversa un errore 401 e un 400, e il file di log del figlio non la
  contiene; caso positivo appaiato in cui il filtro è disattivato e la chiave compare.

### Decisione D4

`secrets.json` 0600 (cartella 0700) in `config_dir()`, scrittura atomica con `O_EXCL` e
`os.replace`, env prioritaria, chiavi mai in `os.environ` né nei figli di estrazione e import,
API che restituisce solo lo stato, filtro di redazione in ogni processo.

---

## D5. GPU arbiter con catena mista (A5)

### Passata 1: approcci generati

1. Lock solo sull'anello Ollama: `_guarded` avvolge la `call` del link Ollama, non la catena.
2. Lock sull'intera catena, come oggi.
3. Nessun lock quando la catena contiene almeno un anello cloud.
4. Durante una trascrizione locale, rimuovere l'anello Ollama dalla catena del processo web.

### Passata 2: valutazione

**Opzione 1, lock solo sull'anello Ollama (raccomandata)**

- Pro: la chat con un provider cloud funziona durante una trascrizione Whisper, che è il caso in
  cui il cloud serve di più. Se il cloud fallisce e si arriva a Ollama mentre Whisper occupa la
  GPU, `chat_turn` solleva `GpuBusyError` come oggi: la catena lo tratta come ultimo esito e la
  risposta resta 409 `GPU_BUSY`, con la stessa interfaccia di oggi.
- Contro: l'utente vede "GPU occupata" anche avendo scelto il cloud, quando il cloud è giù. Il
  messaggio deve dire che il provider cloud ha fallito (lista dei motivi da D2).

**Opzione 2, lock sull'intera catena**

- Contro: una chiamata a Groq attende la fine di una trascrizione di 20 minuti senza motivo, e il
  lettore ottiene 409 per una risorsa che non usa.

**Scartate**

- 3: con Ollama ultimo anello il lock serve comunque nel caso di fallback.
- 4: equivale all'opzione 1 con più stato da tenere sincronizzato.

### Decisione D5

Opzione 1. In più, per la coda:

- con `transcription_engine = "assemblyai"` il supervisor **non** prende `transcription_lease` e
  **non** chiama `unload_ollama_models`: la GPU resta libera per la chat durante l'upload e
  l'attesa;
- la FIFO non cambia: un lavoro con catena cloud occupa comunque il suo turno di coda. Far correre
  in parallelo i lavori senza GPU è un'ottimizzazione possibile, rinviata finché una misura non
  mostra code lunghe.

---

## D6. AssemblyAI come motore di trascrizione (A6)

### Passata 1: approcci generati

Segmentazione:

1. Endpoint delle frasi (`/v2/transcript/{id}/sentences`, UNVERIFIED): un `Segment` per frase.
2. Endpoint dei paragrafi: un `Segment` per paragrafo.
3. Raggruppamento locale delle parole per pausa, riusando `paragraph_gap_s`.
4. Raggruppamento locale per punteggiatura forte più un tetto di parole, simile ai segmenti
   Whisper.

Confidenza:

5. `confidence` copiata in `probability`, soglia unica.
6. `confidence` copiata, soglia di incertezza per motore, tarata sul gold set.
7. Trasformazione in percentile per lezione.

Fallimento:

8. Ripiego automatico su faster-whisper locale.
9. Errore esplicito con l'azione "Riprova in locale".

### Passata 2: valutazione, segmentazione

**Opzione 1, frasi come segmenti (raccomandata)**

- Pro: i segmenti Whisper sono unità di qualche secondo, circa una frase; tutto il codice a valle
  è tarato su quella grana: `chunk_segments` della correzione (200 parole), `cleanup.py` che toglie
  un "Grazie." isolato in un segmento, le pause fra segmenti che `render.group_paragraphs` usa per
  i paragrafi, le finestre della chat. Una frase conserva tutto questo.
- Contro: una chiamata HTTP in più dopo la trascrizione; dipendenza da come AssemblyAI spezza le
  frasi in italiano (V8).

**Opzione 3, raggruppamento per pausa con `paragraph_gap_s`**

- Pro: nessuna chiamata in più, logica nostra e testabile.
- Contro: con una soglia di 2 s produce segmenti della dimensione di un paragrafo. Poi
  `group_paragraphs` cerca pause **fra** segmenti che non ci sono più dentro, e i paragrafi
  diventano di un segmento ciascuno; `cleanup.py` non trova più il "Grazie." isolato.
- Giusta se: l'endpoint delle frasi non esiste o è inaffidabile in italiano. Resta come ripiego
  locale nella forma 4 (punteggiatura forte più tetto di 40 parole).

**Scartata**

- 2, paragrafi come segmenti: stesso difetto della 3, più marcato.

### Passata 2: valutazione, confidenza

**Opzione 6, soglia per motore (raccomandata)**

- Pro: `probability` mantiene il significato di "fiducia 0-1 della parola", quindi `render.py` e
  il report non cambiano. La soglia 0,7 è stata scelta per Whisper; la confidenza di AssemblyAI
  ha un'altra calibrazione (BASIS: unknown). `uncertain_threshold` è già in `JobConfig`: alla
  creazione del job si sceglie il default del motore (`uncertain_threshold_assemblyai`).
- Contro: serve una taratura sul gold set con `wer.py`: soglia tale che la quota di parole
  segnate e la precisione sugli errori reali siano vicine a quelle di Whisper (V8).

**Opzione 5, soglia unica**

- Contro: se AssemblyAI è più "sicuro" di Whisper, il lettore segna quasi nulla e lo studente
  perde il segnale di revisione; se meno, segna tutto. Nessuno dei due casi si vede senza misura.

**Scartata**

- 7, percentile per lezione: segna sempre la stessa quota di parole anche su una registrazione
  pulita, cioè inventa incertezza.

### Passata 2: valutazione, fallimento

**Opzione 9, errore esplicito con "Riprova in locale" (raccomandata)**

- Pro: l'utente che ha scelto AssemblyAI su CPU non si ritrova un'ora di Whisper su processore
  partita da sola; l'audio non viene caricato due volte.
- Contro: un clic in più quando il servizio è giù.

**Scartata**

- 8, ripiego automatico: su un PC senza GPU trasforma un errore di rete in un'ora di CPU non
  richiesta; sui PC con GPU ribalta la scelta dell'utente senza chiedere.

### Decisione D6

`assemblyai_transcriber.py`, confine httpx unico verso AssemblyAI, con la stessa firma di
`transcribe_file` (`audio_path`, `config`, `on_progress`) e lo stesso `Transcript`:

- **Flusso** (UNVERIFIED): upload del file in streaming (`/v2/upload`, corpo letto a blocchi dal
  disco, mai tutto in memoria), creazione della trascrizione con `language_code: "it"` e il
  modello scelto, polling dello stato ogni 5 s, lettura di parole e frasi, poi **cancellazione**
  della trascrizione sul servizio (`DELETE /v2/transcript/{id}`) e dell'upload, se l'API lo
  consente, per non lasciare la lezione sui loro server.
- **Mappatura**: millisecondi in secondi; parola con spazio iniziale come in Whisper (`" " +
  text`); `probability = confidence`; `Transcript.model = "assemblyai:<speech_model>"`.
- **Progresso a fasi**: upload in percentuale sui byte inviati; "in coda" e "in elaborazione"
  come stato indeterminato con il tempo trascorso; download e scrittura. L'interfaccia oggi
  mostra una barra a percentuale: serve uno stato indeterminato con etichetta di fase.
- **Timeout**: connessione 10 s, scrittura per blocco 60 s; scadenza complessiva del polling pari
  a `max(15 min, durata dell'audio)`, poi errore. Gli errori transitori del polling (rete, 5xx)
  si ritentano con attesa crescente fino alla scadenza complessiva, perché la trascrizione
  remota continua comunque.
- **Annullamento**: l'id della trascrizione remota si salva nella cartella del job appena creato;
  un annullamento o un'interruzione lascia un'operazione di cancellazione da fare al riavvio.
- **Niente lease GPU** e niente scaricamento di Ollama (D5).
- **File grandi**: limite di dimensione e durata di AssemblyAI da verificare (V8); il controllo
  avviene prima dell'upload, con errore chiaro, sotto `web_max_upload_mb`.

### Conseguenze D6

- AssemblyAI non sostituisce Whisper nelle misure del progetto finché non passa sul gold set
  (WER e taratura della soglia, V8). Fino ad allora l'interfaccia lo presenta come "alternativa",
  non come raccomandato.
- Le parole di AssemblyAI potrebbero portare la punteggiatura attaccata in modo diverso da
  Whisper: `edits.py` (difflib ≥ 0,6, sostituzioni fino a 3 parole) e il WER vanno rieseguiti su
  una lezione trascritta così.

---

## Ordine di implementazione (fasi indipendenti)

1. `json_repair.py` estratto; correttore e studio portati sul `ChatClient`; catena di un solo
   anello Ollama. Nessun cambio di comportamento, test esistenti verdi.
2. `config_dir()`, `SecretStore`, filtro di redazione, `_child_env` ripulito, API delle chiavi.
3. Protocolli OpenAI-compatible e Anthropic, catalogo di capacità, `LlmChain` con tassonomia,
   breaker e registro; snapshot in `JobConfig` e nei record di generazione; guardia GPU spostata
   sull'anello Ollama.
4. Pagina Impostazioni (motore, ordine, consenso, stato chiavi).
5. AssemblyAI, dopo V8.

Ogni fase lascia il sistema usabile: dopo la 3 la catena è usabile da variabili d'ambiente anche
senza la pagina.

## Domande aperte per l'utente

1. **Ollama sempre ultimo anello, o rimovibile?** Se è rimovibile, i budget di contesto possono
   salire alla finestra minima dei soli anelli cloud (D2), ma un job con tutti i provider in
   quota si ferma. Default proposto: sempre presente.
2. **Consenso per l'audio**: una volta sola nelle Impostazioni, o confermato a ogni lezione inviata
   ad AssemblyAI? Default proposto: una volta, con l'indicazione "AssemblyAI" visibile sul job.
3. **Il motore API vale anche per chat e giudizio**, o solo per i lavori in coda? Default
   proposto: per tutto, perché è il caso d'uso che beneficia di più del cloud durante una
   trascrizione.

## Rischi

| Causa | Rischio | Effetto |
|---|---|---|
| Testo dei documenti del corso inviato a un provider cloud | violazione di licenza del materiale o uso per addestramento sui piani gratuiti (UNVERIFIED per Gemini e Groq) | esposizione dell'utente; mitigato da consenso esplicito e testo per provider nella pagina |
| Chiave in chiaro su disco | lettura da parte di un altro processo dell'utente o di un backup | uso della quota dell'utente; mitigato da 0600, cancellazione dalla pagina, chiavi a quota limitata |
| Modelli di ragionamento con limiti di uscita tarati su qwen | JSON troncato a ogni blocco | ogni blocco saltato con `InvalidResponseError`, correzione vuota senza fallback; mitigato dal moltiplicatore del catalogo e da V6 |
| Catalogo di capacità non aggiornato | 400 su un modello nuovo (per esempio `temperature` rifiutata) | l'anello resta aperto per il job e si passa al successivo; visibile nel log e nel registro |
| Modelli misti nello stesso artefatto | qualità disomogenea fra blocchi | lo studente non sa quale parte fidarsi meno; mitigato dal registro mostrato nel lettore |
| Confidenza AssemblyAI con calibrazione diversa | flag di incertezza sbagliati | revisione mirata inefficace; mitigato da soglia per motore (V8) |
| Trascrizione remota non cancellata dopo un crash | lezione che resta sui server di AssemblyAI | esposizione dei dati; mitigato da id salvato e cancellazione al riavvio |

## Verifiche da fare prima di accettare

- **V1** Endpoint OpenAI-compatible: per OpenAI, Groq e Gemini, forma esatta di
  `response_format` (`json_schema` non strict, `json_object`), campi di uso dei token,
  `finish_reason` per troncamento e filtro di sicurezza. Fonte: documentazione ufficiale via
  context7 o pagina del provider.
- **V2** Anthropic Messages: header (`x-api-key`, `anthropic-version`), `max_tokens` obbligatorio,
  nome e forma del parametro di output strutturato su Opus 5.5 e Sonnet 5, `stop_reason` per
  troncamento, codice 529 per sovraccarico. Confermare il 400 su `temperature` (dato dall'utente).
- **V3** `Retry-After` su 429 per i quattro provider, e limiti dei piani gratuiti di Groq e Gemini.
- **V4** Endpoint a costo nullo per `POST /check` (elenco modelli) per i quattro provider.
- **V5** Prova su una lezione reale: correzione con catena `[groq, ollama]` e chiave Groq non
  valida; atteso report con tutti i blocchi su Ollama, un solo 401 nel log (breaker), chiave
  assente dal log.
- **V6** `num_predict` misurati (T036) su un modello di ragionamento per provider: quota di
  risposte troncate; taratura del moltiplicatore e del livello minimo di ragionamento.
- **V7** Riparazioni JSON su risposte cloud: quante risposte valide cambiano dopo
  `escape_latex_backslashes` su 30 risposte con formule (T067).
- **V8** AssemblyAI: endpoint frasi in italiano, mappatura parole e punteggiatura, limiti di
  dimensione e durata, cancellazione di trascrizione e upload, politica di conservazione dei dati;
  WER sul gold set con `wer.py` e taratura di `uncertain_threshold_assemblyai`.
- **V9** Windows: comportamento di `os.chmod(0o600)`, ACL predefinito di `%APPDATA%`, `os.replace`
  con file aperto. Da aggiungere a `docs/checklist-windows-macos.md` come prova manuale.

## Verifiche eseguite (2026-10-06, context7 su doc ufficiali)

| Voce | Esito | Fonte |
|---|---|---|
| V8 AssemblyAI flusso | `POST /v2/upload` (file locale max 2,2 GB) → `upload_url`; `POST /v2/transcript` con `language_code`, `speech_models: ["universal-3-5-pro", "universal-2"]`; polling `GET /v2/transcript/{id}` fino a `completed`/`error`; header `authorization`; durata max 10 h; endpoint UE `api.eu.assemblyai.com` | https://www.assemblyai.com/docs/llms-full.txt |
| V8 AssemblyAI frasi | `GET /v2/transcript/{id}/sentences` → `sentences[{text, start, end, confidence, words[{text, start, end, confidence}]}]`, tempi in ms | https://www.assemblyai.com/docs/api-reference/transcripts/get-sentences |
| V8 italiano | supportato da `universal-3-5-pro` e `universal-2` | https://www.assemblyai.com/docs/getting-started/models |
| V1 Groq | `https://api.groq.com/openai/v1/chat/completions`, `response_format: {type: "json_schema", json_schema: {name, strict, schema}}`; `strict: true` solo su modelli selezionati e richiede tutti i campi `required` + `additionalProperties: false`; `strict: false` può rispondere 400 "Generated JSON does not match the expected schema" | https://console.groq.com/docs/structured-outputs |
| V3 Groq | 429 con `retry-after` | https://console.groq.com/docs/rate-limits |
| V1 Gemini | endpoint OpenAI-compatible `https://generativelanguage.googleapis.com/v1beta/openai/` con `response_format` json_schema; chiave come Bearer, quindi mai `?key=` | https://ai.google.dev/gemini-api/docs/openai |
| V2/V3 Anthropic | `POST /v1/messages`, header `x-api-key` + `anthropic-version: 2023-06-01`; 429 `rate_limit_error` con `retry-after`, 529 `overloaded_error`, 500 `api_error` | https://platform.claude.com/docs/en/api/errors |
| V2 Anthropic output | structured output in `output_config.format = {type: "json_schema", schema}`; `max_tokens` obbligatorio; `stop_reason` `max_tokens` per troncamento; testo in `content[].text` | https://platform.claude.com/docs/en/api/beta/messages |

Restano aperte: vincoli di schema di OpenAI
`strict` e Gemini, cancellazione dell'upload AssemblyAI, V4-V7, V9.

Le domande aperte sopra sono state chiuse dall'utente il 2026-10-06 (`plan.md` § Riconciliazione,
K5): Ollama ultimo anello attivo di default e rimovibile; consenso audio una volta; motore API
anche per chat e giudizio.

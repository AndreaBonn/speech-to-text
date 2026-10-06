# Piano: provider cloud per LLM e trascrizione (Groq, Gemini, OpenAI, Anthropic, AssemblyAI)

Versione 1.0 - 2026-10-06. Task in `specs/003-cloud-providers/tasks.md`. Decisioni architetturali
in `specs/003-cloud-providers/adr.md` (ADR-003, in scrittura dall'architect in parallelo): la
scelta httpx-thin contro SDK ufficiali (A1), il formato di structured output per provider (A2) e
la tabella codici HTTP → tipo di guasto (A3) stanno lì; il piano le isola in task dedicati e non
le anticipa. Branch `main`, commit atomici (scelta dell'utente del 2026-10-02 per 001, assunta
invariata). Le decisioni D1-D4 sono dell'utente e non si riaprono.

Ogni dettaglio delle API dei provider citato qui (endpoint, campi, codici d'errore, limiti di
upload) è `UNVERIFIED: da training data, verificare prima della produzione`: il task T010 li
verifica sulla documentazione ufficiale via context7 prima di qualunque adapter.

## Riconciliazione con ADR-003 e review di sicurezza (v1.1, 2026-10-06)

Piano e ADR scritti in parallelo divergevano; queste righe prevalgono sul resto del documento.

- **K1 Configurazione**: lettura all'avvio di ogni stage + `served_by` nel risultato (Dis.1 B del
  piano). L'ADR proponeva lo snapshot in `JobConfig`: scartato perché le generazioni non hanno
  `JobConfig` e una regola sola vale per job, generazioni e chat.
- **K2 Nomi dei file**: `credentials.json` (chiavi) e `preferences.json` (non segreti) nella config
  dir; l'ADR li chiamava `secrets.json` e `llm.json`.
- **K3 Segmentazione AssemblyAI**: frasi dall'endpoint `/v2/transcript/{id}/sentences` come
  segmenti (ADR D6, opzione 1), non raggruppamento per pausa: segmenti grandi come paragrafi
  rompono `render.group_paragraphs` e `cleanup.py`. Ripiego locale (punteggiatura forte + tetto 40
  parole) solo se l'endpoint risulta inaffidabile in italiano.
- **K4 AssemblyAI fallito**: errore del job con motivo (Dis.4 A), più l'azione "Riprova in locale"
  dell'ADR se il retry di job esistente la rende economica; altrimenti parcheggiata.
- **K5 Domande ADR chiuse dall'utente** (2026-10-06): Ollama ultimo anello, attivo di default e
  rimovibile; consenso audio una volta nelle Impostazioni con "AssemblyAI" visibile sul job;
  motore API valido anche per chat e giudizio.
- **K6 Budget di contesto**: finestra minima della catena, quindi 8192 finché Ollama è in coda
  (ADR D2); invariati in v1 anche senza Ollama.
- **S1 (alta)** chiavi in env propagate ai figli non fidati: `_child_env` toglie `SBOBINA_*_API_KEY`
  per i figli di estrazione e import (T033 emendato; prima diceva "diff vuoto").
- **S2 (alta)** mutazioni senza `Origin`: gli endpoint `/api/v1/settings/*` rifiutano anche
  `Origin` assente (T034, T035).
- **S3 (media)** traceback non redatti: il filtro redige anche `exc_text`/eccezioni formattate
  (T020).
- **S4 (bassa)** Windows: avviso nella sezione "Chiavi API" che 0600 non protegge il file (T037).
- **Fatti verificati** su doc ufficiali (T010/T050 in parte anticipati): vedi `adr.md` §
  Verifiche eseguite. Restano UNVERIFIED la posizione esatta dello structured output Anthropic, i
  limiti di schema di OpenAI `strict` e Gemini, l'endpoint di cancellazione dell'upload AssemblyAI.

## Obiettivo

Lo studente sceglie nelle Impostazioni se correzione, studio, generazioni, chat e valutazione
delle esercitazioni girano su Ollama locale (default, invariato) o su una catena ordinata di
modelli cloud (Groq, Gemini, OpenAI, Anthropic) con Ollama come ultimo anello, e se la
trascrizione usa Whisper locale o AssemblyAI. Le chiavi si inseriscono dalla UI, restano in un
file 0600 fuori da `data/` e dal repo, e non tornano mai in chiaro al browser, nei log o in
`job.json`. Con il motore locale nulla lascia la macchina, come oggi.

## Ordine delle fasi e perché

F1 confine LLM multi-provider (backend, configurabile da env) → F2 Impostazioni (file chiavi,
preferenze, pagina, avvisi) → F3 AssemblyAI → F4 documentazione e vincolo costitutivo.

- F1 prima perché porta tutto il rischio tecnico (4 API, catena, errori, GPU, tracciabilità) ed è
  usabile da sola: con `SBOBINA_GROQ_API_KEY=... SBOBINA_LLM_ENGINE=api` e la catena in env la
  CLI e la web UI usano già i provider cloud. Il motore locale resta il percorso esistente, non
  un anello della catena: zero regressioni per chi non attiva niente.
- F2 dopo: aggiunge la seconda sorgente di chiavi e preferenze (file in config dir, scritto dalla
  UI) sopra quella env di F1, con precedenza env > file > default. La UI non può essere testata
  senza un backend che usi davvero le impostazioni.
- F3 indipendente da F1/F2 nel codice LLM, ma riusa secret store, preferenze, redazione e pagina
  Impostazioni di F2. Se F3 non arriva, il prodotto ha già i provider LLM.
- F4 per ultima perché descrive ciò che è stato spedito. L'aggiornamento di `CLAUDE.md` riga 3 è
  però un prerequisito del merge di F1 (T027): il vincolo "Ollama, not a cloud API" smetterebbe
  di essere vero nel momento in cui F1 entra.

Nessuna "fase 0": l'indagine è stata fatta (Research dell'orchestratore). T010 verifica premesse
esterne (doc dei provider) come V1-V11 in 002, non esplora il codebase.

## Definition of Done

### C1 - Confine LLM multi-provider e catena di fallback (fase F1)

- [ ] Le riparazioni del testo JSON oggi dentro `ollama_chat.chat_json` (fence markdown, escape
      LaTeX, parentesi non chiuse, virgolette interne) stanno in un modulo puro
      `llm_repair.py` con `repair_json_reply(raw, truncated) -> str`, usato da Ollama e da ogni
      adapter cloud. Test: gli esempi già in `tests/test_ollama_chat.py` passano identici sul
      modulo nuovo; `chat_json` produce lo stesso output di prima su ogni fixture esistente.
- [ ] Tassonomia errori: `ProviderUnavailableError(CorrectorUnavailableError)` con
      `kind: FailureKind` (`auth`, `quota`, `rate_limit`, `timeout`, `network`, `server`,
      `bad_request`, `missing_key`, `model_missing`) e `retry_after_s: float | None`. Sottoclasse della classe
      esistente: i 34 siti che catturano `CorrectorUnavailableError` non cambiano. Mappatura
      HTTP → `FailureKind` in una funzione pura (A3). Esempi: 401 → `auth`; 429 con
      `Retry-After: 30` → `rate_limit`, 30 s; 503 → `server`; `httpx.ReadTimeout` → `timeout`.
- [ ] Adapter cloud (Groq, OpenAI, Gemini, Anthropic) con la stessa firma `ChatClient`
      (`Callable[[ChatRequest], str]`, `chat_pipeline.py:46`): `num_predict` → limite di token in
      uscita (default costante per Anthropic, dove è obbligatorio, UNVERIFIED); nessuna
      `temperature` inviata ad Anthropic (Opus 5.5 / Sonnet 5 rispondono 400); chiave solo in
      header, mai in query string (Gemini accetta `?key=`: vietato, perché httpx logga l'URL a
      INFO); risposta troncata (`finish_reason`/`stop_reason` di lunghezza) loggata a WARNING
      come oggi per Ollama. Test solo con `httpx.MockTransport` o fake, nessuna rete reale.
- [ ] Catena: `FallbackChain` è un `ChatClient` che prova gli anelli in ordine. Passa al
      successivo su `ProviderUnavailableError` (rete, timeout, 401/403, 429, 5xx, 400, chiave
      mancante); **non** passa al successivo su `InvalidResponseError` (motivazione in §
      Disambiguazione, punto 2). Esaurita la catena solleva `ChainExhaustedError`
      (sottoclasse di `CorrectorUnavailableError`) con l'elenco `provider/modello: kind`, senza
      testo di risposta né chiavi.
      - Given catena [groq/llama, gemini/flash, ollama/qwen3.5:9b]; When groq risponde 429 e
        gemini 200 con JSON valido; Then il chiamante riceve il JSON di gemini e `served_by`
        registra `gemini/flash`.
      - Given correzione di 6 chunk; When groq risponde 200 ai chunk 1-3 e 429 dal 4; Then i
        chunk 1-3 restano corretti da groq, 4-6 da gemini, il report elenca entrambi con i
        conteggi (3 e 3) e nessun chunk è rifatto.
- [ ] Politica per anello (`chain_policy.py`, pura, orologio iniettato, thread-safe nel chiamante):
      `auth`, `missing_key` e `model_missing` disattivano l'anello per la vita della catena; `rate_limit`/`quota`
      lo saltano fino a `retry_after_s` (default 60 s se assente); 3 `timeout`/`server`
      consecutivi lo saltano per 120 s; 3 `InvalidResponseError` consecutivi lo segnano
      "risposte non valide" e lo saltano per il resto della catena con WARNING. Esempio: anello
      con 401 al chunk 1 → nei chunk 2-50 non riceve nessuna richiesta (contatore del
      MockTransport = 1).
- [ ] Ollama come ultimo anello (D4): presente di default, rimovibile. In motore API non si
      chiama `ensure_model` in testa al lavoro e non si fa mai `pull`: l'anello Ollama verifica
      alla prima richiesta che il modello sia già presente, altrimenti solleva
      `kind=model_missing` ("modello locale non installato"), disattivato come `auth`.
- [ ] Factory unica `llm_factory.build_chat_client(...)` sostituisce le 6 costruzioni del client
      (`llm_corrector.make_ollama_corrector`, `web/api_chat._chat_client`,
      `study_command._prepare_chat`, `web/study_stage.py`, `web/generation_runner._build_chat`,
      `web/practice_grading.py`). Motore `local` → client identico a oggi (stessa chiamata a
      `chat_json`, stesso `ensure_model`). La suite esistente resta verde senza modifiche ai
      test del percorso locale.
- [ ] GPU: in motore API il lock della chat e della valutazione si applica solo all'anello
      Ollama. Given trascrizione in corso (lease presa); When chat con catena [groq, ollama] e
      groq risponde; Then 200, nessun `GpuBusyError`. Se groq fallisce e si arriva a Ollama →
      l'anello Ollama solleva `GpuBusyError`, trattato come guasto dell'anello, e la risposta è
      quella di oggi per GPU occupata se era l'unico anello rimasto.
- [ ] `practice_grading_mode="auto"`: con motore API e almeno un anello cloud con chiave, il
      giudice è disponibile anche senza CUDA.
- [ ] Tracciabilità: report correzioni, metadati delle generazioni, record di studio e risposte
      di chat registrano `served_by` (`{"groq/llama-...": 48, "ollama/qwen3.5:9b": 2}`) accanto
      al campo `model` esistente; i file vecchi senza il campo si leggono ancora. Ogni risposta
      cloud logga a INFO provider, modello, token in/out, latenza; mai prompt né chiave.
- [ ] Errori verso l'utente: motore locale → codici di oggi (`OLLAMA_UNAVAILABLE`,
      `CHAT_TIMEOUT`); motore API e catena esaurita → 503 `LLM_UNAVAILABLE` con messaggio
      "Nessun modello disponibile: groq (limite raggiunto), gemini (chiave non valida), ollama
      (non raggiungibile)". Gli stage figli mappano `ChainExhaustedError` sull'exit code
      esistente (`stage_runner.py:235`), con messaggio in `job.json` privo di chiavi.
- [ ] Configurazione F1 da env (fonte unica `Settings`, nessun `os.getenv` sparso):
      `SBOBINA_LLM_ENGINE=local|api`, `SBOBINA_LLM_CHAIN` (JSON, lista `provider`+`model`),
      `SBOBINA_LLM_OLLAMA_FALLBACK=true`, `SBOBINA_<PROVIDER>_API_KEY` come `SecretStr`.

### C2 - Chiavi e preferenze (fase F2, D1, D3)

- [ ] `config_dir.py`: cartella di config utente `SBOBINA_CONFIG_DIR`, default
      `$XDG_CONFIG_HOME/sbobina` o `~/.config/sbobina` (Linux); su Windows `%APPDATA%\sbobina`.
      Mai sotto `data_dir`, mai sotto la root del repo: un test lo verifica confrontando i path
      risolti.
- [ ] `secret_store.py`: `credentials.json` scritto con file temporaneo nella stessa cartella
      creato `0o600`, `fsync`, `os.replace`; cartella `0o700`. Lettura di un file con permessi
      più larghi → riportato a 0600 con WARNING (Linux/macOS). `SBOBINA_<PROVIDER>_API_KEY`
      sovrascrive il file. Vista mascherata: `{configured: true, last4: "a1b2", source:
      "file"|"env"}`; `last4` solo se la chiave ha almeno 12 caratteri, altrimenti `null`.
- [ ] `user_preferences.py`: `preferences.json` (non segreto) nella stessa cartella con
      `llm_engine`, `llm_chain` (lista ordinata `provider`+`model`, max 8, coppie uniche),
      `ollama_fallback`, `transcription_engine`, `cloud_ack` (timestamp della conferma
      "il testo lascia la macchina"). Precedenza env > file > default; il campo fissato da env è
      marcato `locked_by_env` e la UI non lo rende modificabile.
- [ ] API (formato `{"data":...}` / `{"error":...}`, `OriginMiddleware` già sulle mutazioni):
      `GET /api/v1/settings` → preferenze + chiavi mascherate + `warnings`;
      `PUT /api/v1/settings/llm` (motore, catena, fallback); `PUT /api/v1/settings/keys/<provider>`
      con `{key}` → 200 con la sola vista mascherata; `DELETE .../keys/<provider>` → 204;
      `POST .../keys/<provider>/test` → chiamata minima al provider (elenco modelli, nessun
      token generato, UNVERIFIED) con esito `ok` / `auth` / `network`. Provider sconosciuto →
      404; chiave vuota, oltre 512 caratteri o con spazi/a capo → 422 senza eco del valore;
      `llm_engine=api` senza `cloud_ack` → 409 `CLOUD_ACK_REQUIRED`.
- [ ] Avviso D3: `warnings` contiene `missing_keys: ["openai"]` quando il motore è API e un
      provider in catena non ha chiave, `empty_chain` se la catena cloud è vuota. Il banner
      "Aggiungi le chiavi nelle Impostazioni" (link a `/impostazioni`) compare nella home (form
      nuovo job), nel dettaglio corso (generazioni, chat) e nello studio; non compare con motore
      locale.
- [ ] Pagina `/impostazioni` (voce nel rail via `pages_nav.py`, `design.md` autoritativo):
      sezioni "Motore testo" (Locale / API), "Ordine dei modelli" (lista con su/giù, aggiungi,
      rimuovi, Ollama in coda con interruttore), "Chiavi API" (per provider: stato mascherato,
      inserisci/sostituisci, rimuovi, prova), "Trascrizione" (Whisper locale / AssemblyAI, da
      F3). Passare a "API" apre una conferma con il testo "Il testo delle lezioni e dei
      documenti verrà inviato ai provider scelti" e registra `cloud_ack`. Campo chiave
      `type="password"`, `autocomplete="off"`, svuotato dopo il salvataggio. 5 stati per sezione.
- [ ] Con motore API la select "modello Ollama" del form job resta (serve all'anello Ollama) ed è
      etichettata "Modello locale di riserva"; una riga mostra la catena attiva.
- [ ] Le chiavi non compaiono mai: in nessuna risposta di `/api/v1/*` (test che fa PUT di una
      chiave sentinella e cerca la stringa in ogni GET dell'app), nei log (filtro di redazione
      installato in `cli.py:214`, `stage_runner.py:262` e nel logger di uvicorn, con test su un
      `logger.info` che contiene la chiave e su un messaggio d'errore che la riporta come fa
      OpenAI su 401), in `job.json` e nei record di chat/generazioni (test con chiave
      sentinella su un job completo in `tmp_path`), negli export del pacchetto corso.

### C3 - AssemblyAI (fase F3)

- [ ] `assemblyai_mapping.py` (puro): risposta AssemblyAI → `Transcript` di `models.py`. Parole
      con `start`/`end` da ms a s, `confidence` → `probability`; segmenti raggruppati per pausa
      ≥ `paragraph_gap_s` o durata ≥ `paragraph_max_s` (stesse soglie di oggi). Given 3 parole
      `{text:"Buongiorno", start:0, end:640, confidence:0.98}`, pausa di 2500 ms, 2 parole;
      Then 2 segmenti, il primo `start=0.0`, `end=0.64` sull'ultima parola.
- [ ] `assemblyai_client.py` (unico boundary httpx verso AssemblyAI): upload, creazione del
      transcript con lingua `it`, polling con intervallo costante e timeout totale, download,
      cancellazione del transcript e dell'audio caricato a fine lavoro (UNVERIFIED se esiste).
      Errori mappati sulla stessa `FailureKind`; 401 → errore "chiave AssemblyAI non valida".
      Cancellazione fallita → WARNING e riga nel report del job, mai silenziosa.
- [ ] `pipeline.transcribe_to_dir` sceglie il motore da preferenze: `whisper` → percorso di oggi;
      `assemblyai` → client sopra, progresso a fasi (caricamento %, in coda, elaborazione,
      download) sullo stesso `on_progress`. Nessun fallback automatico su Whisper: se
      AssemblyAI fallisce il job va in errore con il motivo (decisione in § Disambiguazione 4).
- [ ] Con AssemblyAI lo stage TRANSCRIBING non prende la lease GPU e non scarica i modelli
      Ollama (`transcription_gate.py`, `gpu_release.py`): test con una chat in corso durante la
      trascrizione → nessuna attesa.
- [ ] `job.json` registra il motore effettivo (`transcription_engine: "assemblyai"`) e l'id del
      transcript remoto (serve a ritentare la cancellazione), mai la chiave. La select "modello
      Whisper" del form è nascosta con AssemblyAI. Attivarlo richiede la chiave AssemblyAI e una
      conferma "l'audio della lezione verrà caricato su AssemblyAI" (`cloud_ack_audio`).

### C4 - Vincolo costitutivo e documentazione (fase F4)

- [ ] `CLAUDE.md` riga 3 riscritta: locale di default; provider cloud opt-in con conferma
      esplicita; chiavi fuori da `data/` e dal repo; OCR solo locale. Entra con F1 (T027).
- [ ] Proposta per README, SECURITY e guida utente (`docs/guida-utente.md`, `docs/user-guide.md`)
      come task separato per `doc-writer`, da eseguire solo su richiesta dell'utente (regola: mai
      toccare README/docs senza richiesta).

## Assunzioni

- Runtime e stack invariati: Python ≥ 3.12, FastAPI con un solo processo web, frontend vanilla
  JS senza build, persistenza a file, `httpx` già dipendenza.
- Budget di contesto invariati (`CONTEXT_WINDOW_TOKENS=8192`, 2,29 token/parola, `num_predict`
  di T036): conservativi per il cloud, nessun allargamento in questo piano.
- Motore e catena si leggono **all'avvio di ogni stage** (correzione, studio, generazione) e di
  ogni turno di chat, non si fotografano nel `JobConfig`. La tracciabilità sta nel risultato
  (`served_by`), non nella configurazione. Vedi § Disambiguazione 1.
- I figli (`processes._child_env` eredita `os.environ`) rileggono `Settings()` e i due file della
  config dir: nessuna chiave passata via argomenti o ambiente aggiunto dal supervisor.
- I modelli si scrivono a mano (testo libero) con un suggerimento per provider in una costante;
  nessun catalogo remoto in v1. Nomi di modello suggeriti: UNVERIFIED (T010).
- Nessuna stima dei costi né tetto di spesa in v1: l'utente paga il proprio account. Won't.
- Linux-first come i piani precedenti: su Windows `chmod 0600` non ha effetto, il limite si
  dichiara nella UI e nella proposta di doc, non si implementano ACL.
- La CLI legge le stesse preferenze della web UI; nessun flag CLI nuovo.
- OCR (`ollama_vision.py`) fuori scope (D2): resta locale anche con motore API.
- Limiti dimensionali: `generation_runner.py` è a 300 righe, `stage_runner.py` 283,
  `pages.py` 265, `jobs.js` 602, `modelli.js` 413. La factory deve **accorciare**
  `generation_runner.py`; JS nuovo in moduli nuovi, i file oltre 300 non crescono.
- [BLOCCANTE per T010, T057] premesse esterne: A1-A3 dall'ADR; per la prova reale facoltativa
  di F3 (T057) servono una chiave AssemblyAI dell'utente e il suo consenso a caricare un audio.

## Disambiguazione

Gli approcci architetturali (A1 httpx o SDK, A2 structured output, A3 codici) sono nell'ADR.
Restano quattro punti di prodotto, con la scelta del piano:

1. **Fotografare la configurazione LLM nel job o leggerla a ogni stage.**
   - Opzione A: snapshot in `JobConfig` all'accodamento → ripetibilità, ma un job accodato prima
     di inserire una chiave non la vede e le generazioni (che non hanno `JobConfig`) seguirebbero
     un'altra regola.
   - Opzione B: lettura all'avvio dello stage + `served_by` nel risultato → una regola sola per
     job, generazioni e chat; la storia di cosa è stato usato sta dove serve.
   - Raccomandata: B.
2. **`InvalidResponseError` passa all'anello successivo?**
   - Opzione A: sì, ogni JSON invalido riprova sul prossimo → più risposte valide, ma un errore di
     contenuto finisce in silenzio su Ollama 9B (qualità mescolata), raddoppia la latenza e
     scavalca le politiche già misurate dei chiamanti (salto del paragrafo, rigenerazione).
   - Opzione B: no per la singola richiesta; dopo 3 invalidi consecutivi lo stesso anello viene
     escluso per il resto della catena (C1) → la catena resta una questione di disponibilità,
     un modello che non regge lo schema si scopre e si toglie.
   - Raccomandata: B.
3. **Catena una sola o per uso** (correzione, studio, generazioni, chat).
   - Opzione A: una catena globale (D3 la definisce "una volta nelle Impostazioni").
   - Opzione B: catena per uso → più controllo, 4 liste da tenere coerenti.
   - Raccomandata: A, come D3. Per-uso eventualmente in una versione successiva.
4. **AssemblyAI fallito: ripiego su Whisper?**
   - Opzione A: errore del job con motivo → l'utente sa cosa è successo e ritenta.
   - Opzione B: ripiego automatico su Whisper → su CPU sono ore inattese, con GPU prende la
     lease a sorpresa mentre l'utente usa la chat.
   - Raccomandata: A (D-trascrizione dice "alternativa", non "catena").

## Rischi e mitigazioni

- **R1 Chiave nei log via messaggi d'errore.** Poiché OpenAI riporta la chiave mascherata nel
  corpo del 401 e httpx logga l'URL a INFO, una chiave o un suo frammento può finire in log,
  `job.json` o risposta API, e l'utente lo scoprirebbe solo condividendo un log. → chiave solo in
  header, messaggi d'errore costruiti dall'adapter (mai `response.text` grezzo), filtro di
  redazione su valori noti, test con chiave sentinella su log, `job.json`, API ed export.
  Effetto se sfugge: F2 +1 g.
- **R2 Structured output disomogeneo.** Poiché `strict` di OpenAI richiede schemi chiusi
  (`additionalProperties: false`, tutti i campi required), Gemini accetta un sottoinsieme di
  JSON Schema e Groq lo supporta solo su alcuni modelli (tutto UNVERIFIED), alcuni schemi di
  oggi potrebbero essere rifiutati con 400. → A2 nell'ADR, ripiego "JSON mode + schema nel
  prompt + validazione pydantic esistente", test di contratto degli schemi reali in
  `src/sbobina/prompts/` contro il trasformatore di ogni adapter. Effetto: F1 +1-2 g.
- **R3 Modelli con ragionamento che consumano il budget di uscita.** Gemini 2.5+ e i modelli o-*
  di OpenAI contano i token di ragionamento nel limite di uscita (UNVERIFIED): con `num_predict`
  di T036 la risposta può arrivare troncata e invalida. → budget di thinking minimo dove
  configurabile, WARNING su troncamento, 3 invalidi escludono l'anello (C1). Effetto: F1 +0,5 g.
- **R4 Rate limit dei piani gratuiti.** Poiché una lezione da 85 min sono ~50 chunk e il piano
  free di Groq ha pochi RPM (UNVERIFIED), la catena può rimbalzare spesso su Ollama. → cooldown
  da `Retry-After`, ritorno all'anello alla scadenza, `served_by` nel report rende visibile il
  mix.
- **R5 Vincolo costitutivo.** Il progetto si presenta come "tutto in locale". → opt-in con
  conferma esplicita (`cloud_ack`, `cloud_ack_audio`), default locale invariato, `CLAUDE.md`
  aggiornato con F1, doc pubbliche su richiesta.
- **R6 Calibrazione della confidenza AssemblyAI.** `uncertain_threshold=0.7` è tarato su
  Whisper: con le confidenze AssemblyAI i flag "incerto" possono essere troppi o troppi pochi.
  → misura facoltativa sul gold set (T057), soglia per motore solo se la misura lo giustifica.
- **R7 Concorrenza nella catena della chat.** Il client chat è condiviso in `app.state` e gli
  handler sync girano in threadpool: lo stato della politica va protetto da lock, test con 2
  thread su un anello che risponde 429.
- **R8 Limiti dimensionali.** `generation_runner.py` a 300. → la factory sostituisce
  `_build_chat` (−3 righe nette), check `wc -l` in T024.

## Stima

Ore di sviluppo senior con test; buffer imprevisti 20% esplicito. F1 è la "prima integrazione
della sua specie" (4 API esterne senza precedente nel codebase): promossa di un livello.

| Fase | Min | Max |
| --- | --- | --- |
| F1 confine LLM multi-provider | 7 g | 9,5 g |
| F2 chiavi, preferenze, Impostazioni | 4,5 g | 6 g |
| F3 AssemblyAI | 3,5 g | 5 g |
| F4 vincolo e proposta doc | 0,5 g | 1 g |
| Subtotale | 15,5 g | 21,5 g |
| Buffer 20% | 3 g | 4,5 g |
| **Totale** | **18,5 g** | **26 g** |

Esclusi: tempo dell'utente per chiavi e prove reali (T028, T057), scrittura doc pubbliche.

## Delega

- Codex via `tdd-guide` (logica pura, adapter, catena) e `senior-backend` (API, persistenza,
  wiring): task **[C]**, 2-4 per invocazione, blocchi **[B-n]**.
- `fullstack-developer` in-house: task **[UI]**.
- `security-reviewer` obbligatorio sul diff di F1 e F2 (chiavi, redazione) e F3 (upload audio).
- Non delegabili: verifica doc dei provider (T010, context7, prima degli adapter), prove reali
  con chiavi dell'utente **[M]**, gate di fase **[G]**.

## Criteri di verifica

Per ogni fase: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
`uv run mypy src tests` verdi; `grep -rn "api_key\|Authorization" tests` mostra solo chiavi
sentinella; nessun test apre una connessione reale (fixture che fa fallire `httpx` fuori da
`MockTransport`); click-through registrato di `/impostazioni` e del banner; `a11y-gate` e render
a 375/1280 px dove c'è UI; `/analyze` su `specs/003-cloud-providers/`; esiti di A1-A3 riportati
in `adr.md`.

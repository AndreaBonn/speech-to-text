[English](./SECURITY.md) | **Italiano**

# Politica di sicurezza

## Versioni supportate

Il progetto è in sviluppo attivo e non ha release con tag. Le correzioni di sicurezza vengono applicate all'ultimo commit su `main`.

## Segnalare una vulnerabilità

Segnala le vulnerabilità tramite [GitHub Security Advisories](https://github.com/AndreaBonn/speech-to-text/security/advisories/new). Non aprire una issue pubblica.

Indica:

- una descrizione della vulnerabilità
- i passi per riprodurla
- il comportamento atteso e quello osservato
- l'impatto (cosa potrebbe ottenere un attaccante)

È un progetto personale mantenuto da una sola persona. Puoi aspettarti una risposta entro 7 giorni; correzione e divulgazione vengono concordate con chi segnala.

## Modello di minaccia

Transcriber è uno strumento per un solo utente che gira sul suo computer. L'interfaccia web non ha autenticazione per scelta: è raggiungibile solo dalla stessa macchina. I rischi principali da cui si difende sono un sito malevolo, aperto nello stesso browser, che manda richieste al server locale, e input troppo grandi o malformati, compresi documenti del corso costruiti per esaurire memoria o disco, e testo dentro i documenti o nelle risposte dell'LLM che prova a entrare nella pagina come markup.

## Misure di sicurezza implementate

- **Server solo su loopback**: l'host configurato deve essere `127.0.0.1`, `::1` o `localhost`; qualsiasi altro valore viene rifiutato all'avvio (`src/sbobina/settings.py:80`).
- **Controllo dell'header Host**: `TrustedHostMiddleware` di Starlette accetta solo nomi di loopback, il che blocca il DNS rebinding (`src/sbobina/web/app.py:178`).
- **Controllo dell'Origin sulle richieste che modificano lo stato**: `POST`, `PUT`, `PATCH` e `DELETE` con un header `Origin` diverso da quello del server ricevono un 403 (`src/sbobina/web/middleware.py:27`).
- **Limite di dimensione prima di leggere il corpo**: l'audio oltre `SBOBINA_WEB_MAX_UPLOAD_MB` (1024 MB di default), i documenti del corso oltre `SBOBINA_COURSE_DOC_MAX_MB` (200 MB di default) e i caricamenti senza `Content-Length` vengono rifiutati prima di scrivere qualsiasi cosa su disco (`src/sbobina/web/upload_limit.py:74`, limiti impostati in `src/sbobina/web/app.py:181`).
- **Tipo del documento controllato dal contenuto**: il tipo di un documento del corso si ricava dai primi byte (firma PDF, struttura dell'archivio ZIP per DOCX e PPTX), non dall'estensione (`src/sbobina/document_sniff.py:75`).
- **Limiti sugli archivi Office**: un DOCX o PPTX con più di 10.000 voci o più di 500 MB decompressi viene rifiutato con un 413 prima di aprirlo, il che blocca le zip bomb (`src/sbobina/document_sniff.py:33`).
- **Lettura dei documenti in un processo figlio limitato**: l'estrazione del testo gira in un processo separato con un limite allo spazio di indirizzamento (`RLIMIT_AS`, `SBOBINA_EXTRACTION_MAX_MEMORY_MB`, 2048 MB di default; non disponibile su Windows) e un tempo massimo, superato il quale viene terminato (`src/sbobina/web/extraction_runner.py:26`, `src/sbobina/web/extraction_worker.py:218`).
- **OCR limitato in memoria, tempo e dimensione del rendering**: il figlio dell'OCR ha lo stesso limite di memoria (`src/sbobina/web/ocr_runner.py:131`), ogni pagina viene renderizzata con il lato lungo al massimo di 2500 pixel (`src/sbobina/pdf_text.py:10`) e un'esecuzione ancora in corso dopo `SBOBINA_OCR_PROCESS_TIMEOUT_S` (un'ora di default) viene terminata, così non blocca la coda (`src/sbobina/web/ocr_supervisor.py:126`).
- **Identificativi validati prima di toccare il file system**: l'ID di un lavoro deve essere un UUID versione 4 prima di diventare un percorso, il che esclude il path traversal (`src/sbobina/web/job_store.py:73`); gli ID delle conversazioni devono essere UUID in forma canonica (`src/sbobina/web/api_chat.py:86`); gli ancoraggi delle flashcard e gli ID delle lezioni importate devono essere UUID versione 4 (`src/sbobina/card_models.py:30`, `src/sbobina/web/job_models.py:151`).
- **Le query di ricerca non raggiungono la sintassi FTS5**: i termini dell'utente vengono quotati come stringhe letterali (`src/sbobina/search_text.py:36`) e passati a `MATCH` come parametro bindato (`src/sbobina/web/search_index.py:101`).
- **Output dell'LLM trattato come non fidato**: le citazioni di esercitazioni, riassunti e chat vengono controllate contro i passaggi dati al modello, e una voce con una citazione non trovata viene scartata (`src/sbobina/generation_validation.py:71`, `src/sbobina/source_citations.py:115`). Le pagine dei corsi costruiscono il DOM solo con `createElement` e `textContent`, così nomi dei corsi, nomi dei file, testo dei documenti e risposte dell'LLM non possono iniettare markup (`src/sbobina/web/static/js/dom.js:2`).
- **Content-Security-Policy sulle pagine HTML**: script, stili, font e connessioni sono limitati all'origine del server, gli oggetti sono bloccati e la pagina non può essere incorniciata (`frame-ancestors 'none'`) (`src/sbobina/web/middleware.py:14`, applicata in `src/sbobina/web/middleware.py:49`). KaTeX, che rende le formule scritte dall'LLM o lette con l'OCR, è servito dal repository e gira con `trust: false` e un'espansione delle macro limitata (`src/sbobina/web/static/js/math-text.js:15`).
- **Pacchetti di corso validati prima di scrivere**: un `.sbobina.zip` importato viene rifiutato se il nome di una voce è assoluto, contiene `..`, una barra rovesciata o un byte NUL, o è un link simbolico (`src/sbobina/package_validate.py:89`), oppure se supera i limiti sul numero di voci (5.000), sulla dimensione di una voce, sulla dimensione totale e sul rapporto di compressione (100:1) (`src/sbobina/package_validate.py:19`). L'importazione gira in un processo figlio con lo stesso limite di memoria dell'estrazione (`src/sbobina/web/package_import_runner.py:30`), e il caricamento è limitato da `SBOBINA_WEB_MAX_UPLOAD_MB` (`src/sbobina/web/app.py:187`).
- **Nomi dei modelli validati**: i modelli Whisper devono essere nell'elenco noto; i nomi Ollama devono rispettare un pattern e una lunghezza precisi (`src/sbobina/web/downloads.py:53`).
- **Validazione delle richieste**: gli input delle API passano da modelli Pydantic; gli errori restituiscono 422 con i dettagli per campo (`src/sbobina/web/responses.py:37`).
- **Escape HTML nella coda dei lavori**: le stringhe fornite dal server vengono sottoposte a escape prima di entrare nella pagina (`src/sbobina/web/static/js/jobs.js:426`).
- **Dipendenze bloccate e CI**: `uv.lock` è nel repository e la CI installa con `uv sync --locked`; le GitHub Actions sono fissate allo SHA del commit, girano con permesso `contents` in sola lettura e senza credenziali persistenti (`.github/workflows/ci.yml`).

Non implementato: autenticazione, rate limiting, gli header `X-Frame-Options` e `Strict-Transport-Security` (l'incorniciamento è bloccato dalla CSP; il server parla HTTP semplice su loopback), scansione automatica delle dipendenze in CI.

## Trattamento dei dati

File audio, trascrizioni, documenti del corso, esercitazioni e riassunti generati, tentativi delle esercitazioni, flashcard e conversazioni della chat vengono elaborati sulla macchina locale e salvati nella cartella `data/` (`SBOBINA_DATA_DIR`). Correzione, materiali di studio, esercitazioni, riassunti, valutazione delle risposte e chat mandano testo delle trascrizioni e dei documenti al server Ollama indicato in `SBOBINA_OLLAMA_HOST`, `http://localhost:11434` di default; l'OCR manda allo stesso server le immagini delle pagine scansionate. Se quella variabile punta a un'altra macchina, quel contenuto esce dal tuo computer. Un pacchetto di corso esportato contiene trascrizioni, i documenti del corso scelti, esercitazioni e flashcard: chi lo riceve ottiene quel contenuto.

## Best practice per gli utenti

- Non mettere il server dietro un reverse proxy o un port forwarding: non ha autenticazione.
- Su un computer condiviso con altre persone, ricorda che qualsiasi utente locale può raggiungere `127.0.0.1:8765` mentre il server è acceso.
- Lascia `SBOBINA_OLLAMA_HOST` su `localhost`, salvo che tu controlli la macchina remota.

## Fuori ambito

- Attacchi che richiedono l'accesso all'account dell'utente sullo stesso computer
- Vulnerabilità di dipendenze di terze parti già rese pubbliche (vanno segnalate al progetto originale)
- Denial of service tramite uso legittimo eccessivo, per esempio mettere in coda molte registrazioni lunghe

---

[Torna al README](./README.it.md)

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

Transcriber è uno strumento per un solo utente che gira sul suo computer. L'interfaccia web non ha autenticazione per scelta: è raggiungibile solo dalla stessa macchina. I rischi principali da cui si difende sono un sito malevolo, aperto nello stesso browser, che manda richieste al server locale, e input troppo grandi o malformati.

## Misure di sicurezza implementate

- **Server solo su loopback**: l'host configurato deve essere `127.0.0.1`, `::1` o `localhost`; qualsiasi altro valore viene rifiutato all'avvio (`src/sbobina/settings.py:59`).
- **Controllo dell'header Host**: `TrustedHostMiddleware` di Starlette accetta solo nomi di loopback, il che blocca il DNS rebinding (`src/sbobina/web/app.py:73`).
- **Controllo dell'Origin sulle richieste che modificano lo stato**: `POST`, `PUT`, `PATCH` e `DELETE` con un header `Origin` diverso da quello del server ricevono un 403 (`src/sbobina/web/middleware.py:19`).
- **Limite di dimensione prima di leggere il corpo**: i caricamenti oltre `SBOBINA_WEB_MAX_UPLOAD_MB` (1024 MB di default), o senza `Content-Length`, vengono rifiutati prima di scrivere qualsiasi cosa su disco (`src/sbobina/web/upload_limit.py:17`).
- **Identificativi dei lavori validati prima di toccare il file system**: l'ID di un lavoro deve essere un UUID versione 4 prima di diventare un percorso, il che esclude il path traversal (`src/sbobina/web/job_store.py:62`).
- **Nomi dei modelli validati**: i modelli Whisper devono essere nell'elenco noto; i nomi Ollama devono rispettare un pattern e una lunghezza precisi (`src/sbobina/web/downloads.py:53`).
- **Validazione delle richieste**: gli input delle API passano da modelli Pydantic; gli errori restituiscono 422 con i dettagli per campo (`src/sbobina/web/responses.py:33`).
- **Escape HTML nella coda dei lavori**: le stringhe fornite dal server vengono sottoposte a escape prima di entrare nella pagina (`src/sbobina/web/static/js/jobs.js:426`).
- **Dipendenze bloccate**: `uv.lock` è nel repository.

Non implementato: autenticazione, rate limiting, header di sicurezza (CSP, `X-Frame-Options`), scansione automatica delle dipendenze in CI (non c'è CI).

## Trattamento dei dati

File audio e trascrizioni vengono elaborati sulla macchina locale e salvati nella cartella `data/` (`SBOBINA_DATA_DIR`). La correzione manda il testo della trascrizione al server Ollama indicato in `SBOBINA_OLLAMA_HOST`, `http://localhost:11434` di default. Se quella variabile punta a un'altra macchina, il testo esce dal tuo computer.

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

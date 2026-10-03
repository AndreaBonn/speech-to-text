# Checklist di verifica su Windows e macOS

sbobina è sviluppato e provato su Linux. Su Windows e macOS il codice prevede i casi giusti, ma nessuno l'ha ancora eseguito davvero: questa lista serve al collega che lo prova per la prima volta. Per ogni riga segna **OK** oppure scrivi cosa è successo (una foto dello schermo va benissimo).

Sistema: ______________ (es. Windows 11, macOS 14 su M2) · Scheda NVIDIA: sì / no

## Avvio

| # | Prova | Atteso | Esito |
| --- | --- | --- | --- |
| 1 | Doppio clic su `avvia.bat` (Windows) o `./avvia.sh` dal Terminale (macOS) senza uv installato | Chiede il permesso di installare uv; con **S** lo installa e prosegue | |
| 2 | Primo avvio completo | Si apre il browser su `http://127.0.0.1:8765` | |
| 3 | Nella finestra nera, le prime righe dopo l'avvio | Dicono sistema, dispositivo (GPU o processore), modello e stato di Ollama, con le lettere accentate leggibili | |
| 4 | Secondo avvio | Parte in pochi secondi, senza reinstallare nulla | |
| 5 | Avvio con sbobina già aperto in un'altra finestra | Messaggio "Porta 8765 già occupata", nessun crash | |

## Trascrizione

| # | Prova | Atteso | Esito |
| --- | --- | --- | --- |
| 6 | Trascrivere un audio di 30 secondi (m4a registrato col telefono) | Barra che avanza, poi "Completata" | |
| 7 | Tempo impiegato per i 30 secondi | Annotalo: ______ secondi | |
| 8 | Con scheda NVIDIA: la riga in fondo al menu di sinistra | "CUDA · large-v3"; se dice processore, annota il motivo mostrato | |
| 9 | Annulla durante una trascrizione | Il job diventa "Annullata" entro pochi secondi | |
| 10 | Chiudere la finestra nera durante una trascrizione e riavviare | Il job risulta "Interrotta", gli altri restano | |

## Lettore e altre pagine

| # | Prova | Atteso | Esito |
| --- | --- | --- | --- |
| 11 | Aprire la lezione, cliccare una parola a metà | L'audio parte da quella parola e l'evidenza la segue | |
| 12 | Scaricare .md e .json | I file si aprono e il testo ha le lettere accentate corrette | |
| 13 | Storico: eliminare una lezione completata | La riga sparisce | |
| 14 | Modelli: scaricare `tiny` | La riga diventa "Scaricato" | |

## Ollama (facoltativo)

| # | Prova | Atteso | Esito |
| --- | --- | --- | --- |
| 15 | Ollama non installato, pagina Modelli | Messaggio con il link a ollama.com | |
| 16 | Ollama installato ma chiuso | Messaggio "non è avviato" con l'azione da fare | |
| 17 | Ollama aperto, trascrizione con correzione su 30 secondi | Completata, con il report delle correzioni scaricabile | |

## Corsi e materiale

| # | Prova | Atteso | Esito |
| --- | --- | --- | --- |
| 18 | Trascrivere con **Materia** compilata, poi aprire **Corsi** | Il corso compare con la lezione dentro | |
| 19 | Nella pagina del corso, caricare un PDF con testo e un `.docx` | Entrambi passano a "Pronto"; **Apri** mostra il testo con le lettere accentate corrette | |
| 20 | Cercare una parola presente nella lezione e nel PDF | Escono entrambi; il clic sull'orario apre il Lettore in quel punto | |
| 21 | Se compare "La ricerca non è disponibile su questo computer" | Annota sistema e versione di Python: il modulo FTS5 di SQLite manca | |

## Funzioni di studio con Ollama (facoltativo)

| # | Prova | Atteso | Esito |
| --- | --- | --- | --- |
| 22 | **Esercitazioni e riassunti**: Crocette, 3 domande, **Genera** | Completata; `compito.docx` e `soluzioni.docx` si aprono in Word | |
| 23 | **Domande sul corso**: una domanda sul PDF caricato | Risposta con la fonte cliccabile, oppure "Non trovo la risposta nel materiale di questo corso." | |
| 24 | Dal Lettore, **Materiali di studio** e poi **Genera** su una lezione breve | Compaiono riassunto, concetti chiave e domande con l'orario | |
| 25 | Caricare un PDF scansionato di 1-2 pagine, poi **Estrai il testo con OCR** | "OCR: pagina 1 di 2", poi "Pronto"; annota il tempo per pagina: ______ | |

## Per chi sviluppa (facoltativo)

| # | Prova | Atteso | Esito |
| --- | --- | --- | --- |
| 26 | `uv run pytest` nella cartella del progetto | Tutti i test passano | |

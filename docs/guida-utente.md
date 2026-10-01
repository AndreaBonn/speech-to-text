[English](./user-guide.md) | **Italiano**

# Guida utente di Transcriber

Transcriber (nel codice si chiama sbobina) trasforma la registrazione di una lezione in testo scritto. Lavora tutto sul tuo computer: l'audio non viene mandato su internet.

Questa guida vale per Windows, macOS e Linux. Non serve saper programmare: basta seguire i passi nell'ordine.

## Indice

1. [Cosa serve](#cosa-serve)
2. [Scaricare il programma](#scaricare-il-programma)
3. [Primo avvio](#primo-avvio)
4. [Gli avvii successivi](#gli-avvii-successivi)
5. [Trascrivere una lezione](#trascrivere-una-lezione)
6. [Leggere e ascoltare la trascrizione](#leggere-e-ascoltare-la-trascrizione)
7. [Correggere a mano](#correggere-a-mano)
8. [Scaricare il testo](#scaricare-il-testo)
9. [Storico e modelli](#storico-e-modelli)
10. [Correzione automatica con Ollama (facoltativa)](#correzione-automatica-con-ollama-facoltativa)
11. [Chiudere il programma](#chiudere-il-programma)
12. [Dove finiscono i file](#dove-finiscono-i-file)
13. [Se qualcosa non va](#se-qualcosa-non-va)

## Cosa serve

- Un computer con Windows 10 o 11, macOS oppure Linux.
- Almeno 8 GB di spazio libero sul disco.
- Una connessione a internet **solo per il primo avvio**: il programma scarica Python, le librerie e il modello di trascrizione (fra 2 e 4 GB in tutto). Dopo, la trascrizione funziona anche senza internet.
- Una registrazione della lezione in uno di questi formati: m4a, mp3, wav, ogg, opus, flac, webm, aac. Le registrazioni fatte col telefono vanno bene.

Una scheda video NVIDIA rende tutto molto più veloce, ma non è obbligatoria. Sui Mac la trascrizione usa sempre il processore.

**Quanto ci vuole.** Con una scheda NVIDIA RTX 4060, una lezione di 85 minuti si trascrive in circa 6 minuti e mezzo. Senza scheda NVIDIA, su un portatile con processore Intel Core i7 di 13ª generazione, una lezione di 90 minuti richiede circa mezz'ora. Su un computer meno recente può volerci di più; la pagina mostra il tempo che manca, calcolato sulla tua lezione.

> Il programma è sviluppato e provato su Linux. Su Windows e macOS è previsto tutto, ma non è ancora stato provato su molti computer: se qualcosa non torna, vedi [Se qualcosa non va](#se-qualcosa-non-va).

## Scaricare il programma

Se qualcuno ti ha già passato la cartella del programma, salta al punto 5.

1. Apri il browser e vai su https://github.com/AndreaBonn/speech-to-text
2. Clicca il pulsante verde **Code**.
3. Nel menu che si apre, clicca **Download ZIP**. Parte il download di un file chiamato `speech-to-text-main.zip`.
4. Apri la cartella **Download** del computer e trova il file appena scaricato.
5. Estrai il file ZIP:
   - **Windows**: clic destro sul file, poi **Estrai tutto...**, poi **Estrai**.
   - **macOS**: doppio clic sul file.
   - **Linux**: clic destro sul file, poi **Estrai qui**.
6. Ora hai una cartella chiamata `speech-to-text-main`. Spostala dove preferisci, per esempio in **Documenti**. Non metterla sul Desktop di un computer aziendale sincronizzato con OneDrive o iCloud: i file del programma sono molti e la sincronizzazione lo rallenta.

## Primo avvio

Scegli la sezione del tuo sistema. La prima volta serve qualche minuto, perché il programma prepara tutto quello che gli serve.

### Windows

1. Apri la cartella `speech-to-text-main`.
2. Fai doppio clic sul file `avvia.bat`. Se non vedi `.bat` alla fine dei nomi, ci sono due file `avvia`: scegli quello che Windows descrive come **File batch Windows** (lo vedi passando sopra il mouse).
3. Se compare un riquadro blu "Windows ha protetto il PC", clicca **Ulteriori informazioni** e poi **Esegui comunque**.
4. Si apre una finestra nera. La prima volta compare la domanda: `Lo installo ora da https://astral.sh/uv/install.ps1 [S,N]?`. Premi il tasto **S**. È il programma che installa Python e le librerie.
5. Aspetta. Nella finestra nera scorrono delle righe di testo: è normale. Quando è tutto pronto, il browser si apre da solo sulla pagina `http://127.0.0.1:8765`.

**La finestra nera deve restare aperta** finché usi il programma. Puoi ridurla a icona, ma non chiuderla.

### macOS

1. Apri l'app **Terminale**: premi insieme i tasti **Cmd** e **Spazio**, scrivi `Terminale` e premi **Invio**. Si apre una finestra con del testo.
2. Nel Terminale scrivi `cd` seguito da uno spazio. Non premere ancora Invio.
3. Apri il Finder, trova la cartella `speech-to-text-main` e trascinala dentro la finestra del Terminale. Il percorso della cartella compare scritto dopo `cd `.
4. Premi **Invio**.
5. Scrivi questo comando e premi **Invio**:

   ```
   bash avvia.sh
   ```

6. La prima volta compare la domanda: `Lo installo ora da https://astral.sh/uv/install.sh? [S/n]`. Premi **Invio** (vuol dire sì). È il programma che installa Python e le librerie.
7. Aspetta. Quando è tutto pronto, il browser si apre da solo sulla pagina `http://127.0.0.1:8765`.

**La finestra del Terminale deve restare aperta** finché usi il programma.

### Linux

1. Apri la cartella `speech-to-text-main` nel gestore file.
2. Clic destro in uno spazio vuoto della cartella, poi **Apri nel terminale**. Se la voce non c'è, apri il Terminale dal menu delle applicazioni, scrivi `cd ` (con lo spazio), trascina la cartella nella finestra e premi **Invio**.
3. Scrivi questo comando e premi **Invio**:

   ```
   bash avvia.sh
   ```

4. La prima volta compare la domanda: `Lo installo ora da https://astral.sh/uv/install.sh? [S/n]`. Premi **Invio** (vuol dire sì).
5. Se compare `Manca curl`, scrivi `sudo apt install curl`, premi **Invio**, inserisci la password del computer (mentre la scrivi non si vede nulla, è normale) e poi ripeti il passo 3. Il comando vale per Ubuntu, Debian e Linux Mint.
6. Aspetta. Quando è tutto pronto, il browser si apre da solo sulla pagina `http://127.0.0.1:8765`.

**La finestra del Terminale deve restare aperta** finché usi il programma.

### Cosa ti dice il programma all'avvio

Nelle prime righe della finestra il programma scrive cosa userà, in italiano. Per esempio:

```
Sistema linux: trascrivo con GPU NVIDIA (float16), modello large-v3.
```

oppure, senza scheda NVIDIA, una riga che dice che trascrive con il **processore**. Entrambe vanno bene: con il processore è solo più lento.

## Gli avvii successivi

Dalla seconda volta il programma parte in pochi secondi e non chiede più nulla.

- **Windows**: doppio clic su `avvia.bat`.
- **macOS e Linux**: apri il Terminale nella cartella (come ai passi 1-4 del primo avvio) e scrivi `bash avvia.sh`.

## Trascrivere una lezione

La pagina che si apre si chiama **Nuova trascrizione**. A sinistra c'è il menu con le altre pagine.

1. Trascina il file audio nel riquadro **File audio**, oppure cliccaci sopra e scegli il file dal disco.
2. Facoltativo: nel campo **Materia** scrivi il nome del corso, per esempio `Analisi matematica`. Serve solo alla correzione automatica (vedi più sotto).
3. Clicca **Trascrivi**.
4. A destra, nella sezione **Coda**, compare la lezione con una barra che avanza. Puoi caricare altre lezioni: aspettano il loro turno.
5. Quando la riga dice **Completata**, clicca **Apri**.

Durante la trascrizione puoi chiudere il browser e riaprirlo su `http://127.0.0.1:8765`: il lavoro continua finché la finestra nera (o il Terminale) è aperta. Per fermare una trascrizione, clicca **Annulla** sulla sua riga.

Puoi lasciar stare **Impostazioni avanzate**: i valori predefiniti vanno bene per le lezioni.

## Leggere e ascoltare la trascrizione

La pagina **Lettore** mostra il testo diviso in paragrafi, con l'orario di inizio di ciascuno.

- Le parole **evidenziate in giallo** sono quelle di cui il modello non è sicuro: controllale.
- A lato c'è l'elenco dei **punti da riascoltare**.
- **Clicca una parola** e l'audio riparte da quel punto.
- In fondo alla pagina c'è il lettore audio: pulsante play/pausa, **−10s** e **+10s** per tornare indietro o andare avanti di 10 secondi, la barra della posizione e la velocità (1×, 1.25×, 1.5×).

Se hai usato la correzione automatica, in alto compaiono due pulsanti, **Originale** e **Corretta**, per passare da una versione all'altra.

## Correggere a mano

1. Nel Lettore clicca **Correggi a mano**. In basso si apre il riquadro **Correzione manuale**.
2. Clicca la parola sbagliata, oppure tieni premuto il mouse e trascina su una frase intera. Per allungare la selezione tieni premuto **Maiuscolo** e clicca un'altra parola.
3. Nella casella scrivi il testo giusto.
4. Clicca **Salva** (oppure premi **Invio**). Per rinunciare clicca **Annulla** (oppure premi **Esc**).

Il pulsante **Riascolta** fa ripartire l'audio dalle parole selezionate. Se lasci la casella vuota e salvi, le parole selezionate vengono cancellate.

## Scaricare il testo

Nel Lettore, in alto, ci sono i pulsanti per scaricare:

| Pulsante | Cosa ottieni | Quando usarlo |
| --- | --- | --- |
| **Scarica .docx** | Documento Word, testo pulito senza orari | Per studiare o stampare |
| **Scarica .txt** | Testo semplice, senza orari | Per incollarlo dove vuoi |
| **Scarica .md** | Testo con orari e parole incerte segnate `[?così?]` | Per ricontrollare la trascrizione |
| **Scarica .json** | Dati tecnici completi | Serve solo a chi sviluppa |
| **Scarica corretta (.md)** | Versione corretta da Ollama | Compare solo dopo la correzione automatica |
| **Report correzioni** | Elenco delle parole cambiate da Ollama | Compare solo dopo la correzione automatica |

I file `.docx` e `.txt` scaricano la versione che stai guardando (Originale o Corretta).

## Storico e modelli

- **Storico**: l'elenco di tutte le lezioni caricate, con data e stato. **Apri** porta al Lettore, **Elimina** cancella la lezione e i suoi file. Attenzione: **Elimina** non chiede conferma.
- **Modelli**: i modelli di trascrizione scaricati sul computer. Qui puoi scaricarne uno prima di usarlo, così la prima trascrizione parte subito. Non serve cambiare modello: il programma sceglie da solo quello adatto al tuo computer (`large-v3` con scheda NVIDIA, `large-v3-turbo` senza).
- **Confronto (WER)**: serve a misurare la precisione confrontando la trascrizione con un testo scritto a mano. Puoi ignorarla.

## Correzione automatica con Ollama (facoltativa)

La correzione rilegge il testo e sistema le parole sentite male, senza riscrivere le frasi. Usa un programma separato e gratuito, Ollama, che gira anch'esso sul tuo computer.

Senza scheda NVIDIA la correzione è molto lenta: per una lezione lunga conviene non usarla. Con una RTX 4060, una lezione di 85 minuti viene corretta in circa 18 minuti.

1. Vai su https://ollama.com/download e scarica la versione per il tuo sistema.
2. Installa Ollama:
   - **Windows e macOS**: apri il file scaricato e segui l'installazione. Poi apri l'app Ollama; su Windows resta vicino all'orologio, su macOS nella barra in alto.
   - **Linux**: copia nel Terminale il comando indicato sulla pagina di download e premi **Invio**.
3. In Transcriber apri la pagina **Modelli**. Nella sezione **Ollama**, nel campo **Scarica per nome**, scrivi `qwen3.5:9b` e clicca **Scarica**. Il download pesa circa 6 GB.
4. Nella pagina **Nuova trascrizione** spunta **Correggi con Ollama dopo la trascrizione** prima di cliccare **Trascrivi**.

Se non usi Ollama, in cima alle pagine può comparire un avviso giallo "Ollama non è disponibile": puoi ignorarlo, la trascrizione funziona lo stesso.

## Chiudere il programma

- **Windows**: chiudi la finestra nera.
- **macOS e Linux**: nella finestra del Terminale premi insieme **Ctrl** e **C**, poi chiudi la finestra.

Se chiudi mentre una trascrizione è in corso, al prossimo avvio quella lezione risulta **Interrotta**: caricala di nuovo.

## Dove finiscono i file

Audio e trascrizioni restano nella cartella `data`, dentro la cartella del programma. Per fare spazio puoi eliminare le lezioni dalla pagina **Storico**. Se sposti o cancelli la cartella del programma, sposti o cancelli anche le tue trascrizioni.

## Se qualcosa non va

| Cosa vedi | Cosa fare |
| --- | --- |
| Il browser non si apre da solo | Apri il browser e scrivi nella barra degli indirizzi `http://127.0.0.1:8765` |
| "Porta 8765 già occupata" | Il programma è già aperto in un'altra finestra: usa quella, oppure chiudila e riavvia |
| La pagina non si carica | Controlla che la finestra nera (o il Terminale) sia ancora aperta; se l'hai chiusa, riavvia il programma |
| Avviso "Trascrizione su CPU: sarà più lenta" | Non è un errore: il computer non ha una scheda NVIDIA utilizzabile, la trascrizione funziona ma ci mette di più |
| "Ollama non è disponibile. Installa Ollama..." o "Scarica l'app Ollama..." | Installa Ollama (vedi sopra), oppure togli la spunta alla correzione automatica |
| "Ollama non è disponibile. Avvia l'app Ollama." | Apri l'app Ollama e ricarica la pagina |
| "Ollama non è disponibile. Avvia ollama serve." (Linux) | Apri un nuovo Terminale, scrivi `ollama serve`, premi **Invio** e lascia aperta quella finestra |
| macOS: "Permission denied" o "Operazione non permessa" | Assicurati di aver scritto `bash avvia.sh` e non `./avvia.sh` |
| Nella finestra compare un errore e il programma si ferma | Fai una foto dello schermo e mandala a chi ti ha passato il programma, oppure apri una segnalazione su https://github.com/AndreaBonn/speech-to-text/issues |
| La trascrizione ha molte parole sbagliate | Registra più vicino al docente; controlla le parole in giallo; prova la correzione automatica |

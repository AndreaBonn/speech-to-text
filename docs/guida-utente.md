[English](./user-guide.md) | **Italiano**

# Guida utente di Transcriber

Transcriber (nel codice si chiama sbobina) trasforma la registrazione di una lezione in testo scritto. Lavora tutto sul tuo computer: l'audio non viene mandato su internet.

Le lezioni sono raggruppate per corso. Per ogni corso puoi aggiungere il materiale su cui studi (libro, slide, appunti), cercare insieme nelle lezioni e nel materiale, creare esercitazioni e riassunti, svolgere le esercitazioni con la correzione, fare domande e ripassare con le flashcard. Le funzioni di studio usano un secondo programma gratuito, Ollama, che gira anch'esso sul tuo computer.

Questa guida vale per Windows, macOS e Linux. Non serve saper programmare: basta seguire i passi nell'ordine.

## Indice

1. [Cosa serve](#cosa-serve)
2. [Scaricare il programma](#scaricare-il-programma)
3. [Primo avvio](#primo-avvio)
4. [Gli avvii successivi](#gli-avvii-successivi)
5. [Aggiornare il programma](#aggiornare-il-programma)
6. [Trascrivere una lezione](#trascrivere-una-lezione)
7. [Leggere e ascoltare la trascrizione](#leggere-e-ascoltare-la-trascrizione)
8. [Correggere a mano](#correggere-a-mano)
9. [Scaricare il testo](#scaricare-il-testo)
10. [Storico, modelli e altre pagine](#storico-modelli-e-altre-pagine)
11. [Installare Ollama (facoltativo)](#installare-ollama-facoltativo)
12. [Correzione automatica](#correzione-automatica)
13. [I corsi](#i-corsi)
14. [Cercare nelle lezioni e nel materiale](#cercare-nelle-lezioni-e-nel-materiale)
15. [Aggiungere il materiale del corso](#aggiungere-il-materiale-del-corso)
16. [PDF scansionati: leggerli con l'OCR](#pdf-scansionati-leggerli-con-locr)
17. [Le formule matematiche](#le-formule-matematiche)
18. [Esercitazioni e riassunti](#esercitazioni-e-riassunti)
19. [Svolgere un'esercitazione](#svolgere-unesercitazione)
20. [Frasi da esame](#frasi-da-esame)
21. [Fare domande sul corso](#fare-domande-sul-corso)
22. [Materiali di studio di una lezione](#materiali-di-studio-di-una-lezione)
23. [Ripasso con le flashcard](#ripasso-con-le-flashcard)
24. [Esportare e importare un corso](#esportare-e-importare-un-corso)
25. [Chiudere il programma](#chiudere-il-programma)
26. [Dove finiscono i file](#dove-finiscono-i-file)
27. [Se qualcosa non va](#se-qualcosa-non-va)

## Cosa serve

- Un computer con Windows 10 o 11, macOS oppure Linux.
- Almeno 8 GB di spazio libero sul disco, più circa 6 GB se vuoi le funzioni di studio con Ollama.
- Una connessione a internet **solo per il primo avvio**: il programma scarica Python, le librerie e il modello di trascrizione (fra 2 e 4 GB in tutto). Dopo, la trascrizione funziona anche senza internet.
- Una registrazione della lezione in uno di questi formati: m4a, mp3, wav, ogg, opus, flac, webm, aac. Le registrazioni fatte col telefono vanno bene.
- Facoltativo: il materiale del corso in file PDF, Word (`.docx`), PowerPoint (`.pptx`), testo semplice (`.txt`) o Markdown (`.md`).

Una scheda video NVIDIA rende tutto molto più veloce, ma non è obbligatoria. Sui Mac la trascrizione usa sempre il processore.

**Quanto ci vuole.** Con una scheda NVIDIA RTX 4060, una lezione di 85 minuti si trascrive in circa 6 minuti e mezzo. Senza scheda NVIDIA, su un portatile con processore Intel Core i7 di 13ª generazione, una lezione di 90 minuti richiede circa mezz'ora. Su un computer meno recente può volerci di più; la pagina mostra il tempo che manca, calcolato sulla tua lezione.

> Il programma è sviluppato e provato su Linux. Su Windows e macOS è previsto tutto, ma non è ancora stato provato su molti computer: se qualcosa non torna, vedi [Se qualcosa non va](#se-qualcosa-non-va).

## Scaricare il programma

Se qualcuno ti ha già passato la cartella del programma, salta a [Primo avvio](#primo-avvio).

Ci sono due modi per scaricarlo. Con **Git** (consigliato) scrivi due comandi una volta sola, e dopo aggiornare il programma è un comando solo. Con il **file ZIP** non installi niente, ma per ogni aggiornamento devi riscaricare tutto a mano.

### Non hai un account GitHub?

Non ti serve. Il programma è pubblico: per scaricarlo con Git o come ZIP non devi registrarti né accedere a GitHub. L'account serve solo per aprire una segnalazione (vedi [Se qualcosa non va](#se-qualcosa-non-va)).

Ti serve invece **Git**, un programma gratuito che scarica il codice e lo tiene aggiornato. Installalo seguendo la sezione del tuo sistema.

#### Installare Git su Windows

1. Apri il browser e vai su https://git-scm.com/downloads/win
2. Clicca **Click here to download**. Parte il download di un file che si chiama `Git-` seguito dal numero di versione, per esempio `Git-2.51.0-64-bit.exe`.
3. Apri il file scaricato dalla cartella **Download**. Se Windows chiede "Consentire a questa app di apportare modifiche?", clicca **Sì**.
4. L'installazione fa molte domande: lascia le scelte già proposte e clicca **Next** a ogni schermata, poi **Install**, poi **Finish**.

#### Installare Git su macOS

1. Apri l'app **Terminale**: premi insieme i tasti **Cmd** e **Spazio**, scrivi `Terminale` e premi **Invio**.
2. Scrivi questo comando e premi **Invio**:

   ```
   git --version
   ```

3. Se compare una riga come `git version 2.39.5`, Git c'è già: passa a [Clonare il programma](#clonare-il-programma).
4. Se invece si apre una finestra che propone di installare gli **strumenti da riga di comando per sviluppatori**, clicca **Installa**, poi **Accetta**. Il download dura qualche minuto.
5. A installazione finita, ripeti il passo 2: deve comparire `git version` seguito da un numero.

#### Installare Git su Linux

1. Apri il Terminale dal menu delle applicazioni.
2. Scrivi questo comando e premi **Invio** (vale per Ubuntu, Debian e Linux Mint):

   ```
   sudo apt install git
   ```

3. Inserisci la password del computer e premi **Invio**. Mentre la scrivi non si vede nulla: è normale.
4. Se ti chiede `Continuare? [S/n]`, premi **Invio**.

### Clonare il programma

"Clonare" vuol dire scaricare la cartella del programma con Git, in modo che si possa aggiornare.

1. Apri un terminale nella cartella **Documenti**:
   - **Windows**: apri Esplora file e vai in **Documenti**. Clicca sulla barra degli indirizzi in alto (dove c'è scritto il percorso), cancella il testo, scrivi `cmd` e premi **Invio**. Si apre una finestra nera già posizionata in **Documenti**.
   - **macOS**: apri il Terminale (Cmd + Spazio, `Terminale`, Invio), scrivi `cd Documents` e premi **Invio**.
   - **Linux**: apri il Terminale, scrivi `cd ~/Documenti` e premi **Invio**. Se compare "File o directory non esistente", scrivi `cd ~/Documents` e premi **Invio**.
2. Scrivi questo comando e premi **Invio**:

   ```
   git clone https://github.com/AndreaBonn/speech-to-text.git
   ```

3. Compaiono alcune righe che finiscono con `done.` o `fatto.`. Ora in **Documenti** c'è una cartella chiamata `speech-to-text`: è la cartella del programma.
4. Se compare `git: command not found` o `"git" non è riconosciuto come comando`, Git non è installato: torna alla sezione del tuo sistema. Su Windows, se lo hai appena installato, chiudi la finestra nera e riaprila come al passo 1.

### In alternativa: il file ZIP

1. Apri il browser e vai su https://github.com/AndreaBonn/speech-to-text
2. Clicca il pulsante verde **Code**.
3. Nel menu che si apre, clicca **Download ZIP**. Parte il download di un file chiamato `speech-to-text-main.zip`.
4. Apri la cartella **Download** del computer e trova il file appena scaricato.
5. Estrai il file ZIP:
   - **Windows**: clic destro sul file, poi **Estrai tutto...**, poi **Estrai**.
   - **macOS**: doppio clic sul file.
   - **Linux**: clic destro sul file, poi **Estrai qui**.
6. Ora hai una cartella chiamata `speech-to-text-main`: è la cartella del programma. Spostala dove preferisci, per esempio in **Documenti**.

Qualunque modo tu scelga, non mettere la cartella sul Desktop di un computer aziendale sincronizzato con OneDrive o iCloud: i file del programma sono molti e la sincronizzazione lo rallenta.

## Primo avvio

Nei passi che seguono, "la cartella del programma" è `speech-to-text` se l'hai clonata con Git, `speech-to-text-main` se hai usato il file ZIP. La prima volta serve qualche minuto, perché il programma prepara tutto quello che gli serve.

### Windows

1. Apri la cartella del programma.
2. Fai doppio clic sul file `avvia.bat`. Se non vedi `.bat` alla fine dei nomi, ci sono due file `avvia`: scegli quello che Windows descrive come **File batch Windows** (lo vedi passando sopra il mouse).
3. Se compare un riquadro blu "Windows ha protetto il PC", clicca **Ulteriori informazioni** e poi **Esegui comunque**.
4. Si apre una finestra nera. La prima volta compare la domanda: `Lo installo ora da https://astral.sh/uv/install.ps1 [S,N]?`. Premi il tasto **S**. È il programma che installa Python e le librerie.
5. Aspetta. Nella finestra nera scorrono delle righe di testo: è normale. Quando è tutto pronto, il browser si apre da solo sulla pagina `http://127.0.0.1:8765`.

**La finestra nera deve restare aperta** finché usi il programma. Puoi ridurla a icona, ma non chiuderla.

### macOS

1. Apri l'app **Terminale**: premi insieme i tasti **Cmd** e **Spazio**, scrivi `Terminale` e premi **Invio**. Si apre una finestra con del testo.
2. Nel Terminale scrivi `cd` seguito da uno spazio. Non premere ancora Invio.
3. Apri il Finder, trova la cartella del programma e trascinala dentro la finestra del Terminale. Il percorso della cartella compare scritto dopo `cd `.
4. Premi **Invio**.
5. Scrivi questo comando e premi **Invio**:

   ```
   bash avvia.sh
   ```

6. La prima volta compare la domanda: `Lo installo ora da https://astral.sh/uv/install.sh? [S/n]`. Premi **Invio** (vuol dire sì). È il programma che installa Python e le librerie.
7. Aspetta. Quando è tutto pronto, il browser si apre da solo sulla pagina `http://127.0.0.1:8765`.

**La finestra del Terminale deve restare aperta** finché usi il programma.

### Linux

1. Apri la cartella del programma nel gestore file.
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
- **macOS e Linux**: apri il Terminale nella cartella del programma (come ai passi 1-4 del primo avvio) e scrivi `bash avvia.sh`.

## Aggiornare il programma

Le lezioni, i corsi e tutto quello che hai creato stanno nella cartella `data`, che l'aggiornamento non tocca.

**Se hai clonato con Git:**

1. Chiudi il programma (vedi [Chiudere il programma](#chiudere-il-programma)).
2. Apri un terminale nella cartella del programma, come ai passi 1-4 del primo avvio. Su Windows: apri la cartella in Esplora file, clicca la barra degli indirizzi, scrivi `cmd` e premi **Invio**.
3. Scrivi questo comando e premi **Invio**:

   ```
   git pull
   ```

4. Se compare `Already up to date.` o `Già aggiornato.`, avevi già l'ultima versione. Altrimenti compare l'elenco dei file cambiati.
5. Avvia il programma come al solito. Se l'aggiornamento ha portato librerie nuove, il primo avvio dopo l'aggiornamento ci mette un po' di più.

**Se hai usato il file ZIP:**

1. Chiudi il programma.
2. Scarica di nuovo lo ZIP ed estrailo, come in [In alternativa: il file ZIP](#in-alternativa-il-file-zip).
3. Copia la cartella `data` dalla vecchia cartella del programma dentro la nuova.
4. Avvia il programma dalla nuova cartella. Quando hai controllato che lezioni e corsi ci sono, puoi cancellare la vecchia cartella.

## Trascrivere una lezione

La pagina che si apre si chiama **Nuova trascrizione**. A sinistra c'è il menu con le altre pagine: **Nuova trascrizione**, **Corsi**, **Ripasso**, **Lettore**, **Storico**, **Modelli** e **Confronto (WER)**.

1. Trascina il file audio nel riquadro **File audio**, oppure cliccaci sopra e scegli il file dal disco.
2. Nel campo **Materia** scrivi il nome del corso, per esempio `Analisi matematica`. La lezione finisce in quel corso nella pagina **Corsi**, e la correzione automatica usa il nome per riconoscere i termini del corso. Per le lezioni dello stesso corso scrivi sempre lo stesso nome. Puoi anche lasciarlo vuoto e assegnare il corso più tardi dal Lettore.
3. Clicca **Trascrivi**.
4. A destra, nella sezione **Coda**, compare la lezione con una barra che avanza. Puoi caricare altre lezioni: aspettano il loro turno.
5. Quando la riga dice **Completata**, clicca **Apri**.

Durante la trascrizione puoi chiudere il browser e riaprirlo su `http://127.0.0.1:8765`: il lavoro continua finché la finestra nera (o il Terminale) è aperta. Per fermare una trascrizione, clicca **Annulla** sulla sua riga.

Puoi lasciar stare **Impostazioni avanzate**: i valori predefiniti vanno bene per le lezioni.

## Leggere e ascoltare la trascrizione

La pagina **Lettore** mostra il testo diviso in paragrafi, con l'orario di inizio di ciascuno. La voce **Lettore** del menu apre l'ultima lezione completata; resta grigia finché non ne hai trascritta almeno una.

- Le parole **evidenziate in giallo** sono quelle di cui il modello non è sicuro: controllale.
- A lato c'è l'elenco dei **punti da riascoltare**.
- **Clicca una parola** e l'audio riparte da quel punto. Mentre l'audio va avanti, la parola che senti è evidenziata.
- In fondo alla pagina c'è il lettore audio: pulsante play/pausa, **−10s** e **+10s** per tornare indietro o andare avanti di 10 secondi, la barra della posizione e la velocità (1×, 1.25×, 1.5×).

Se hai usato la correzione automatica, in alto compaiono due pulsanti, **Originale** e **Corretta**, per passare da una versione all'altra.

**Cambiare il corso di una lezione.** In cima al Lettore c'è il campo **Corso**. Scrivi il nome del corso (mentre scrivi, il programma suggerisce i corsi che esistono già) e clicca **Salva corso**. La lezione passa a quel corso nella pagina **Corsi**.

**Creare una flashcard.** Seleziona col mouse una frase del testo: compare il pulsante **Crea carta**. Cliccalo, controlla **Fronte** (la domanda) e **Retro** (la risposta) e conferma. La carta va nel **Ripasso** del corso della lezione: vedi [Ripasso con le flashcard](#ripasso-con-le-flashcard). Serve che la lezione abbia un corso.

Il pulsante **Materiali di studio** apre la pagina di studio di questa lezione: vedi [Materiali di studio di una lezione](#materiali-di-studio-di-una-lezione).

Le lezioni arrivate da un corso importato non hanno l'audio: cliccando una parola o un orario il testo si sposta in quel punto, ma non si sente niente.

## Correggere a mano

1. Nel Lettore clicca **Correggi a mano**. In basso si apre il riquadro **Correzione manuale**.
2. Clicca la parola sbagliata, oppure tieni premuto il mouse e trascina su una frase intera. Per allungare la selezione tieni premuto **Maiuscolo** e clicca un'altra parola.
3. Nella casella scrivi il testo giusto.
4. Clicca **Salva** (oppure premi **Invio**). Per rinunciare clicca **Annulla** (oppure premi **Esc**).

Il pulsante **Riascolta** fa ripartire l'audio dalle parole selezionate. Se lasci la casella vuota e salvi, le parole selezionate vengono cancellate.

Se la stessa lezione è aperta in un'altra scheda del browser e lì l'hai già modificata, il salvataggio viene rifiutato invece di sovrascrivere: ricarica la pagina e rifai la correzione.

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

## Storico, modelli e altre pagine

- **Storico**: l'elenco di tutte le lezioni caricate, con data e stato. **Apri** porta al Lettore, **Elimina** cancella la lezione e i suoi file. Attenzione: **Elimina** non chiede conferma.
- **Modelli**: i modelli di trascrizione scaricati sul computer. Qui puoi scaricarne uno prima di usarlo, così la prima trascrizione parte subito. Non serve cambiare modello: il programma sceglie da solo quello adatto al tuo computer (`large-v3` con scheda NVIDIA, `large-v3-turbo` senza) e lo segna **In uso ora**. La sezione **Ollama** della stessa pagina scarica i modelli per la correzione e per le funzioni di studio.
- **Confronto (WER)**: serve a misurare la precisione confrontando la trascrizione con un testo scritto a mano. Puoi ignorarla.
- **Tema**: il pulsante in fondo al menu di sinistra cambia l'aspetto delle pagine fra **Auto** (segue il computer), **Chiaro** e **Scuro**.

## Installare Ollama (facoltativo)

Ollama è un programma separato e gratuito che fa girare un modello linguistico sul tuo computer. Transcriber lo usa per la correzione automatica, i materiali di studio, le esercitazioni, i riassunti, la correzione delle risposte, le domande sul corso e la lettura dei PDF scansionati. Senza Ollama trascrizione, Lettore, ricerca, download, frasi da esame e Ripasso funzionano lo stesso.

Senza scheda NVIDIA queste funzioni sono molto lente: per le lezioni lunghe conviene non usarle.

1. Vai su https://ollama.com/download e scarica la versione per il tuo sistema.
2. Installa Ollama:
   - **Windows e macOS**: apri il file scaricato e segui l'installazione. Poi apri l'app Ollama; su Windows resta vicino all'orologio, su macOS nella barra in alto.
   - **Linux**: copia nel Terminale il comando indicato sulla pagina di download e premi **Invio**.
3. In Transcriber apri la pagina **Modelli**. Nella sezione **Ollama**, nel campo **Scarica per nome**, scrivi `qwen3.5:9b` e clicca **Scarica**. Il download pesa circa 6 GB. Questo modello serve a tutte le funzioni di studio.
4. Solo se hai PDF scansionati: ripeti il passo 3 con `qwen2.5vl:7b`, il modello che legge le immagini delle pagine. Se salti questo passo, il programma lo scarica la prima volta che usi l'OCR, e quella prima volta ci mette di più.

Se Ollama non è avviato, in cima alle pagine può comparire un avviso giallo "Ollama non è disponibile": se ti serve solo trascrivere, puoi ignorarlo.

## Correzione automatica

La correzione rilegge il testo e sistema le parole sentite male, senza riscrivere le frasi. Serve Ollama (vedi la sezione precedente). Con una RTX 4060, una lezione di 85 minuti viene corretta in circa 18 minuti.

1. Nella pagina **Nuova trascrizione** compila **Materia**: la correzione la usa per riconoscere i termini del corso.
2. Spunta **Correggi con Ollama dopo la trascrizione** prima di cliccare **Trascrivi**.
3. A lavoro finito, nel Lettore compaiono i pulsanti **Originale** e **Corretta**, e il download **Report correzioni** elenca ogni parola cambiata.

La correzione si chiede al caricamento: nell'interfaccia non c'è un pulsante per correggere una lezione già trascritta.

## I corsi

La pagina **Corsi** elenca i tuoi corsi, con il numero di lezioni e la data dell'ultima. Le lezioni senza corso stanno sotto **Senza corso**.

1. Clicca il nome di un corso. Si apre la pagina del corso.
2. In alto c'è la tabella delle sue lezioni: clicca una lezione per aprirla nel Lettore, oppure **Materiali di studio** per la sua pagina di studio.
3. Sotto ci sono le sezioni **Frasi da esame**, **Materiali**, **Esercitazioni e riassunti**, **Tentativi**, **Errori da ripassare** e **Domande sul corso**. Le prossime sezioni della guida le spiegano.
4. Il pulsante **Esporta il corso** crea un pacchetto da portare su un altro computer: vedi [Esportare e importare un corso](#esportare-e-importare-un-corso).
5. Per tornare all'elenco clicca **← Tutti i corsi**.

Per spostare una lezione in un altro corso usa il campo **Corso** nel Lettore (vedi [Leggere e ascoltare la trascrizione](#leggere-e-ascoltare-la-trascrizione)).

## Cercare nelle lezioni e nel materiale

In cima alla pagina **Corsi** c'è la ricerca **Cerca nelle lezioni e nei materiali**.

1. In **Parole o frase** scrivi quello che cerchi, per esempio `causa del contratto`. Per trovare una frase esatta mettila fra virgolette: `"causa del contratto"`. Trova anche le forme simili: `contratti` trova anche `contratto`.
2. Facoltativo: in **Corso** scegli un corso. **Tutti i corsi** cerca ovunque.
3. Clicca **Cerca**.
4. Ogni risultato mostra la lezione o il documento e il passaggio che corrisponde.
   - Per una lezione, clicca l'orario accanto al passaggio (per esempio **12:30**): il Lettore si apre in quel punto.
   - Per un documento, clicca il nome: il documento si apre sulla pagina trovata, con le parole cercate evidenziate.

La prima ricerca può metterci un po' di più, perché il programma indicizza tutte le lezioni.

## Aggiungere il materiale del corso

Nella pagina di un corso, la sezione **Materiali** raccoglie i file su cui studi. Formati accettati: PDF, Word (`.docx`), PowerPoint (`.pptx`), testo semplice (`.txt`) e Markdown (`.md`), fino a 200 MB per file.

1. Apri il corso dalla pagina **Corsi**.
2. Trascina il file nel riquadro **Trascina un file qui o scegli**, oppure cliccaci sopra e scegli il file. Un file alla volta.
3. Una barra mostra il caricamento. Poi sulla riga compare un'etichetta:
   - **Caricamento** e poi **Estrazione in corso**: aspetta, la pagina si aggiorna da sola.
   - **Pronto**: il testo è stato letto. Da qui in poi il documento entra nella ricerca, nelle esercitazioni, nei riassunti e nelle domande.
   - **Pronto (senza testo)**: il file non ha testo leggibile, di solito è un PDF scansionato. Vedi la sezione successiva.
   - **Errore**: il file non si è potuto leggere. Il motivo è scritto sotto il nome.
4. Su ogni riga: **Apri** mostra il testo pagina per pagina, con **Precedente**, **Successiva** e **Scarica originale**; **Scarica** scarica il file; **Elimina** lo cancella dopo aver chiesto conferma.

Se la pagina del corso dice "Per caricare materiali assegna prima un corso alla lezione", sei in **Senza corso**: il materiale ha bisogno di un corso vero. Assegna il corso dal Lettore, poi torna qui.

Lo stesso file non si può caricare due volte nello stesso corso.

## PDF scansionati: leggerli con l'OCR

Un PDF scansionato contiene foto delle pagine, non testo. Il programma può leggerle con l'OCR (riconoscimento ottico dei caratteri) usando il modello `qwen2.5vl:7b` di Ollama. È lento: sul computer del progetto ogni pagina richiede da 4 a 5 minuti. Una singola esecuzione si ferma dopo un'ora, cioè circa 12 pagine a quella velocità, e il testo viene salvato solo quando tutte le pagine sono state lette. Per un documento scansionato più lungo, dividi il PDF in file da circa 10 pagine e caricali uno alla volta.

1. Nella sezione **Materiali** trova la riga segnata **Pronto (senza testo)**.
2. Clicca **Estrai il testo con OCR**.
3. Sulla riga compare **OCR in coda** e poi **OCR: pagina 3 di 10**. Puoi lasciare la pagina e tornare più tardi.
4. Per fermarlo clicca **Annulla**. Non viene salvato niente: l'esecuzione successiva riparte dalla prima pagina.
5. Alla fine la riga dice **Pronto** e il documento si usa come gli altri.

Il testo letto con l'OCR può contenere errori, a volte tali da cambiare il senso. Dovunque venga citato è segnato **testo da OCR**: confrontalo con la pagina originale prima di studiarci sopra. L'OCR trascrive anche le formule delle slide, che poi compaiono formattate (vedi la sezione successiva).

## Le formule matematiche

Le formule scritte dal modello (nelle esercitazioni, nei riassunti, nelle risposte della chat, nei materiali di studio e nelle carte del Ripasso) e quelle lette con l'OCR compaiono formattate come in un libro, con frazioni, apici e simboli. Non devi fare niente: succede da solo.

Se una formula è scritta male e non si riesce a formattarla, compare il suo testo grezzo, per esempio `\frac{a}{b`. Il resto della pagina si legge lo stesso.

## Esercitazioni e riassunti

Nella sezione **Esercitazioni e riassunti** della pagina di un corso puoi creare esercitazioni e riassunti dalle lezioni e dal materiale di quel corso. Serve Ollama con `qwen3.5:9b`.

1. In **Formato** scegli:
   - **Crocette**: domande a risposta multipla
   - **Domande aperte**
   - **Orale**: domande per un esame orale
   - **Riassunto**
2. Per le esercitazioni, in **Numero di domande** scrivi un numero da 1 a 10.
3. Facoltativo: in **Argomento** scrivi un argomento, per esempio `leggi di Newton`. Se lo lasci vuoto, il programma prende passaggi da tutto il corso.
4. Facoltativo: apri **Fonti** e scegli quali documenti e lezioni usare. Per sceglierne più di uno tieni premuto **Ctrl** (sul Mac **Cmd**) e clicca. Senza selezione usa tutto il corso.
5. Clicca **Genera**.
6. La nuova riga nell'elenco mostra **In coda**, **In corso** e poi **Completata**. Con una RTX 4060 ci vogliono fra mezzo minuto e un minuto e mezzo. Mentre è in corso, **Annulla** la ferma.
7. Clicca **Mostra** per leggere il risultato, **Nascondi** per chiuderlo. Per svolgere un'esercitazione clicca **Svolgi**: vedi [Svolgere un'esercitazione](#svolgere-unesercitazione).

**Leggere il risultato.** Ogni domanda, risposta e frase del riassunto mostra la sua fonte: il nome del documento con la pagina (per esempio `manuale.pdf p.31`) oppure la lezione con l'orario, seguiti dalla frase citata. Clicca la fonte per aprire la pagina del documento o il Lettore in quel punto. Nelle crocette l'opzione giusta è segnata **Corretta**. Le domande aperte e orali hanno una **Soluzione** divisa in punti: sono i punti che una buona risposta deve toccare.

Le domande con una citazione che non si trova nel materiale vengono scartate. Il risultato dice quante ne sono rimaste, per esempio **8 su 10 richieste**, e perché le altre sono state scartate. Se un documento o una lezione è stato modificato dopo la generazione, le sue fonti sono segnate **fonte modificata dopo la generazione**.

Ogni esercitazione e ogni riassunto hanno anche una pagina propria, con il risultato e i download: ci arrivi, per esempio, dalla fonte di una carta del Ripasso creata da quella esercitazione.

**Scaricare.** Un'esercitazione completata ha quattro pulsanti: `compito.md` e `compito.docx` (solo le domande, per fare la prova), `soluzioni.md` e `soluzioni.docx` (domande con risposte e fonti). Un riassunto ha `riassunto.md` e `riassunto.docx`. I file `.docx` si aprono con Word.

**Elimina** cancella un risultato dopo aver chiesto conferma.

Messaggi che puoi vedere:

| Messaggio | Cosa vuol dire |
| --- | --- |
| "Nel materiale del corso non trovo questo argomento." | L'argomento non compare nel corso: prova con un'altra parola, oppure lascia vuoto **Argomento** |
| "Nessun materiale disponibile per generare: carica documenti o lezioni in questo corso." | Il corso non ha ancora lezioni o documenti con del testo |
| "Il modello ha risposto in un formato non valido: riprova." | La risposta del modello non si è potuta leggere: clicca di nuovo **Genera** |

## Svolgere un'esercitazione

1. Nella sezione **Esercitazioni e riassunti**, su un'esercitazione completata, clicca **Svolgi**. Si apre la pagina con tutte le domande.
2. Per le **crocette**: scegli un'opzione e clicca **Verifica**. Compare se è giusta e qual è la risposta corretta.
3. Per le **domande aperte** e l'**orale**: scrivi la risposta nella casella e clicca **Verifica**.
4. La risposta viene valutata in uno di due modi, secondo il computer:
   - **Con scheda NVIDIA** la valuta il modello: ti dice **Corretta**, **Parziale** o **Errata**, quali **Punti che hai coperto** (con la frase della tua risposta che li copre), quali **Punti che mancano** e la soluzione con le fonti.
   - **Senza scheda NVIDIA** la valutazione automatica sarebbe troppo lenta: leggi la soluzione e scegli tu il voto con i pulsanti **Mi do il voto: Corretta / Parziale / Errata**.

   Anche quando valuta il modello puoi cambiare il voto con **Mi do il voto**: vale il tuo.
5. Puoi chiudere la pagina a metà. Nella sezione **Tentativi** della pagina del corso ogni tentativo mostra quante risposte hai consegnato e il punteggio, per esempio **6 di 10 consegnate · punteggio 4,5 su 10**. **Riprendi** riapre un tentativo non finito, **Apri** uno finito.

Se una risposta resta **Da valutare** (per esempio perché Ollama non rispondeva o la scheda video era occupata da una trascrizione), clicca **Valuta** per riprovare, oppure datti il voto.

**Errori da ripassare.** La sezione con questo nome, nella pagina del corso, raccoglie le risposte errate o parziali di tutti i tentativi, con il voto e le fonti della soluzione. **Crea carta** trasforma un errore in una flashcard del Ripasso; dopo, il pulsante diventa **Nel Ripasso**.

## Frasi da esame

Il programma cerca nelle trascrizioni le frasi in cui il docente segnala cosa chiederà, come "all'esame", "vi chiederò", "ricordatevelo" o "domanda d'esame". Le trova da solo, senza Ollama.

1. Apri la pagina del corso. La sezione **Frasi da esame** elenca queste frasi, divise per lezione.
2. All'inizio vedi solo i segnali forti. Spunta **Mostra anche i segnali deboli** per vedere anche le frasi con parole come "importante" o "fondamentale", che spesso non riguardano l'esame.
3. Clicca l'orario di una frase per aprire il Lettore in quel punto e ascoltare il contesto.
4. **Crea carta** apre la creazione di una flashcard con la frase già scritta nel retro: scrivi la domanda nel fronte e conferma.

## Fare domande sul corso

Nella sezione **Domande sul corso** puoi fare domande e ricevere una risposta presa solo dalle lezioni e dal materiale di quel corso. Serve Ollama con `qwen3.5:9b`.

1. Clicca **Nuova conversazione**.
2. Scrivi la domanda in **Domanda** (al massimo 1000 caratteri), per esempio `Che cos'è l'avviamento?`.
3. Clicca **Invia**. Mentre aspetti, la pagina mostra "Sto cercando nel materiale…". Con una RTX 4060 la risposta arriva in circa 10 secondi; la prima domanda dopo l'avvio può metterci di più.
4. Ogni frase della risposta ha la sua fonte, come nelle esercitazioni: cliccala per aprire la pagina del documento o il Lettore in quel punto.
5. Per continuare sullo stesso argomento, scrivi la domanda successiva nella stessa conversazione.

Se la risposta è **"Non trovo la risposta nel materiale di questo corso."**, il corso non copre la domanda: il programma non risponde con conoscenze generali.

Le conversazioni restano nell'elenco a sinistra: cliccane una per riaprirla. **Elimina** la cancella dopo aver chiesto conferma.

Se compare "La scheda video è occupata da una trascrizione: riprova tra poco.", aspetta che la trascrizione finisca e rifai la domanda.

## Materiali di studio di una lezione

Per una singola lezione il programma può preparare un riassunto, i concetti chiave e alcune possibili domande d'esame. Serve Ollama con `qwen3.5:9b`.

1. Apri la lezione nel Lettore e clicca **Materiali di studio**.
2. Clicca **Genera**. Secondo il programma, per una lezione di un'ora e mezza servono circa venti minuti. La pagina mostra l'avanzamento; puoi uscire e tornare.
3. La pagina mostra tre parti: **Riassunto**, **Concetti chiave** e **Possibili domande d'esame**, divise per parte della lezione.
4. Sotto ogni voce c'è la frase della lezione da cui viene, con paragrafo e orario (per esempio **§3 23:10**): cliccala per aprire il Lettore in quel punto e ascoltare.
5. **Aggiungi i concetti al mazzo** trasforma i concetti chiave in flashcard del Ripasso; poi compare **Vai al ripasso**. Serve che la lezione abbia un corso. Se lo clicchi di nuovo, i concetti già nel mazzo non vengono duplicati.
6. Per crearli di nuovo, per esempio dopo aver corretto la trascrizione, clicca **Rigenera**. **Torna al lettore** ti riporta alla lezione.

Se la pagina dice che il materiale è stato generato su una versione precedente della trascrizione, hai corretto il testo dopo la generazione: clicca **Rigenera** per aggiornarlo.

## Ripasso con le flashcard

Il **Ripasso** ti ripropone le carte nel giorno giusto: quelle che sai bene tornano dopo molti giorni, quelle che sbagli tornano presto. Il calcolo usa FSRS, un algoritmo di ripetizione dilazionata. Non serve Ollama.

Le carte si creano in quattro modi:

- dal Lettore, selezionando una frase (vedi [Leggere e ascoltare la trascrizione](#leggere-e-ascoltare-la-trascrizione));
- dai **Materiali di studio**, con **Aggiungi i concetti al mazzo**;
- dalle **Frasi da esame**, con **Crea carta**;
- dagli **Errori da ripassare**, con **Crea carta**.

Per ripassare:

1. Clicca **Ripasso** nel menu a sinistra. La schermata **Oggi** mostra, per ogni corso, quante carte ci sono da ripassare oggi.
2. Clicca **Ripassa** sul corso. Se dice **Nessuna carta oggi**, per quel corso hai finito.
3. Leggi il fronte, pensa alla risposta e clicca **Mostra risposta** (oppure premi la **barra spaziatrice**).
4. Confronta con la risposta e scegli quanto ti è venuta facile: **Di nuovo** (tasto **1**), **Difficile** (**2**), **Bene** (**3**) o **Facile** (**4**).
5. Si passa alla carta successiva. Alla fine compare "Per oggi hai finito.". **Torna a Oggi** ti riporta al riepilogo in qualsiasi momento.

Sul retro di ogni carta c'è la fonte, con **Apri la fonte** per tornare alla lezione o al documento. Un'etichetta dice se la fonte è ancora come quando hai creato la carta: **Fonte verificata**, **Fonte spostata** (il testo c'è ma in un altro punto, per esempio dopo una correzione), **Fonte modificata**, **Fonte rimossa** o **Fonte non leggibile ora**.

Ogni giorno entrano al massimo 20 carte nuove per corso, così il ripasso non diventa troppo lungo se ne aggiungi molte insieme. Nell'interfaccia le carte si creano e si ripassano, ma non si modificano né si cancellano.

## Esportare e importare un corso

Puoi portare un corso su un altro computer, o passarlo a un compagno che usa Transcriber, con un pacchetto `.sbobina.zip`.

**Esportare:**

1. Apri la pagina del corso e clicca **Esporta il corso**.
2. Nella finestra che si apre scegli i **Materiali da includere**: una casella per ogni documento, con lo spazio che occupano.
3. Clicca **Esporta**. Il browser scarica il pacchetto.

Il pacchetto contiene le trascrizioni delle lezioni (senza audio), i materiali scelti, le esercitazioni e le carte del Ripasso. Le lezioni annullate o non concluse non vengono incluse, e il messaggio finale lo dice.

Prima di condividere un pacchetto ricorda che libri e slide sono spesso protetti dal diritto d'autore, e che le trascrizioni possono contenere voci e nomi di altri studenti.

**Importare:**

1. Apri la pagina **Corsi**.
2. Nella sezione **Importa un corso**, trascina il file `.sbobina.zip` nel riquadro oppure cliccaci sopra e sceglilo.
3. Una barra mostra l'invio, poi "Controllo e copia del pacchetto: può richiedere qualche minuto.".
4. Alla fine clicca **Apri il corso**.

Il corso importato arriva come corso nuovo, accanto a quelli che hai già. Le sue lezioni non hanno audio: si leggono, si cercano e si usano per lo studio, ma non si possono riascoltare né trascrivere di nuovo.

## Chiudere il programma

- **Windows**: chiudi la finestra nera.
- **macOS e Linux**: nella finestra del Terminale premi insieme **Ctrl** e **C**, poi chiudi la finestra.

Se chiudi mentre una trascrizione è in corso, al prossimo avvio quella lezione risulta **Interrotta**: caricala di nuovo. Lo stesso vale per un'esercitazione, un riassunto o un OCR in corso: rilancialo dalla pagina del corso. Un'importazione interrotta viene cancellata al riavvio: ripetila.

## Dove finiscono i file

Tutto resta nella cartella `data`, dentro la cartella del programma: audio e trascrizioni delle lezioni e, in `data/courses`, materiale dei corsi, esercitazioni, riassunti, tentativi, carte del Ripasso e conversazioni. Per fare spazio elimina le lezioni dalla pagina **Storico** e il materiale dalle pagine dei corsi. Se sposti o cancelli la cartella del programma, sposti o cancelli anche tutto questo: per tenerne una copia, copia la cartella `data` oppure esporta i corsi.

## Se qualcosa non va

| Cosa vedi | Cosa fare |
| --- | --- |
| `git: command not found` o `"git" non è riconosciuto come comando` | Git non è installato, o la finestra è stata aperta prima di installarlo: vedi [Non hai un account GitHub?](#non-hai-un-account-github), poi apri una finestra nuova |
| `git pull` scrive `Your local changes would be overwritten` | Hai modificato a mano un file del programma: scrivi `git stash` e poi di nuovo `git pull` |
| Il browser non si apre da solo | Apri il browser e scrivi nella barra degli indirizzi `http://127.0.0.1:8765` |
| "Porta 8765 già occupata" | Il programma è già aperto in un'altra finestra: usa quella, oppure chiudila e riavvia |
| La pagina non si carica | Controlla che la finestra nera (o il Terminale) sia ancora aperta; se l'hai chiusa, riavvia il programma |
| Avviso "Trascrizione su CPU: sarà più lenta" | Non è un errore: il computer non ha una scheda NVIDIA utilizzabile, la trascrizione funziona ma ci mette di più |
| "Ollama non è disponibile. Installa Ollama..." o "Scarica l'app Ollama..." | Installa Ollama (vedi [Installare Ollama](#installare-ollama-facoltativo)), oppure togli la spunta alla correzione automatica |
| "Ollama non è disponibile. Avvia l'app Ollama." | Apri l'app Ollama e ricarica la pagina |
| "Ollama non è disponibile. Avvia ollama serve." (Linux) | Apri un nuovo Terminale, scrivi `ollama serve`, premi **Invio** e lascia aperta quella finestra |
| "Ollama non risponde: avvialo e riprova." | Apri l'app Ollama (su Linux `ollama serve`), poi clicca di nuovo il pulsante |
| "GPU occupata da una trascrizione: valuta più tardi." | Aspetta che la trascrizione finisca, poi clicca **Valuta** sulla risposta |
| "Nessun corso associato a questa lezione: imposta un corso per creare carte." | Assegna un corso alla lezione con il campo **Corso** nel Lettore, poi crea di nuovo la carta |
| "La ricerca non è disponibile su questo computer" | Al Python di questo computer manca un componente che serve alla ricerca; corsi e Lettore funzionano lo stesso. Segnalalo al link qui sotto |
| "Il documento è in elaborazione: riprova tra poco." | Aspetta che l'etichetta diventi **Pronto**, poi riprova |
| "OCR interrotto: ci stava mettendo troppo." | Il documento ha troppe pagine per una sola esecuzione: dividi il PDF in file da circa 10 pagine e caricali separatamente |
| "La generazione è in corso: annullala prima di eliminarla." | Clicca **Annulla** su quella riga, poi **Elimina** |
| "Importazione non riuscita." | Il messaggio sotto dice il motivo. Controlla che il file sia un `.sbobina.zip` esportato da Transcriber e che non si sia rovinato durante la copia |
| macOS: "Permission denied" o "Operazione non permessa" | Assicurati di aver scritto `bash avvia.sh` e non `./avvia.sh` |
| Nella finestra compare un errore e il programma si ferma | Fai una foto dello schermo e mandala a chi ti ha passato il programma, oppure apri una segnalazione su https://github.com/AndreaBonn/speech-to-text/issues (per le segnalazioni serve un account GitHub gratuito) |
| La trascrizione ha molte parole sbagliate | Registra più vicino al docente; controlla le parole in giallo; prova la correzione automatica |

[English](./user-guide.md) | **Italiano**

# Guida utente di Transcriber

Transcriber (nel codice si chiama sbobina) trasforma la registrazione di una lezione in testo scritto. Lavora tutto sul tuo computer: l'audio non viene mandato su internet.

Le lezioni sono raggruppate per corso. Per ogni corso puoi aggiungere anche il materiale su cui studi (libro, slide, appunti), cercare insieme nelle lezioni e nel materiale, creare esercitazioni e riassunti e fare domande. Queste funzioni di studio usano un secondo programma gratuito, Ollama, che gira anch'esso sul tuo computer.

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
9. [Storico, modelli e altre pagine](#storico-modelli-e-altre-pagine)
10. [Installare Ollama (facoltativo)](#installare-ollama-facoltativo)
11. [Correzione automatica](#correzione-automatica)
12. [I corsi](#i-corsi)
13. [Cercare nelle lezioni e nel materiale](#cercare-nelle-lezioni-e-nel-materiale)
14. [Aggiungere il materiale del corso](#aggiungere-il-materiale-del-corso)
15. [PDF scansionati: leggerli con l'OCR](#pdf-scansionati-leggerli-con-locr)
16. [Esercitazioni e riassunti](#esercitazioni-e-riassunti)
17. [Fare domande sul corso](#fare-domande-sul-corso)
18. [Materiali di studio di una lezione](#materiali-di-studio-di-una-lezione)
19. [Chiudere il programma](#chiudere-il-programma)
20. [Dove finiscono i file](#dove-finiscono-i-file)
21. [Se qualcosa non va](#se-qualcosa-non-va)

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
2. Nel campo **Materia** scrivi il nome del corso, per esempio `Analisi matematica`. La lezione finisce in quel corso nella pagina **Corsi**, e la correzione automatica usa il nome per riconoscere i termini del corso. Per le lezioni dello stesso corso scrivi sempre lo stesso nome. Puoi anche lasciarlo vuoto e assegnare il corso più tardi dal Lettore.
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

**Cambiare il corso di una lezione.** In cima al Lettore c'è il campo **Corso**. Scrivi il nome del corso (mentre scrivi, il programma suggerisce i corsi che esistono già) e clicca **Salva corso**. La lezione passa a quel corso nella pagina **Corsi**.

Il pulsante **Materiali di studio** apre la pagina di studio di questa lezione: vedi [Materiali di studio di una lezione](#materiali-di-studio-di-una-lezione).

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

## Storico, modelli e altre pagine

- **Storico**: l'elenco di tutte le lezioni caricate, con data e stato. **Apri** porta al Lettore, **Elimina** cancella la lezione e i suoi file. Attenzione: **Elimina** non chiede conferma.
- **Modelli**: i modelli di trascrizione scaricati sul computer. Qui puoi scaricarne uno prima di usarlo, così la prima trascrizione parte subito. Non serve cambiare modello: il programma sceglie da solo quello adatto al tuo computer (`large-v3` con scheda NVIDIA, `large-v3-turbo` senza). La sezione **Ollama** della stessa pagina scarica i modelli per la correzione e per le funzioni di studio.
- **Confronto (WER)**: serve a misurare la precisione confrontando la trascrizione con un testo scritto a mano. Puoi ignorarla.
- **Tema**: il pulsante in fondo al menu di sinistra cambia l'aspetto delle pagine fra **Auto** (segue il computer), **Chiaro** e **Scuro**.

## Installare Ollama (facoltativo)

Ollama è un programma separato e gratuito che fa girare un modello linguistico sul tuo computer. Transcriber lo usa per la correzione automatica, i materiali di studio, le esercitazioni, i riassunti, le domande sul corso e la lettura dei PDF scansionati. Senza Ollama trascrizione, Lettore, ricerca e download funzionano lo stesso.

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

## I corsi

La pagina **Corsi** elenca i tuoi corsi, con il numero di lezioni e la data dell'ultima. Le lezioni senza corso stanno sotto **Senza corso**.

1. Clicca il nome di un corso. Si apre la pagina del corso.
2. In alto c'è la tabella delle sue lezioni: clicca una lezione per aprirla nel Lettore.
3. Sotto ci sono tre sezioni: **Materiali**, **Esercitazioni e riassunti** e **Domande sul corso**. Le prossime sezioni della guida le spiegano.
4. Per tornare all'elenco clicca **← Tutti i corsi**.

Per spostare una lezione in un altro corso usa il campo **Corso** nel Lettore (vedi [Leggere e ascoltare la trascrizione](#leggere-e-ascoltare-la-trascrizione)).

## Cercare nelle lezioni e nel materiale

In cima alla pagina **Corsi** c'è la ricerca **Cerca nelle lezioni e nei materiali**.

1. In **Parole o frase** scrivi quello che cerchi, per esempio `causa del contratto`. Per trovare una frase esatta mettila fra virgolette: `"causa del contratto"`. Trova anche le forme simili: `contratti` trova anche `contratto`.
2. Facoltativo: in **Corso** scegli un corso. **Tutti i corsi** cerca ovunque.
3. Clicca **Cerca**.
4. Ogni risultato mostra la lezione o il documento e il passaggio che corrisponde.
   - Per una lezione, clicca l'orario accanto al passaggio (per esempio **12:30**): il Lettore si apre in quel punto.
   - Per un documento, clicca il nome: il documento si apre sulla pagina trovata.

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

Il testo letto con l'OCR può contenere errori, a volte tali da cambiare il senso. Dovunque venga citato è segnato **testo da OCR**: confrontalo con la pagina originale prima di studiarci sopra.

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
7. Clicca **Mostra** per leggere il risultato, **Nascondi** per chiuderlo.

**Leggere il risultato.** Ogni domanda, risposta e frase del riassunto mostra la sua fonte: il nome del documento con la pagina (per esempio `manuale.pdf p.31`) oppure la lezione con l'orario, seguiti dalla frase citata. Clicca la fonte per aprire la pagina del documento o il Lettore in quel punto. Nelle crocette l'opzione giusta è segnata **Corretta**, e le domande aperte e orali hanno una **Soluzione**.

Le domande con una citazione che non si trova nel materiale vengono scartate. Il risultato dice quante ne sono rimaste, per esempio **8 su 10 richieste**, e perché le altre sono state scartate. Se un documento o una lezione è stato modificato dopo la generazione, le sue fonti sono segnate **fonte modificata dopo la generazione**.

**Scaricare.** Un'esercitazione completata ha quattro pulsanti: `compito.md` e `compito.docx` (solo le domande, per fare la prova), `soluzioni.md` e `soluzioni.docx` (domande con risposte e fonti). Un riassunto ha `riassunto.md` e `riassunto.docx`. I file `.docx` si aprono con Word.

**Elimina** cancella un risultato dopo aver chiesto conferma.

Messaggi che puoi vedere:

| Messaggio | Cosa vuol dire |
| --- | --- |
| "Nel materiale del corso non trovo questo argomento." | L'argomento non compare nel corso: prova con un'altra parola, oppure lascia vuoto **Argomento** |
| "Nessun materiale disponibile per generare: carica documenti o lezioni in questo corso." | Il corso non ha ancora lezioni o documenti con del testo |
| "Il modello ha risposto in un formato non valido: riprova." | La risposta del modello non si è potuta leggere: clicca di nuovo **Genera** |

## Fare domande sul corso

Nella sezione **Domande sul corso** puoi fare domande e ricevere una risposta presa solo dalle lezioni e dal materiale di quel corso. Serve Ollama con `qwen3.5:9b`.

1. Clicca **Nuova conversazione**.
2. Scrivi la domanda in **Domanda**, per esempio `Che cos'è l'avviamento?`.
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
5. Per crearli di nuovo, per esempio dopo aver corretto la trascrizione, clicca **Rigenera**. **Torna al lettore** ti riporta alla lezione.

Se la pagina dice che il materiale è stato generato su una versione precedente della trascrizione, hai corretto il testo dopo la generazione: clicca **Rigenera** per aggiornarlo.

## Chiudere il programma

- **Windows**: chiudi la finestra nera.
- **macOS e Linux**: nella finestra del Terminale premi insieme **Ctrl** e **C**, poi chiudi la finestra.

Se chiudi mentre una trascrizione è in corso, al prossimo avvio quella lezione risulta **Interrotta**: caricala di nuovo. Lo stesso vale per un'esercitazione, un riassunto o un OCR in corso: rilancialo dalla pagina del corso.

## Dove finiscono i file

Tutto resta nella cartella `data`, dentro la cartella del programma: audio e trascrizioni delle lezioni e, in `data/courses`, materiale dei corsi, esercitazioni, riassunti e conversazioni. Per fare spazio elimina le lezioni dalla pagina **Storico** e il materiale dalle pagine dei corsi. Se sposti o cancelli la cartella del programma, sposti o cancelli anche tutto questo.

## Se qualcosa non va

| Cosa vedi | Cosa fare |
| --- | --- |
| Il browser non si apre da solo | Apri il browser e scrivi nella barra degli indirizzi `http://127.0.0.1:8765` |
| "Porta 8765 già occupata" | Il programma è già aperto in un'altra finestra: usa quella, oppure chiudila e riavvia |
| La pagina non si carica | Controlla che la finestra nera (o il Terminale) sia ancora aperta; se l'hai chiusa, riavvia il programma |
| Avviso "Trascrizione su CPU: sarà più lenta" | Non è un errore: il computer non ha una scheda NVIDIA utilizzabile, la trascrizione funziona ma ci mette di più |
| "Ollama non è disponibile. Installa Ollama..." o "Scarica l'app Ollama..." | Installa Ollama (vedi [Installare Ollama](#installare-ollama-facoltativo)), oppure togli la spunta alla correzione automatica |
| "Ollama non è disponibile. Avvia l'app Ollama." | Apri l'app Ollama e ricarica la pagina |
| "Ollama non è disponibile. Avvia ollama serve." (Linux) | Apri un nuovo Terminale, scrivi `ollama serve`, premi **Invio** e lascia aperta quella finestra |
| "Ollama non risponde: avvialo e riprova." | Apri l'app Ollama (su Linux `ollama serve`), poi clicca di nuovo il pulsante |
| "La ricerca non è disponibile su questo computer" | Al Python di questo computer manca un componente che serve alla ricerca; corsi e Lettore funzionano lo stesso. Segnalalo al link qui sotto |
| "Il documento è in elaborazione: riprova tra poco." | Aspetta che l'etichetta diventi **Pronto**, poi riprova |
| "OCR interrotto: ci stava mettendo troppo." | Il documento ha troppe pagine per una sola esecuzione: dividi il PDF in file da circa 10 pagine e caricali separatamente |
| "La generazione è in corso: annullala prima di eliminarla." | Clicca **Annulla** su quella riga, poi **Elimina** |
| macOS: "Permission denied" o "Operazione non permessa" | Assicurati di aver scritto `bash avvia.sh` e non `./avvia.sh` |
| Nella finestra compare un errore e il programma si ferma | Fai una foto dello schermo e mandala a chi ti ha passato il programma, oppure apri una segnalazione su https://github.com/AndreaBonn/speech-to-text/issues |
| La trascrizione ha molte parole sbagliate | Registra più vicino al docente; controlla le parole in giallo; prova la correzione automatica |

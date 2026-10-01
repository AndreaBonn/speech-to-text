# Installare e usare sbobina su Windows

sbobina trascrive le registrazioni delle lezioni sul tuo computer. Funziona anche senza scheda video NVIDIA: in quel caso usa il processore ed è più lento.

Questa guida è per Windows. Su Mac e su Linux i passi sono gli stessi, ma al posto del doppio clic su `avvia.bat` si apre il Terminale nella cartella e si scrive `./avvia.sh`.

## Cosa serve

- Windows 10 o 11.
- Una connessione a internet per il primo avvio: vengono scaricati Python, le librerie e il modello di trascrizione (circa 2-4 GB in tutto). Dopo, internet serve solo per scaricare altri modelli dalla pagina **Modelli**; la trascrizione funziona anche offline.
- Almeno 8 GB di spazio libero sul disco.

## Primo avvio

1. Estrai la cartella `sbobina` che ti è stata passata (per esempio in `Documenti`).
2. Apri la cartella e fai doppio clic su `avvia.bat`.
3. Se Windows mostra "Windows ha protetto il PC", clicca **Ulteriori informazioni** e poi **Esegui comunque**.
4. La prima volta compare la domanda "Lo installo ora da https://astral.sh/uv/install.ps1". Premi **S**. È il programma che prepara Python e le librerie.
5. Aspetta: la prima preparazione può richiedere qualche minuto. Quando è pronta si apre il browser su `http://127.0.0.1:8765`.

Dalla seconda volta basta il doppio clic su `avvia.bat`: parte in pochi secondi.

La finestra nera deve restare aperta mentre usi sbobina. Per chiudere tutto, chiudi quella finestra.

## Trascrivere una lezione

1. Nella pagina **Nuova trascrizione** trascina il file audio nel riquadro, oppure cliccaci sopra e sceglilo dal disco. Vanno bene m4a, mp3, wav, ogg, opus, flac, webm e aac.
2. Se vuoi, scrivi la materia (per esempio "diritto privato"): la usa solo la correzione automatica descritta più sotto, per riconoscere i termini del corso.
3. Clicca **Trascrivi**. La barra mostra a che punto è; puoi chiudere il browser e riaprirlo, il lavoro continua finché la finestra nera è aperta.
4. Quando è finita, clicca **Apri**: nel lettore le parole incerte sono evidenziate in giallo e cliccando una parola l'audio riparte da lì.

### Quanto ci vuole senza scheda NVIDIA

Sul processore sbobina usa un modello più leggero (`large-v3-turbo`). Su un computer fisso con 16 core, 30 secondi di audio hanno richiesto 16 secondi: una lezione di un'ora e mezza richiede quindi circa tre quarti d'ora. Su un portatile può volerci di più. La pagina mostra la velocità e il tempo che manca, calcolati sulla tua lezione.

## Correzione automatica con Ollama (facoltativa)

La correzione rilegge il testo e sistema le parole sentite male, senza riscrivere le frasi. Usa un programma separato, Ollama.

1. Scarica Ollama da https://ollama.com/download e installalo.
2. Avvia l'app Ollama (resta nell'area di notifica, vicino all'orologio).
3. In sbobina apri **Modelli**, scrivi `qwen3.5:9b` (il nome del modello che fa la correzione) in **Scarica per nome** e clicca **Scarica** (circa 6 GB).
4. Nella pagina **Nuova trascrizione** spunta **Correggi con Ollama dopo la trascrizione**.

Senza scheda video la correzione è molto lenta: se la lezione è lunga, puoi lasciarla disattivata.

## Se qualcosa non va

| Cosa vedi | Cosa fare |
| --- | --- |
| "Ollama non è installato" | Installalo da https://ollama.com/download, oppure togli la spunta alla correzione. |
| "Ollama non è avviato" | Apri l'app Ollama dal menu Start e ricarica la pagina. |
| "Porta 8765 già occupata" | Vuol dire che sbobina è già aperto in un'altra finestra nera: usa quella, oppure chiudila e riavvia. |
| Nella finestra nera compare un errore e "Premere un tasto per continuare" | Fai una foto del messaggio e mandala a chi ti ha passato sbobina, prima di premere un tasto. |
| Il browser non si apre da solo | Apri tu `http://127.0.0.1:8765`. |

Tutto resta sul tuo computer: l'audio e le trascrizioni sono nella cartella `data` dentro `sbobina`.

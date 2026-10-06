# T060 - Misura V10: formule nell'OCR (2026-10-05)

OCR con `qwen2.5vl:7b` via Ollama 0.18, `temperature` 0, `num_ctx` 4096, con la stessa funzione
dell'app (`ollama_vision.read_page_image`) e la stessa resa della pagina (`render_pdf_page` a
`ocr_scale` 1.0). Due prompt a confronto: `ocr-v1.md` (in uso) e `ocr-v2.md` (chiede le formule
fra `\(…\)` e `\[…\]`, mai fra `$`). Una esecuzione per prompt.

**Pagine di Claude, non dello studente.** Il 2026-10-05 l'utente ha scelto pagine generate da
Claude invece di materiale proprio (U5 delegata). Dieci pagine in italiano (analisi, serie,
matrici, probabilità, statistica, cinematica, termodinamica, elettromagnetismo, economia con
prezzi in `$` e una parola in corsivo), 39 formule (22 in linea, 17 su riga propria), composte
con `pdflatex`, rasterizzate a 200 dpi, sporcate come una scansione (rotazione fino a 0,6°,
sfocatura, rumore; seme fisso) e salvate come PDF di sole immagini, così che l'app debba farne
l'OCR. Le pagine sono più corte e più pulite di un libro o di appunti veri: **i numeri sono un
limite superiore** finché non si misura una pagina reale.

Generatore e contenuto: `scripts/math_pages.py`, `scripts/math_pages_content.py`; misura:
`scripts/eval_math.py` con `scripts/katex_check.js`. Le pagine e i testi letti stanno in
`data/eval/math/` (fuori dal repo).

Criterio: una formula è **trovata** se compare fra `\(…\)` o `\[…\]` con la stessa regola di
`math-text.js`, **leggibile** se KaTeX 0.19 (quello del repo) la accetta, **corretta** se il suo
MathML coincide con quello della formula originale (spazi e graffe superflue non contano). Il
confronto è severo: anche uno spazio sottile mancante o una variante di glifo contano come errore,
per questo gli errori sono classificati sotto. Né l'ADR né il piano fissano una soglia numerica
per V10, e non ne è stata scritta una prima dei numeri.
`BUDGET: 1 esecuzione per prompt, nessuna modifica a ocr-v2 | ranking: nessun $ come delimitatore
> formule corrette > formule leggibili > tempo`

## Risultati

| Prompt | Trovate | Leggibili da KaTeX | Corrette (MathML) | `$` come delimitatore | s/pagina (CPU) |
|---|---|---|---|---|---|
| `ocr-v1` | 30/39 | 30/39 | 22/39 (56%) | 3 | 118 |
| `ocr-v2` | 39/39 | 39/39 | 31/39 (79%) | 0 | 123 |

Per pagina (trovate / corrette / `$`):

| Pagina | Formule | `ocr-v1` | `ocr-v2` |
|---|---|---|---|
| 01 Limiti e derivate | 5 | 6 / 4 / 0 | 5 / 5 / 0 |
| 02 Integrali | 6 | 6 / 6 / 0 | 6 / 6 / 0 |
| 03 Serie | 5 | 0 / 0 / 3 | 5 / 5 / 0 |
| 04 Matrici | 4 | 4 / 3 / 0 | 4 / 2 / 0 |
| 05 Probabilità | 3 | 3 / 1 / 0 | 3 / 1 / 0 |
| 06 Statistica | 4 | 3 / 3 / 0 | 4 / 4 / 0 |
| 07 Cinematica | 3 | 3 / 3 / 0 | 3 / 3 / 0 |
| 08 Termodinamica | 4 | 0 / 0 / 0 | 4 / 3 / 0 |
| 09 Elettromagnetismo | 3 | 3 / 1 / 0 | 3 / 1 / 0 |
| 10 Economia | 2 | 2 / 1 / 0 | 2 / 1 / 0 |

Già con `ocr-v1` il modello scrive spesso LaTeX fra `\(…\)` per abitudine, ma non sempre: sulla
pagina 03 usa `$$…$$` e `$…$` (che l'app mostrerebbe come testo), sulla 08 scrive le formule come
testo semplice. `ocr-v2` usa i delimitatori giusti su tutte le pagine. Su entrambe le versioni i
`$` dei prezzi della pagina 10 restano testo.

## Errori di `ocr-v2` (8 su 39)

| Pagina | Originale | Letta | Natura |
|---|---|---|---|
| 05 (×2) | `P(A) \, P(B)` | `P(A) P(B)` | spazio sottile mancante, a schermo quasi identica |
| 09 (×2) | `\varepsilon_0` | `\epsilon_0` | variante del glifo, stesso simbolo |
| 10 | `1{,}05` | `1,05` | in modalità matematica compare uno spazio dopo la virgola |
| 04 | `\det A = 2 \cdot 3 - 1 \cdot 1 = 5` | `A = 2 \cdot 3 - 1 \cdot 1 = 5` | perde "det": cambia il significato |
| 04 | `A\mathbf{x} = \mathbf{b}` | `A x = b` | perde il grassetto dei vettori |
| 08 | `\eta = 1 - \frac{T_C}{T_H}` | `\eta = 1 - \frac{T_c}{T_h}` | pedici minuscoli al posto di maiuscoli |

Escluse le 5 differenze di spaziatura e di glifo, `ocr-v2` ha 36/39 formule corrette (92%) e 3
errori di contenuto. BASIS: measured.

## Non misurato

- Fedeltà del testo normale fuori dalle formule: il confronto riguarda solo le formule e il
  testo letto non è stato confrontato con l'originale. BASIS: unknown.
- Pagine reali (scansioni di libri o appunti, scrittura a mano): assenti per scelta (U5).
- Tempo su GPU: `qwen2.5vl:7b` con il proiettore visivo richiede 12,5 GiB e non entra nella RTX
  4060 da 8 GB; Ollama lo carica tutto sulla CPU (circa 7 GiB di RAM di sistema). Con lo swap
  pieno il caricamento fallisce: è servito liberare memoria prima della misura.

# T068 - Misura V9: citazioni su pagine con formule (2026-10-06)

Generazioni reali con `qwen3.5:9b` via Ollama 0.18 sul testo che `ocr-v2` ha letto dalle 10 pagine
di V10, con il percorso dell'app: `chunk_document_pages`, la pagina dell'argomento prima delle
altre (come la metterebbe il retrieval) tagliate al budget di parole del formato,
`generation_pipeline.generate` con i prompt `compito-v3` e `riassunto-v2`. Per pagina un compito
a domande aperte da 3 e un riassunto, argomento uguale al titolo della pagina: 20 generazioni.
Ogni citazione proposta dal modello viene risolta di nuovo con `resolve_citation`, così il tasso
conta le citazioni e non le domande o frasi che la pipeline tiene. Una citazione "con formula"
contiene `\(` o `\[`.

Script: `scripts/eval_citations_math.py`; risultati per generazione in
`data/eval/math/citations-runs.jsonl` e `citations.json` (fuori dal repo).
`BUDGET: 1 esecuzione per pagina e formato, prompt invariati durante la misura | soglia 20% dal
piano (T068)`

## Risultati

Tre esecuzioni, una per ogni correzione emersa durante il gate F4 (ADR D5, "Correzioni emerse in
F4"). Vale l'ultima, fatta con il codice spedito; le prime due restano come storia, con i
risultati in `data/eval/math/citations-hint.json` e `citations-multiline.json`.

| Esecuzione | Generazioni `DONE` | Citazioni scartate | Con formula scartate | Testi con formula fra delimitatori | Testi con barre doppie |
|---|---|---|---|---|---|
| 1. prompt con "la barra si scrive doppia" | 20/20 | 2/117 (2%) | 0/57 | non contati | non contati |
| 2. indicazione tolta, passaggi su più righe | 18/20 | 0/90 | 0/66 | 35/113 | 0 |
| 3. passaggi su una riga (codice spedito) | **20/20** | **1/89 (1%)** | **0/75** | **47/118** | **0** |

Nella prima esecuzione le citazioni passavano, ma un riassunto reale nell'app è uscito con
`\\lim` (due barre letterali) e senza delimitatori, quindi con la formula come sorgente: il
conteggio delle sole citazioni non lo vedeva. Nella seconda, due compiti (serie, matrici) sono
falliti due volte: una citazione fatta di soli a capo fino al limite di token, e una parentesi in
più nel JSON. Con i passaggi su una riga entrambi riescono al primo tentativo.

Nell'esecuzione 3 tutte le 20 generazioni sono finite `DONE` al primo tentativo: 30 domande
aperte e 58 frasi di riassunto tenute. L'unica citazione scartata (`QUOTE_NOT_FOUND`) è
"quindi il sistema Ax = b ha una sola soluzione": l'OCR aveva letto `A x = b` (spazio e grassetto
persi, errore di V10), e per il controllo `Ax` è una parola sola. È il caso di riformattazione
previsto da D5, sotto soglia.

**Decisione T069a: no.** L'1% è sotto la soglia del 20% e nessuna delle 75 citazioni con formula è
stata scartata; la normalizzazione dei segmenti matematici in `normalize_tokens` non serve.
BASIS: measured.

## Non misurato

- Pagine reali e materiale più lungo: le pagine sono corte e pulite, con una formula ogni poche
  righe. BASIS: unknown.
- Variabilità fra esecuzioni: una esecuzione per pagina e formato per ogni versione del codice.
- Formati a crocette e orale: stesso prompt `compito-v3`, non eseguiti.
- Aderenza all'argomento: un riassunto dell'esecuzione 1 citava la pagina di un altro argomento;
  non è oggetto di V9 e non è stata misurata.

# V10 e V9 su slide reali del corso (2026-10-06)

Prima misura su materiale vero: `data/prove/Lezioni 11 29 Ottobre.pdf`, slide di macroeconomia
(modello di Solow) con formule. Il PDF ha già il testo, quindi l'app non ne farebbe l'OCR: le 9
pagine con più segni di formula (`=`, `^`, `Δ` e simili nel testo nativo) sono rese come immagine
con `render_pdf_page` e lette con `ocr-v2` attraverso `ocr_missing_pages`, come farebbe l'azione
OCR. È una **scansione simulata**: pagine nitide, senza rotazione né rumore. Il testo nativo
fa da riferimento.

Script: `scripts/eval_math_real.py` (OCR) e `scripts/eval_citations_real.py` (citazioni); dati in
`data/eval/math-real/` (fuori dal repo).
`BUDGET: 1 esecuzione per pagina e formato, prompt e codice invariati durante la misura | soglia
V9 20% dal piano; nessuna soglia per V10`

## OCR (V10)

| Pagina | Formule fra delimitatori | Leggibili da KaTeX | Richiamo parole | Secondi |
|---|---|---|---|---|
| 2 | 10 | 10 | 0,944 | 184 |
| 3 | 3 | 3 | 0,833 | 122 |
| 4 | 6 | 6 | 0,943 | 105 |
| 6 | 7 | 7 | 0,828 | 114 |
| 7 | 5 | 5 | 0,906 | 97 |
| 8 | 5 | 5 | 0,900 | 95 |
| 10 | 8 | 8 | 0,815 | 95 |
| 22 | 11 | 11 | 0,839 | 111 |
| 24 | 9 | 9 | 0,808 | 114 |

64 formule, tutte leggibili da KaTeX, nessun `$` come delimitatore. Controllo a mano delle pagine
2 e 22 (21 formule): tutte corrispondono al testo del PDF; `Y/L` diventa `\frac{Y}{L}` e la `s`
del tasso di risparmio `\mathbf{s}`. Le altre 7 pagine non sono state controllate a mano.

Il richiamo (parole del testo nativo presenti nel testo letto) sottostima la qualità: le parole
"mancanti" sono quasi tutte i punti elenco della slide (un glifo privato, ``), `δ` scritto
dall'OCR come `\delta`, e due refusi della slide che l'OCR ha corretto ("amortamento",
"poichè").

Difetto trovato e corretto (commit `8c0bc09`): su 2 pagine su 9 `ocr-v2` ha scritto le liste come
LaTeX (`\begin{itemize}`, `\item`). Il lettore le mostrava come sorgente e la parola `item` rompeva
la contiguità delle citazioni. La pulizia OCR ora toglie gli ambienti di lista e scrive ogni
`\item` come "- ", accanto alla pulizia dei titoli di F69. Le misure sotto sono state fatte
**prima** della correzione, sul testo con `\item`.

## Citazioni (V9)

Stessa procedura di T068: un compito a domande aperte da 3 e un riassunto per pagina, con
`compito-v4` e `riassunto-v2`, argomento uguale al titolo della slide; 18 generazioni. La misura
si è interrotta dopo 13 generazioni per un blocco della GPU (`CUDA error: unspecified launch
failure`, riavvio della macchina) ed è ripresa dalle generazioni salvate.

| Generazioni `DONE` | Citazioni scartate | Testi con formula fra delimitatori | Testi con barre doppie |
|---|---|---|---|
| 18/18, tutte al primo tentativo | **11/103 (11%)** | 44/116 | 0 |

Sotto la soglia del 20%, ma lontano dall'1% delle pagine sintetiche. Le 11 scartate, classificate
a mano (BASIS: inferred, la causa è letta dal confronto fra citazione e testo, non misurata):

| Causa | Quante |
|---|---|
| Il modello riscrive la formula: `δk` invece di `\delta k`, `c*` invece di `c^*`, `s` senza `\mathbf` | 5 |
| Formula da sola, sotto le 3 parole (`\delta k`, `= sy`) | 2 |
| Citazione che salta un pezzo del testo o unisce due pagine | 3 |
| La parola `item` del markup di lista fra due frasi | 1 |

La divisione dello script fra citazioni "con" e "senza formula" (5/82 e 6/21) non va usata: guarda
i delimitatori nella citazione, e quando il modello riscrive la formula in testo semplice li
toglie, quindi una scartata per colpa della formula finisce fra quelle "senza".

La citazione scartata per `item` ora viene trovata, verificato sul testo pulito della pagina 2.
Altre 2 delle 11 contengono `\item` copiato dal modello: con la correzione il modello non lo vede
più, ma non è stato rimisurato (BASIS: inferred).

Un compito (pagina 22, "La Regola Aurea") ha perso tutte e 3 le domande: tutte citavano formule
riscritte in Unicode. La pipeline lo chiude `DONE` con 0 domande, e la pagina delle generazioni
mostra "0 su 3 tenute" con il motivo di ogni scarto: comportamento previsto, non un errore.

**Decisione T069a: resta no**, perché l'11% è sotto la soglia. Il candidato, se il tasso salisse
su altro materiale, è già visibile: in `normalize_tokens`, rendere equivalenti i comandi LaTeX
delle lettere greche e i loro caratteri Unicode (`\delta` e `δ`), separando la lettera dalla
parola che segue (`δk` oggi è un token solo). Coprirebbe 2 delle 5 riscritture (BASIS: inferred,
non provato).

## Seconda esecuzione: testo senza `\item` (2026-10-06)

Stesse 18 generazioni, sul testo OCR ripassato dalla pulizia corrente (0 `\item` rimasti), con
60 s di pausa e l'attesa che la GPU scenda sotto 75 °C prima di ogni generazione: il portatile si
era spento due volte con le generazioni una dopo l'altra. Con le pause non si è spento.

| Generazioni `DONE` | Citazioni scartate | Testi con formula fra delimitatori | Testi con barre doppie |
|---|---|---|---|
| 17/18 | **17/111 (15%)** | 43/122 | 0 |

Le 17 scartate sono tutte nei riassunti; i 9 compiti non ne hanno persa nessuna. Un solo
riassunto ("Lo stato stazionario") ne ha 8: in quella generazione il modello ha scritto ogni
formula in testo semplice (`δk`, `k*`, `Y/L`). Cause (BASIS: inferred, classificate a mano):
circa 10 formule riscritte dal modello, 6 formule da sole sotto le 3 parole (`= sy`,
`\delta k`), 1 con i delimitatori scambiati (`\( k \]`). Nessuna per `\item`.

Il passaggio da 11% a 15% non è un peggioramento del codice: una esecuzione per pagina, e una
singola generazione sposta 8 citazioni. Entrambe le esecuzioni restano sotto il 20%, quindi
**T069a resta chiuso**. La causa dominante resta la riscrittura delle formule da parte del
modello, non l'OCR.

Il riassunto della pagina 4 è finito `FAILED`: tagliato dal limite di token in uscita a entrambi
i tentativi (nella prima esecuzione era riuscito). I riassunti non hanno il recupero delle parti
complete che hanno i compiti (F40) e lo studio. La prima volta questo caso aveva fatto cadere lo
script con `KeyError`: era un errore introdotto in `d803e43`, corretto in `0cacd8f`.

## Non misurato

- Una scansione vera (carta fotografata o scanner): qui le pagine sono rese dal PDF nativo.
  BASIS: unknown.
- Variabilità fra esecuzioni: una esecuzione per pagina e formato.
- Formati a crocette e orale.

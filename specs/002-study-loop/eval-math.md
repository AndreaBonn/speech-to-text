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

| Citazioni | Proposte | Scartate | Motivi |
|---|---|---|---|
| Con formula | 57 | 0 (0%) | - |
| Senza formula | 60 | 2 (3%) | 1 `QUOTE_NOT_FOUND`, 1 `QUOTE_LENGTH` |
| Totale | 117 | 2 (2%) | |

Tutte le 20 generazioni sono finite `DONE` al primo tentativo: 30 domande aperte e 84 frasi di
riassunto tenute, una frase scartata in due riassunti. Le due citazioni scartate:

- riassunto di statistica descrittiva: `det A = 2 \cdot 3 - 1 \cdot 1 = 5, ...`, copiata dalla
  pagina delle matrici. Il testo OCR di quella pagina aveva perso "det" (errore di contenuto di
  V10), quindi la citazione corretta rispetto all'originale non si trova nel testo letto. Lo
  stesso riassunto cita la pagina delle matrici anche altrove: l'aderenza all'argomento non è
  oggetto di V9 e non è stata misurata.
- riassunto di elettromagnetismo: `\section*{Probabilità}`, un titolo di 1 parola sotto il minimo
  di 3.

**Decisione T069a: no.** Il 2% è sotto la soglia del 20% e nessuna citazione con formula è stata
scartata; la normalizzazione dei segmenti matematici in `normalize_tokens` non serve. BASIS:
measured.

## Non misurato

- Pagine reali e materiale più lungo: le pagine sono corte e pulite, con una formula ogni poche
  righe. BASIS: unknown.
- Variabilità fra esecuzioni: una esecuzione per pagina e formato.
- Quante soluzioni e frasi riportano davvero una formula fra delimitatori: i testi generati non
  sono stati contati, solo le citazioni.
- Formati a crocette e orale: stesso prompt `compito-v3`, non eseguiti.

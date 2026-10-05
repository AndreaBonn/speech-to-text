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

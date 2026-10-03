# Misure del piano 001-course-workspace

## T024 - Recupero dei passaggi (2026-10-03)

Comando: `uv run python scripts/eval_retrieval.py <data_dir> data/prove/retrieval_eval.json 8`.
Il file delle domande sta in `data/` (fuori da git): contiene materiale del corso dell'utente.

Corpus: 6 PDF reali dell'utente nel corso "economia aziendale" (manuale da 246 pagine, slide
sulla crescita, esercitazione di microeconomia, riassunto, mappa concettuale, domande d'esame) e
una lezione reale di Diritto da 70 minuti. Il PDF con le domande d'esame è escluso dal corpus
quando si misurano quelle domande, altrimenti il recupero troverebbe la domanda stessa.

Metodo: una domanda è un HIT se fra i primi 8 passaggi restituiti da `retrieve_windows` uno
contiene la frase chiave della risposta (maiuscole e accenti ignorati). Le frasi chiave le ha
scelte Claude: la misura dice se il passaggio con quel concetto arriva nei primi 8, non se la
frase scelta è l'unica risposta giusta.

| Origine delle domande | Domande | recall@8 |
|---|---|---|
| Domande d'esame del PDF dell'utente | 14 | 11/14 = 0,79 |
| Scritte da Claude, parafrasate, su slide, esercitazione e lezione | 16 | 16/16 = 1,00 |
| Totale | 30 | 27/30 = **0,90** |

Soglia dell'ADR D2: 0,7. **Esito: BM25 resta, nessun embedding.**

Mancati: "caratteri del fenomeno aziendale" (rank 15), "negozio di abbigliamento" (rank 20),
"imprenditore secondo la legge" (la frase chiave "2082" non compare nei passaggi recuperati).

| Tentativo | Baseline → Risultato | Verdetto | Perché |
|---|---|---|---|
| Prima misura | 18/30 = 0,60 | difetto, non tuning | `course_scope` confrontava la chiave del corso con l'id del registro: nessuna lezione entrava nello scope (3/3 domande di Diritto senza alcun risultato). Corretto in `33f04eb` |
| Dopo il fix | 27/30 = 0,90 | tenuto | Sopra soglia; nessuna iterazione della query necessaria (BUDGET di 3 non usato) |

SPEDITO: query BM25 di T023 invariata, finestre di lezione di T025.

## T050 - OCR dei PDF scansionati con qwen2.5vl:7b (2026-10-03)

Pagina 31 del manuale scansionato `librib` (che ha già un livello di testo OCR, usato come
riferimento), renderizzata con pypdfium2 e passata a `qwen2.5vl:7b` via Ollama 0.18.

| Impostazione | Tempo per pagina | Dove gira | Esito |
|---|---|---|---|
| scala 2,0, num_ctx 8192 | oltre 600 s, interrotto | 100% CPU, 13 GB stimati | nessuna pagina completata |
| scala 1,0, num_ctx 4096 | 171,6 s (+31,8 s di caricamento) | 100% CPU, 13 GB stimati, GPU a 26 MiB | 434 parole contro 441 |

Qualità (scala 1,0): WER 0,17 contro il livello di testo del PDF. Oltre a sillabazioni e
punteggiatura, **un errore che cambia il significato**: il PDF dice "i piccoli redditi erano
cresciuti meno dei grandi", l'OCR "i piccoli redditi erano crescenti nel grado di incremento".
Il modello visivo riscrive invece di trascrivere.

Conseguenze per F5:
- Un manuale di 246 pagine costerebbe circa 12 ore di CPU: l'OCR va lanciato per documento, con
  avanzamento e annullabile, mai automatico.
- Il testo OCR va marcato nel lettore e nelle citazioni come "testo riconosciuto automaticamente,
  può contenere errori anche di significato": una citazione verbatim di un testo riscritto non
  prova niente.
- Perché il modello non usa la GPU: BASIS inferred, la stima di 13 GB supera gli 8 GB e Ollama non
  divide il modello visivo; da verificare nei log di Ollama.

## T051-T052 - OCR reale dalla pagina del corso (2026-10-03)

PDF di sole immagini con le pagine 31-32 del manuale `librib` (la 31 è quella di T050),
caricato nel corso e passato all'OCR dal pulsante della pagina. `qwen2.5vl:7b`, scala 1.0,
`num_ctx` 4096, prompt `ocr-v1`.

| | Misura |
|---|---|
| Pagina 1 | 265 s |
| Pagina 2 | 286 s |
| Parole pagina 1 | 431 (livello di testo del PDF originale: 441) |
| Frase che in T050 cambiava significato | trascritta corretta: "i piccoli redditi erano cresciuti meno dei grandi" |

Il documento passa a `ready`, il lettore mostra l'avviso sulle pagine OCR, le citazioni portano
"testo da OCR". Una sola frase controllata a vista: la marcatura come testo non affidabile resta.

Il gate T059 (OCR e Whisper mai insieme) **non è valido**: durante la prova Whisper girava su CPU
perché `uv add pillow` (commit `7f5b76a`) aveva sincronizzato l'ambiente senza l'extra `cuda`,
disinstallando `nvidia-cublas-cu12` e `nvidia-cudnn-cu12`. Va ripetuto dopo
`uv sync --extra cuda`.

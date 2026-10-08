# Misure: recupero ibrido BM25 + embedding densi

Piano: `plan.md` § C1. Corpus e gold set in `data/eval/retrieval-hybrid/` (fuori da git).

## Regola di scelta (scritta il 2026-10-06, prima di qualunque misura)

BUDGET: 5 candidati (qwen3-embedding 0.6b/4b/8b, bge-m3, embeddinggemma), varianti di T016 solo sui
2 migliori, un solo rigiudizio se il controllo a campione fallisce | ranking: gate Q > gate L >
recall@8 ibrido > MRR@10 > recall@8 `crosslingual` > tempo di indicizzazione > disco.

- **Gate Q**: ibrido contro BM25 con vittorie - sconfitte >= +4 domande (hit@8, appaiato), al
  massimo 1 domanda persa sul sottoinsieme `exam`, MRR@10 non inferiore a BM25.
- **Gate L**: embedding della query p95 <= 1,0 s sul percorso scelto, e `qwen3.5:9b` ancora in
  `/api/ps` con `size_vram` invariata dopo 20 query.
- Nessun candidato passa il gate Q: F2 non parte, i numeri tornano all'utente. Il migliore per
  qualità fallisce solo il gate L: si misura il percorso della query su GPU e la scelta torna
  all'utente.

## Verifiche su Ollama (T010)

Misurate il 2026-10-06 su Ollama 0.18.0 con `qwen3-embedding:0.6b` (639 MB, Q8_0, 1024 dimensioni,
contesto 32768). Script: chiamate HTTP dirette a `/api/embed`, `/api/ps`, `/api/show`, `/api/generate`.
Tutte le righe: BASIS: measured.

| Voce | Osservato |
| --- | --- |
| Batch su `/api/embed` | 3 input, 3 vettori da 1024; norma L2 = 1,0 |
| `dimensions=256` | 200, vettore da 256 (troncamento Matryoshka rispettato) |
| `truncate=false` oltre il contesto (`num_ctx` 2048) | 400 "the input length exceeds the context length" |
| `truncate` di default oltre il contesto | 200, `prompt_eval_count` 2047: tronca in silenzio |
| Template | `TEMPLATE {{ .Prompt }}`: Ollama non aggiunge istruzioni, il prefisso `Instruct:...\nQuery:` va messo dal codice |
| `/api/show` capabilities | `["embedding"]` |
| `num_gpu=0` | `size_vram` 0 per l'embedding (log: "offloaded 0/29 layers to GPU") |
| Coseno GPU contro CPU, stesso testo | 0,999572 (soglia 0,99: Dis.5 regge) |
| Latenza query su CPU, 20 query | p50 0,358 s, p95 0,437 s; prima query 1,233 s (caricamento) |
| `generate(keep_alive=0)` sul modello di embedding | 200, `done_reason: "unload"`; `/api/ps` vuoto dopo |
| `qwen3.5:9b` residente dopo le 20 query su CPU | **No**: scaricato al caricamento dell'embedding |

**Misura contaminata, da ripetere.** Durante la misura ComfyUI (`foocus-personal`) occupava 4,6 GB
di VRAM: Ollama vedeva 3,1 GiB liberi e ha caricato `qwen3.5:9b` con 12/33 layer su GPU. Lo scarico
del 9B è avvenuto in questa condizione di offload parziale; se si ripete con la GPU libera, il gate L
è valutabile.

**Ripetuta il 2026-10-07 con la GPU libera** (nessun altro processo CUDA): `qwen3.5:9b` caricato
con 32/33 layer su GPU, `size_vram` 6 278 025 216 prima e dopo 20 query su CPU, ancora in `/api/ps`
alla fine. Latenza query su CPU p50 0,306 s, p95 0,404 s, prima query 0,922 s. Coseno GPU/CPU
invariato (0,999572). Gate L per `qwen3-embedding:0.6b`: **passa**. Lo scarico del giorno prima
era dovuto all'offload parziale causato da ComfyUI. BASIS: measured.

## Corpus (T011)

Costruito il 2026-10-06 da `scripts/build_hybrid_eval_corpus.py` (non in git, come il
resto della cartella) in `data/eval/retrieval-hybrid/corpus/`: un data dir completo,
usabile dal codice di produzione (`JobStore`, `document_store`, `search_session`), non
una copia a parte.

- **Corso "economia aziendale"**: 5 PDF di `data/prove/` caricati ed estratti con la
  pipeline di produzione (`document_sniff`, `document_store`, `extraction_runner`),
  escluso `EcAziendale2017_domande_esame_*.pdf` (fornisce solo le domande `exam` del
  gold set, come T024), più i 2 capitoli in inglese di
  `data/eval/retrieval-hybrid/english-staging/` (vedi nota sotto). Tutti e 7 `ready`:

  | File | Pagine |
  | --- | --- |
  | `EcAziendale2017_mappa_concettuale_20251030_135016.pdf` | 3 |
  | `EcAziendale2017_riassunto_20251030_134914.pdf` | 82 |
  | `Esercitazione_2_2023.pdf` | 3 |
  | `Lezioni 11 29 Ottobre.pdf` | 24 |
  | `librib_685541.pdf` | 246 |
  | `chapter-firm-and-accounting.md` | 14 |
  | `chapter-costs-and-decisions.md` | 12 |

  `librib_685541.pdf` non è materiale del corso: è il "Manuale di Statistica" di Felice
  Vinci (1934), un trattato di statistica generale senza relazione con economia
  aziendale. Resta nel corpus (era già nel corso in `data/prove/`, nota di Research nel
  piano) come materiale voluminoso e topicamente estraneo: utile per i `negative` e per
  misurare se il denso si fa distrarre dal volume di BM25.

  **Materiale inglese (crosslingual).** I due capitoli `.md` sono testo **sintetico**,
  scritto da un LLM sugli argomenti del corso su indicazione dell'utente, non un
  estratto da un libro di testo reale: coprono la rappresentazione contabile
  dell'impresa (patrimonio netto, reddito, stato patrimoniale, conto economico,
  avviamento) e la contabilità gestionale (costi fissi/variabili, margine di
  contribuzione, break-even, make-or-buy, budgeting). Questo può rendere il task
  cross-lingua **più facile** del previsto per il recupero denso rispetto a un libro
  reale: un capitolo scritto da un LLM tende a una terminologia più uniforme e a frasi
  più prevedibili di un testo accademico vero, il che riduce il divario lessicale che
  il cross-lingua dovrebbe misurare.

  **Pagina per i `.md`.** `document_extract._sections_to_pages` (usata anche per i
  `.docx`) tratta ogni intestazione Markdown (riga che inizia per `#`, a qualunque
  livello) come l'inizio di una nuova "pagina logica", ulteriormente spezzata ogni 500
  parole se la sezione è lunga; è la stessa convenzione già in uso per i `.docx`, non
  una nuova regola introdotta per questo corpus. Il numero di pagina risultante non
  corrisponde a una pagina fisica ma è stabile al reindex (funzione pura del testo
  sorgente) ed è compatibile senza adattamenti con `DocumentRef(filename, page)` di
  `src/sbobina/retrieval_metrics.py`, che è già agnostico rispetto al tipo di
  documento. Verificato leggendo l'estrazione reale: `chapter-firm-and-accounting.md`
  produce 14 pagine (il titolo da solo è la pagina 1; due sezioni lunghe, "The
  entrepreneur..." e "Income...", superano le 500 parole e si spezzano su due pagine
  consecutive), `chapter-costs-and-decisions.md` ne produce 12.

  Nota sul conteggio: il piano (DoD C1 e T011) parla di "6 PDF di `data/prove/`". I file
  nella cartella sono 6 includendo l'esame; il corpus ne usa 5, l'esame resta escluso
  perché la stessa DoD lo richiede come sorgente delle domande `exam`, non come corpus.

- **Corso "diritto"**: copia di 3 lezioni di `data/jobs/` (job.json, progress.json,
  transcript; esclusi `audio.m4a` e `child.log`, non necessari al recupero e grandi
  30-40 MB l'uno). Un quarto job dello stesso corso, `77593c93-...`, è rimasto in stage
  `transcribing` senza transcript: non è una lezione completa e non è stato copiato.
  Dei 3 copiati, due (`82144973-...` e `7aef7b66-...`) sono la **stessa registrazione**
  trascritta due volte: una interrotta durante la correzione (transcript originale), una
  completata (transcript corretto). È lo stato reale di produzione, non un artefatto
  della copia: la nota di Research nel piano misura infatti "3 lezioni, 4156 segmenti"
  sullo stesso contenuto.

Verifica: `uv run python scripts/eval_retrieval.py data/eval/retrieval-hybrid/corpus
<eval.json>` gira sul nuovo data dir senza modifiche al codice (query di prova su
"avviamento" ed "possesso", hit a rank 1 su entrambe). Conteggi dall'indice FTS
ricostruito da `search_session` (`data/eval/retrieval-hybrid/corpus/search.sqlite3`),
prima e dopo l'aggiunta dei 2 capitoli inglesi:

| Voce | Prima (5 documenti) | Dopo (7 documenti) |
| --- | --- | --- |
| Documenti `ready` | 5 / 5 | 7 / 7 |
| Passaggi FTS documento (`doc_passages`) | 426 | 458 |
| Lezioni indicizzate | 3 | 3 (invariato) |
| Passaggi FTS lezione (`passages`, segmenti Whisper) | 4156 | 4156 (invariato) |

BASIS: measured (comandi sopra, eseguiti su questo corpus prima e dopo la ricostruzione
con `scripts/build_hybrid_eval_corpus.py`).

## Gold set (T012)

`data/eval/retrieval-hybrid/gold.json`, 81 domande in italiano. Riferimenti stabili al
reindex:

- documento: `{"kind": "document", "filename": "<file>", "page": <1-based>}`
- lezione: `{"kind": "lecture", "job_id": "<uuid>", "start_s": <float>, "end_s": <float>}`

Una domanda può avere più riferimenti (più pagine, o più job_id quando la stessa
registrazione è indicizzata due volte, vedi `dir-lec-01` sotto).

| Tipo | Conteggio | Corso |
| --- | --- | --- |
| `exam` | 12 | economia aziendale |
| `paraphrase` | 26 | economia aziendale |
| `lecture` | 16 | diritto |
| `negative` | 11 (6 economia aziendale, 5 diritto) | entrambi |
| `crosslingual` | 16 | economia aziendale |
| **Totale** | **81** | |

Le 16 domande `crosslingual` (`eco-xl-01`...`eco-xl-16`) sono in italiano naturale, ma
la risposta esiste solo nei due capitoli inglesi, mai nei 5 PDF italiani: coprono
margine di contribuzione, break-even (anche multiprodotto con mix di vendita), costi
diretti/indiretti, costi fissi/variabili (comportamento per unità, semi-variabili, a
gradino), make-or-buy con costi sommersi e costo opportunità, sotto-budget e scostamenti
di budget, e la distinzione soggetto giuridico/soggetto economico. Argomenti scelti
perché verificati assenti dal testo italiano estratto (grep mirato su "margine di
contribuzione", "break-even"/"punto di pareggio", "mix di vendita", "costi
diretti"/"indiretti", "scostamento favorevole/sfavorevole", "budget operativo",
"soggetto economico"/"giuridico": 0 occorrenze in tutte); la vicina "competenza
economica" (principio di accrual) è invece già coperta in italiano ed è stata esclusa
per non introdurre un falso crosslingual. Esempio:

```json
{
  "id": "eco-xl-08",
  "type": "crosslingual",
  "course": "economia aziendale",
  "question": "In un mix di vendita con un prodotto che ha margine di contribuzione 30 al 60% dei volumi e un altro con margine 10 al 40%, quanto vale il margine di contribuzione medio ponderato?",
  "references": [
    {"kind": "document", "filename": "chapter-costs-and-decisions.md", "page": 7}
  ]
}
```

Un esempio per tipo:

```json
{
  "id": "eco-exam-04",
  "type": "exam",
  "course": "economia aziendale",
  "question": "Qual è il concetto di avviamento?",
  "references": [
    {"kind": "document",
     "filename": "EcAziendale2017_mappa_concettuale_20251030_135016.pdf", "page": 2}
  ]
}
```

```json
{
  "id": "eco-par-04",
  "type": "paraphrase",
  "course": "economia aziendale",
  "question": "Perché un'organizzazione può valere, per chi la rileva, più della semplice somma di ciò che possiede materialmente?",
  "references": [
    {"kind": "document",
     "filename": "EcAziendale2017_mappa_concettuale_20251030_135016.pdf", "page": 2}
  ]
}
```

```json
{
  "id": "dir-lec-01",
  "type": "lecture",
  "course": "diritto",
  "question": "Il possesso è un diritto?",
  "references": [
    {"kind": "lecture", "job_id": "82144973-acfa-4b8b-ab8b-90c8ef51e85e",
     "start_s": 16.5, "end_s": 29.3},
    {"kind": "lecture", "job_id": "7aef7b66-2f4c-4f4c-9cb8-4848faa0bbaf",
     "start_s": 16.5, "end_s": 29.3}
  ]
}
```

```json
{
  "id": "eco-neg-01",
  "type": "negative",
  "course": "economia aziendale",
  "question": "Come si contabilizza un leasing secondo il principio contabile IFRS 16?",
  "references": []
}
```

Le domande `exam` vengono dal PDF d'esame escluso dal corpus
(`EcAziendale2017_domande_esame_20251030_135219.pdf`), ma i riferimenti sono stati
verificati sul testo reale del corpus, non sulle citazioni interne del PDF d'esame:
quel PDF cita come fonte "File: 20171204 EcAziendale 2017-18 Savino.pdf", un file che
non esiste in `data/prove/` (è materiale della generazione automatica dell'esame, non
del corso). Un riferimento del genere non sarebbe stato verificabile; ogni domanda
`exam` nel gold è ancorata invece a una pagina del corpus dove lo stesso concetto è
effettivamente presente.

Le domande `negative` sono state verificate assenti dal materiale scopato (grep su
tutte le pagine/segmenti del corso), non solo assunte plausibili.

Scostamento dall'esempio illustrativo del piano (DoD C1): l'esempio del piano marca
come riferimento "`librib_685541.pdf` pagina con la definizione di avviamento" per una
domanda sull'avviamento. `librib_685541.pdf` è il manuale di statistica del 1934 (vedi
§ Corpus): non contiene la parola "avviamento" né alcuna definizione di economia
aziendale. Quell'esempio è stato trattato come illustrativo del meccanismo del gold
(non serve overlap lessicale per essere rilevante), non come riferimento letterale da
riprodurre: `eco-par-04` copre lo stesso concetto con un riferimento verificato
(`EcAziendale2017_mappa_concettuale...pdf`, pagina 2).

Verifica: `scripts/check_gold.py` (T012), verifica che ogni riferimento esista nel
corpus (pagina presente nel documento, intervallo dentro la durata della lezione), che
nessuna domanda `paraphrase` condivida una parola di contenuto (non-stopword) con il
testo del proprio riferimento, e che ogni domanda `crosslingual` punti solo ai 2 file
inglesi (mai a un PDF italiano o a una lezione di diritto).

```
$ uv run python scripts/check_gold.py
81 domande, 0 errori
```

BASIS: measured (comando sopra, eseguito su questo gold set e questo corpus).

## Baseline BM25 (T014)

### Primo run, gold preliminare (2026-10-07, prima del pooling)

Riferimenti del gold così come annotati in T012, **senza** giudizi alla cieca sul pool: un
passaggio rilevante che nessuno ha annotato conta come mancato, quindi i numeri sottostimano
tutti i sistemi e soprattutto BM25 sulle domande che non sono `paraphrase`. Le `paraphrase`
sono costruite senza parole in comune col riferimento, quindi BM25 a 0 è atteso per
costruzione. `qwen3-embedding:0.6b`, istruzione sulla query attiva, ibrido = RRF su 4 liste
(BM25 e denso, documenti e lezioni). Output in `data/eval/retrieval-hybrid/out/q06-*.json`.

| Tipo (n) | BM25 r@8 / MRR@10 | Denso r@8 / MRR@10 | Ibrido r@8 / MRR@10 |
| --- | --- | --- | --- |
| exam (12) | 0,83 / 0,653 | 1,00 / 0,581 | 0,92 / 0,729 |
| paraphrase (26) | 0,00 / 0,000 | 0,65 / 0,495 | 0,23 / 0,059 |
| lecture (16) | 0,81 / 0,601 | 1,00 / 0,844 | 1,00 / 0,811 |
| crosslingual (16) | 0,50 / 0,273 | 0,94 / 0,938 | 0,88 / 0,645 |
| tutte (81, 11 negative incluse) | 0,38 / 0,269 | 0,74 / 0,597 | 0,58 / 0,415 |

Tempi: BM25 3,3 s; denso 1140 s, quasi tutto il calcolo dei vettori del corpus su GPU con
ComfyUI che occupava 4,6 GB (da rimisurare); ibrido 55 s con la cache dei vettori.

Lettura: l'ibrido batte BM25 su ogni tipo, ma perde contro il denso da solo su `paraphrase`
e `crosslingual`. Con pesi uguali, le due liste BM25 spingono in alto passaggi lessicalmente
vicini e non pertinenti. Il confronto definitivo aspetta i giudizi alla cieca sul pool.
BASIS: measured (gold preliminare).

### Giudizi alla cieca sul pool (2026-10-07)

Pool: unione deduplicata e mescolata dei top-10 di BM25, denso e ibrido (`out/pool-q06.json`),
1565 passaggi su 81 domande, 5 lotti in `judging/batch-*.json`. Giudici: 5 subagent Sonnet a
contesto pulito, ognuno con la sola domanda e il testo del passaggio, senza sapere quale
sistema l'ha prodotto. Scala: 2 risponde, 1 parziale, 0 no. Voti in `judging/verdicts-*.json`,
controllati contro i lotti: 1565 voti, nessun mancante, nessun valore fuori scala.
Distribuzione: 0 = 1338, 1 = 90, 2 = 137.

Rilevante = voto 2 **oppure** riferimento del gold T012. Metriche sulle 70 domande con
risposta (le 11 `negative` escluse, servono alla soglia di T016). Riproducibile con
`scripts/eval_hybrid.py --system <s> --judgments data/eval/retrieval-hybrid/judging` (T009).

| Tipo (n) | BM25 r@8 / MRR@10 | Denso r@8 / MRR@10 | Ibrido 4 liste r@8 / MRR@10 |
| --- | --- | --- | --- |
| exam (12) | 0,83 / 0,653 | 1,00 / 0,581 | 0,92 / 0,729 |
| paraphrase (26) | 0,04 / 0,027 | 0,73 / 0,522 | 0,38 / 0,154 |
| lecture (16) | 0,94 / 0,757 | 1,00 / 1,000 | 1,00 / 1,000 |
| crosslingual (16) | 0,50 / 0,319 | 0,94 / 0,938 | 0,88 / 0,645 |
| tutte (70) | 0,49 / 0,368 | 0,89 / 0,737 | 0,73 / 0,558 |

Confronto appaiato hit@8 contro BM25: denso +28 (30 vinte, 2 perse, 0 perse su `exam`);
ibrido +17 (18 vinte, 1 persa, 0 su `exam`). Con soglia larga (voto >= 1) l'ordine non cambia:
denso 0,93, ibrido 0,81, BM25 0,63.

Gate Q per l'ibrido O1 di `qwen3-embedding:0.6b`: **passa** (+17 >= +4, 0 perdite `exam`,
MRR@10 0,558 > 0,368). Il denso da solo però è migliore su ogni aggregato.

**RRF pesata, stima offline.** Fusione di 2 liste (BM25 e denso, ciascuna già unita fra
documenti e lezioni) con peso `w` sul denso, ricostruita dai top-10 salvati: approssimazione,
perché le liste sono troncate a 10 invece dei 50 candidati della produzione. Riproducibile con
`scripts/eval_hybrid_analysis.py weighted --bm25 out/q06-bm25.json --dense out/<modello>-dense.json
--weight <w> --judgments judging`.

| w denso | r@8 tutte | MRR@10 tutte | MRR@10 exam | netto vs BM25 |
| --- | --- | --- | --- | --- |
| 1 | 0,87 | 0,581 | 0,718 | +27 |
| 2 | 0,89 | 0,652 | 0,733 | +28 |
| 3 | 0,89 | 0,650 | 0,719 | +28 |
| 5 | 0,89 | 0,640 | 0,622 | +28 |

Lettura: gran parte della perdita dell'ibrido viene dalla fusione a 4 liste, dove ogni sorgente
BM25 mette comunque un suo primo classificato in cima. Con 2 liste e peso 2 sul denso la
recall eguaglia il denso (0,89), l'MRR resta sotto (0,652 contro 0,737) tranne che sulle
domande `exam` (0,733 contro 0,581). Limiti: un solo modello misurato; le `paraphrase` sono
costruite contro BM25; le `crosslingual` usano materiale sintetico.
BASIS: measured (giudizi sul pool), inferred per la RRF pesata (ricostruzione da top-10).

## Candidati (T015)

Misurati il 2026-10-07 con la GPU libera (salvo il denso di 0.6b, calcolato il 6 con ComfyUI
attivo). Giudizi alla cieca estesi ai passaggi nuovi dei 4 candidati: altri 1083 passaggi in
`judging/batch-6..10.json`, 2648 voti in tutto, nessuno mancante. Rilevante = voto 2 oppure
riferimento del gold; 70 domande con risposta. `w2` = RRF a 2 liste (BM25 e denso, ciascuna già
unita fra documenti e lezioni) con peso 2 sul denso, ricostruita dai top-10 salvati (BASIS:
inferred, approssimazione; `scripts/eval_hybrid_analysis.py weighted`); le altre colonne sono
output dell'harness (BASIS: measured).
`embeddinggemma`: 3 passaggi (tavole numeriche di `librib_685541.pdf`) oltre il contesto di 2048
token, troncati e contati dall'harness.

| Modello | Denso r@8 / MRR | O1 4 liste r@8 / MRR | w2 r@8 / MRR | MRR exam denso | Vettori corpus | Query CPU p95 | Gate L |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 (riferimento) | 0,49 / 0,368 | | | 0,653 | | | |
| qwen3-embedding:0.6b | 0,89 / 0,737 | 0,73 / 0,558 | 0,89 / 0,652 | 0,581 | 1140 s (GPU occupata) | 0,404 s | passa |
| qwen3-embedding:4b | 0,99 / 0,849 | 0,76 / 0,559 | 0,99 / 0,749 | 0,776 | 2043 s | 1,188 s | no |
| qwen3-embedding:8b | **1,00 / 0,892** | 0,76 / 0,577 | 1,00 / 0,768 | **0,917** | 3156 s | 2,046 s | no |
| bge-m3 | 0,93 / 0,716 | 0,74 / 0,531 | 0,93 / 0,702 | 0,597 | 259 s | 0,284 s | passa |
| embeddinggemma | 0,91 / 0,742 | 0,74 / 0,541 | 0,91 / 0,652 | 0,806 | 148 s | 0,261 s | passa |

Confronto appaiato hit@8 contro BM25, denso: 0.6b +28, 4b +35, 8b +36, bge-m3 +31,
embeddinggemma +30; nessuna domanda `exam` persa da nessun denso. Gate Q dell'ibrido O1:
passa per tutti (+17..+19, 0 perdite `exam`, MRR sopra BM25).

**Percorso della query su GPU** (piano C1: il migliore per qualità fallisce solo il gate L).
5 ripetizioni con `qwen3.5:9b` residente: l'embedding della domanda su GPU scarica il 9B.

| Modello | Embedding query su GPU | Ricarica del 9B per la risposta |
| --- | --- | --- |
| qwen3-embedding:8b | 4,0-8,2 s | 7,2-8,0 s |
| qwen3-embedding:4b | 2,7-7,3 s | 7,2-13,6 s |

Il percorso GPU costa 10-20 s a domanda: per 8b e 4b la query su CPU (p95 2,0 s e 1,2 s, 9B
residente) è il percorso migliore. BASIS: measured.

Lettura: il denso da solo vince su ogni modello; il BM25 in fusione abbassa l'MRR senza
aggiungere recall su questo gold. Limiti: 42 domande su 70 (`paraphrase`, `crosslingual`) sono
costruite in modo sfavorevole al BM25; mancano domande su termini esatti (sigle, numeri di
articolo, nomi propri), dove il BM25 dovrebbe aiutare; il materiale inglese è sintetico.

## Varianti (T016)

In v1.1 resta solo la soglia minima di coseno per `qwen3-embedding:8b`. Sweep offline sulle liste
top-50 di `--system dense --k 50 --judgments` (stessi giudizi alla cieca di § Scelta, nessun nuovo
embedding): un passaggio sotto soglia è tolto prima del taglio a 8. Regola (piano C1, Dis.4 B):
perdere al massimo 1 domanda di hit@8 rispetto a nessuna soglia, minimizzando i passaggi sopra
soglia delle 11 domande `negative`. Riproducibile con `scripts/eval_hybrid_analysis.py sweep
--dense out/x8b-dense.json --judgments judging` (verificato: stessa tabella).

| Soglia | hit@8 su 82 | Perse | Passaggi `negative` sopra soglia (top-8) | Domande `negative` con almeno un passaggio |
| --- | --- | --- | --- | --- |
| nessuna | 82 | 0 | 88 | 11 |
| 0,35 | 82 | 0 | 70 | 9 |
| 0,40 | 81 | 1 | 44 | 6 |
| 0,44 | 81 | 1 | 27 | 6 |
| 0,45 | 81 | 1 | 24 | 5 |
| **0,46** | **81** | **1** | **20** | **3** |
| 0,465 | 80 | 2 | 20 | 3 |
| 0,48 | 77 | 5 | 20 | 3 |
| 0,50 | 75 | 7 | 17 | 3 |

Coseni del primo passaggio delle 11 `negative`: 0,280-0,639; dei top-8 di tutte le domande:
0,252-0,893.

**Soglia scelta: 0,46** per la regola scritta prima della misura (1 domanda persa, passaggi
`negative` da 88 a 20, domande `negative` con almeno un passaggio da 11 a 3). È sul bordo di un
gradino: a 0,465 si perde una seconda domanda, a 0,48 cinque. Con 82 domande la posizione esatta
del gradino è poco stabile; 0,44 dà margine (stessa perdita, 27 passaggi e 6 domande `negative`)
ed è il ripiego se la misura su un corso reale (F2) perde più di quanto qui previsto.
BASIS: measured su questo gold; la stabilità della soglia su altri corsi è unknown.

## Indicizzazione (T033)

Misurata il 2026-10-07 con `qwen3-embedding:8b`, Ollama 0.18, 100 passaggi del corpus di misura
(`judging/batch-1.json`), `num_ctx` 2048, `/api/ps` vuoto prima di ogni serie, un embedding di
riscaldamento escluso dal tempo. Script: `scratchpad/t033.py` (misura una tantum, [M]).

**Condizione non pulita:** il container `voicestudio` (avviato dall'utente, non legato a sbobina)
occupava 2,7 GB di VRAM; Ollama vedeva 3,8 GiB disponibili e ha caricato l'8b con 30 layer su 37
in GPU (`size_vram` 3,96 GB). I numeri sono quindi un limite inferiore.

| Batch | Tempo per 100 unità | Unità/s | Note |
| --- | --- | --- | --- |
| 32 | 117,8 s | 0,85 | include un ricaricamento del modello (log: 9/37 poi 30/37 layer) |
| 8 | 58,6 s | 1,71 | modello già caricato, 30/37 layer |

Confronto con § Candidati: 3156 s per 552 unità erano circa 0,18 unità/s, ma quel tempo
comprendeva anche le 93 query su CPU e i caricamenti alternati fra CPU e GPU dello stesso
modello (vedi sotto). Un corso da 3.000 unità a 0,85-1,7 unità/s richiede **30-60 minuti**, non
4-5 ore: la stima di R7 nel piano va rivista. Soglia di T045 (0,5 unità/s): superata, **T045 non
necessario**. Da rimisurare con la GPU libera prima di T044, insieme alla scelta del batch.

**Convivenza CPU/GPU (R12): l'istanza GPU non sopravvive.** Una query con `num_gpu=0` lanciata
3 s dopo l'inizio di un batch GPU ha aspettato la fine del batch, poi Ollama ha scaricato
l'istanza GPU e ricaricato il modello su CPU (`/api/ps` durante la query: `size_vram` 0; log:
"offloaded 0/37 layers"). La query ha impiegato 63,8 s. Ollama tiene una sola istanza per
modello. Conseguenza per T041: mentre gira un'indicizzazione la chat non deve chiedere
l'embedding della domanda, ma passare al BM25 con `reason="gpu_busy"`; altrimenti aspetta
l'intero batch e costringe a ricaricare il modello due volte. BASIS: measured.

## Cache di misura (T019)

Il 2026-10-07 restano in `data/eval/retrieval-hybrid/cache/` solo i vettori del modello scelto,
`qwen3-embedding_8b-ada0db1b.npz` (il suffisso è l'impronta del prompt dei documenti). Rimosse le
cache di 0.6b, 4b, bge-m3 ed embeddinggemma, insieme ai modelli in Ollama: rimisurarli richiede
di riscaricarli e ricalcolare i vettori.

## Scelta (T018)

**Modello** (decisione dell'utente, 2026-10-07, "D1a"): `qwen3-embedding:8b`, embedding della
query su CPU (`num_gpu=0`), istruzione Qwen sulla query, documenti senza prefisso. Il gate L
(p95 <= 1,0 s) non è soddisfatto (p95 2,05 s): l'utente accetta circa 2 s in più a domanda in
cambio della qualità massima. Il 9B resta residente su questo percorso; il percorso GPU costa
10-20 s a domanda ed è scartato.

**Fusione** (decisione dell'utente, "D2a"): prima si aggiungono 12 domande `exact` (termini
letterali rari: articoli, sigle, nomi propri, cifre) e si confronta il denso da solo con la RRF a
2 liste pesata 2:1, ricostruita da liste top-50. Se la pesata vince sulle `exact` senza perdere
sul resto, resta l'ibrido pesato; altrimenti denso da solo con BM25 come fallback quando il
modello manca.

Esito (2026-10-07): 12 domande `exact` aggiunte (`check_gold.py`: 93 domande, 0 errori), BM25 e
`qwen3-embedding:8b` rieseguiti con top-50 (`out/x8b-*.json`), pesata ricostruita da quelle liste
(`scripts/eval_hybrid_analysis.py weighted`, verificato: stessa tabella),
209 passaggi nuovi giudicati alla cieca (`judging/batch-11..12.json`, nessun voto mancante).

| Tipo (n) | BM25 r@8 / MRR | Denso 8b r@8 / MRR | Pesata 2:1 r@8 / MRR |
| --- | --- | --- | --- |
| exact (12) | 1,00 / 0,892 | 1,00 / 1,000 | 1,00 / 1,000 |
| exam (12) | 0,83 / 0,653 | 1,00 / 0,917 | 1,00 / 0,861 |
| paraphrase (26) | 0,04 / 0,027 | 1,00 / 0,776 | 0,65 / 0,299 |
| lecture (16) | 0,94 / 0,757 | 1,00 / 0,953 | 1,00 / 0,969 |
| crosslingual (16) | 0,50 / 0,319 | 1,00 / 1,000 | 0,94 / 0,708 |
| tutte (82) | 0,56 / 0,445 | 1,00 / 0,908 | 0,88 / 0,694 |

La pesata pareggia sulle `exact` e perde sul resto: con liste da 50 il BM25 porta più rumore che
con liste da 10. Per la regola D2a la fusione è scartata.

SPEDITO: iter 5/5 candidati + 1 variante di fusione - `qwen3-embedding:8b`, query su CPU con
istruzione Qwen, ricerca solo densa, BM25 come fallback quando il modello manca o Ollama non
risponde. Gate L non rispettato per scelta dell'utente (p95 2,05 s). BASIS: measured, tranne la
pesata (inferred, ricostruzione offline).

## Produzione (T032)

### Gold set attraverso il codice di produzione (2026-10-07)

`scripts/eval_hybrid.py --system production --index --k 50 --judgments judging`: il corpus di
misura viene indicizzato da `vector_reconcile.embed_course` in un `vectors.sqlite3` dedicato e ogni
domanda passa da `course_retrieval.retrieve_windows_with_report` con il `DenseRanker` di
produzione (soglia 0,46, query su CPU). Indicizzazione: 552 unità in 270 s (1,95-2,64 unità/s, GPU
meno contesa che in T033). 93 domande su 93 con `mode=dense`, nessun ripiego sul BM25.

| Tipo (n) | Harness § Scelta r@8 / MRR | Produzione r@8 / MRR |
| --- | --- | --- |
| exam (12) | 1,00 / 0,917 | 1,00 / 0,917 |
| paraphrase (26) | 1,00 / 0,776 | 0,96 / 0,769 |
| lecture (16) | 1,00 / 0,953 | 1,00 / 0,841 |
| crosslingual (16) | 1,00 / 1,000 | 1,00 / 1,000 |
| exact (12) | 1,00 / 1,000 | 1,00 / 0,944 |

Recall entro ±1 domanda dalla verifica del piano. Divergenze spiegate:

- `eco-par-01` senza risultati: tutti i candidati del corso stanno sotto la soglia 0,46, che la
  produzione applica e l'harness di § Scelta no. È la domanda che lo sweep di § Varianti dava già
  per persa a 0,46. BASIS: measured.
- MRR più basso su `lecture` ed `exact` (`dir-lec-08`, `dir-lec-11`, `dir-ex-01` a rank 3-5): il
  corpus di misura contiene la stessa registrazione in due job (§ Corpus), e la produzione restituisce
  entrambe le copie delle finestre, che occupano le prime posizioni. Su un corso senza registrazioni
  duplicate l'effetto non dovrebbe esistere. BASIS: inferred (top-5 osservati, corso senza duplicati
  non misurato).

Restano da misurare in T032 i turni di chat reali (10 col 9B residente, 10 con una generazione in
corso) e la latenza della query in quelle condizioni.

### Turni di chat reali e latenza della query (2026-10-07)

App avviata sul corpus di misura (`SBOBINA_DATA_DIR=data/eval/retrieval-hybrid/corpus`, motore
`local`, porta 8799), corso "economia aziendale" indicizzato al 100% (458 unità, 3 troncate).
10 turni consecutivi: 10 risposte 200, tutte `mode=dense`, `qwen3.5:9b` residente per tutta la
serie (`size_vram` 6 445 453 312 invariata) con `qwen3-embedding:8b` su CPU (`size_vram` 0). Durata
di un turno 6,8-27,2 s. 7 turni `DONE`, 3 `NOT_FOUND` (vedi F21 sotto). BASIS: measured.

Latenza dell'embedding della domanda su CPU, 10 campioni per riga, macchina con carico medio mai
sotto 11 su 16 thread durante la misura (lavoro in background non legato a sbobina): numeri
rumorosi.

| `num_thread` | 9B fermo p50 / p95 | 9B che genera p50 / p95 |
| --- | --- | --- |
| automatico | 2,34 / 2,49 s | 3,55 / 4,11 s |
| 4 | 2,66 / 2,76 s | 3,88 / 4,27 s |
| 8 | 2,25 / 2,30 s | 3,29 / 3,33 s |
| 12 | 2,18 / 2,60 s | 3,26 / 4,17 s |

Una serie precedente nella stessa sessione, a carico più alto, dava p95 2,98 s a 9B fermo e
8,69 s a 9B che genera.

Lettura: col 9B fermo la soglia di T032 (p95 <= 2,5 s) regge appena; mentre il 9B genera non
regge con nessun valore di `num_thread` (3,3-4,3 s). La differenza fra 8 thread e l'automatico non
si separa dal rumore con una serie per valore: `num_thread` resta automatico (performance.md,
"neutro è un revert"). La scelta di accettare 3-4 s di query a 9B occupato torna all'utente.
BASIS: measured, rumore alto.

**F21, tre `NOT_FOUND` nei turni reali: non è la ricerca.** Rieseguita la ricerca di produzione sulle
tre domande: per "principi di redazione del bilancio" arrivano in cima le pagine 41-42 del
riassunto (rappresentazione veritiera e corretta, principi elencati); per "soggetto economico e
soggetto giuridico" il capitolo inglese p. 5 ("The economic subject and the legal subject"); per
"budget operativo" il capitolo inglese p. 9 ("Budgeting as a planning and control tool"). Il
`NOT_FOUND` nasce nella fase di risposta (`chat_pipeline`, frasi citate alla lettera): per le due
domande con risposta solo in inglese l'ipotesi è che la citazione letterale di un passaggio inglese
in una risposta italiana non superi la validazione. Fuori dal perimetro di 004; da trattare a parte.
BASIS: measured per la ricerca, inferred per la causa nella fase di risposta.

**Decisione dell'utente (2026-10-07, "D6"):** si resta su `qwen3-embedding:8b`; si accettano
3-4 s di embedding della domanda (p95) quando il 9B sta generando. Il tetto di T032 (2,5 s) vale
quindi solo col 9B fermo; a 9B occupato il riferimento è la misura sopra.

## Prova reale su `data/` (T044, 2026-10-08)

Condizioni: RTX 4060 8 GB senza altri processi GPU all'avvio (`/api/ps` vuoto, 15 MiB usati),
`qwen3-embedding:8b` installato, `vectors.sqlite3` assente (indice da zero), `sbobina web` sulla
porta 8765, campioni `nvidia-smi` ogni 2 s (100 campioni, 01:11:46-01:15:06). Per "lezione e PDF
nuovi" si è usato un corso separato, "Prova T044", così il corso Diritto ha ricevuto solo il
backfill: uno spezzone di 5 minuti di un audio già presente (ffmpeg, da 600 s) e il riassunto
di Economia aziendale da `data/prove/`.

| Passo | Ora | Esito |
|---|---|---|
| `sbobina indicizza-semantico --backfill` | prima dell'avvio (non registrato) | "1 corso in coda" (Diritto, mai indicizzato) |
| Avvio di `sbobina web` | 01:11:44 | azione `embed` ripresa dal disco e avviata |
| Lezione nuova accodata (corso "Prova T044") | 01:11:48 | `queued` dietro l'indicizzazione |
| Chat su Diritto durante l'indicizzazione | 01:11:55 | `GPU_BUSY`, stage `embedding`, stima 57 s |
| Indicizzazione Diritto finita | 01:12:23 | 97/97, 0 troncati |
| Trascrizione della lezione nuova | 01:12:23-01:12:50 | partita 35 s dopo l'accodamento, alla fine dell'indicizzazione |
| Indicizzazione automatica "Prova T044" | 01:12:52 | 3/3, senza comandi |
| PDF caricato in "Prova T044" | 01:13:57 | estrazione `READY`, poi azione `embed` automatica |
| Indicizzazione dopo il PDF | 01:14:33 | 85/85, 0 troncati |
| Chat su Diritto a indice completo | dopo 01:14:33 | `DONE`, `retrieval_mode` denso, copertura 97/97, 24 s il turno intero |

Tempi: Diritto 97 unità in 38 s dall'avvio del figlio (2,6 unità/s), di cui circa 15 s per caricare
il modello sulla GPU (primo `/api/embed` alle 01:12:00); a modello caricato i tre batch sono
durati 9-11 s ciascuno. "Prova T044" 85 unità in 36 s dal caricamento del PDF, estrazione
compresa. `vectors.sqlite3`: 1,7 MB dopo Diritto, 3,1 MB dopo i due corsi (182 unità, 4096
dimensioni float32).

GPU: campioni con più di un processo GPU = 0 su 100. La sequenza osservata è Ollama
(embedding, 5,1 GB) fino alle 01:12:20, nessun processo alle 01:12:21, il figlio di trascrizione
(Whisper, 4,1 GB) dalle 01:12:23 alle 01:12:50, di nuovo Ollama dalle 01:12:52.

Lettura: il lease GPU serializza indicizzazione e trascrizione come previsto; la chat durante
l'indicizzazione risponde `GPU_BUSY` invece di contendere la VRAM; la copertura arriva al 100%
su lezione e PDF nuovi senza comandi manuali. Il backfill da CLI serve un riavvio di `sbobina web`
se è già aperto (le azioni accodate si riprendono all'avvio). BASIS: measured.

Il corso "Prova T044" (lezione e PDF) e la chat di prova su Diritto restano in `data/`: si
cancellano dall'interfaccia.

## Click-through Impostazioni e pagina corso (T052, T053, 2026-10-08)

Istanza isolata: `sbobina web` sulla porta 8799 con `SBOBINA_DATA_DIR` su una copia di `data/`
(corsi, job, `vectors.sqlite3`, `search.sqlite3`) e `XDG_CONFIG_HOME` su una cartella temporanea,
così preferenze e dati reali non sono toccati. Browser: Chromium headless 1243 via Playwright.

| Controllo | Esito osservato |
|---|---|
| Apertura della sezione "Ricerca semantica" | scheletro, poi corpo; console senza errori |
| Interruttore ricerca semantica | `true -> false`, letto di ritorno dall'API di stato |
| Select del modello | `qwen3-embedding:8b (consigliato)`, unico modello di embedding installato |
| Copertura per corso | `Diritto · 97/97`; `Prova T044 · 88/88, 3 da indicizzare` dopo un PDF caricato a ricerca spenta |
| "Indicizza ora" con la durata prima del click | etichetta "Indicizza ora (meno di un minuto)", solo sui corsi con unità mancanti |
| Click su "Indicizza ora" | bottone disabilitato subito; un secondo invio sullo stesso corso → HTTP 409; corso a 88/88 dopo l'indicizzazione |
| Modello impostato a `bge-m3` (non installato) | box con `ollama pull bge-m3`; "Copia" mette il comando negli appunti e mostra la conferma |
| Pagina corso con modello assente | "Solo parole chiave: modello di embedding non installato" |
| Cambio modello in sospeso (vettore di un modello precedente) | banner "L'indice usa ancora il modello precedente"; "Ricostruisci" apre il dialog; Escape lo chiude col focus di ritorno sul bottone; "Annulla" lo chiude; "Conferma" → HTTP 202 |
| Pagina corso a ricerca spenta | "Solo parole chiave: ricerca semantica spenta nelle Impostazioni" |
| Pagina corso con cambio modello in sospeso e corso completo | "Ricerca per significato", coerente con la ricerca reale |
| Risposta salvata in chat (turno denso di T044) | riga "Ricerca per significato" sotto la risposta |

Render: Impostazioni e pagina corso a 375 e 1280 px senza overflow orizzontale (screenshot
guardati). `a11y-gate`: axe pulito in chiaro e in scuro su entrambe le pagine, responsive pulito.
Il gate degli stati risulta rosso su tutti i 105 stati, nav preesistente compresa, con rapporti
~1,0:1: legge i colori calcolati `oklch()` come componenti rgb (VERDETTO: strumento). Misura
sostitutiva, colori convertiti in sRGB via canvas nel browser: sezione nuova 0 fallimenti su 33
stati (default, hover, focus) in chiaro e in scuro; riga di stato del corso 5,83:1 in chiaro e
7,15:1 in scuro. Le due "violazioni" dei timestamp della lista chat in hover e focus in scuro
(4,35:1) erano un artefatto della misura: il campione prendeva una data già tornata a riposo
contro lo sfondo di un hover ancora in dissolvenza (alpha 0,017). Rimisurato con transizioni e
animazioni spente: 0 fallimenti su 283-286 stati in chiaro e in scuro, senza modifiche al CSS.

Corretti dopo il click-through: "Indicizza ora" mostrato anche sui corsi completi; conteggio x/y
che non vedeva il testo aggiunto dopo l'ultimo run; la pagina corso mostrava "indice da
ricostruire" col cambio modello in sospeso anche quando la ricerca usa i vettori; frase di
`rebuild_needed` (vale "indice ricreato dopo un errore", non "cambio di modello"). BASIS: measured.

Gate aggiuntivi di `a11y-gate`: RTL pulito su Impostazioni e pagina corso (0 px di overflow in
LTR e RTL). `verify_focustrap` sul dialog di ricostruzione (harness dal DOM renderizzato, apertura
con `showModal` come nell'app) risulta rosso: `role`/`aria-modal` espliciti assenti e "focus uscito
dopo 2 Tab". Percorso del focus osservato: Annulla → Conferma → fuori dal documento → Annulla; il
dialog è `:modal` (ruolo e modalità impliciti) e il contenuto dietro resta inerte, mai raggiunto.
È il comportamento del `<dialog>` modale nativo, lo stesso dei cinque dialog già nel progetto
(VERDETTO: strumento).

Copertura parziale (`/analyze` A1): nella copia isolata un'unità in più nel manifest di Diritto
porta la copertura a 97/98. Pagina corso: "Solo parole chiave: indicizzazione incompleta
(97/98)"; una domanda in chat sullo stesso corso risponde `DONE` con `retrieval_mode` `bm25`,
motivo `partial`, copertura 97/98. Pagina e ricerca coincidono. BASIS: measured.

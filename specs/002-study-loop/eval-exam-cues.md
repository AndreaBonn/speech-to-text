# T015 - Misura V7 del rilevatore di frasi da esame (2026-10-05)

Rilevatore `exam_cues.py` con i pattern v1 (`STRONG_PATTERNS_V1`, `WEAK_PATTERNS_V1`,
`NEGATIVE_PATTERNS_V1`), sulle trascrizioni corrette di 2 lezioni reali di Diritto
(`82144973`, `8319d0b3`) più la ritrascrizione dello stesso audio della prima (`7aef7b66`, senza
correzione) per la stabilità. Comando:

```
uv run python scripts/eval_exam_cues.py data/eval/exam-cues-gold-1791133948107899008.jsonl \
  --job-dirs data/jobs/82144973-… data/jobs/8319d0b3-… data/jobs/7aef7b66-… \
  --duplicate-pair 82144973-… 7aef7b66-…
```

Il gold set resta in `data/eval/` (contiene testo delle lezioni, non versionato).

**Etichette di Claude, non dello studente.** Il 2026-10-05 l'utente ha delegato a Claude la
preparazione dei dataset (U5). Ogni candidato è stato letto con il segmento precedente e il
successivo, e per i casi dubbi con una finestra di 12 segmenti, applicando le definizioni di C1:
`strong` se il docente nomina l'esame o chiede esplicitamente di ricordare, `weak` se segnala
importanza senza riferimento all'esame, `none` altrimenti.

Soglia scritta prima dei numeri (plan.md C1): precisione `strong` ≥ 0,80.
`BUDGET: 1 misura, nessuna modifica ai pattern dentro T015`

## Risultati

| | Totale | 82144973 | 8319d0b3 |
|---|---|---|---|
| Candidati etichettati | 76 (29 rilevatore, 47 rete larga) | 32 | 44 |
| Etichette strong / weak / none | 7 / 15 / 54 | 3 / 5 / 24 | 4 / 10 / 30 |
| Precisione `strong` | **1,00 (5/5)** | 1,00 (2/2) | 1,00 (3/3) |
| Precisione `weak` | 0,63 (15/24) | 0,45 (5/11) | 0,77 (10/13) |
| Recall stimato sulla rete larga | 0,91 (20/22) | 0,88 (7/8) | 0,93 (13/14) |

Il recall è calcolato solo sui candidati della rete larga lessicale (`WIDE_NET_KEYWORDS` in
`scripts/exam_cues_gold.py`: esame, chieder, ricorda, importante, fondamentale, attenzione,
domanda): un segnale che non contiene nessuna di quelle parole, come "segnatevelo", non entra nel
denominatore, quindi è una stima per eccesso. Il recall non guarda il livello: un segnale trovato
come `weak` ma etichettato `strong` conta come trovato.

Stabilità (cue `strong` delle due trascrizioni dello stesso audio): Jaccard 100%, 2 cue in comune,
nessuno esclusivo. Le due trascrizioni non sono identiche (una corretta dal LLM, l'altra no), quindi
la prova copre anche la variazione introdotta dalla correzione, ma solo su 2 cue.

Latenza di `find_exam_cues`, una chiamata per lezione senza riscaldamento: 2,7 / 3,3 / 2,7 ms
(totale 8,8 ms per tre lezioni).

Latenza della rotta `GET /api/v1/courses/diritto/exam-cues?level=all` (criterio di C1: < 500 ms a
cache fredda per 3 lezioni da 25k parole), prima richiesta in un processo nuovo, con le pagine dei
file di `data/jobs` e `data/courses` tolte dalla cache del sistema con `posix_fadvise(DONTNEED)`.
Lo svuotamento è verificato con `mincore`: una trascrizione passa da 284/284 a 0/284 pagine.

| Corso | Parole | Cue | Freddo, prima richiesta |
|---|---|---|---|
| Diritto reale (4 job; completati: 2) | 7.592 + 9.079 nei completati | 44 | 109-201 ms (6 esecuzioni) |
| Sintetico, 3 lezioni | 3 × 25.000 | 2.919 | 266-292 ms (3 esecuzioni) |

Il caso sintetico ha un cue in ogni frase, quindi è un limite superiore del lavoro sui cue. A caldo
il corso reale dà 97-132 ms: il costo è CPU (lettura del JSON e rilevamento), non disco. La
forbice sul corso reale viene da due sessioni diverse; la più lenta girava col disco quasi pieno.
Esito: criterio rispettato. BASIS: measured.

## Errori osservati

Segnali persi (2, entrambi `strong`):

- "ricordatevelo sempre, perché torneranno miliardi di volte" (8319d0b3, 42:03). Il pattern
  `ricordatevi` è a parola intera e non copre la forma con il pronome attaccato
  (`ricordatevelo`, `ricordatevele`).
- "la classica domanda è" (82144973, 25:22), il seguito di "e all'esame". Il rilevatore prende
  il segmento precedente, che contiene solo le due parole "e all'esame": la frase da ricordare
  sta nel segmento dopo. Il cue è trovato, ma la citazione mostrata allo studente non contiene il
  contenuto d'esame.

Falsi positivi `weak` (9 su 24): "attenzione" come trascrizione sbagliata di "azione" (2),
"all'attenzione del giudice" in senso proprio (2), "importante" detto della materia nell'introduzione
o in un esempio narrativo (3), "l'attenzione si è calata" sulla classe (1), "di attenzione" nella
presentazione del programma (1).

## Esito

`SPEDITO: iter 1/1 - pattern v1 invariati.` V7 **superata sulla soglia dichiarata**: precisione
`strong` 1,00 contro 0,80.

Limiti da tenere presenti prima di rendere i cue vistosi nel Lettore:

- 5 rilevazioni `strong` sono poche: con 5/5 l'intervallo di Wilson al 95% parte da 0,57. Un solo
  falso positivo in più porterebbe la precisione a 0,83.
- Etichette di Claude: la misura vale come provvisoria, nello stesso senso di V6. Un "sì"
  dell'utente su questi 7 `strong` la rende definitiva.
- La precisione `weak` (0,63) giustifica che i segnali deboli restino dietro l'interruttore,
  come oggi.

BASIS: measured su precisione, stabilità e latenza; inferred sul recall (rete larga non esaustiva).

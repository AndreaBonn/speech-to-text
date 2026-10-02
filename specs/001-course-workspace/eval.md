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

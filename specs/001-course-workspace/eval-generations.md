# T036 - Misura reale delle generazioni (2026-10-03)

Corso reale "economia aziendale" (6 PDF dell'utente: manuale scansionato da 246 pagine, slide
sulla crescita, esercitazione, riassunto, mappa concettuale, domande d'esame con risposte) e
"diritto" (una lezione reale da 70 minuti). Server di misura con dati copiati fuori da `data/`,
`qwen3.5:9b` via Ollama 0.18, `num_ctx` 8192, GPU RTX 4060 8 GB. Script di misura nella
scratchpad di sessione: invia le 5 richieste in coda, campiona `nvidia-smi` ogni 2 s, salva i
record. Token per chiamata dal log del processo figlio (`ollama_chat._log_usage`, commit
`def257f`). Revisione a mano: Claude, contro il materiale citato.

`BUDGET: 4 iterazioni del prompt | ranking: domande sbagliate (meno) > soluzioni sbagliate
(meno) > domande scartate (meno) > durata`

## Esiti per iterazione

| Richiesta | Iter 1 | Iter 2 | Iter 3 |
|---|---|---|---|
| Crocette, 10, argomento vuoto | 0 domande in 3 s: **B1**, nessun passaggio | fallita: troncata a 1756 token (**R1**) | 9 tenute, 84 s |
| Aperte, 10, "crescita economica" | 7 tenute, 60 s | 5 tenute, 51 s | 5 tenute, 54 s |
| Orale, 10, "impresa e azienda" | 5 tenute, 114 s | 8 tenute, 78 s | 9 tenute, 75 s |
| Riassunto, "il sistema aziendale" | fallito: troncato a 556 token (**B3**) | fallito: manca la `}` finale (**R2**) | 3 frasi, 36 s |
| Riassunto, lezione, argomento vuoto | vuoto in 0 s: **B1** | 6 frasi al 2° tentativo (1° troncato a 2048) | 6 frasi, 33 s |

Massimo `prompt_eval_count`: 5720 (iter 1), 4973 (iter 2), 4099 (iter 3). Picco VRAM: 6311 MiB
su 8188 in tutte le iterazioni. `num_ctx` 16384 non provato: nessuna richiesta ha superato 6000
token di ingresso, e R2 di `plan.md` non lo chiede.

## Revisione a mano

| Generazione | Tenute | Domanda giusta | Fuori tema | Rimando al materiale | Soluzione sbagliata o ambigua |
|---|---|---|---|---|---|
| Aperte iter 1 | 7 | 5 | 6 | 2 ("domanda teorica Q1/Q2") | 2 ambigue |
| Aperte iter 3 | 5 | 5 | 3 | 1 ("nella mappa concettuale") | 0 |
| Orale iter 1 | 5 | 5 | 0 | 0 | 1 ambigua (aggiunta non citata) |
| Orale iter 3 | 9 | 9 | 0 | 1 ("secondo la mappa concettuale") | 1 ambigua ("massimizzare l'utilità") |
| Crocette iter 3 | 9 | 9 | n/a | 0 | 1 ambigua (citazione che non regge "obiettivi di profitto") |
| Riassunti iter 3 | 9 frasi | 9 | 0 | 0 | 0 |

Crocette iter 3: distrattori plausibili e sbagliati secondo il materiale; due coppie di domande
sullo stesso concetto (attività economica; fine dell'impresa e dell'azienda). Il campionamento
porta passaggi da tutti e 6 i documenti (12 passaggi, 1250 parole su 1254 di budget), ma il
modello scrive solo da riassunto, mappa e domande d'esame, che contengono definizioni pronte.

## Tentativi

| Tentativo | Baseline → Risultato | Verdetto | Perché |
|---|---|---|---|
| B1: campionamento distribuito con argomento vuoto | 0 → 9 crocette | tenuto (`95e7f25`) | era un difetto: query vuota, nessun passaggio |
| B2: fonti scelte salvate e applicate | ignorate → applicate | tenuto (`95e7f25`) | era un difetto, non osservabile in questa misura (nessuna fonte scelta) |
| B3 + R1: `num_predict` dalle misure | 2 troncamenti → 0 | tenuto (`3bf6828`) | 150 token per crocetta e 2048 per riassunto non bastavano; massimo 10 domande, sopra il materiale scende sotto 1000 parole |
| R2: chiusura delle parentesi dimenticate | 1 riassunto perso → 0 | tenuto (`2166972`) | Ollama ignora lo schema con `think=False`; mai applicata a risposte troncate |
| Prompt `compito-v2`: argomento e domande autonome | aperte: 6/7 → 3/5 fuori tema; rimandi 2 → 1 | tenuto (`3aba677`) | migliora, non risolve: vedi limite aperto |
| Iter 4 del prompt | - | non spesa | il residuo fuori tema viene dal recupero, non dal prompt |

SPEDITO: iter 3/4 - `compito-v2` + `riassunto-v1`, B1-B3 e R1-R2 corretti. Iterazione 4 non
spesa perché la causa residua è misurata altrove.

## Limite aperto: argomenti con parole comuni

La domanda su "crescita economica" recupera 7 passaggi, di cui solo 2 (le slide) trattano la
crescita: la query è `"crescit"* OR "economic"*` e in un corso di economia "economic*" compare in
66 passaggi; con AND resta un solo passaggio. Il modello riceve materiale in tema per 2 domande
e riempie le altre con i passaggi fuori tema, nonostante il prompt chieda meno domande. Strade
possibili, non provate: ordinare i candidati dando precedenza a chi contiene il termine più raro;
scartare le domande la cui citazione non contiene nessun termine dell'argomento tranne quelli
presenti in quasi tutto il corso. Entrambe toccano il recupero condiviso con chat e ricerca e
vanno rimisurate con `scripts/eval_retrieval.py` (T024) prima di tenerle.

## T039 - Gate F3 (2026-10-03)

Server di misura, clip di 5 minuti della lezione reale. In coda, nell'ordine: trascrizione,
generazione (aperte, 5, "avviamento"), trascrizione. `nvidia-smi --query-compute-apps`
campionato ogni 2 s (più fitto dei 15 s richiesti).

| t | Processi sulla GPU |
|---|---|
| 2-28 s | figlio Python di Whisper |
| 30-69 s | ollama |
| 69-93 s | figlio Python di Whisper; Ollama scaricato da `gpu_release` prima dello stage |

48 campioni, **0 con più di un processo**. Tre job `done`. Suite 1400 test, ruff, format e mypy
verdi; nessun file nuovo sopra 300 righe dopo `a74c19f`. Export DOCX di compito e soluzioni
coperto dai test API (`test_download_compito_docx_never_contains_solution_text`).

Durante il gate una richiesta da 11 domande è stata accettata: il server di misura era partito
prima di `3bf6828` e il processo padre teneva in memoria il vecchio massimo (20). Annullata prima
che partisse; il codice corrente la rifiuta con 422 (`test_generation_request_rejects_out_of_range_count`).

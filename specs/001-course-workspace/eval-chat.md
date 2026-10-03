# T046 - Misura reale della chat (2026-10-03)

Corso reale "economia aziendale" (6 PDF dell'utente), dati copiati fuori da `data/`,
`qwen3.5:9b` via Ollama 0.18, `num_ctx` 8192, RTX 4060 8 GB. Le domande passano dallo stesso
codice della route (`chat_turn.ask`: salvataggio, recupero, chiamata guardata dall'arbitro GPU,
validazione), ciascuna in una conversazione nuova; la prima a modello scaricato. Token dal log di
`ollama_chat`. Revisione a mano: Claude, contro i passaggi citati.

`BUDGET: 3 iterazioni del prompt | ranking: risposte sbagliate (meno) > fuori-materiale non
riconosciute (meno) > latenza`

## Risultati

| Domanda | Iter 1 | Iter 2 |
|---|---|---|
| Che cos'è l'avviamento? | parziale (definizione persa, C1) | corretta |
| Chi è l'imprenditore secondo il codice civile? | corretta | corretta |
| Quali sono i caratteri del fenomeno aziendale? | corretta | corretta |
| Qual è la differenza tra impresa e azienda? | **non trovata** (C2) | corretta |
| Che cosa rappresentano le ammortizzazioni? | corretta | corretta |
| Che cos'è l'utilità in economia? | corretta | corretta |
| Quali attività sono soggette all'obbligo di registrazione? | corretta | corretta |
| Che cos'è lo stato stazionario nel modello di crescita? (slide) | corretta | corretta |
| Chi ha vinto i mondiali del 2006? (fuori materiale) | riconosciuta | riconosciuta |
| Qual è la capitale dell'Australia? (fuori materiale) | riconosciuta | riconosciuta |
| Mondiali dopo una domanda sull'avviamento, stessa conversazione | **risposta sull'avviamento** (C3) | riconosciuta |

| | Iter 1 | Iter 2 |
|---|---|---|
| Latenza a freddo | 13,9 s | 15,8 s |
| Latenza a caldo p50 / massima | 14,2 / 25,5 s | 10,1 / 17,4 s |
| `prompt_eval_count` massimo | 5575 | 5552 |

p50 a caldo sotto i 30 s: la risposta in streaming non serve, nessuna decisione da portare
all'utente.

## Cause e correzioni

| Tentativo | Baseline → Risultato | Verdetto | Perché |
|---|---|---|---|
| C1: una citazione inventata scarta solo sé stessa | definizione persa → tenuta | tenuto (`5714a4e`) | la frase giusta aveva una citazione vera e una inventata; la regola "una sbagliata annulla la voce" perdeva contenuto corretto senza aggiungere garanzie |
| C2: citazione verbatim attribuita al passaggio che la contiene | "impresa e azienda" non trovata → corretta | tenuto (`cbd2e2c`) | il modello copiava la frase giusta sotto l'etichetta di un altro passaggio |
| C3: prompt `chat-v2` (ogni frase risponde alla nuova domanda; cambio d'argomento senza materiale → vuoto) | seguito fuori materiale con risposta → riconosciuto | tenuto (`2c83e61`) | gli scambi precedenti trascinavano il modello sull'argomento vecchio, con citazioni vere ma estranee |
| Iter 3 del prompt | - | non spesa | ranking già saturo sulle prime due voci |

SPEDITO: iter 2/3 - `chat-v2` con C1 e C2.

## Limite aperto

La validazione controlla che una citazione esista nel materiale, non che sostenga la frase: C3
era una frase sull'avviamento "citata" con un passaggio sugli ammortamenti. Il prompt v2 copre il
caso misurato; un controllo automatico di pertinenza (sovrapposizione di termini fra frase e
citazione) non è stato provato.

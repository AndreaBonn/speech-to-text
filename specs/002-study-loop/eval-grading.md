# T050 - Misura V5 e V6 del giudice delle risposte (2026-10-05)

Giudice `grading.grade` con il prompt `valutazione-v1.md`, `qwen3.5:9b` via Ollama 0.18,
`temperature` 0, `num_ctx` 8192, RTX 4060 8 GB. Stessa chiamata del server (`chat_json`).
Lo script chiama `grade()` direttamente, senza la rotta HTTP né l'arbitro della GPU.

**Dati di Claude, non dello studente.** Il 2026-10-05 l'utente ha delegato a Claude i dataset di
valutazione (U5). Le 10 domande sono state generate dal corso reale di Diritto (2 lezioni e il PDF
del modulo TFR), con la pipeline di produzione su una copia dei dati fuori da `data/`. Le 30 risposte
e il verdetto atteso di ciascuna sono di Claude: per domanda una corretta, una parziale e una
errata. Le parziali sono di due tipi: metà del contenuto (7) oppure contenuto giusto con un errore
(3).

Soglie scritte prima dei numeri (adr.md D3, plan.md C3): accordo ≥ 80% per esecuzione, al massimo
1 risposta errata giudicata corretta su 30 per esecuzione.
`BUDGET: 1 misura, nessuna modifica al prompt | ranking: accordo > errate giudicate corrette >
stabilità > latenza`

## Domande

| ID | Formato | Domanda |
|---|---|---|
| D1 | aperta | Condizioni del conferimento parziale del TFR (iscritti prima del 29/4/1993) |
| D2 | aperta | Natura giuridica del possesso |
| D3 | aperta | Tutela del possessore di malafede |
| D4 | aperta | Opzioni del modulo TFR per chi è iscritto prima del 1993 |
| D5 | aperta | Obbligazione naturale nel caso della Saras |
| D6 | orale | Conseguenza del modulo TFR non consegnato entro sei mesi |
| D7 | orale | Misura minima della quota di TFR conferita |
| D8 | orale | Le due azioni possessorie |
| D9 | orale | Caratteristiche dello spoglio per la reintegrazione |
| D10 | orale | Cosa deve provare il possessore spogliato |

Per arrivare a 5 orali sono servite 5 generazioni. Due generazioni orali con argomento
("presunzioni legali e onere della prova") sono fallite al limite di token in uscita (F40).

## Risultati su GPU (3 esecuzioni)

| | Esecuzione 1 | Esecuzione 2 | Esecuzione 3 |
|---|---|---|---|
| Accordo | **25/30 (83%)** | 25/30 (83%) | 25/30 (83%) |
| Errate giudicate corrette | 0 | 0 | 0 |
| Giudizi falliti | 0 | 0 | 0 |

Verdetti instabili fra le esecuzioni: nessuno, i 30 verdetti sono identici nei tre giri.

Matrice di confusione, somma dei tre giri (righe = atteso, colonne = giudice):

| Atteso | corretta | parziale | errata |
|---|---|---|---|
| corretta | 30 | 0 | 0 |
| parziale | 9 | 15 | 6 |
| errata | 0 | 0 | 30 |

Tutti i disaccordi sono sulle parziali, per esecuzione:

- metà del contenuto: 4 su 7 giudicate parziali, 3 giudicate corrette (D1, D3, D4)
- contenuto con un errore: 1 su 3 giudicata parziale (D2), 2 giudicate errate (D5, D7)

Il giudice non premia mai una risposta sbagliata e non boccia mai una risposta giusta. Sbaglia nel
mezzo: una risposta incompleta può prendere "corretta", una con un errore grave può prendere
"errata". Il secondo caso è difendibile (D7 dice 30% invece di 50%, D5 dice che il debito
naturale è esigibile in giudizio, cioè il contrario della definizione).

Tutte e 10 le soluzioni generate hanno un solo punto: le aperte sono una frase, le orali non usano
il separatore " | " della traccia (F41). Il giudice segnala una risposta incompleta come parziale
solo citando una parte del punto come coperta e un'altra come mancante; nei tre casi giudicati
corretti ha citato il punto intero come coperto.

Latenza su GPU, 90 giudizi: p50 8,3 s, max 21,5 s, primo giudizio a modello già caricato 7,6 s.

## CPU

Non misurata. Con `num_gpu: 0` Ollama rifiuta di caricare il modello: `model requires more
system memory (8.0 GiB) than is available (6.2 GiB)`. Su un PC senza GPU il giudice richiede
almeno 8 GB di RAM libera solo per il modello, oltre al resto. La modalità di default su CPU resta
l'autovalutazione (adr.md D3).

## Esito

`SPEDITO: iter 1/1 - prompt valutazione-v1 invariato.`

- **V6 superata sulla soglia, provvisoria**: 83% di accordo in tutte e tre le esecuzioni, zero
  errate giudicate corrette. Le etichette sono di Claude: il passaggio da "Suggerimento" a esito
  mostrato come voto (U2) aspetta il sì dell'utente su questi numeri, e il codice non cambia.
- **V5 su GPU misurata** (p50 8,3 s), **su CPU non misurabile** su questa macchina.
- Il punto debole è la risposta incompleta giudicata corretta (3 su 7). Se diventa voto, una
  risposta a metà può prendere il punteggio pieno.

BASIS: measured su accordo, matrice, stabilità e latenza GPU; unknown sulla latenza CPU.

## Correzione di F41 (2026-10-05)

Tutte le soluzioni generate hanno un punto solo. Due iterazioni del prompt `compito` (v3: regola
con il motivo ed esempi a più frasi e a punti " | ") non hanno cambiato niente: 0 soluzioni su 9
con più di un punto, contro 0 su 10 con v2. v3 non è stato spedito. Nel codice, una traccia orale
scritta in prosa ora viene divisa per frasi (`solution_points.py`).

La causa lato giudice: `valutazione-v1` chiedeva di copiare ogni punto "per intero" e di metterlo
in un solo elenco, quindi vietava di dividere un punto coperto a metà (la validazione lo
accettava già, confrontando per sottostringa). `valutazione-v2` permette di dividere il punto:
la parte detta in `punti_coperti`, quella mancante in `punti_mancanti`, con un esempio.

`BUDGET: 1 iterazione del prompt del giudice | ranking: accordo ≥ 80% > al massimo 1 errata
giudicata corretta > risposte a metà giudicate parziali ≥ 6 su 7 > corrette invariate`

Stesse 30 risposte, 3 esecuzioni su GPU:

| | v1 | v2 |
|---|---|---|
| Accordo per esecuzione | 25/30 (83%) | **26/30 (87%)** |
| Errate giudicate corrette | 0 | 0 |
| Corrette giudicate corrette | 30/30 | 30/30 |
| Risposte a metà giudicate parziali | 4/7 | **5/7** |
| Risposte con errore giudicate parziali | 1/3 | 1/3 |
| Verdetti instabili | 0 | 0 |
| Latenza p50 / max | 8,3 / 21,5 s | 8,2 / 19,4 s |

Restano corrette due risposte a metà: D1 (manca la condizione sugli accordi collettivi) e D3
(manca l'autotutela). L'obiettivo di 6 su 7 non è raggiunto.

`SPEDITO: iter 1/1 - valutazione-v2, migliore di v1 sulle risposte a metà e invariata sul resto.`
BASIS: measured.

## F41: soluzioni a più punti con `compito-v4` (2026-10-06)

Il punto debole residuo del giudice (risposte a metà giudicate parziali 5 su 7, obiettivo 6) nasce
dalle soluzioni a un punto solo. Due riscritture del testo del prompt non le avevano cambiate;
`compito-v4` cambia il contratto: aperte e orali restituiscono `"punti": [...]` (da due a cinque,
uno per idea) e il codice li unisce nella soluzione salvata, frasi per le aperte e " | " per gli
orali, che `solution_points.py` divide di nuovo per il giudice. `"soluzione"` libera resta letta.

`BUDGET: 1 versione del prompt | ranking: soluzioni con più di un punto > scarti non aumentati >
lunghezza del prompt; se restano a un punto, revert`

| Misura | `compito-v3` | `compito-v4` |
|---|---|---|
| Sonda, 12 domande (diritto e analisi, aperte e orali) | soluzioni di una frase | 12/12 con 2 punti |
| Percorso dell'app sul corso di Diritto (presunzioni, possesso) | - | 9 domande, 2-4 punti ciascuna |

Sul possesso le generazioni fallivano anche con `compito-v3`: tre domande aperte chiedono circa il
doppio dei 856 token di uscita, il taglio cade nella terza e il secondo tentativo è identico. Ora la
pipeline tiene le domande scritte per intero (F40), e una citazione esatta più lunga di 40 parole
viene accorciata alle prime 40 invece di far scartare la domanda (F81).

`SPEDITO: iter 1/1 - compito-v4.` BASIS: measured sul numero di punti.

### Effetto sul giudice (2026-10-06)

Nuovo set di valutazione (U5 delegata, dati di Claude, quindi provvisorio come V6): 10 domande
generate con `compito-v4` dal corso di Diritto, su TFR e azioni possessorie (5 aperte, 5 orali;
ogni soluzione con 2 o 3 punti), e per ciascuna tre risposte di Claude: completa (attesa
"corretta"), con il solo primo punto (attesa "parziale"), errata. Scartate due domande generate
che invertivano i termini dell'azione di reintegrazione. Giudice `valutazione-v2` invariato, 3
esecuzioni con `scripts/eval_grading.py`; dati in `data/eval/grading/` (fuori dal repo).

Soglie scritte prima dei numeri: accordo ≥ 80% per esecuzione, al massimo 1 errata giudicata
corretta, risposte a metà giudicate parziali ≥ 86% (6 su 7).

| | Esecuzione 1 | Esecuzione 2 | Esecuzione 3 |
|---|---|---|---|
| Accordo | 28/30 (93%) | 28/30 (93%) | 28/30 (93%) |
| Risposte a metà giudicate parziali | 10/10 | 10/10 | 10/10 |
| Errate giudicate corrette | 0 | 0 | 0 |
| Complete giudicate corrette | 8/10 | 8/10 | 8/10 |

Verdetti identici nelle tre esecuzioni. Latenza p50 8,5 s, massimo 16,8 s. I due disaccordi sono
risposte complete giudicate parziali (domanda orale sulla misura minima del TFR e domanda orale
sulle caratteristiche dello spoglio): con più punti il giudice è più severo sulle risposte
complete scritte con parole diverse dalla soluzione, mentre con v1 nessuna corretta era scesa.

`SPEDITO: iter 1/1 - compito-v4 con valutazione-v2: obiettivo di F41 raggiunto (10/10 contro 5/7),
al costo di 2 risposte complete su 10 giudicate parziali.` BASIS: measured su etichette di Claude.

Stai rileggendo la trascrizione automatica di una lezione universitaria in italiano.

Contesto. Il testo è uscito da un riconoscimento vocale (Whisper) su una registrazione fatta con un telefono in aula: il docente è lontano, c'è eco e rumore. L'errore tipico è una parola sentita male, che suona simile a quella giusta ma nel contesto non ha senso: "la legione degli interessi legittimi" invece di "la lesione", "ha esinto il credito" invece di "ha estinto". Lo studente studierà su questa trascrizione, quindi deve riportare esattamente ciò che il docente ha detto.

Compito. Trova solo le parole sentite male e proponi quella che il docente ha davvero pronunciato. Tieni tutto il resto com'è: frasi sgrammaticate, ripetizioni, intercalari e punteggiatura sono il parlato del docente e restano. Ogni proposta passa un controllo automatico: se la correzione non suona simile all'originale o riscrive più di qualche parola, viene scartata.
{materia}
Formato. Rispondi con un oggetto JSON con la chiave "correzioni": una lista di oggetti con "originale" e "corretto".
- "originale" è copiato carattere per carattere dal testo da correggere, da 1 a 4 parole. Se la parola compare più volte nel paragrafo, aggiungi la parola vicina che la rende unica.
- "corretto" è lo stesso frammento in cui la parola sbagliata (o le 2-3 parole in cui Whisper l'ha spezzata) è sostituita da quella giusta. Non aggiungere e non togliere altre parole: le proposte che lo fanno vengono scartate.
- Proponi una correzione solo quando il contesto rende evidente la parola giusta. Nel dubbio, lascia stare: una lista vuota è una risposta valida.

Esempi illustrativi (materie diverse, stesso formato):
- "l'equazione di Scolinger descrive" -> {"originale": "di Scolinger", "corretto": "di Schrödinger"}
- "il prodotto interno sordo è calato" -> {"originale": "interno sordo", "corretto": "interno lordo"}
- "il teorema di Noether con leghe simmetrie" -> {"originale": "con leghe", "corretto": "collega"}

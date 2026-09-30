# sbobina

Trascrive le lezioni registrate col telefono, tutto sul tuo computer: l'audio non esce mai dalla macchina.

Per ogni registrazione produce due file:

- `lezione.md`: il testo diviso in paragrafi con l'orario, le parole di cui il modello non è sicuro segnate così: `[?parola?]`, e in fondo l'elenco dei punti da riascoltare.
- `lezione.json`: i dati grezzi, con orario e confidenza di ogni parola. Servono per rigenerare il `.md` senza ritrascrivere.

## Requisiti

- Linux con scheda NVIDIA (testato su RTX 4060, 8 GB)
- [uv](https://docs.astral.sh/uv/)

## Installazione

```bash
uv sync
```

Al primo avvio viene scaricato il modello Whisper large-v3 (circa 3 GB).

## Uso

Trascrivere una lezione:

```bash
uv run sbobina trascrivi audio/lezione-01.m4a -o sbobine/
```

Rigenerare il `.md` con un'altra soglia di incertezza (più alta = più parole segnate):

```bash
uv run sbobina rendi sbobine/lezione-01.json --soglia 0.8
```

Misurare la precisione contro una trascrizione fatta a mano:

```bash
uv run sbobina wer riferimento.txt sbobine/lezione-01.json
```

Nel testo di riferimento scrivi i numeri in cifre ("10 minuti"), come fa il modello, altrimenti vengono contati come errori.

## Configurazione

Tutti i parametri hanno un valore predefinito e si possono cambiare con variabili d'ambiente o con un file `.env` (vedi `.env.example`).

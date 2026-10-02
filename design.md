# Design: sbobina

Locked design system for the local web UI. Every page defers to this file;
pages share the system instead of differing from each other. Amend it on
purpose, never override it inside one page.

DIAL: work tool for students reading 1-2 h transcripts, utilitarian-editorial
language · ENERGY 1 / RHYTHM 2 / MOTION 1

## System
- Genre · modern-minimal, app variant (a work tool, not a marketing page)
- Shell · side-rail app (Workbench): left rail with 5 destinations, one work
  area, a sticky audio bar only in the reader
- Theme · custom (vibe: "quiet slate desk, petrol ink, reading lamp")
- Axes · light paper / grotesk-sans UI + serif reading / cool accent
- Dark mode · `prefers-color-scheme`, overridable with `data-theme` on `<html>`

## Tokens
`src/sbobina/web/static/tokens.css` is the source of truth. Pages reference
tokens by name only: no inline OKLCH, hex or `font-family`.

| Role | Token | Use |
| --- | --- | --- |
| Paper | `--color-paper`, `-2`, `-3` | page, rail and table stripes, pressed states |
| Surface | `--color-surface` | cards, inputs, dropzone |
| Ink | `--color-ink`, `-2`, `-3` | text, secondary text, helper text (all ≥ 4.5:1) |
| Rules | `--color-rule`, `--color-rule-strong` | dividers only |
| Control border | `--color-control-border` | inputs, selects, checkboxes (≥ 3:1) |
| Accent | `--color-accent`, `-hover`, `-soft`, `-ink` | primary action, links, active nav, progress, current word |
| Focus | `--color-focus` | `:focus-visible` ring, 2 px, offset 2 px |
| Reader | `--color-uncertain-*`, `--color-corrected*` | doubtful words, LLM corrections |
| Status | `--color-success/warning/danger` + `-bg` | badges and banners, always with a word |

Contrast measured on every text/background pair in both modes: 46/46 pass
(body ≥ 4.5:1, UI boundaries ≥ 3:1).

Type: Inter for all UI (house face). Source Serif 4 only for transcript text,
at `--text-reading` with `--leading-reading` and `--measure-reading`.
Timestamps and numbers use Inter with `font-variant-numeric: tabular-nums`,
never monospace labels. Headings are roman, weight 600, tracking
`--tracking-display`; no italic headings, no uppercase eyebrows, no numbered
section labels. Fonts are not downloaded from the network: if Inter or
Source Serif 4 are not installed, the stack falls back to system faces.

Spacing: 4-pt scale `--space-3xs` … `--space-3xl`. Radii: 6 px controls,
10 px cards, 3 px word marks. No pill buttons.

## Layout
- Rail `--rail-width`, content up to `--content-max`, reader text column at
  `--measure-reading`. Below 768 px the rail becomes a top bar with the six
  destinations in one scrollable row; no hamburger.
- Pages: Nuova trascrizione · Corsi · Lettore · Storico · Modelli ·
  Confronto (WER). Corsi added in T013 to group lectures by course.
- The reader puts the transcript in the centre column and the list of points
  to re-listen in a side column from 1024 px; below, the list follows the text.

## Components
- **Button** · primary: accent fill, `--color-accent-ink` text; secondary:
  surface with control border; ghost: text only; danger: danger text, danger
  border on hover. 6 px radius, 40 px min height (44 px on touch). All 8
  states: default, hover, focus-visible, active, disabled, loading (spinner +
  label kept), error, success.
- **Field** · label above, helper below in `--color-ink-3`, error replaces the
  helper in danger with an icon; validate on blur; input keeps its value on
  error.
- **Dropzone** · dashed control border on surface, the whole area is a
  `<label>` for a real file input (keyboard and screen reader work without
  drag); drag-over switches border and background to accent / accent-soft;
  shows file name and size once chosen, with "Cambia file".
- **Disclosure** · "Impostazioni avanzate" (beam, VAD, previous-text,
  threshold) collapsed by default; model, correction and subject stay visible.
- **Progress** · 6 px track in paper-3, accent fill, determinate with
  percentage, stage name, speed and remaining time when known; indeterminate
  stripe while a model loads. Never invent an ETA: show it only when computed.
- **Badge** · status word + dot: In coda, In corso, Completata, Errore,
  Annullata, Interrotta. Colour never carries the meaning alone.
- **Banner** · system notices (device CPU, Ollama not installed / not
  running, CUDA libraries missing), with the exact action to take.
- **Table** (history) · columns Lezione, Data, Durata, Stato, Azioni; rows
  link to the reader; pagination with page numbers and counts.
- **Word marks** (reader) · uncertain: `--color-uncertain-bg` marker,
  dotted underline in uncertain ink; corrected: corrected underline, tooltip
  and inline "prima: …"; current word while playing: accent-soft background.
- **Audio bar** · sticky bottom in the reader: play/pause, −10 s / +10 s,
  time, speed (1×, 1.25×, 1.5×), seek bar; click on a word seeks there.

## UI states (every data surface)
- Loading · skeleton rows; after 15 s "Ci sta mettendo più del previsto".
- Empty · first use: one sentence on what the page does + primary action;
  no results: echo the filter and suggest the next step.
- Error · cause in plain Italian + recovery action; form input preserved.
- Populated · the designed case.
- Edge · 2-hour lectures (virtualise nothing, but keep paragraphs light),
  200-character file names (wrap with `overflow-wrap: anywhere`), missing
  optional metadata, 1000+ history rows (paginated).

## Motion stance
- Silent UI: hover and press transitions on colour/opacity only,
  `--dur-fast` / `--dur-base`, `--ease-out`. No reveals, no parallax.
- Progress bar moves with `transform: scaleX`, never `width`.
- `prefers-reduced-motion: reduce` turns transitions into instant changes.

## Copy voice
- Italian, plain, second person singular ("Carica la lezione").
- Verbs on buttons: "Trascrivi", "Annulla", "Scarica .md", "Riapri".
- Errors name the cause and the fix ("Ollama non è avviato: aprilo e riprova").
- No invented numbers: speeds, times and counts come from the running job.

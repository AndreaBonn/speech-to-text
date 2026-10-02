# sbobina

Local-only lecture transcription (Italian). Audio must never leave the machine; text correction (phase 4) uses a local LLM via Ollama, not a cloud API.

## Stack
- faster-whisper large-v3, float16, CUDA (RTX 4060 8 GB)
- CUDA libs from pip wheels (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`), preloaded by `cuda_libs.py`: no `LD_LIBRARY_PATH`
- Ollama 0.18 ignores `format` when `think=False`: JSON arrives in a markdown fence, validated by pydantic
- VAD off by default: Silero merged speech into windows Whisper under-decoded (-35% words)
- `av` pinned `<19`: faster-whisper 1.2.1 passes `metadata_errors` to `av.open`, removed in av 19

## Layout
- `models.py` domain dataclasses + JSON I/O; `render.py` and `wer.py` pure logic; `transcriber.py` the only faster-whisper boundary; `cli.py` entry point
- `edits.py` applies LLM edits behind guards (substitutions only, ≤3 words, difflib ≥0.6); `correction.py` chunks and orchestrates; `ollama_chat.py` is the shared Ollama chat boundary (request, errors, markdown fences); `llm_corrector.py` validates corrections and ensures model availability; `cleanup.py` drops isolated "Grazie." hallucinations; `report.py` the corrections report
- `study_models.py` separates persisted study dataclasses from the LLM response schema and runtime citation matches; `study_citations.py` validates exact normalized quotes within a passage and its allowed successor, resolving current word indices and timestamps without I/O
- `book.py` (pure) and `docx_export.py` (the only python-docx boundary) export the reading copy as TXT/DOCX: book layout, no timestamps or review marks
- `manual_edit.py` replaces a word span typed by the user in the reader; `web/api_corrected.py` serves exports and edits. Edits quote the file `revision` (hash of the saved JSON): word indices shift after an edit, and repeated words make a text-only check unsafe
- Prompts are versioned files in `src/sbobina/prompts/`
- `courses.py` normalizes and groups courses; `web/api_courses.py` lists courses and edits `LectureMeta` in user-owned `meta.json`. The supervisor owns `job.json`; effective courses fall back to `config.subject`. The empty key identifies uncategorized lectures.

## Roadmap
1. Transcription + uncertainty flags + WER tool (done)
2. Per-course glossary → `hotwords`/`initial_prompt`; keep only if WER drops on the gold set
3. Second model (Cohere Transcribe) + disagreement flags
4. Local LLM correction (Ollama qwen3.5:9b), substitution-only guards, corrections report (done; ~38 min per 85-min lecture)

## Commands
`uv run pytest`, `uv run ruff check .`, `uv run mypy src tests`

# sbobina

Local-only lecture transcription (Italian). Audio must never leave the machine; text correction (phase 4) uses a local LLM via Ollama, not a cloud API.

## Stack
- faster-whisper large-v3, float16, CUDA (RTX 4060 8 GB)
- CUDA libs from pip wheels (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`), preloaded by `cuda_libs.py`: no `LD_LIBRARY_PATH`
- Ollama 0.18 ignores `format` when `think=False`: JSON arrives in a markdown fence, validated by pydantic
- VAD off by default: Silero merged speech into windows Whisper under-decoded (-35% words)
- `av` pinned `<19`: faster-whisper 1.2.1 passes `metadata_errors` to `av.open`, removed in av 19
- Ollama `num_ctx` fixed at 8192 (changing it reloads the model); Italian costs 2.29 tokens per word. Output budgets per item come from the T036 measurements; exams are capped at 10 items so material stays above 1000 words
- `ollama_chat.chat_json` logs token counts and closes brackets a complete reply forgot (Ollama ignores the schema with `think=False`), never on a reply cut by `num_predict`

## Layout
- `models.py` domain dataclasses + JSON I/O; `render.py` and `wer.py` pure logic; `transcriber.py` the only faster-whisper boundary; `cli.py` entry point
- `edits.py` applies LLM edits behind guards (substitutions only, ≤3 words, difflib ≥0.6); `correction.py` chunks and orchestrates; `ollama_chat.py` is the shared Ollama chat boundary (request, errors, markdown fences); `llm_corrector.py` validates corrections and ensures model availability; `cleanup.py` drops isolated "Grazie." hallucinations; `report.py` the corrections report
- `study_models.py` separates persisted study dataclasses from the LLM response schema and runtime citation matches; `study_citations.py` validates exact normalized quotes within a passage and its allowed successor, resolving current word indices and timestamps without I/O
- `book.py` (pure) and `docx_export.py` (the only python-docx boundary) export the reading copy as TXT/DOCX: book layout, no timestamps or review marks
- `manual_edit.py` replaces a word span typed by the user in the reader; `web/api_corrected.py` serves exports and edits. Edits quote the file `revision` (hash of the saved JSON): word indices shift after an edit, and repeated words make a text-only check unsafe
- Prompts are versioned files in `src/sbobina/prompts/`
- `courses.py` normalizes and groups courses; `web/api_courses.py` lists courses and edits `LectureMeta` in user-owned `meta.json`. The supervisor owns `job.json`; effective courses fall back to `config.subject`. The empty key identifies uncategorized lectures.
- Course workspace (specs/001-course-workspace): `course_registry.py` gives each course a uuid folder under `data/courses/<id>/`. Documents: `document_sniff.py` decides the type from content, `document_extract.py`/`pdf_text.py` extract text in a child process under RLIMIT_AS (`web/extraction_worker.py`), `web/document_store.py` persists, `document_passages.py` chunks for the FTS5 index (`web/document_index.py`, `search_schema.py`)
- Retrieval: `retrieval.py` (BM25 per table, reciprocal rank fusion), `lecture_windows.py` (~250-word lecture windows), `source_sampling.py` (spread sampling for an empty topic), `web/course_retrieval.py` the I/O edge. Citations of course material: `source_citations.py`
- Generations (exams, summaries): `generation_pipeline.py` + `generation_validation.py` + `generation_render.py`/`docx_export.py`, run as a queue action (`web/generation_runner.py` in the child, `web/generation_queue.py`/`generation_supervisor.py` in the supervisor), served by `web/api_generations.py`
- Chat: `chat_pipeline.py` answers with cited sentences only; `web/chat_turn.py` runs one turn; `web/chat_store.py` keeps append-only JSONL per conversation; `web/api_chat.py` the routes
- GPU: `web/gpu_lock.py` is a readers-writer lock (writer priority) between chat turns in the web process and the supervisor's TRANSCRIBING stage (`web/transcription_gate.py`); queue children are already serial

## Roadmap
1. Transcription + uncertainty flags + WER tool (done)
2. Per-course glossary → `hotwords`/`initial_prompt`; keep only if WER drops on the gold set
3. Second model (Cohere Transcribe) + disagreement flags
4. Local LLM correction (Ollama qwen3.5:9b), substitution-only guards, corrections report (done; ~38 min per 85-min lecture)

## Commands
`uv run pytest`, `uv run ruff check .`, `uv run mypy src tests`

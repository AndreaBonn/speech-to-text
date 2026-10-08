# sbobina

Lecture transcription (Italian), local by default: with the default engines (Whisper, Ollama) nothing leaves the machine. Cloud engines are opt-in and need an explicit confirmation in Settings: text to Groq/Gemini/OpenAI/Anthropic (`cloud_ack`), audio to AssemblyAI (`cloud_ack_audio`). API keys live in `credentials.json` (0600) in the user config dir, never under `data/` or the repo, never in `os.environ`, logs or `job.json`. OCR stays local only. Design: `specs/003-cloud-providers/`.

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
- `edits.py` applies LLM edits behind guards (substitutions only, ≤3 words, difflib ≥0.6); `correction.py` chunks and orchestrates; `ollama_chat.py` is the Ollama chat boundary; `llm_corrector.py` validates corrections and ensures model availability; `cleanup.py` drops isolated "Grazie." hallucinations; `report.py` the corrections report
- `study_models.py` separates persisted study dataclasses from the LLM response schema and runtime citation matches; `study_citations.py` validates exact normalized quotes within a passage and its allowed successor, resolving current word indices and timestamps without I/O
- `book.py` (pure) and `docx_export.py` (the only python-docx boundary) export the reading copy as TXT/DOCX: book layout, no timestamps or review marks
- `manual_edit.py` replaces a word span typed by the user in the reader; `web/api_corrected.py` serves exports and edits. Edits quote the file `revision` (hash of the saved JSON): word indices shift after an edit, and repeated words make a text-only check unsafe
- Prompts are versioned files in `src/sbobina/prompts/`
- `courses.py` normalizes and groups courses; `web/api_courses.py` lists courses and edits `LectureMeta` in user-owned `meta.json`. The supervisor owns `job.json`; effective courses fall back to `config.subject`. The empty key identifies uncategorized lectures.
- Course workspace (specs/001-course-workspace): `course_registry.py` gives each course a uuid folder under `data/courses/<id>/`. Documents: `document_sniff.py` decides the type from content, `document_extract.py`/`pdf_text.py` extract text in a child process under RLIMIT_AS (`web/extraction_worker.py`), `web/document_store.py` persists, `document_passages.py` chunks for the FTS5 index (`web/document_index.py`, `search_schema.py`)
- Retrieval: `retrieval.py` (BM25 per table, reciprocal rank fusion), `lecture_windows.py` (~250-word lecture windows), `source_sampling.py` (spread sampling for an empty topic), `web/course_retrieval.py` the I/O edge. Citations of course material: `source_citations.py`
- Generations (exams, summaries): `generation_pipeline.py` + `generation_validation.py` + `generation_render.py`/`docx_export.py`, run as a queue action (`web/generation_runner.py` in the child, `web/generation_queue.py`/`generation_supervisor.py` in the supervisor), served by `web/api_generations.py`
- Chat: `chat_pipeline.py` answers with cited sentences only; `web/chat_turn.py` runs one turn; `web/chat_store.py` keeps append-only JSONL per conversation; `web/api_chat.py` the routes
- LLM engines (specs/003-cloud-providers): `llm_factory.py` is the only place that builds a `ChatClient` (`build_from_settings`); engine `local` keeps the Ollama path, engine `api` builds `llm_chain.FallbackChain` over `providers/openai_compat.py` (OpenAI, Groq, Gemini) and `providers/anthropic.py`, with `providers/ollama_link.py` (never pulls) as optional last link. A provider outage moves one request to the next link (`chain_policy.py`, `llm_errors.py`); invalid JSON is re-raised, not passed on. Results carry `served_by`. JSON repairs are provider-neutral in `llm_repair.py`; `providers/schema_compat.py` makes schemas portable
- Config: `config_dir.py` (per-user dir), `credential_store.py` (keys, atomic 0600 writes), `user_preferences.py` (engine, chain; env wins), `log_redaction.py` (key redaction on every handler, tracebacks included). Never name modules `secret*`: a permission deny blocks reading them
- Dense retrieval (specs/004-hybrid-retrieval): `ollama_embed.py` is the only `/api/embed` boundary; `embedding_prompts.py`, `embedding_units.py`, `dense_math.py`, `rank_fusion.py` are pure; `web/vector_store.py` + `web/vector_schema.py` keep `data/vectors.sqlite3` (one instance per process, via `web/dense_factory.py`); `web/vector_reconcile.py` syncs manifests and embeds; `web/dense_retrieval.py` ranks or falls back to BM25 with a reason. Indexing is a queue action (`web/embedding_supervisor.py`, `embedding_queue.py`, `embedding_runner.py`, `embedding_store.py`), auto-queued after text changes and backfilled by `web/embedding_backfill.py` (CLI `indicizza-semantico --backfill`); status and Settings in `web/api_semantic_index.py`, `semantic_index_status.py`, `semantic_index_queue.py`. Evaluation: `retrieval_metrics.py`, `hybrid_eval.py`, `scripts/eval_hybrid*.py`, results in `specs/004-hybrid-retrieval/eval.md`
- GPU: `web/gpu_lock.py` is a readers-writer lock (writer priority) between chat turns in the web process and the supervisor's TRANSCRIBING and embedding stages (`web/transcription_gate.py`; a chat during indexing answers `GPU_BUSY`); queue children are already serial

## Roadmap
1. Transcription + uncertainty flags + WER tool (done)
2. Per-course glossary → `hotwords`/`initial_prompt`; keep only if WER drops on the gold set
3. Second model (Cohere Transcribe) + disagreement flags
4. Local LLM correction (Ollama qwen3.5:9b), substitution-only guards, corrections report (done; ~38 min per 85-min lecture)

## Commands
`uv run pytest`, `uv run ruff check .`, `uv run mypy src tests`

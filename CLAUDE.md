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
- `edits.py` applies LLM edits behind guards (substitutions only, ≤3 words, difflib ≥0.6); `correction.py` chunks and orchestrates; `llm_corrector.py` the only Ollama boundary; `cleanup.py` drops isolated "Grazie." hallucinations; `report.py` the corrections report
- Prompts are versioned files in `src/sbobina/prompts/`

## Roadmap
1. Transcription + uncertainty flags + WER tool (done)
2. Per-course glossary → `hotwords`/`initial_prompt`; keep only if WER drops on the gold set
3. Second model (Cohere Transcribe) + disagreement flags
4. Local LLM correction (Ollama qwen3.5:9b), substitution-only guards, corrections report (done; ~38 min per 85-min lecture)

## Commands
`uv run pytest`, `uv run ruff check .`, `uv run mypy src tests`

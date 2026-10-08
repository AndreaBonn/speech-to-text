**English** | [Italiano](./SECURITY.it.md)

# Security Policy

## Supported Versions

This project is in active development and has no tagged releases. Security fixes are applied to the latest commit on `main`.

## Reporting a Vulnerability

Report vulnerabilities through [GitHub Security Advisories](https://github.com/AndreaBonn/speech-to-text/security/advisories/new). Please do not open a public issue.

Include:

- a description of the vulnerability
- steps to reproduce
- expected and actual behavior
- the impact (what an attacker could achieve)

This is a personal project maintained by one person. Expect an acknowledgment within 7 days; fixes and disclosure are coordinated with the reporter.

## Threat Model

Transcriber is a single-user tool that runs on the user's own computer. The web UI has no authentication by design: it is reachable only from the same machine. The main risks it defends against are a malicious website, opened in the same browser, sending requests to the local server, oversized or malformed input, including course documents built to exhaust memory or disk, and text inside course documents or LLM replies that tries to reach the page as markup. Since cloud engines exist, two more risks are in scope: content leaving the computer without the user knowing, and API keys leaking into logs, course exports or the repository.

## Security Measures Implemented

- **Loopback-only server**: the configured host must be `127.0.0.1`, `::1` or `localhost`; any other value is rejected at startup (`src/sbobina/settings.py:136`).
- **All-interfaces bind only inside a container**: `SBOBINA_WEB_BIND_HOST` accepts only `0.0.0.0` or `::` (`src/sbobina/settings.py:143`), and the launcher refuses to start with it unless a Docker or Podman marker file exists (`src/sbobina/web/launcher.py:88`). The Compose file publishes the port on the host's `127.0.0.1` only (`compose.yaml:17`), and the origin the server accepts stays the loopback one.
- **Host header check**: Starlette `TrustedHostMiddleware` accepts only loopback host names, which blocks DNS rebinding (`src/sbobina/web/app.py:189`).
- **Origin check on state-changing requests**: `POST`, `PUT`, `PATCH` and `DELETE` with an `Origin` header different from the server's own origin get a 403 (`src/sbobina/web/middleware.py:27`).
- **Upload size limit before reading the body**: audio uploads larger than `SBOBINA_WEB_MAX_UPLOAD_MB` (1024 MB by default) and course documents larger than `SBOBINA_COURSE_DOC_MAX_MB` (200 MB by default), or uploads without a `Content-Length`, are refused before anything is written to disk (`src/sbobina/web/upload_limit.py:74`, limits set in `src/sbobina/web/app.py:192`).
- **Document type checked from content**: the type of a course document comes from its first bytes (PDF signature, ZIP archive layout for DOCX and PPTX), not from its extension (`src/sbobina/document_sniff.py:75`).
- **Office archive limits**: a DOCX or PPTX with more than 10,000 entries or more than 500 MB uncompressed is refused with a 413 before it is opened, which blocks zip bombs (`src/sbobina/document_sniff.py:33`).
- **Document parsing in a limited child process**: text extraction runs in a separate process with an address-space limit (`RLIMIT_AS`, `SBOBINA_EXTRACTION_MAX_MEMORY_MB`, 2048 MB by default; not available on Windows) and a timeout, after which it is terminated (`src/sbobina/web/extraction_runner.py:26`, `src/sbobina/web/extraction_worker.py:230`).
- **OCR bounded in memory, time and render size**: the OCR child gets the same memory limit (`src/sbobina/web/ocr_runner.py:131`), each page is rendered with its long side capped at 2500 pixels (`src/sbobina/pdf_text.py:10`), and a run still going after `SBOBINA_OCR_PROCESS_TIMEOUT_S` (one hour by default) is killed so it cannot hold the queue (`src/sbobina/web/ocr_supervisor.py:125`).
- **Identifiers validated before touching the file system**: a job ID must parse as a UUID version 4 before it is used to build a path, which rules out path traversal (`src/sbobina/web/job_store.py:73`); chat IDs must be canonical UUIDs (`src/sbobina/web/api_chat.py:138`); flashcard anchors and imported-lecture IDs must be UUID version 4 (`src/sbobina/card_models.py:30`, `src/sbobina/web/job_models.py:168`).
- **Search queries never reach FTS5 syntax**: user terms are quoted as literal strings (`src/sbobina/search_text.py:36`) and passed as a bound parameter to `MATCH` (`src/sbobina/web/search_index.py:101`).
- **LLM output treated as untrusted**: exam, summary and chat citations are checked against the passages given to the model, and an item whose quote is not found is dropped (`src/sbobina/generation_validation.py:71`, `src/sbobina/source_citations.py:115`). Course pages build the DOM with `createElement` and `textContent` only, so course names, file names, document text and LLM replies cannot inject markup (`src/sbobina/web/static/js/dom.js:2`).
- **Content-Security-Policy on HTML pages**: scripts, styles, fonts and connections are limited to the server's own origin, objects are blocked and the page cannot be framed (`frame-ancestors 'none'`) (`src/sbobina/web/middleware.py:14`, applied at `src/sbobina/web/middleware.py:49`). KaTeX, which renders formulas written by the LLM or read by OCR, is served from the repository and runs with `trust: false` and bounded macro expansion (`src/sbobina/web/static/js/math-text.js:15`).
- **Course packages validated before any write**: an imported `.sbobina.zip` is refused if a member name is absolute, contains `..`, a backslash or a NUL byte, or is a symlink (`src/sbobina/package_validate.py:89`), or if it exceeds the limits on member count (5,000), member size, total size and compression ratio (100:1) (`src/sbobina/package_validate.py:19`). The import itself runs in a child process with the same memory limit as extraction (`src/sbobina/web/package_import_runner.py:30`), and the upload is capped at `SBOBINA_WEB_MAX_UPLOAD_MB` (`src/sbobina/web/app.py:198`).
- **Model names validated**: Whisper models must be in the known list; Ollama names must match a strict pattern and length (`src/sbobina/web/downloads.py:53`).
- **Request validation**: API inputs are parsed with Pydantic models; errors return 422 with per-field details (`src/sbobina/web/responses.py:38`).
- **HTML escaping in the job queue**: server-provided strings are escaped before being inserted into the page (`src/sbobina/web/static/js/jobs.js:426`).
- **Cloud engines require explicit consent**: switching text features to a cloud engine or transcription to AssemblyAI is refused unless the request carries the confirmation from the consent dialog (`src/sbobina/settings_service.py:163`, `src/sbobina/settings_service.py:177`). A cloud choice found saved without its consent falls back to the local engine at startup (`src/sbobina/user_preferences.py:142`). OCR and semantic search have no cloud path.
- **API keys outside data and repository**: keys are saved in `credentials.json` in the per-user config folder, which is refused if it resolves inside the data folder or the repository (`src/sbobina/config_dir.py:59`). The file is written with mode `0600` and corrected with a warning if found otherwise (not on Windows), and a symlink in its place is ignored (`src/sbobina/credential_store.py:58`, `src/sbobina/credential_store.py:70`).
- **API keys masked in logs**: a logging filter replaces known key values and common key formats with `***`, tracebacks included, on the root, Uvicorn and httpx handlers (`src/sbobina/log_redaction.py:179`).
- **Remote audio deleted after transcription**: with AssemblyAI the remote transcript and audio are deleted at the end of every job, failed ones included; a failed deletion is reported to the user (`src/sbobina/assemblyai_transcriber.py:59`).
- **Container runs as an unprivileged user**: the Docker image runs the server as uid 1000, not root (`Dockerfile:49`).
- **Pinned dependencies and CI**: `uv.lock` is committed and CI installs with `uv sync --locked`; GitHub Actions are pinned to commit SHAs, run with read-only `contents` permission and without persisted credentials (`.github/workflows/ci.yml`).

Not implemented: authentication, rate limiting, the `X-Frame-Options` and `Strict-Transport-Security` headers (framing is blocked by the CSP instead; the server speaks plain HTTP on loopback), automated dependency scanning in CI.

## Data Handling

Audio files, transcripts, course documents, generated exams and summaries, practice attempts, flashcards and chat conversations are processed on the local machine and stored under the `data/` folder (`SBOBINA_DATA_DIR`). Correction, study notes, exams, summaries, answer grading and chat send text from transcripts and course documents to the Ollama server set in `SBOBINA_OLLAMA_HOST`, `http://localhost:11434` by default; OCR sends images of the scanned pages to the same server. If you point that variable at another machine, that content leaves your computer. With a cloud engine chosen in **Impostazioni**, the same text goes to the selected providers (Groq, Gemini, OpenAI or Anthropic, in the configured order), and with AssemblyAI the audio file is uploaded to AssemblyAI; their own data policies then apply. With Docker, the data lives in named Docker volumes on the same machine. An exported course package contains transcripts, the chosen course documents, practice exams and flashcards: whoever receives it gets that content.

## Security Best Practices for Users

- Do not put the server behind a reverse proxy or a port forward: it has no authentication.
- On a computer shared with other people, remember that any local user can reach `127.0.0.1:8765` while the server is running.
- Keep `SBOBINA_OLLAMA_HOST` on `localhost` unless you control the remote machine.
- With Docker, keep the port mapping `127.0.0.1:8765:8765` in `compose.yaml`: removing the `127.0.0.1` prefix exposes the UI to the network.
- Prefer API keys restricted to the services this tool uses, and revoke a key from the provider's console if the computer is shared or lost.

## Out of Scope

- Attacks that require access to the user's account on the same computer
- Vulnerabilities in third-party dependencies already publicly disclosed (report them to the upstream project)
- Denial of service through excessive legitimate use, such as queuing many long recordings

---

[Back to README](./README.md)

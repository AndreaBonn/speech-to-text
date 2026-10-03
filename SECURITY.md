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

Transcriber is a single-user tool that runs on the user's own computer. The web UI has no authentication by design: it is reachable only from the same machine. The main risks it defends against are a malicious website, opened in the same browser, sending requests to the local server, oversized or malformed input, including course documents built to exhaust memory or disk, and text inside course documents or LLM replies that tries to reach the page as markup.

## Security Measures Implemented

- **Loopback-only server**: the configured host must be `127.0.0.1`, `::1` or `localhost`; any other value is rejected at startup (`src/sbobina/settings.py:75`).
- **Host header check**: Starlette `TrustedHostMiddleware` accepts only loopback host names, which blocks DNS rebinding (`src/sbobina/web/app.py:139`).
- **Origin check on state-changing requests**: `POST`, `PUT`, `PATCH` and `DELETE` with an `Origin` header different from the server's own origin get a 403 (`src/sbobina/web/middleware.py:24`).
- **Upload size limit before reading the body**: audio uploads larger than `SBOBINA_WEB_MAX_UPLOAD_MB` (1024 MB by default) and course documents larger than `SBOBINA_COURSE_DOC_MAX_MB` (200 MB by default), or uploads without a `Content-Length`, are refused before anything is written to disk (`src/sbobina/web/upload_limit.py:58`, limits set in `src/sbobina/web/app.py:150`).
- **Document type checked from content**: the type of a course document comes from its first bytes (PDF signature, ZIP archive layout for DOCX and PPTX), not from its extension (`src/sbobina/document_sniff.py:75`).
- **Office archive limits**: a DOCX or PPTX with more than 10,000 entries or more than 500 MB uncompressed is refused with a 413 before it is opened, which blocks zip bombs (`src/sbobina/document_sniff.py:33`).
- **Document parsing in a limited child process**: text extraction runs in a separate process with an address-space limit (`RLIMIT_AS`, `SBOBINA_EXTRACTION_MAX_MEMORY_MB`, 2048 MB by default; not available on Windows) and a timeout, after which it is terminated (`src/sbobina/web/extraction_runner.py:26`, `src/sbobina/web/extraction_worker.py:218`).
- **OCR bounded in memory, time and render size**: the OCR child gets the same memory limit (`src/sbobina/web/ocr_runner.py:123`), each page is rendered with its long side capped at 2500 pixels (`src/sbobina/pdf_text.py:10`), and a run still going after `SBOBINA_OCR_PROCESS_TIMEOUT_S` (one hour by default) is killed so it cannot hold the queue (`src/sbobina/web/ocr_supervisor.py:126`).
- **Identifiers validated before touching the file system**: a job ID must parse as a UUID version 4 before it is used to build a path, which rules out path traversal (`src/sbobina/web/job_store.py:73`); chat IDs must be canonical UUIDs (`src/sbobina/web/api_chat.py:86`).
- **Search queries never reach FTS5 syntax**: user terms are quoted as literal strings (`src/sbobina/search_text.py:36`) and passed as a bound parameter to `MATCH` (`src/sbobina/web/search_index.py:101`).
- **LLM output treated as untrusted**: exam, summary and chat citations are checked against the passages given to the model, and an item whose quote is not found is dropped (`src/sbobina/generation_validation.py:67`, `src/sbobina/source_citations.py:81`). Course pages build the DOM with `createElement` and `textContent` only, so course names, file names, document text and LLM replies cannot inject markup (`src/sbobina/web/static/js/dom.js:2`).
- **Model names validated**: Whisper models must be in the known list; Ollama names must match a strict pattern and length (`src/sbobina/web/downloads.py:53`).
- **Request validation**: API inputs are parsed with Pydantic models; errors return 422 with per-field details (`src/sbobina/web/responses.py:37`).
- **HTML escaping in the job queue**: server-provided strings are escaped before being inserted into the page (`src/sbobina/web/static/js/jobs.js:426`).
- **Pinned dependencies and CI**: `uv.lock` is committed and CI installs with `uv sync --locked`; GitHub Actions are pinned to commit SHAs, run with read-only `contents` permission and without persisted credentials (`.github/workflows/ci.yml`).

Not implemented: authentication, rate limiting, security headers (CSP, `X-Frame-Options`), automated dependency scanning in CI.

## Data Handling

Audio files, transcripts, course documents, generated exams and summaries, and chat conversations are processed on the local machine and stored under the `data/` folder (`SBOBINA_DATA_DIR`). Correction, study notes, exams, summaries and chat send text from transcripts and course documents to the Ollama server set in `SBOBINA_OLLAMA_HOST`, `http://localhost:11434` by default; OCR sends images of the scanned pages to the same server. If you point that variable at another machine, that content leaves your computer.

## Security Best Practices for Users

- Do not put the server behind a reverse proxy or a port forward: it has no authentication.
- On a computer shared with other people, remember that any local user can reach `127.0.0.1:8765` while the server is running.
- Keep `SBOBINA_OLLAMA_HOST` on `localhost` unless you control the remote machine.

## Out of Scope

- Attacks that require access to the user's account on the same computer
- Vulnerabilities in third-party dependencies already publicly disclosed (report them to the upstream project)
- Denial of service through excessive legitimate use, such as queuing many long recordings

---

[Back to README](./README.md)

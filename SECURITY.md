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

Transcriber is a single-user tool that runs on the user's own computer. The web UI has no authentication by design: it is reachable only from the same machine. The main risks it defends against are a malicious website, opened in the same browser, sending requests to the local server, and oversized or malformed input.

## Security Measures Implemented

- **Loopback-only server**: the configured host must be `127.0.0.1`, `::1` or `localhost`; any other value is rejected at startup (`src/sbobina/settings.py:59`).
- **Host header check**: Starlette `TrustedHostMiddleware` accepts only loopback host names, which blocks DNS rebinding (`src/sbobina/web/app.py:73`).
- **Origin check on state-changing requests**: `POST`, `PUT`, `PATCH` and `DELETE` with an `Origin` header different from the server's own origin get a 403 (`src/sbobina/web/middleware.py:19`).
- **Upload size limit before reading the body**: uploads larger than `SBOBINA_WEB_MAX_UPLOAD_MB` (1024 MB by default), or without a `Content-Length`, are refused before anything is written to disk (`src/sbobina/web/upload_limit.py:17`).
- **Job identifiers validated before touching the file system**: a job ID must parse as a UUID version 4 before it is used to build a path, which rules out path traversal (`src/sbobina/web/job_store.py:62`).
- **Model names validated**: Whisper models must be in the known list; Ollama names must match a strict pattern and length (`src/sbobina/web/downloads.py:53`).
- **Request validation**: API inputs are parsed with Pydantic models; errors return 422 with per-field details (`src/sbobina/web/responses.py:33`).
- **HTML escaping in the job queue**: server-provided strings are escaped before being inserted into the page (`src/sbobina/web/static/js/jobs.js:426`).
- **Pinned dependencies**: `uv.lock` is committed.

Not implemented: authentication, rate limiting, security headers (CSP, `X-Frame-Options`), automated dependency scanning in CI (there is no CI).

## Data Handling

Audio files and transcripts are processed on the local machine and stored under the `data/` folder (`SBOBINA_DATA_DIR`). The correction pass sends the transcript text to the Ollama server set in `SBOBINA_OLLAMA_HOST`, `http://localhost:11434` by default. If you point that variable at another machine, the text leaves your computer.

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

# syntax=docker/dockerfile:1
# Multi-arch image (linux/amd64, linux/arm64) of the sbobina web UI.
# amd64 ships the CUDA wheels so the same image runs on GPU or CPU; arm64
# (Apple Silicon under Docker Desktop) has no NVIDIA GPU and skips them.
# The NVIDIA driver is never in the image: the host provides it through the
# NVIDIA Container Toolkit (see compose.gpu.yaml).

ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm

FROM ghcr.io/astral-sh/uv:0.9.26 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
ARG TARGETARCH
# Dependencies first: a source change must not reinstall ~2 GB of wheels.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$TARGETARCH" = "amd64" ]; then extra="--extra cuda"; else extra=""; fi; \
    uv sync --frozen --no-dev --no-install-project $extra
COPY README.md LICENSE NOTICE ./
COPY src ./src
# Non-editable: the runtime stage copies only the venv, not the source tree.
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$TARGETARCH" = "amd64" ]; then extra="--extra cuda"; else extra=""; fi; \
    uv sync --frozen --no-dev --no-editable $extra

FROM ${PYTHON_IMAGE} AS runtime
ARG APP_UID=1000
RUN useradd --uid "$APP_UID" --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data /models /config \
    && chown "$APP_UID:$APP_UID" /data /models /config \
    && chmod 700 /config
COPY --from=build --chown=$APP_UID:$APP_UID /app/.venv /app/.venv
# The server binds every interface inside the container only; compose
# publishes the port on the host's loopback, which is the origin it checks.
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models/huggingface \
    SBOBINA_DATA_DIR=/data \
    SBOBINA_CONFIG_DIR=/config \
    SBOBINA_WEB_BIND_HOST=0.0.0.0 \
    SBOBINA_WEB_PORT=8765
WORKDIR /app
USER $APP_UID
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import os, sys, httpx; port = os.environ['SBOBINA_WEB_PORT']; sys.exit(0 if httpx.get(f'http://127.0.0.1:{port}/api/v1/system', timeout=4).status_code == 200 else 1)"]
CMD ["sbobina", "web", "--no-browser"]

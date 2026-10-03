import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

import anyio.to_thread
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from sbobina.settings import LOOPBACK_HOSTS, Settings
from sbobina.web import search_service
from sbobina.web.api_chat import router as chat_router
from sbobina.web.api_corrected import router as corrected_router
from sbobina.web.api_courses import router as courses_router
from sbobina.web.api_documents import router as documents_router
from sbobina.web.api_files import router as files_router
from sbobina.web.api_generations import router as generations_router
from sbobina.web.api_jobs import router as jobs_router
from sbobina.web.api_models import create_models_router
from sbobina.web.api_ocr import router as ocr_router
from sbobina.web.api_search import router as search_router
from sbobina.web.api_study import router as study_router
from sbobina.web.api_system import create_system_router
from sbobina.web.api_wer import WER_REQUEST_LIMIT_BYTES
from sbobina.web.api_wer import router as wer_router
from sbobina.web.downloads import DownloadManager
from sbobina.web.errors import AppError
from sbobina.web.extraction_worker import ExtractionWorker, ExtractionWorkerOptions
from sbobina.web.gpu_lock import GpuArbiter
from sbobina.web.gpu_release import unload_ollama_models
from sbobina.web.job_store import JobStore
from sbobina.web.middleware import OriginMiddleware, web_origin
from sbobina.web.pages import router as pages_router
from sbobina.web.responses import (
    app_error_handler,
    http_error_handler,
    request_validation_handler,
)
from sbobina.web.search_index import index_session
from sbobina.web.sse import router as events_router
from sbobina.web.supervisor import Supervisor, SupervisorOptions
from sbobina.web.upload_limit import UploadLimitMiddleware, upload_limit_bytes

logger = logging.getLogger(__name__)

# Starlette's TrustedHostMiddleware matches the Host header as parsed, which
# keeps brackets around IPv6 literals (RFC 3986 host rule): "::1" must be
# "[::1]" here or a request to http://[::1]:PORT/ gets a 400 before reaching
# OriginMiddleware. https://github.com/encode/starlette/blob/master/starlette/_utils.py
_TRUSTED_HOSTS = [f"[{host}]" if ":" in host else host for host in LOOPBACK_HOSTS]


def _reconcile_search_index(app: FastAPI) -> None:
    with index_session(path=app.state.search_index_path) as index:
        search_service.reconcile(store=app.state.job_store, index=index)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    supervisor: Supervisor = app.state.supervisor
    extraction_worker: ExtractionWorker = app.state.extraction_worker
    try:
        # start() first marks jobs left running by a previous server as
        # interrupted; both calls block on disk and child processes, so they run
        # off the event loop.
        await anyio.to_thread.run_sync(supervisor.start)
        await anyio.to_thread.run_sync(extraction_worker.recover_on_boot)
        await anyio.to_thread.run_sync(extraction_worker.start)
        try:
            await anyio.to_thread.run_sync(partial(_reconcile_search_index, app=app))
        except Exception as error:
            logger.warning(
                "Search index reconciliation failed at startup", exc_info=error
            )
        yield
    finally:
        await anyio.to_thread.run_sync(extraction_worker.stop)
        await anyio.to_thread.run_sync(supervisor.stop)


def create_app(
    settings: Settings,
    data_dir: Path | None = None,
    supervisor_options: SupervisorOptions | None = None,
    extraction_worker_options: ExtractionWorkerOptions | None = None,
) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    app.state.job_store = JobStore(
        data_dir=data_dir if data_dir is not None else settings.data_dir
    )
    app.state.search_index_path = app.state.job_store.jobs_dir.parent / "search.sqlite3"
    app.state.gpu_arbiter = GpuArbiter()
    # None means "build the real Ollama client lazily"; tests set a fake here.
    app.state.chat_client = None
    app.state.supervisor = Supervisor(
        job_store=app.state.job_store,
        before_transcribe=partial(unload_ollama_models, host=settings.ollama_host),
        options=supervisor_options,
        gpu_arbiter=app.state.gpu_arbiter,
    )
    app.state.extraction_worker = ExtractionWorker(
        courses_dir=app.state.job_store.courses_dir,
        options=extraction_worker_options
        if extraction_worker_options is not None
        else ExtractionWorkerOptions(
            timeout_s=settings.extraction_timeout_s,
            max_memory_mb=settings.extraction_max_memory_mb,
        ),
    )
    app.state.download_manager = DownloadManager(settings=settings)
    app.add_middleware(OriginMiddleware, origin=web_origin(settings=settings))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_TRUSTED_HOSTS)
    app.add_middleware(
        UploadLimitMiddleware,
        limits={
            "/api/v1/jobs": upload_limit_bytes(
                max_upload_mb=settings.web_max_upload_mb
            ),
            "/api/v1/wer": WER_REQUEST_LIMIT_BYTES,
        },
        suffix_limits={
            "/documents": upload_limit_bytes(max_upload_mb=settings.course_doc_max_mb),
        },
    )
    _register_routes(app=app, settings=settings)
    return app


def _register_routes(app: FastAPI, settings: Settings) -> None:
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.include_router(create_system_router(settings=settings))
    app.include_router(create_models_router(settings=settings))
    app.include_router(jobs_router)
    app.include_router(courses_router)
    app.include_router(chat_router)
    app.include_router(ocr_router)
    app.include_router(documents_router)
    app.include_router(generations_router)
    app.include_router(search_router)
    app.include_router(study_router)
    app.include_router(files_router)
    app.include_router(corrected_router)
    app.include_router(wer_router)
    app.include_router(events_router)
    app.include_router(pages_router)
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )

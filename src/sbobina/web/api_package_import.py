import logging
from dataclasses import replace
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory
from typing import Annotated

from fastapi import APIRouter, File, Request, UploadFile
from starlette.responses import JSONResponse

from sbobina.web import package_import_worker
from sbobina.web.package_import_worker import (
    PackageImportOptions,
    PackageImportOutcome,
    PackageImportStatus,
)
from sbobina.web.responses import error_response
from sbobina.web.upload_limit import BYTES_PER_MB

router = APIRouter(prefix="/api/v1/courses")
logger = logging.getLogger(__name__)
ERROR_RESPONSES = {
    PackageImportStatus.REJECTED: (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "Il pacchetto non è valido. Esporta nuovamente il corso e riprova.",
    ),
    PackageImportStatus.BUSY: (
        HTTPStatus.CONFLICT,
        "È già in corso l'importazione di un pacchetto. Attendi e riprova.",
    ),
    PackageImportStatus.STORAGE_ERROR: (
        HTTPStatus.INSUFFICIENT_STORAGE,
        (
            "Impossibile salvare il pacchetto su disco. "
            "Verifica lo spazio disponibile e i permessi."
        ),
    ),
    PackageImportStatus.RESOURCE_EXHAUSTED: (
        HTTPStatus.SERVICE_UNAVAILABLE,
        (
            "Memoria insufficiente per importare il pacchetto. "
            "Chiudi altre applicazioni e riprova."
        ),
    ),
    PackageImportStatus.FAILED: (
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "Importazione del pacchetto non riuscita. Riprova.",
    ),
    PackageImportStatus.TIMEOUT: (
        HTTPStatus.SERVICE_UNAVAILABLE,
        "L'importazione del pacchetto ha superato il tempo disponibile. Riprova.",
    ),
}


def _outcome_response(outcome: PackageImportOutcome) -> JSONResponse:
    if outcome.status is PackageImportStatus.IMPORTED:
        return JSONResponse(
            status_code=HTTPStatus.CREATED,
            content={
                "data": {
                    "course_id": outcome.course_id,
                    "course_label": outcome.course_label,
                    "warning": outcome.warning,
                }
            },
        )
    status, message = ERROR_RESPONSES[outcome.status]
    if outcome.status is PackageImportStatus.REJECTED:
        if outcome.code == "PACKAGE_TOO_LARGE":
            status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
            message = "Il pacchetto supera i limiti consentiti. Riduci il contenuto e riprova."
        elif outcome.code == "PACKAGE_VERSION_UNSUPPORTED":
            message = "Pacchetto creato con una versione più recente. Aggiorna Sbobina e riprova."
    return error_response(
        code=outcome.code or "PACKAGE_IMPORT_FAILED",
        message=message,
        status_code=status,
        details=[],
    )


def _import_upload(
    file: UploadFile, data_dir: Path, options: PackageImportOptions
) -> PackageImportOutcome:
    """Store the upload, then import it; only the first step is a disk error."""
    with TemporaryDirectory(prefix="sbobina-upload-") as temporary:
        source = Path(temporary) / "package.sbobina.zip"
        with source.open(mode="wb") as output:
            copyfileobj(fsrc=file.file, fdst=output, length=BYTES_PER_MB)
        try:
            return package_import_worker.run_package_import(
                source=source,
                data_dir=data_dir,
                now=datetime.now(tz=UTC),
                options=options,
            )
        except OSError:
            logger.exception("Could not run the package import")
            return PackageImportOutcome(
                status=PackageImportStatus.FAILED, code="PACKAGE_IMPORT_FAILED"
            )


@router.post("/import", status_code=HTTPStatus.CREATED)
def import_course(
    request: Request, file: Annotated[UploadFile, File()]
) -> JSONResponse:
    settings = request.app.state.settings
    limit = settings.web_max_upload_mb * BYTES_PER_MB
    if file.size is not None and file.size > limit:
        return _outcome_response(
            outcome=PackageImportOutcome(
                status=PackageImportStatus.REJECTED, code="PACKAGE_TOO_LARGE"
            )
        )
    try:
        outcome = _import_upload(
            file=file,
            data_dir=request.app.state.job_store.jobs_dir.parent,
            options=replace(
                package_import_worker.DEFAULT_OPTIONS,
                max_member_mb=settings.course_doc_max_mb,
            ),
        )
    except OSError:
        logger.exception("Could not store the uploaded package")
        outcome = PackageImportOutcome(
            status=PackageImportStatus.STORAGE_ERROR, code="PACKAGE_STORAGE_FAILED"
        )
    return _outcome_response(outcome=outcome)

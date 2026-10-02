import json
import os
import shutil
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from pydantic import JsonValue, TypeAdapter

from sbobina.courses import course_key as normalized_course_key
from sbobina.courses import effective_course
from sbobina.web.errors import NotFoundError, ValidationError
from sbobina.web.job_models import (
    JobConfig,
    JobRecord,
    JobStage,
    JobStatus,
    LectureMeta,
)

PROGRESS_ADAPTER = TypeAdapter(dict[str, JsonValue])
# Windows rejects renaming onto a path a reader still has open; a short retry
# rides out that window instead of failing the whole write (BASIS: inferred).
REPLACE_MAX_ATTEMPTS = 3
REPLACE_RETRY_DELAY_S = 0.05


@dataclass(frozen=True)
class JobPage:
    items: list[JobRecord]
    page: int
    per_page: int
    total: int
    total_pages: int


def _replace_with_retry(source: Path, destination: Path) -> None:
    for attempt in range(1, REPLACE_MAX_ATTEMPTS + 1):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == REPLACE_MAX_ATTEMPTS:
                raise
            time.sleep(REPLACE_RETRY_DELAY_S)


def atomic_write(path: Path, content: str) -> None:
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(content)
            temporary.close()
            _replace_with_retry(source=temporary_path, destination=path)
        finally:
            temporary_path.unlink(missing_ok=True)


class JobStore:
    def __init__(self, data_dir: Path) -> None:
        self.jobs_dir = data_dir / "jobs"
        # Course registry and documents live beside the jobs, in the same data dir.
        self.courses_dir = data_dir / "courses"

    def _job_dir(self, job_id: str) -> Path:
        try:
            identifier = UUID(job_id)
        except ValueError as error:
            raise NotFoundError(entity="Job", id=job_id) from error
        if identifier.version != 4:
            raise NotFoundError(entity="Job", id=job_id)
        path = self.jobs_dir / str(identifier)
        if not path.is_dir():
            raise NotFoundError(entity="Job", id=job_id)
        return path

    def create(self, config: JobConfig, source_name: str = "") -> JobRecord:
        now = datetime.now(tz=UTC)
        record = JobRecord(
            id=uuid4(),
            status=JobStatus.QUEUED,
            stage=JobStage.QUEUED,
            config=config,
            source_name=source_name,
            created_at=now,
            updated_at=now,
        )
        path = self.jobs_dir / str(record.id)
        path.mkdir(parents=True)
        atomic_write(path=path / "job.json", content=record.model_dump_json())
        return record

    def get(self, job_id: str) -> JobRecord:
        path = self._job_dir(job_id=job_id) / "job.json"
        return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def iter_records(self) -> Iterator[JobRecord]:
        for path in self.jobs_dir.glob("*/job.json"):
            yield JobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def _course_key(self, record: JobRecord) -> str:
        meta = self.read_meta(job_id=str(record.id))
        label = effective_course(course=meta.course, subject=record.config.subject)
        return normalized_course_key(label=label)

    def list(
        self, page: int = 1, per_page: int = 10, course_key: str | None = None
    ) -> JobPage:
        if page < 1 or per_page < 1:
            raise ValidationError(message="Pagina e dimensione devono essere positive")
        records = [
            record
            for record in self.iter_records()
            if course_key is None or self._course_key(record=record) == course_key
        ]
        records.sort(key=lambda record: record.created_at, reverse=True)
        total = len(records)
        start = (page - 1) * per_page
        return JobPage(
            items=records[start : start + per_page],
            page=page,
            per_page=per_page,
            total=total,
            total_pages=(total + per_page - 1) // per_page,
        )

    def update(self, record: JobRecord) -> JobRecord:
        validated = JobRecord.model_validate(record)
        original = self.get(job_id=str(validated.id))
        updated = validated.model_copy(
            update={
                "created_at": original.created_at,
                "updated_at": datetime.now(tz=UTC),
            }
        )
        path = self._job_dir(job_id=str(updated.id)) / "job.json"
        atomic_write(path=path, content=updated.model_dump_json())
        return updated

    def delete(self, job_id: str) -> None:
        shutil.rmtree(self._job_dir(job_id=job_id))

    def read_meta(self, job_id: str) -> LectureMeta:
        path = self._job_dir(job_id=job_id) / "meta.json"
        if not path.exists():
            return LectureMeta(course=None)
        return LectureMeta.model_validate_json(path.read_text(encoding="utf-8"))

    def write_meta(self, job_id: str, meta: LectureMeta) -> LectureMeta:
        path = self._job_dir(job_id=job_id) / "meta.json"
        validated = LectureMeta.model_validate(meta)
        atomic_write(path=path, content=validated.model_dump_json())
        return validated

    def read_progress(self, job_id: str) -> dict[str, JsonValue]:
        path = self._job_dir(job_id=job_id) / "progress.json"
        if not path.exists():
            return {}
        return PROGRESS_ADAPTER.validate_json(path.read_text(encoding="utf-8"))

    def write_progress(self, job_id: str, progress: dict[str, JsonValue]) -> None:
        path = self._job_dir(job_id=job_id) / "progress.json"
        atomic_write(path=path, content=json.dumps(progress, ensure_ascii=False))

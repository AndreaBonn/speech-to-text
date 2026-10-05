import re
from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field, field_validator

from sbobina.web.job_models import JobRecord

PackageKind = Literal[
    "transcript",
    "corrected",
    "meta",
    "study",
    "document",
    "text",
    "original",
    "generation",
    "cards",
]

PACKAGE_PATH_PATTERN = re.compile(
    r"(?:lectures/[0-9]+/(?:transcript|corrected|meta|study)\.json"
    r"|documents/[0-9]+/(?:document\.json|text\.json|original\.(?:pdf|docx|pptx|txt|md))"
    r"|generations/[0-9]+\.json|cards/cards\.jsonl)"
)
JOB_FIELD_EXPORT = {
    # Identity and provenance let the recipient remap references and name lectures.
    "id": True,
    "created_at": True,
    "updated_at": True,
    "source_name": True,
    # Runtime state, device configuration and nested study errors stay local.
    # So does the import marker: import_id names a course on this machine and
    # the recipient's import sets both fields for its own course.
    "imported": False,
    "import_id": False,
    "status": False,
    "stage": False,
    "config": False,
    "study": False,
    "pid": False,
    "error": False,
}


class ExportOptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    excluded_document_ids: frozenset[str] = frozenset()


class PackageCourse(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str


class InventoryEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    kind: PackageKind

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("Inventory paths cannot contain backslashes")
        if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
            raise ValueError("Inventory paths cannot be absolute")
        if ".." in value.split("/"):
            raise ValueError("Inventory paths cannot contain parent segments")
        if PACKAGE_PATH_PATTERN.fullmatch(string=value) is None:
            raise ValueError("Path is outside the audio-free package layout")
        return value


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    format_version: Literal[1]
    app_version: str
    package_id: UUID4
    created_at: datetime
    course: PackageCourse
    inventory: tuple[InventoryEntry, ...]
    options: ExportOptions

    @field_validator("format_version", mode="before")
    @classmethod
    def validate_format_version(cls, value: object) -> object:
        if isinstance(value, int) and value > 1:
            raise ValueError("Package created by a newer version")
        return value


def project_job(record: JobRecord) -> dict[str, Any]:
    """Export only explicitly classified identity and provenance fields."""
    fields = {field for field, exported in JOB_FIELD_EXPORT.items() if exported}
    return record.model_dump(mode="json", include=fields)

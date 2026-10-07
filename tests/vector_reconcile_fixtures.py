from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from conftest import make_segment, make_transcript, make_word

from sbobina.course_registry import CourseRecord, get_or_create
from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.models import save_transcript
from sbobina.ollama_embed import EmbeddedText, EmbeddingInput, ModelStatus
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.document_store import write_document, write_text
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore
from sbobina.web.vector_reconcile import CourseEmbedding, EmbeddingConfig
from sbobina.web.vector_store import VectorStore


@dataclass
class FakeEmbedder:
    calls: list[list[EmbeddingInput]] = field(default_factory=list)
    fail_batch: int | None = None
    truncated_text: str | None = None
    dimensions: int = 2

    def __call__(self, texts: Sequence[EmbeddingInput]) -> list[EmbeddedText]:
        self.calls.append(list(texts))
        if len(self.calls) == self.fail_batch:
            raise RuntimeError("Embedding interrupted")
        return [
            EmbeddedText(
                vector=[1.0] * self.dimensions,
                truncated=item.text == self.truncated_text,
            )
            for item in texts
        ]


def make_context(tmp_path: Path, fake: FakeEmbedder) -> CourseEmbedding:
    return CourseEmbedding(
        store=JobStore(data_dir=tmp_path),
        vectors=VectorStore(path=tmp_path / "vectors.sqlite3"),
        embedding=EmbeddingConfig(
            model="qwen3-embedding:8b",
            status=ModelStatus(digest="test-digest", dimensions=2),
            embedder=fake,
        ),
    )


def write_course(store: JobStore, label: str = "Diritto") -> CourseRecord:
    return get_or_create(courses_dir=store.courses_dir, key=label.lower(), label=label)


def write_pages(store: JobStore, course: CourseRecord, texts: list[str]) -> Path:
    document = CourseDocument(
        id=str(uuid4()),
        course_id=course.id,
        filename="materiale.pdf",
        kind=DocumentKind.PDF,
        size=10,
        sha256="0" * 64,
        status=DocumentStatus.READY,
        error=None,
        pages=len(texts),
        created_at=datetime.now(tz=UTC),
    )
    path = store.courses_dir / course.id / "documents" / document.id
    path.mkdir(parents=True)
    write_document(courses_dir=store.courses_dir, document=document)
    write_text(
        doc_dir=path,
        extracted=ExtractedText(
            pages=tuple(Page(text=text, no_text=False) for text in texts),
            status=DocumentStatus.READY,
        ),
    )
    return path


def write_lecture(store: JobStore, texts: list[str]) -> Path:
    job = store.create(config=JobConfig(subject="Diritto"))
    path = store.jobs_dir / str(job.id) / TRANSCRIPT_FILES["original"]
    replace_lecture(path=path, texts=texts)
    return path


def replace_lecture(path: Path, texts: list[str]) -> None:
    transcript = make_transcript(
        segments=[
            make_segment(words=[make_word(text=text, start=float(index))])
            for index, text in enumerate(texts)
        ]
    )
    save_transcript(transcript=transcript, path=path)

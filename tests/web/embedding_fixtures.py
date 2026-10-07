import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import ollama
import pytest
from vector_reconcile_fixtures import write_course, write_pages

from sbobina.web import embedding_supervisor
from sbobina.web.embedding_store import EmbeddingRun, load_embed
from sbobina.web.job_store import JobStore
from sbobina.web.supervisor import Supervisor, SupervisorOptions

RUNNER = """
import sys
import time
from functools import partial
from pathlib import Path
from sbobina.ollama_embed import EmbeddedText, ModelStatus
from sbobina.web.embedding_runner import run_embed
from sbobina.web.job_store import JobStore
from sbobina.web.vector_reconcile import CourseEmbedding, EmbeddingConfig, embed_course
from sbobina.web.vector_store import VectorStore

stage, directory = sys.argv[1:]
path = Path(directory)
(path / (stage + '.started')).touch()
exit_path = path / 'embed.exit'
if exit_path.exists():
    exit_code = int(exit_path.read_text())
    if exit_code < 0:
        import os
        os.kill(os.getpid(), -exit_code)
    sys.exit(exit_code)
calls = 0
def embedder(texts):
    global calls
    calls += 1
    if calls == 2:
        (path / 'batch.saved').touch()
        while (path / 'hold').exists():
            time.sleep(0.01)
    return [EmbeddedText(vector=[1.0, 0.0], truncated=False) for item in texts]
context = CourseEmbedding(
    store=JobStore(data_dir=path.parent.parent),
    vectors=VectorStore(path=path.parent.parent / 'vectors.sqlite3'),
    embedding=EmbeddingConfig(model='test',
        status=ModelStatus(digest='digest', dimensions=2), embedder=embedder),
)
run_embed(course_dir=path, embed=partial(embed_course, context=context))
"""


@dataclass
class EmbeddingHarness:
    store: JobStore
    supervisor: Supervisor
    course_dir: Path
    released: list[tuple[str, int]] = field(default_factory=list)

    def record(self) -> EmbeddingRun:
        record = load_embed(course_dir=self.course_dir)
        assert record is not None
        return record


@pytest.fixture
def embedding_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[EmbeddingHarness]:
    store = JobStore(data_dir=tmp_path)
    course = write_course(store=store)
    write_pages(store=store, course=course, texts=[f"norma {i}" for i in range(33)])
    child = tmp_path / "embed_child.py"
    child.write_text(RUNNER, encoding="utf-8")
    supervisor = Supervisor(
        job_store=store,
        options=SupervisorOptions(
            command=(sys.executable, str(child)),
            terminate_timeout_s=0.1,
        ),
    )
    harness = EmbeddingHarness(
        store=store,
        supervisor=supervisor,
        course_dir=store.courses_dir / course.id,
    )
    _install_fakes(harness=harness, monkeypatch=monkeypatch)
    try:
        yield harness
    finally:
        supervisor.stop()


def _install_fakes(harness: EmbeddingHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    class ReleaseClient:
        def ps(self) -> ollama.ProcessResponse:
            model = "chat:9b" if not harness.released else "test"
            return ollama.ProcessResponse(
                models=[ollama.ProcessResponse.Model(model=model)]
            )

        def generate(self, *, model: str, keep_alive: int) -> None:
            harness.released.append((model, keep_alive))

    monkeypatch.setattr(ollama, "Client", lambda **kwargs: ReleaseClient())
    monkeypatch.setattr(
        embedding_supervisor, "estimate_embed_seconds", lambda **kw: 10.0
    )

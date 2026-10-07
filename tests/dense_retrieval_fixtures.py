from collections.abc import Sequence
from pathlib import Path

from ollama_embed_fixtures import FakeClient

from sbobina.embedding_units import content_hash
from sbobina.ollama_embed import ModelStatus
from sbobina.retrieval import DocumentSource, LectureSource, RetrievedPassage
from sbobina.web.dense_retrieval import DenseRanker
from sbobina.web.vector_reconcile import embedding_model_key
from sbobina.web.vector_store import StoredVector, VectorStore

MODEL = "qwen3-embedding:8b"
STATUS = ModelStatus(digest="dense-test", dimensions=2)
COURSE = "diritto"


def document(number: int) -> RetrievedPassage:
    return RetrievedPassage(
        text=f"contratto documento {number}",
        source=DocumentSource(doc_id="document", page=1, chunk=number),
        passage_id=f"document:p1:c{number}",
    )


def lecture(number: int) -> RetrievedPassage:
    return RetrievedPassage(
        text=f"contratto lezione {number}",
        source=LectureSource(
            job_id="lecture", segment_index=number, start=float(number)
        ),
        passage_id=f"Llecture-S{number}",
    )


def populate(
    vectors: VectorStore,
    passages: list[RetrievedPassage],
    values: Sequence[tuple[float, ...]],
    model: str = MODEL,
) -> None:
    vectors.sync_units(
        course=COURSE,
        units={item.passage_id: content_hash(item.text) for item in passages},
    )
    vectors.put_vectors(
        model_key=embedding_model_key(model=model, status=STATUS),
        vectors=[
            StoredVector(
                text_sha256=content_hash(item.text), vector=value, truncated=False
            )
            for item, value in zip(passages, values)
        ],
    )


def ranker(
    tmp_path: Path, model: str = MODEL
) -> tuple[DenseRanker, VectorStore, FakeClient]:
    vectors = VectorStore(path=tmp_path / "vectors.sqlite3")
    client = FakeClient()
    client.vectors = [[1.0, 0.0]]
    dense = DenseRanker(vectors=vectors, model=model, status=STATUS, client=client)
    return dense, vectors, client

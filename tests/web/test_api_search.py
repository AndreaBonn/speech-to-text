import logging
import threading
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest
from conftest import make_segment, make_transcript, make_word
from fastapi.testclient import TestClient

from sbobina.models import save_transcript
from sbobina.settings import Settings
from sbobina.web import search_index, search_service
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig, JobStatus, LectureMeta
from sbobina.web.job_store import JobStore
from sbobina.web.search_index import SearchCorruptError, SearchUnavailableError

BASE_URL = "http://127.0.0.1:8765"
SEARCH_URL = "/api/v1/search"


def test_search_openapi_exposes_query_and_lecture_pagination(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    operation = app.openapi()["paths"][SEARCH_URL]["get"]
    parameters = {item["name"]: item for item in operation["parameters"]}
    assert set(parameters) == {"q", "course", "page", "per_page"}
    assert parameters["q"]["required"] is True
    assert parameters["page"]["schema"]["minimum"] == 1
    assert parameters["per_page"]["schema"]["default"] == 20


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    transport = TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})
    yield transport
    transport.close()


def write_transcript(directory: Path, texts: list[str]) -> None:
    transcript = make_transcript(
        segments=[
            make_segment(words=[make_word(text=text, start=2472.0 + index * 10)])
            for index, text in enumerate(texts)
        ]
    )
    save_transcript(transcript=transcript, path=directory / "audio.json")


@pytest.fixture
def lectures(tmp_path: Path) -> list[str]:
    store = JobStore(data_dir=tmp_path)
    texts = [
        ["causa contratto"] * 4,
        ["la causa del contratto è discussa insieme a molti altri argomenti di fisica"],
        ["causa senza accordo"],
    ]
    identifiers = []
    for index, subject in enumerate(("Diritto", "Fisica", None)):
        record = store.create(
            config=JobConfig(subject=subject), source_name=f"Lezione {index}.m4a"
        )
        store.update(record=record.model_copy(update={"status": JobStatus.DONE}))
        job_id = str(record.id)
        identifiers.append(job_id)
        write_transcript(directory=store.jobs_dir / job_id, texts=texts[index])
    store.write_meta(job_id=identifiers[0], meta=LectureMeta(course="Diritto privato"))
    return identifiers


def test_search_ranks_and_groups_lectures_with_complete_meta(
    client: TestClient, lectures: list[str]
) -> None:
    response = client.get(url=SEARCH_URL, params={"q": "causa contratto"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"] == {
        "page": 1,
        "per_page": 20,
        "total": 2,
        "total_pages": 1,
        "documents_total": 0,
    }
    assert [item["id"] for item in payload["data"]] == lectures[:2]
    first = payload["data"][0]
    assert first["title"] == "Lezione 0.m4a"
    assert first["course"] == "Diritto privato"
    assert first["passage_count"] == 4
    assert [part["start"] for part in first["passages"]] == [2472.0, 2482.0, 2492.0]
    assert first["passages"][0] == {
        "start": 2472.0,
        "variant": "original",
        "snippet": [
            {"text": "causa", "match": True},
            {"text": " ", "match": False},
            {"text": "contratto", "match": True},
        ],
        "href": f"/lettore/{lectures[0]}?t=2472.0&variant=original",
    }


def test_search_paginates_lectures_instead_of_passages(
    client: TestClient, lectures: list[str]
) -> None:
    response = client.get(
        url=SEARCH_URL, params={"q": "causa contratto", "page": 2, "per_page": 1}
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [lectures[1]]
    assert response.json()["meta"] == {
        "page": 2,
        "per_page": 1,
        "total": 2,
        "total_pages": 2,
        "documents_total": 0,
    }


@pytest.mark.parametrize("query", ['""', "", "   ", "***", "x"])
def test_search_rejects_cleaned_empty_query(client: TestClient, query: str) -> None:
    response = client.get(url=SEARCH_URL, params={"q": query})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"][0]["field"] == "q"


@pytest.mark.parametrize(
    "course, index", [("diritto privato", 0), ("fisica", 1), ("", 2)]
)
def test_search_filters_course_including_uncategorized(
    client: TestClient, lectures: list[str], course: str, index: int
) -> None:
    response = client.get(url=SEARCH_URL, params={"q": "causa", "course": course})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [lectures[index]]
    assert response.json()["meta"]["total"] == 1
    assert (
        response.json()["data"][0]["course"]
        == ("Diritto privato", "Fisica", None)[index]
    )


@pytest.mark.parametrize("code", ["SEARCH_UNAVAILABLE", "SEARCH_CORRUPT"])
def test_search_returns_service_error_envelope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    error_type = (
        SearchUnavailableError if code == "SEARCH_UNAVAILABLE" else SearchCorruptError
    )

    def unavailable(
        store: JobStore,
        path: Path,
        query: search_service.SearchQuery,
        passages_per_lecture: int,
    ) -> search_service.LectureResults:
        raise error_type(message="Ricerca non disponibile", code=code)

    monkeypatch.setattr(search_service, "search_lectures", unavailable)
    response = client.get(url=SEARCH_URL, params={"q": "causa"})
    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": code, "message": "Ricerca non disponibile"}
    }


def test_search_finds_manual_edit_without_restart(
    client: TestClient, lectures: list[str]
) -> None:
    url = f"/api/v1/jobs/{lectures[0]}/transcript/corrected"
    assert client.post(url=url).status_code == 201
    before = client.get(url=SEARCH_URL, params={"q": "causa contratto"})
    assert before.json()["data"][0]["passages"][0]["variant"] == "corrected"
    revision = client.get(
        url=f"/api/v1/jobs/{lectures[0]}/transcript?variant=corrected"
    ).json()["meta"]["revision"]
    edited = client.patch(
        url=url,
        json={
            "start": 0,
            "end": 1,
            "expected": "causa contratto",
            "text": "sopravvenienza",
            "revision": revision,
        },
    )
    assert edited.status_code == 200
    response = client.get(url=SEARCH_URL, params={"q": "sopravvenienza"})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [lectures[0]]
    assert response.json()["data"][0]["passages"][0] == {
        "start": 2472.0,
        "variant": "corrected",
        "snippet": [{"text": "sopravvenienza", "match": True}],
        "href": f"/lettore/{lectures[0]}?t=2472.0&variant=corrected",
    }


def test_search_preserves_literal_html_in_snippet(
    client: TestClient, tmp_path: Path, lectures: list[str]
) -> None:
    write_transcript(
        directory=tmp_path / "jobs" / lectures[0], texts=["<script>causa</script>"]
    )
    response = client.get(
        url=SEARCH_URL, params={"q": "causa", "course": "diritto privato"}
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["passages"][0]["snippet"] == [
        {"text": "<script>", "match": False},
        {"text": "causa", "match": True},
        {"text": "</script>", "match": False},
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"q": "inesistente"},
        {"q": "causa", "course": "inesistente"},
        {"q": "causa contratto", "page": "3", "per_page": "1"},
    ],
)
def test_search_empty_results_have_complete_meta(
    client: TestClient, lectures: list[str], params: dict[str, str]
) -> None:
    assert client.get(url=SEARCH_URL, params={"q": "causa"}).json()["data"]
    response = client.get(url=SEARCH_URL, params=params)
    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "meta": {
            "page": int(params.get("page", "1")),
            "per_page": int(params.get("per_page", "20")),
            "total": 2 if "page" in params else 0,
            "total_pages": 2 if "page" in params else 0,
            "documents_total": 0,
        },
    }


@pytest.mark.parametrize(
    "params", [{}, {"q": "causa", "page": "0"}, {"q": "causa", "per_page": "0"}]
)
def test_search_rejects_missing_query_or_invalid_pagination(
    client: TestClient, params: dict[str, str]
) -> None:
    response = client.get(url=SEARCH_URL, params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_lifespan_reconciles_existing_lectures_before_requests(
    tmp_path: Path, lectures: list[str]
) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL):
        path = tmp_path / "search.sqlite3"
        assert path.is_file()
        with closing(search_index.open_index(path=path)) as index:
            assert set(index.indexed_lectures()) == set(lectures)


def test_lifespan_logs_search_failure_off_loop_and_still_serves_courses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    threads = []

    def unavailable(path: Path) -> search_index.SearchIndex:
        threads.append(threading.get_ident())
        raise SearchUnavailableError(
            message="Ricerca non disponibile", code="SEARCH_UNAVAILABLE"
        )

    monkeypatch.setattr(search_index, "open_index", unavailable)
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with (
        caplog.at_level(logging.WARNING),
        TestClient(app=app, base_url=BASE_URL) as client,
    ):
        assert client.get(url="/api/v1/courses").status_code == 200
    warnings = [record for record in caplog.records if record.name == "sbobina.web.app"]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    assert warnings[0].exc_info is not None
    assert threads and threads[0] != warnings[0].thread

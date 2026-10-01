from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from conftest import make_segment, make_transcript, make_word
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sbobina.cli import main
from sbobina.models import save_transcript
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
WER_URL = "/api/v1/wer"
REFERENCE = "il teorema di Heisenberg vale sempre"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(
        create_app(settings=Settings(), data_dir=tmp_path),
        base_url=BASE_URL,
        headers={"Origin": BASE_URL},
    ) as test_client:
        yield test_client


@pytest.fixture
def job_dir(client: TestClient) -> Path:
    store: JobStore = cast(FastAPI, client.app).state.job_store
    record = store.create(config=JobConfig())
    directory = store.jobs_dir / str(record.id)
    words = [
        make_word(text, float(index))
        for index, text in enumerate((" il", " teorema", " di", " Sennberg", " vale"))
    ]
    save_transcript(make_transcript([make_segment(words)]), directory / "audio.json")
    return directory


def test_wer_against_job_matches_cli(
    client: TestClient,
    job_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reference_path = tmp_path / "riferimento.txt"
    reference_path.write_text(REFERENCE, encoding="utf-8")
    main(["wer", str(reference_path), str(job_dir / "audio.json")])
    cli_line = capsys.readouterr().out.strip()

    response = client.post(
        WER_URL,
        files={"reference": ("riferimento.txt", REFERENCE.encode(), "text/plain")},
        data={"job_id": job_dir.name, "variant": "original"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {
        "wer": pytest.approx(2 / 6),
        "reference_words": 6,
        "substitutions": 1,
        "deletions": 1,
        "insertions": 0,
    }
    assert cli_line.startswith(f"WER {data['wer']:.2%} su 6 parole")


def test_wer_against_hypothesis_file(client: TestClient) -> None:
    response = client.post(
        WER_URL,
        files={
            "reference": ("r.txt", REFERENCE.encode(), "text/plain"),
            "hypothesis": ("h.txt", REFERENCE.encode(), "text/plain"),
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["wer"] == 0.0


def test_wer_corrected_variant_without_correction_returns_404(
    client: TestClient, job_dir: Path
) -> None:
    response = client.post(
        WER_URL,
        files={"reference": ("r.txt", REFERENCE.encode(), "text/plain")},
        data={"job_id": job_dir.name, "variant": "corrected"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    ("files", "data", "field"),
    [
        ({"reference": ("r.txt", b"\xff\xfe\x00bad", "text/plain")}, {}, "reference"),
        (
            {"reference": ("r.txt", b" ... ", "text/plain")},
            {"job_id": "x"},
            "reference",
        ),
        ({"reference": ("r.txt", REFERENCE.encode(), "text/plain")}, {}, "hypothesis"),
    ],
)
def test_wer_invalid_input_returns_field_error(
    client: TestClient,
    job_dir: Path,
    files: dict[str, tuple[str, bytes, str]],
    data: dict[str, str],
    field: str,
) -> None:
    if data.get("job_id") == "x":
        data = {"job_id": job_dir.name}

    response = client.post(WER_URL, files=files, data=data)

    assert response.status_code == 422
    fields = [detail["field"] for detail in response.json()["error"]["details"]]
    assert fields == [field]

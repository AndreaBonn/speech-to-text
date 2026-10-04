import logging
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from practice_grading_fixtures import (
    TEXT,
    JudgeSpy,
    app,
    attempt_url,
    client,
    judge,
    submission,
)

__all__ = ["app", "attempt_url", "client", "judge"]


def test_busy_saves_before_retry(
    client: TestClient,
    app: FastAPI,
    attempt_url: str,
    judge: JudgeSpy,
    caplog: pytest.LogCaptureFixture,
) -> None:
    url = f"{attempt_url}/answers/0"
    with (
        app.state.gpu_arbiter.transcription_lease(stage="TRANSCRIBING"),
        caplog.at_level(level=logging.WARNING, logger="sbobina.web.practice_grading"),
    ):
        response = client.post(url=url, json=submission())
    assert "GPU busy" in caplog.text
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ungraded"
    assert response.json()["data"]["reason"] == "GPU_BUSY"
    assert judge.calls == 0
    saved = client.get(url=attempt_url).json()["data"]["answers"][0]
    assert (saved["text"], saved["status"]) == (TEXT, "ungraded")
    response = client.post(url=f"{url}/grade")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "graded"
    assert judge.calls == 1


def test_judge_observes_persisted_ungraded_answer(
    client: TestClient,
    attempt_url: str,
    judge: JudgeSpy,
) -> None:
    def check_saved() -> None:
        saved = client.get(url=attempt_url).json()["data"]["answers"][0]
        assert (saved["text"], saved["status"]) == (TEXT, "ungraded")

    judge.before_call = check_saved
    response = client.post(url=f"{attempt_url}/answers/0", json=submission())
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["outcome"], data["score"], data["is_suggestion"]) == (
        "corretta",
        1,
        True,
    )
    assert data["judgement"]["covered_points"][0]["evidence"] == TEXT
    assert judge.calls == 1


@pytest.mark.parametrize(
    "failure_case",
    [
        ("unavailable", "OLLAMA_UNAVAILABLE", 1),
        ("invalid", "GRADING_FAILED", 2),
    ],
)
def test_judge_failure_preserves_text_and_retry(
    client: TestClient,
    attempt_url: str,
    judge: JudgeSpy,
    failure_case: tuple[str, str, int],
) -> None:
    failure, reason, calls = failure_case
    setattr(judge, failure, True)
    url = f"{attempt_url}/answers/0"
    response = client.post(url=url, json=submission())
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["status"], data["reason"], data["text"]) == ("ungraded", reason, TEXT)
    saved = client.get(url=attempt_url).json()["data"]["answers"][0]
    assert (saved["text"], saved["status"]) == (TEXT, "ungraded")
    setattr(judge, failure, False)
    assert client.post(url=f"{url}/grade").json()["data"]["status"] == "graded"
    assert judge.calls == calls + 1


@pytest.mark.parametrize("parallel", [False, True])
def test_duplicate_answer_id_calls_once(
    client: TestClient,
    attempt_url: str,
    judge: JudgeSpy,
    parallel: bool,
) -> None:
    body = submission()

    def send() -> dict[str, object]:
        response = client.post(url=f"{attempt_url}/answers/0", json=body)
        assert response.status_code == 200
        return dict(response.json()["data"])

    if parallel:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(send) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
    else:
        results = [send(), send()]
    assert results[0] == results[1]
    assert judge.calls == 1
    saved = client.get(url=attempt_url).json()["data"]["answers"]
    assert len(saved) == 1
    assert saved[0]["answer_id"] == body["answer_id"]


@pytest.mark.parametrize(
    "invalid",
    [
        {"answer_id": "invalid"},
        {"answer_id": "00000000-0000-1000-8000-000000000000"},
        {"text": ""},
        {"text": " \n "},
    ],
)
def test_invalid_submission_returns_422(
    client: TestClient,
    attempt_url: str,
    invalid: dict[str, str],
) -> None:
    url = f"{attempt_url}/answers/0"
    response = client.post(url=url, json={**submission(), **invalid})
    assert response.status_code == 422
    assert client.get(url=attempt_url).json()["data"]["answers"] == []
    assert client.post(url=url, json=submission()).status_code == 200
    assert len(client.get(url=attempt_url).json()["data"]["answers"]) == 1

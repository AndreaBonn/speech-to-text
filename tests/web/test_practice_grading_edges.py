from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from practice_grading_fixtures import (
    JudgeSpy,
    app,
    attempt_url,
    client,
    judge,
    submission,
)

__all__ = ["app", "attempt_url", "client", "judge"]


@pytest.mark.parametrize("change", ["id", "text", "question"])
def test_conflicting_submission_preserves_original(
    client: TestClient,
    attempt_url: str,
    judge: JudgeSpy,
    change: str,
) -> None:
    body = submission()
    url = f"{attempt_url}/answers/0"
    assert client.post(url=url, json=body).status_code == 200
    conflicting = {**body, "answer_id": str(uuid4())} if change == "id" else dict(body)
    if change == "text":
        conflicting["text"] = "Different answer"
    if change == "question":
        url = f"{attempt_url}/answers/1"
    assert client.post(url=url, json=conflicting).status_code == 409
    saved = client.get(url=attempt_url).json()["data"]["answers"]
    assert [(answer["answer_id"], answer["text"]) for answer in saved] == [
        (body["answer_id"], body["text"])
    ]
    assert judge.calls == 1


@pytest.mark.parametrize("action", ["grade", "self-grade"])
def test_missing_or_invalid_grade_rejected(
    client: TestClient,
    attempt_url: str,
    action: str,
) -> None:
    url = f"{attempt_url}/answers/0"
    assert (
        client.post(url=f"{url}/{action}", json={"outcome": "errata"}).status_code
        == 404
    )
    assert client.post(url=url, json=submission()).status_code == 200
    assert (
        client.post(url=f"{url}/self-grade", json={"outcome": "invalid"}).status_code
        == 422
    )
    assert (
        client.post(url=f"{url}/{action}", json={"outcome": "errata"}).status_code
        == 200
    )


def test_concurrent_questions_preserve_all_answers(
    client: TestClient,
    attempt_url: str,
    judge: JudgeSpy,
) -> None:
    def send(index: int) -> int:
        status: int = client.post(
            url=f"{attempt_url}/answers/{index}", json=submission()
        ).status_code
        return status

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(send, (0, 1))) == [200, 200]
    saved = client.get(url=attempt_url).json()["data"]
    assert saved["status"] == "graded"
    assert [answer["question_index"] for answer in saved["answers"]] == [0, 1]
    assert judge.calls == 2


def test_judge_calls_for_different_questions_overlap(
    client: TestClient,
    attempt_url: str,
    judge: JudgeSpy,
) -> None:
    # Both judge calls must be in flight at once: holding the attempt lock
    # across the Ollama call would make the second wait for the first, and the
    # barrier would break instead of releasing both.
    barrier = Barrier(parties=2, timeout=5)

    def wait_for_both() -> None:
        barrier.wait()

    judge.before_call = wait_for_both

    def send(index: int) -> int:
        status: int = client.post(
            url=f"{attempt_url}/answers/{index}", json=submission()
        ).status_code
        return status

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(send, (0, 1)))

    assert statuses == [200, 200]
    assert judge.calls == 2
    assert client.get(url=attempt_url).json()["data"]["status"] == "graded"


def test_self_mode_on_gpu_can_be_changed(
    client: TestClient,
    app: FastAPI,
    attempt_url: str,
    judge: JudgeSpy,
) -> None:
    app.state.settings.practice_grading_mode = "self"
    first = client.post(url=f"{attempt_url}/answers/0", json=submission())
    assert first.json()["data"]["status"] == "ungraded"
    assert judge.calls == 0
    app.state.settings.practice_grading_mode = "judge"
    second = client.post(url=f"{attempt_url}/answers/1", json=submission())
    assert second.json()["data"]["status"] == "graded"
    assert judge.calls == 1
    assert client.get(url=attempt_url).json()["data"]["status"] == "submitted"


def test_self_grade_can_create_and_clear_mistake(
    client: TestClient,
    attempt_url: str,
) -> None:
    url = f"{attempt_url}/answers/0"
    client.post(url=url, json=submission())
    client.post(url=f"{url}/self-grade", json={"outcome": "parziale"})
    mistakes = client.get(url="/api/v1/courses/fisica/mistakes").json()["data"]
    assert [(item["outcome"], item["is_suggestion"]) for item in mistakes] == [
        ("parziale", False)
    ]
    client.post(url=f"{url}/self-grade", json={"outcome": "corretta"})
    assert client.get(url="/api/v1/courses/fisica/mistakes").json()["data"] == []


def test_unanchored_judge_evidence_is_discarded(
    client: TestClient,
    attempt_url: str,
) -> None:
    response = client.post(
        url=f"{attempt_url}/answers/0",
        json={**submission(), "text": "Non so rispondere alla domanda."},
    )
    data = response.json()["data"]
    # F42: credit with no evidence in the answer is no grade, never "errata".
    assert (data["outcome"], data["status"], data["reason"]) == (
        None,
        "ungraded",
        "GRADING_FAILED",
    )
    assert data["judgement"] is None
    valid = client.post(url=f"{attempt_url}/answers/1", json=submission()).json()[
        "data"
    ]
    assert valid["outcome"] == "corretta"
    assert len(valid["judgement"]["covered_points"]) == 1


def test_self_grade_during_judge_call_wins_over_judgement(
    client: TestClient,
    attempt_url: str,
    judge: JudgeSpy,
) -> None:
    url = f"{attempt_url}/answers/0"

    def self_grade_meanwhile() -> None:
        # Runs inside the judge call: the attempt lock must be free by now.
        with ThreadPoolExecutor(max_workers=1) as executor:
            response = executor.submit(
                client.post, url=f"{url}/self-grade", json={"outcome": "errata"}
            ).result(timeout=5)
        assert response.status_code == 200

    judge.before_call = self_grade_meanwhile

    response = client.post(url=url, json=submission())

    assert response.status_code == 200
    answer = client.get(url=attempt_url).json()["data"]["answers"][0]
    assert answer["status"] == "self_graded"
    assert answer["self_grade"] == "errata"
    assert answer["judgement"] is None
    assert judge.calls == 1


def test_text_answer_for_another_generation_is_not_found(
    client: TestClient, attempt_url: str, judge: JudgeSpy
) -> None:
    prefix, _, rest = attempt_url.partition("/generations/")
    attempt_id = rest.rsplit("/", maxsplit=1)[1]
    foreign = f"{prefix}/generations/{uuid4()}/attempts/{attempt_id}/answers/0"

    response = client.post(url=foreign, json=submission())

    assert response.status_code == 404
    assert client.get(url=attempt_url).json()["data"]["answers"] == []
    assert judge.calls == 0


def test_text_answer_question_out_of_range_is_not_found(
    client: TestClient, attempt_url: str, judge: JudgeSpy
) -> None:
    response = client.post(url=f"{attempt_url}/answers/99", json=submission())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert judge.calls == 0


def test_text_answer_malformed_attempt_id_is_not_found(
    client: TestClient, attempt_url: str
) -> None:
    malformed = attempt_url.rsplit("/", maxsplit=1)[0] + "/not-a-uuid"

    response = client.post(url=f"{malformed}/answers/0", json=submission())

    assert response.status_code == 404

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from practice_grading_fixtures import (
    JudgeSpy,
    app,
    attempt_url,
    client,
    fake_platform,
    judge,
    submission,
)

from sbobina import platform_info

__all__ = ["app", "attempt_url", "client", "judge"]


@pytest.mark.parametrize(
    "outcome,score", [("corretta", 1), ("parziale", 0.5), ("errata", 0)]
)
def test_self_grade_overrides_preserving_judgement(
    client: TestClient,
    attempt_url: str,
    outcome: str,
    score: float,
) -> None:
    url = f"{attempt_url}/answers/0"
    graded = client.post(url=url, json=submission()).json()["data"]
    assert graded["is_suggestion"] is True
    response = client.post(url=f"{url}/self-grade", json={"outcome": outcome})
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["outcome"], data["score"], data["status"]) == (
        outcome,
        score,
        "self_graded",
    )
    assert data["judgement"] == graded["judgement"]
    assert data["is_suggestion"] is False
    assert client.post(url=f"{url}/grade").json()["data"] == data
    saved = client.get(url=attempt_url).json()["data"]["answers"][0]
    assert saved["self_grade"] == outcome
    assert saved["judgement"]["covered_points"] == data["judgement"]["covered_points"]


def test_cpu_defaults_to_self_grade_until_explicit_grade(
    client: TestClient,
    attempt_url: str,
    judge: JudgeSpy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        platform_info, "detect_platform", lambda: fake_platform(cuda=False)
    )
    url = f"{attempt_url}/answers/0"
    response = client.post(url=url, json=submission())
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ungraded"
    assert response.json()["data"]["grading_mode"] == "self"
    assert judge.calls == 0
    assert client.post(url=f"{url}/grade").json()["data"]["status"] == "graded"
    assert judge.calls == 1


def test_mode_override_allows_judge_on_cpu(
    client: TestClient,
    app: FastAPI,
    attempt_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        platform_info, "detect_platform", lambda: fake_platform(cuda=False)
    )
    app.state.settings.practice_grading_mode = "judge"
    response = client.post(url=f"{attempt_url}/answers/0", json=submission())
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "graded"
    assert response.json()["data"]["grading_mode"] == "judge"

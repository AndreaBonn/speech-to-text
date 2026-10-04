from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from generation_api_fixtures import _register_course, _store, client
from ollama import ChatResponse, Message
from test_api_practice import make_url
from test_practice_store import make_generation

from sbobina import ollama_chat
from sbobina.generation_models import GenerationFormat
from sbobina.web.practice_store import create_attempt, load_attempt

__all__ = ["client"]


@pytest.fixture
def attempt_url(client: TestClient, tmp_path: Path) -> str:
    course_id = _register_course(tmp_path=tmp_path)
    generation = make_generation(
        courses_dir=_store(tmp_path=tmp_path).courses_dir, course_id=course_id
    )
    response = client.post(url=make_url(generation=generation))
    assert response.status_code == 201
    return f"{make_url(generation=generation)}/{response.json()['data']['id']}"


@pytest.mark.parametrize("choice,expected", [(2, ("corretta", 1)), (0, ("errata", 0))])
def test_choice_grades_reveals_and_persists(
    client: TestClient, attempt_url: str, choice: int, expected: tuple[str, float]
) -> None:
    response = client.post(url=f"{attempt_url}/answers/0", json={"choice": choice})
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["outcome"], data["score"]) == expected
    assert data["correct_index"] == 2
    assert data["solution"] == "Expected explanation"
    assert data["citations"][0]["quote"] == "Original source"
    saved = client.get(url=attempt_url).json()["data"]
    assert saved["answers"][0]["chosen_index"] == choice
    assert saved["answers"][0]["status"] == "graded"
    assert saved["questions"][0]["solution"] == data["solution"]
    assert "solution" not in saved["questions"][1]


@pytest.mark.parametrize("choice", [4, -1, True, "2", 1.5, None])
def test_choice_invalid_returns_422(
    client: TestClient, attempt_url: str, choice: object
) -> None:
    response = client.post(url=f"{attempt_url}/answers/0", json={"choice": choice})
    assert response.status_code == 422
    assert client.get(url=attempt_url).json()["data"]["answers"] == []
    assert (
        client.post(url=f"{attempt_url}/answers/0", json={"choice": 2}).status_code
        == 200
    )


def test_choice_duplicate_returns_409(client: TestClient, attempt_url: str) -> None:
    url = f"{attempt_url}/answers/0"
    assert client.post(url=url, json={"choice": 2}).status_code == 200
    response = client.post(url=url, json={"choice": 0})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANSWER_ALREADY_SUBMITTED"
    saved = client.get(url=attempt_url).json()["data"]
    assert len(saved["answers"]) == 1
    assert saved["answers"][0]["chosen_index"] == 2


def test_choice_never_calls_chat_json(
    client: TestClient, attempt_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = Mock(wraps=ollama_chat.chat_json)
    monkeypatch.setattr(ollama_chat, "chat_json", spy)
    response = client.post(url=f"{attempt_url}/answers/0", json={"choice": 2})
    assert response.status_code == 200
    assert response.json()["data"]["outcome"] == "corretta"
    spy.assert_not_called()


def test_chat_json_spy_observes_real_boundary_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = Mock(wraps=ollama_chat.chat_json)
    monkeypatch.setattr(ollama_chat, "chat_json", spy)
    fake_client = Mock()
    fake_client.chat.return_value = ChatResponse(
        message=Message(role="assistant", content='{"punti_coperti": []}')
    )
    request = ollama_chat.ChatRequest(
        model="fake", system_prompt="Judge", user_message="Answer", schema={}
    )
    assert (
        ollama_chat.chat_json(client=fake_client, request=request)
        == '{"punti_coperti": []}'
    )
    spy.assert_called_once_with(client=fake_client, request=request)


@pytest.mark.parametrize("index", [-1, 2])
def test_choice_missing_question_returns_404(
    client: TestClient, attempt_url: str, index: int
) -> None:
    response = client.post(url=f"{attempt_url}/answers/{index}", json={"choice": 2})
    assert response.status_code == 404


def test_choice_wrong_generation_course_or_attempt_returns_404(
    client: TestClient, attempt_url: str, tmp_path: Path
) -> None:
    _register_course(tmp_path=tmp_path, key="altro")
    pieces = attempt_url.split("/")
    generation_id = pieces[-3]
    for url in (
        attempt_url.replace(generation_id, str(uuid4())),
        attempt_url.replace("/fisica/", "/altro/"),
        attempt_url.replace(pieces[-1], "invalid"),
    ):
        assert (
            client.post(url=f"{url}/answers/0", json={"choice": 2}).status_code == 404
        )
    assert (
        client.post(url=f"{attempt_url}/answers/0", json={"choice": 2}).status_code
        == 200
    )


def test_choice_text_format_returns_422(client: TestClient, tmp_path: Path) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    generation = make_generation(courses_dir=courses_dir, course_id=course_id)
    question = replace(generation.questions[0], options=(), correct_index=None)
    generation = replace(
        generation, format=GenerationFormat.OPEN, questions=(question,)
    )
    attempt = create_attempt(
        courses_dir=courses_dir, course_id=course_id, generation=generation
    )
    url = f"{make_url(generation=generation)}/{attempt.id}/answers/0"
    assert client.post(url=url, json={"choice": 2}).status_code == 422
    assert (
        load_attempt(
            courses_dir=courses_dir, course_id=course_id, attempt_id=attempt.id
        ).answers
        == ()
    )


@pytest.mark.parametrize(
    "indices,expected", [((0, 0), [200, 409]), ((0, 1), [200, 200])]
)
def test_choice_concurrent_submissions_preserve_answers(
    client: TestClient, attempt_url: str, indices: tuple[int, int], expected: list[int]
) -> None:
    def submit(index: int) -> int:
        response = client.post(url=f"{attempt_url}/answers/{index}", json={"choice": 2})
        status: int = response.status_code
        return status

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(submit, indices))
    assert sorted(statuses) == expected
    saved = client.get(url=attempt_url).json()["data"]
    assert len(saved["answers"]) == len(set(indices))
    assert saved["status"] == ("graded" if len(set(indices)) == 2 else "in_progress")

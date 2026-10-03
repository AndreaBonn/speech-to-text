from threading import Barrier, Thread

import httpx
from chat_api_fixtures import ANSWER, ChatApp, chat_app

from sbobina.correction import CorrectorUnavailableError
from sbobina.ollama_chat import ChatRequest

__all__ = ["chat_app"]

GUARD_S = 5.0


def _questions(chat_app: ChatApp, chat_id: str) -> list[object]:
    return [
        line["text"] for line in chat_app.lines(chat_id) if line["kind"] == "question"
    ]


def test_gpu_busy_is_409_with_stage_and_keeps_the_question(chat_app: ChatApp) -> None:
    chat_id = chat_app.new_chat()

    with chat_app.arbiter.transcription_lease(stage="transcribing"):
        response = chat_app.ask(chat_id=chat_id, question="causa del contratto?")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "GPU_BUSY"
    assert {"field": "stage", "message": "transcribing"} in error["details"]
    assert _questions(chat_app=chat_app, chat_id=chat_id) == ["causa del contratto?"]


def test_ollama_down_is_503_and_keeps_the_question(chat_app: ChatApp) -> None:
    def down(request: ChatRequest) -> str:
        raise CorrectorUnavailableError("ConnectionError: refused")

    chat_app.model.behaviour = down
    chat_id = chat_app.new_chat()

    response = chat_app.ask(chat_id=chat_id, question="causa del contratto?")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "OLLAMA_UNAVAILABLE"
    assert _questions(chat_app=chat_app, chat_id=chat_id) == ["causa del contratto?"]


def test_timeout_is_504_and_frees_the_gpu_for_transcription(chat_app: ChatApp) -> None:
    def slow(request: ChatRequest) -> str:
        raise CorrectorUnavailableError("ReadTimeout") from httpx.ReadTimeout("slow")

    chat_app.model.behaviour = slow
    chat_id = chat_app.new_chat()

    response = chat_app.ask(chat_id=chat_id)

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "CHAT_TIMEOUT"
    entered: list[bool] = []

    def transcribe() -> None:
        with chat_app.arbiter.transcription_lease(stage="transcribing"):
            entered.append(True)

    worker = Thread(target=transcribe)
    worker.start()
    worker.join(timeout=GUARD_S)
    assert entered == [True]


def test_concurrent_questions_on_one_chat_both_land_in_the_file(
    chat_app: ChatApp,
) -> None:
    together = Barrier(parties=2, timeout=GUARD_S)

    def overlapping(request: ChatRequest) -> str:
        together.wait()
        return ANSWER

    chat_app.model.behaviour = overlapping
    chat_id = chat_app.new_chat()
    statuses: list[int] = []
    threads = [
        Thread(
            target=lambda q=q: statuses.append(
                chat_app.ask(chat_id=chat_id, question=q).status_code
            )
        )
        for q in ("causa del contratto, prima?", "causa del contratto, seconda?")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=GUARD_S)

    assert statuses == [200, 200]
    assert sorted(map(str, _questions(chat_app=chat_app, chat_id=chat_id))) == [
        "causa del contratto, prima?",
        "causa del contratto, seconda?",
    ]
    kinds = [line["kind"] for line in chat_app.lines(chat_id)]
    assert kinds.count("answer") == 2

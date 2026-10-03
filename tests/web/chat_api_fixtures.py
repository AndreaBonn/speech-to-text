"""App client, a course with one indexable lecture, and a scripted chat model."""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from study_fixtures import QUOTE, transcript_fixture

from sbobina.course_registry import get_or_create
from sbobina.models import save_transcript
from sbobina.ollama_chat import ChatRequest
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.chat_store import chat_path
from sbobina.web.gpu_lock import GpuArbiter
from sbobina.web.job_models import JobConfig, JobStage, JobStatus
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
COURSE = "diritto"
CHATS_URL = f"/api/v1/courses/{COURSE}/chats"
ANSWER = json.dumps(
    {
        "frasi": [
            {
                "testo": "La causa è illecita.",
                "citazioni": [{"passaggio": "P1", "testo": QUOTE}],
            }
        ]
    }
)


@dataclass
class ScriptedChat:
    """Chat model double: returns ANSWER, or runs `behaviour` instead."""

    behaviour: Callable[[ChatRequest], str] | None = None
    requests: list[ChatRequest] = field(default_factory=list)

    def __call__(self, request: ChatRequest) -> str:
        self.requests.append(request)
        if self.behaviour is not None:
            return self.behaviour(request)
        return ANSWER


@dataclass
class ChatApp:
    client: TestClient
    store: JobStore
    model: ScriptedChat
    arbiter: GpuArbiter
    course_id: str

    def new_chat(self) -> str:
        return str(self.client.post(CHATS_URL).json()["data"]["id"])

    def ask(
        self, chat_id: str, question: str = "che cos'è la causa del contratto?"
    ) -> httpx.Response:
        response: httpx.Response = self.client.post(
            f"{CHATS_URL}/{chat_id}/messages", json={"question": question}
        )
        return response

    def lines(self, chat_id: str) -> list[dict[str, object]]:
        path = chat_path(
            courses_dir=self.store.courses_dir,
            course_id=self.course_id,
            chat_id=chat_id,
        )
        return [json.loads(line) for line in path.read_text().splitlines()]


def _add_lecture(store: JobStore) -> None:
    record = store.create(config=JobConfig(subject=COURSE))
    store.update(
        record=record.model_copy(
            update={"status": JobStatus.DONE, "stage": JobStage.DONE}
        )
    )
    directory = store.jobs_dir / str(record.id)
    save_transcript(transcript=transcript_fixture(), path=directory / "audio.json")


@pytest.fixture
def chat_app(tmp_path: Path) -> Iterator[ChatApp]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    model = ScriptedChat()
    app.state.chat_client = model
    store: JobStore = app.state.job_store
    course = get_or_create(courses_dir=store.courses_dir, key=COURSE, label="Diritto")
    _add_lecture(store=store)
    client = TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})
    yield ChatApp(
        client=client,
        store=store,
        model=model,
        arbiter=app.state.gpu_arbiter,
        course_id=course.id,
    )
    client.close()

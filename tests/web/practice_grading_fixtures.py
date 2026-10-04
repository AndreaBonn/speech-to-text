import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from generation_api_fixtures import BASE_URL, _register_course, _store
from ollama import Client
from test_api_practice import make_url
from test_practice_store import make_generation

from sbobina import platform_info
from sbobina.correction import CorrectorUnavailableError
from sbobina.generation_models import GenerationFormat
from sbobina.ollama_chat import ChatRequest
from sbobina.platform_info import PlatformInfo
from sbobina.settings import Settings
from sbobina.web import api_chat
from sbobina.web.app import create_app
from sbobina.web.generation_store import save_generation
from sbobina.web.practice_store import create_attempt

TEXT = "La forza determina la variazione della velocità."


@dataclass
class JudgeSpy:
    calls: int = 0
    unavailable: bool = False
    invalid: bool = False
    before_call: Callable[[], None] | None = None

    def chat_json(self, *, client: Client, request: ChatRequest) -> str:
        self.calls += 1
        if self.before_call is not None:
            self.before_call()
        if self.unavailable:
            raise CorrectorUnavailableError("Offline")
        if self.invalid:
            return "invalid json"
        return json.dumps(
            {
                "punti_coperti": [{"punto": TEXT, "prova": TEXT}],
                "punti_mancanti": [],
                "errori": [],
            }
        )


@pytest.fixture
def judge(monkeypatch: pytest.MonkeyPatch) -> JudgeSpy:
    spy = JudgeSpy()
    monkeypatch.setattr(api_chat, "chat_json", spy.chat_json)
    monkeypatch.setattr(platform_info, "detect_platform", lambda: fake_platform())
    return spy


def fake_platform(cuda: bool = True) -> PlatformInfo:
    return PlatformInfo(
        system="linux",
        machine="x86_64",
        is_apple_silicon=False,
        cuda_devices=int(cuda),
        cuda_libs_available=cuda,
        cpu_compute_types=frozenset({"int8"}),
        cpu_count=2,
    )


@pytest.fixture
def app(tmp_path: Path, judge: JudgeSpy) -> FastAPI:
    return create_app(settings=Settings(), data_dir=tmp_path)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    transport = TestClient(app=app, base_url=BASE_URL)
    yield transport
    transport.close()


@pytest.fixture(params=[GenerationFormat.OPEN, GenerationFormat.ORAL])
def attempt_url(tmp_path: Path, request: pytest.FixtureRequest) -> str:
    course_id = _register_course(tmp_path=tmp_path)
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    record = make_generation(courses_dir=courses_dir, course_id=course_id)
    questions = tuple(
        replace(q, options=(), correct_index=None, solution=TEXT)
        for q in record.questions
    )
    record = replace(record, format=request.param, questions=questions)
    save_generation(courses_dir=courses_dir, course_id=course_id, record=record)
    attempt = create_attempt(
        courses_dir=courses_dir, course_id=course_id, generation=record
    )
    return f"{make_url(generation=record)}/{attempt.id}"


def submission() -> dict[str, str]:
    return {"text": TEXT, "answer_id": str(uuid4())}

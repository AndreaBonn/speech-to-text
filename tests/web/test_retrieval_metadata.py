import json
from pathlib import Path

from sbobina.generation_models import GenerationFormat, GenerationRequest
from sbobina.web.chat_records import ChatAnswerRecord, line_to_record, record_to_line
from sbobina.web.generation_store import (
    create_generation,
    generation_path,
    load_generation,
)


def test_generation_runner_shrinks_below_original_limit() -> None:
    path = Path("src/sbobina/web/generation_runner.py")
    assert len(path.read_text().splitlines()) < 298


def test_old_chat_line_loads_without_retrieval_mode() -> None:
    raw = {
        "kind": "answer",
        "question_id": "q1",
        "outcome": "DONE",
        "sentences": [],
        "discarded": 0,
        "error": None,
        "created_at": "2026-10-07T10:00:00Z",
    }
    record = line_to_record(raw=raw)
    assert isinstance(record, ChatAnswerRecord)
    assert record.retrieval_mode is None
    assert json.loads(record_to_line(record=record)) == raw


def test_chat_line_round_trips_retrieval_mode() -> None:
    raw = {
        "kind": "answer",
        "question_id": "q1",
        "outcome": "DONE",
        "sentences": [],
        "discarded": 0,
        "error": None,
        "created_at": "2026-10-07T10:00:00Z",
        "retrieval_mode": {"mode": "bm25", "reason": "model_missing"},
    }
    assert json.loads(record_to_line(record=line_to_record(raw=raw))) == raw


def test_old_generation_json_loads_without_retrieval_mode(tmp_path: Path) -> None:
    record = create_generation(
        courses_dir=tmp_path,
        course_id="course",
        request=GenerationRequest(format=GenerationFormat.OPEN, count=1),
    )
    path = generation_path(courses_dir=tmp_path, course_id="course", gen_id=record.id)
    raw = json.loads(path.read_text())
    raw.pop("retrieval_mode", None)
    path.write_text(json.dumps(raw))
    saved = load_generation(courses_dir=tmp_path, course_id="course", gen_id=record.id)
    assert saved.id == record.id
    assert saved.retrieval_mode is None

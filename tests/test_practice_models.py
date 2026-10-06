from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from sbobina.generation_models import GenerationFormat, GenerationQuestion
from sbobina.grading_models import Judgement, JudgementOutcome
from sbobina.practice_models import (
    AnswerStatus,
    MultipleChoiceAnswer,
    OpenAnswer,
    OralAnswer,
    PracticeAttempt,
    PracticeStatus,
    dump_practice_attempt,
    load_practice_attempt,
)


def make_attempt(
    format: GenerationFormat = GenerationFormat.MULTIPLE_CHOICE,
) -> PracticeAttempt:
    is_mc = format == GenerationFormat.MULTIPLE_CHOICE
    question = GenerationQuestion(
        question="Question?",
        options=("a", "b", "c", "d") if is_mc else (),
        correct_index=2 if is_mc else None,
        solution="Expected explanation",
        citations=(),
    )
    return PracticeAttempt(
        id=str(uuid4()),
        course_id=str(uuid4()),
        generation_id=str(uuid4()),
        format=format,
        status=PracticeStatus.IN_PROGRESS,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
        questions=(question, question),
        answers=(),
    )


def test_multiple_choice_answer_negative_index_rejected() -> None:
    with pytest.raises(ValueError, match="chosen_index"):
        MultipleChoiceAnswer(answer_id=str(uuid4()), question_index=0, chosen_index=-1)
    assert (
        MultipleChoiceAnswer(
            answer_id=str(uuid4()), question_index=0, chosen_index=0
        ).chosen_index
        == 0
    )


@pytest.mark.parametrize("answer_type", (OpenAnswer, OralAnswer))
def test_practice_attempt_text_answer_for_multiple_choice_rejected(
    answer_type: type[OpenAnswer] | type[OralAnswer],
) -> None:
    answer = answer_type(answer_id=str(uuid4()), question_index=0, text="Answer")
    with pytest.raises(ValueError, match="format"):
        replace(make_attempt(), answers=(answer,))
    format = GenerationFormat(answer.kind)
    assert replace(make_attempt(format=format), answers=(answer,)).answers == (answer,)


JUDGEMENT = Judgement(covered_points=(), missing_points=("Punto",), errors=())


def text_answer(**fields: Any) -> OpenAnswer:
    return OpenAnswer(answer_id=str(uuid4()), question_index=1, text="Answer", **fields)


VALID_TEXT_STATES: tuple[dict[str, Any], ...] = (
    {},
    {"reason": "GPU_BUSY"},
    {"status": AnswerStatus.GRADED, "judgement": JUDGEMENT},
    {"status": AnswerStatus.SELF_GRADED, "self_grade": JudgementOutcome.PARTIAL},
    {
        "status": AnswerStatus.SELF_GRADED,
        "self_grade": JudgementOutcome.CORRECT,
        "judgement": JUDGEMENT,
    },
)
INVALID_TEXT_STATES: tuple[dict[str, Any], ...] = (
    {"status": AnswerStatus.GRADED},
    {"judgement": JUDGEMENT},
    {"status": AnswerStatus.SELF_GRADED},
    {"self_grade": JudgementOutcome.PARTIAL},
    {"status": AnswerStatus.GRADED, "judgement": JUDGEMENT, "reason": "GPU_BUSY"},
    {
        "status": AnswerStatus.SELF_GRADED,
        "self_grade": JudgementOutcome.PARTIAL,
        "reason": "GPU_BUSY",
    },
)


@pytest.mark.parametrize("fields", VALID_TEXT_STATES)
@pytest.mark.parametrize("answer_type", (OpenAnswer, OralAnswer))
def test_practice_attempt_roundtrip_preserves_text_answer_states(
    fields: dict[str, Any], answer_type: type[OpenAnswer] | type[OralAnswer]
) -> None:
    answer = answer_type(
        answer_id=str(uuid4()), question_index=1, text="Answer", **fields
    )
    format = GenerationFormat(answer.kind)
    attempt = replace(make_attempt(format=format), answers=(answer,))
    loaded = load_practice_attempt(content=dump_practice_attempt(attempt=attempt))
    assert loaded == attempt
    assert type(loaded.answers[0]) is answer_type


def test_practice_attempt_roundtrip_preserves_multiple_choice_answer() -> None:
    answer = MultipleChoiceAnswer(
        answer_id=str(uuid4()),
        question_index=1,
        status=AnswerStatus.GRADED,
        chosen_index=2,
    )
    attempt = replace(
        make_attempt(format=GenerationFormat.MULTIPLE_CHOICE), answers=(answer,)
    )
    loaded = load_practice_attempt(content=dump_practice_attempt(attempt=attempt))
    assert loaded == attempt
    assert type(loaded.answers[0]) is MultipleChoiceAnswer


@pytest.mark.parametrize("fields", INVALID_TEXT_STATES)
def test_text_answer_inconsistent_grading_state_rejected(
    fields: dict[str, Any],
) -> None:
    # A graded answer without judgement could never be graded again, and a
    # self-graded one without the student's grade would show no outcome.
    with pytest.raises(ValueError, match="status"):
        text_answer(**fields)


@pytest.mark.parametrize("status", (AnswerStatus.UNGRADED, AnswerStatus.SELF_GRADED))
def test_multiple_choice_answer_must_be_graded(status: AnswerStatus) -> None:
    with pytest.raises(ValueError, match="status"):
        MultipleChoiceAnswer(
            answer_id=str(uuid4()), question_index=0, status=status, chosen_index=1
        )


def test_inconsistent_answer_on_disk_rejected_on_load() -> None:
    answer = text_answer(status=AnswerStatus.GRADED, judgement=JUDGEMENT)
    attempt = replace(make_attempt(format=GenerationFormat.OPEN), answers=(answer,))
    content = dump_practice_attempt(attempt=attempt)
    assert load_practice_attempt(content=content) == attempt
    corrupted = content.replace('"status": "graded"', '"status": "self_graded"', 1)
    assert corrupted != content
    with pytest.raises(ValueError, match="status"):
        load_practice_attempt(content=corrupted)


@pytest.mark.parametrize("field", ("id", "course_id", "generation_id"))
@pytest.mark.parametrize(
    "value", ("../outside", "00000000-0000-1000-8000-000000000000")
)
def test_practice_attempt_invalid_uuid_rejected(field: str, value: str) -> None:
    with pytest.raises(ValueError, match="UUID4"):
        attempt = make_attempt()
        replace(
            attempt,
            id=value if field == "id" else attempt.id,
            course_id=value if field == "course_id" else attempt.course_id,
            generation_id=value if field == "generation_id" else attempt.generation_id,
        )


def test_open_answer_invalid_id_and_question_index_rejected() -> None:
    with pytest.raises(ValueError, match="UUID4"):
        OpenAnswer(answer_id="bad", question_index=0, text="Answer")
    with pytest.raises(ValueError, match="question_index"):
        OpenAnswer(answer_id=str(uuid4()), question_index=-1, text="Answer")


@pytest.mark.parametrize("field", ("created_at", "updated_at"))
def test_practice_attempt_naive_datetime_rejected(field: str) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        attempt = make_attempt()
        naive = datetime.now(tz=UTC).replace(tzinfo=None)
        replace(
            attempt,
            created_at=naive if field == "created_at" else attempt.created_at,
            updated_at=naive if field == "updated_at" else attempt.updated_at,
        )


def test_practice_attempt_duplicate_answer_id_rejected() -> None:
    first = MultipleChoiceAnswer(
        answer_id=str(uuid4()), question_index=0, chosen_index=0
    )
    second = replace(first, question_index=1)
    with pytest.raises(ValueError, match="answer_id"):
        replace(make_attempt(), answers=(first, second))
    assert (
        len(
            replace(
                make_attempt(), answers=(first, replace(second, answer_id=str(uuid4())))
            ).answers
        )
        == 2
    )


def test_practice_attempt_duplicate_question_rejected() -> None:
    first = MultipleChoiceAnswer(
        answer_id=str(uuid4()), question_index=0, chosen_index=0
    )
    second = replace(first, answer_id=str(uuid4()))
    with pytest.raises(ValueError, match="question_index"):
        replace(make_attempt(), answers=(first, second))


def test_practice_attempt_question_index_out_of_range_rejected() -> None:
    answer = MultipleChoiceAnswer(
        answer_id=str(uuid4()), question_index=2, chosen_index=0
    )
    with pytest.raises(ValueError, match="question_index"):
        replace(make_attempt(), answers=(answer,))


def test_practice_attempt_summary_and_mismatched_options_rejected() -> None:
    attempt = make_attempt()
    with pytest.raises(ValueError, match="summary"):
        replace(attempt, format=GenerationFormat.SUMMARY)
    with pytest.raises(ValueError, match="options"):
        replace(attempt, format=GenerationFormat.OPEN)
    with pytest.raises(ValueError, match="options"):
        replace(attempt, questions=make_attempt(format=GenerationFormat.OPEN).questions)


def test_open_answer_forged_discriminator_rejected() -> None:
    answer = OpenAnswer(answer_id=str(uuid4()), question_index=0, text="Answer")
    invalid_kind: Any = "multiple_choice"
    with pytest.raises(ValueError, match="kind"):
        replace(answer, kind=invalid_kind)
    assert answer.kind == "open"


def test_practice_attempt_invalid_enum_values_rejected() -> None:
    invalid: Any = "invalid"
    answer = OpenAnswer(answer_id=str(uuid4()), question_index=0, text="Answer")
    with pytest.raises(ValueError, match="AnswerStatus"):
        replace(answer, status=invalid)
    with pytest.raises(ValueError, match="PracticeStatus"):
        replace(make_attempt(), status=invalid)
    with pytest.raises(ValueError, match="GenerationFormat"):
        replace(make_attempt(), format=invalid)


def test_multiple_choice_answer_forged_discriminator_rejected() -> None:
    answer = MultipleChoiceAnswer(
        answer_id=str(uuid4()), question_index=0, chosen_index=1
    )
    invalid_kind: Any = "open"
    with pytest.raises(ValueError, match="kind must be multiple_choice"):
        replace(answer, kind=invalid_kind)
    assert answer.kind == "multiple_choice"


def test_oral_answer_forged_discriminator_rejected() -> None:
    answer = OralAnswer(answer_id=str(uuid4()), question_index=0, text="Answer")
    invalid_kind: Any = "open"
    with pytest.raises(ValueError, match="kind must be oral"):
        replace(answer, kind=invalid_kind)
    assert answer.kind == "oral"


@pytest.mark.parametrize("answer_type", (OpenAnswer, OralAnswer))
@pytest.mark.parametrize("blank", ("", "  \n\t "))
def test_text_answer_blank_text_rejected(
    answer_type: type[OpenAnswer] | type[OralAnswer], blank: str
) -> None:
    assert answer_type(answer_id=str(uuid4()), question_index=0, text="x").text == "x"
    with pytest.raises(ValueError, match="text must not be blank"):
        answer_type(answer_id=str(uuid4()), question_index=0, text=blank)

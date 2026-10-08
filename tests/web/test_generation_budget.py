import pytest

from sbobina.generation_models import MAX_QUESTION_COUNT, GenerationFormat
from sbobina.web.generation_runner import (
    BUDGET_MIN_WORDS,
    SUMMARY_NUM_PREDICT,
    compute_budget_words,
    compute_options,
)


def test_compute_options_scales_num_predict_with_count() -> None:
    few = compute_options(count=1, format_=GenerationFormat.MULTIPLE_CHOICE, model="m")
    many = compute_options(
        count=MAX_QUESTION_COUNT, format_=GenerationFormat.MULTIPLE_CHOICE, model="m"
    )

    assert few.num_predict == 516
    assert many.num_predict == 2856


def test_compute_options_summary_num_predict_is_fixed_regardless_of_count() -> None:
    # B3 regression: a summary has no per-item count (one set of sections,
    # not `count` questions); the old formula gave count=1 only 556 tokens
    # and Ollama truncated the real reply (done_reason=length), which
    # validate() then rejected as INVALID_RESPONSE.
    one = compute_options(count=1, format_=GenerationFormat.SUMMARY, model="m")
    many = compute_options(count=20, format_=GenerationFormat.SUMMARY, model="m")

    assert one.num_predict == many.num_predict == SUMMARY_NUM_PREDICT == 2560


def test_compute_budget_words_for_summary_keeps_a_usable_material_budget() -> None:
    options = compute_options(count=1, format_=GenerationFormat.SUMMARY, model="m")

    budget = compute_budget_words(format_=GenerationFormat.SUMMARY, options=options)

    # Documents the actual number so a future change to the constants above
    # shows up here instead of silently shrinking the material budget.
    assert budget == 1547
    assert budget >= BUDGET_MIN_WORDS


def test_compute_budget_words_shrinks_as_num_predict_grows_but_keeps_floor() -> None:
    few = compute_options(count=1, format_=GenerationFormat.MULTIPLE_CHOICE, model="m")
    many = compute_options(
        count=MAX_QUESTION_COUNT, format_=GenerationFormat.MULTIPLE_CHOICE, model="m"
    )

    budget_few = compute_budget_words(
        format_=GenerationFormat.MULTIPLE_CHOICE, options=few
    )
    budget_many = compute_budget_words(
        format_=GenerationFormat.MULTIPLE_CHOICE, options=many
    )

    assert budget_many < budget_few
    assert budget_many >= BUDGET_MIN_WORDS


MIN_MATERIAL_WORDS = 1000


@pytest.mark.parametrize(
    "format_",
    [GenerationFormat.MULTIPLE_CHOICE, GenerationFormat.OPEN, GenerationFormat.ORAL],
)
def test_largest_allowed_exam_still_leaves_real_material(
    format_: GenerationFormat,
) -> None:
    # Above the floor the whole prompt fits in num_ctx; at the floor (200
    # words) Ollama would silently cut the input and the exam would rest on
    # almost no material. The maximum count must stay clear of it.
    options = compute_options(count=MAX_QUESTION_COUNT, format_=format_, model="m")

    budget = compute_budget_words(format_=format_, options=options)

    assert budget >= MIN_MATERIAL_WORDS

from datetime import UTC, datetime, timedelta

import pytest


@pytest.mark.parametrize(
    ("raw", "label", "key"),
    [
        ("  Diritto   Privato ", "Diritto Privato", "diritto privato"),
        ("", None, ""),
        (" \t\n", None, ""),
        (None, None, ""),
        ("Ｄiritto\u00a0Privato", "Diritto Privato", "diritto privato"),
        ("Straße", "Straße", "strasse"),
        ("  " + "x" * 100 + "  ", "x" * 100, "x" * 100),
    ],
)
def test_normalize_course_label_and_key(
    raw: str | None, label: str | None, key: str
) -> None:
    from sbobina.courses import course_key, normalize_course_label

    assert normalize_course_label(raw=raw) == label
    assert course_key(label=raw) == key


@pytest.mark.parametrize("raw", ["x" * 101, "ﬃ" * 34])
def test_normalize_course_label_rejects_overlong_normalized_label(raw: str) -> None:
    from sbobina.courses import normalize_course_label

    with pytest.raises(ValueError, match="100"):
        normalize_course_label(raw=raw)


@pytest.mark.parametrize(
    ("course", "subject", "expected"),
    [
        (" Diritto ", "Fisica", "Diritto"),
        (None, " Fisica  Teorica ", "Fisica Teorica"),
        ("", "Fisica", "Fisica"),
        (" \t", "Fisica", "Fisica"),
        (None, None, None),
        (None, "  ", None),
    ],
)
def test_effective_course_uses_normalized_override_or_subject(
    course: str | None, subject: str | None, expected: str | None
) -> None:
    from sbobina.courses import effective_course

    assert effective_course(course=course, subject=subject) == expected


@pytest.mark.parametrize("reverse", [False, True])
def test_group_courses_uses_latest_label_and_counts_lectures(reverse: bool) -> None:
    from sbobina.courses import CourseLecture, CourseSummary, group_courses

    older = datetime(2026, 1, 1, tzinfo=UTC)
    newer = older + timedelta(days=1)
    records = [
        CourseLecture(course=None, subject="diritto privato", created_at=older),
        CourseLecture(course=" Diritto  Privato ", subject="Altro", created_at=newer),
    ]
    if reverse:
        records.reverse()
    original = records.copy()
    assert group_courses(records=records) == [
        CourseSummary(
            key="diritto privato",
            label="Diritto Privato",
            lecture_count=2,
            last_lecture_at=newer,
        )
    ]
    assert records == original


def test_group_courses_separates_missing_course_from_literal_label() -> None:
    from sbobina.courses import CourseLecture, group_courses

    older = datetime(2026, 1, 1, tzinfo=UTC)
    newer = older + timedelta(days=1)
    records = [
        CourseLecture(course=None, subject=None, created_at=older),
        CourseLecture(course="Senza corso", subject=None, created_at=newer),
        CourseLecture(course=None, subject="  ", created_at=newer),
    ]
    groups = {group.key: group for group in group_courses(records=records)}
    assert set(groups) == {"", "senza corso"}
    assert (groups[""].label, groups[""].lecture_count) == ("Senza corso", 2)
    assert groups[""].last_lecture_at == newer
    assert groups["senza corso"].lecture_count == 1
    assert group_courses(records=[]) == []


def test_effective_course_preserves_legacy_subject_expanded_by_nfkc() -> None:
    from sbobina.courses import course_key, effective_course

    label = effective_course(course=None, subject="ﬃ" * 34)
    assert label == "ffi" * 34
    assert course_key(label=label) == "ffi" * 34

from datetime import UTC, datetime

from sbobina.courses import CourseLecture, CourseSummary, group_courses


def test_group_courses_registry_union_keeps_lecture_count_and_time() -> None:
    old = datetime(2026, 1, 1, tzinfo=UTC)
    recent = datetime(2026, 2, 1, tzinfo=UTC)
    lecture = CourseLecture(course="Fisica", subject=None, created_at=old)
    registered = [
        CourseSummary(
            key="fisica", label="FISICA", lecture_count=0, last_lecture_at=recent
        ),
        CourseSummary(
            key="diritto", label="Diritto", lecture_count=0, last_lecture_at=recent
        ),
    ]

    result = group_courses(records=[lecture], registered=registered)

    assert result == [
        registered[1],
        CourseSummary(
            key="fisica", label="Fisica", lecture_count=1, last_lecture_at=old
        ),
    ]
    assert registered[0].lecture_count == 0

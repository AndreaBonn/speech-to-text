import pydantic
import pytest

from sbobina.settings import Settings


def test_settings_course_doc_max_mb_accepts_the_package_member_cap() -> None:
    assert Settings(course_doc_max_mb=200).course_doc_max_mb == 200


def test_settings_course_doc_max_mb_above_package_member_cap_raises() -> None:
    # C5: a document larger than a package member could never be re-imported.
    with pytest.raises(pydantic.ValidationError):
        Settings(course_doc_max_mb=201)

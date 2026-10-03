import logging
from pathlib import Path

import pytest

from sbobina.web.ocr_store import (
    OcrRun,
    OcrStatus,
    create_ocr,
    iter_ocr_runs,
    ocr_path,
)


def test_failed_run_requires_an_error_and_others_refuse_one() -> None:
    assert OcrRun(status=OcrStatus.FAILED, done=0, total=3, error="X").error == "X"
    with pytest.raises(ValueError):
        OcrRun(status=OcrStatus.FAILED, done=0, total=3, error=None)
    with pytest.raises(ValueError):
        OcrRun(status=OcrStatus.DONE, done=3, total=3, error="X")


def test_progress_cannot_exceed_the_total_or_go_negative() -> None:
    assert OcrRun(status=OcrStatus.RUNNING, done=2, total=3, error=None).done == 2
    with pytest.raises(ValueError):
        OcrRun(status=OcrStatus.RUNNING, done=4, total=3, error=None)
    with pytest.raises(ValueError):
        OcrRun(status=OcrStatus.RUNNING, done=-1, total=3, error=None)


def test_iter_ocr_runs_skips_corrupt_record_and_yields_the_others(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    created = create_ocr(courses_dir=tmp_path, course_id="corso", doc_id="ok")
    corrupt = ocr_path(courses_dir=tmp_path, course_id="corso", doc_id="rotto")
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("{", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        runs = list(iter_ocr_runs(courses_dir=tmp_path))

    assert runs == [("corso", "ok", created)]
    assert "rotto" in caplog.text

import pytest

from sbobina.web.ocr_store import OcrRun, OcrStatus


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

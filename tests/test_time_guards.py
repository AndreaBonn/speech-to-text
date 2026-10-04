from datetime import UTC, datetime

import pytest

from sbobina.time_guards import require_aware

AWARE = datetime(2026, 10, 4, tzinfo=UTC)


def test_require_aware_naive_datetime_raises_with_field_name() -> None:
    require_aware(value=AWARE, field="due")
    with pytest.raises(ValueError, match="due"):
        require_aware(value=AWARE.replace(tzinfo=None), field="due")

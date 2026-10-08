import importlib
import sys
from collections.abc import Iterator

import pytest

from sbobina.web import child_limits

resource = pytest.importorskip("resource")

LIMIT_MB = 64


@pytest.fixture
def reloaded_child_limits(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    yield
    monkeypatch.undo()
    importlib.reload(child_limits)


def test_apply_memory_limit_sets_rlimit_as_in_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(
        resource,
        "setrlimit",
        lambda which, limits: calls.append((which, limits)),
    )

    child_limits._apply_memory_limit(max_memory_mb=LIMIT_MB)

    limit_bytes = LIMIT_MB * 1024 * 1024
    assert calls == [(resource.RLIMIT_AS, (limit_bytes, limit_bytes))]


def test_apply_memory_limit_without_resource_module_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch, reloaded_child_limits: None
) -> None:
    calls: list[object] = []
    resource_module = resource
    monkeypatch.setattr(resource_module, "setrlimit", lambda *args: calls.append(args))
    monkeypatch.setitem(sys.modules, "resource", None)

    windows_like = importlib.reload(child_limits)
    windows_like._apply_memory_limit(max_memory_mb=LIMIT_MB)

    assert windows_like.HAS_RESOURCE_LIMIT is False
    assert calls == []

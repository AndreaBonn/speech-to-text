import socket
import threading
import time
import webbrowser
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from sbobina.settings import Settings
from sbobina.web import launcher


@pytest.fixture
def busy_port() -> Iterator[int]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        yield holder.getsockname()[1]


@pytest.mark.parametrize(
    ("host", "expected"),
    [("127.0.0.1", "http://127.0.0.1:8765"), ("::1", "http://[::1]:8765")],
)
def test_base_url_brackets_ipv6_hosts(host: str, expected: str) -> None:
    assert launcher.base_url(host=host, port=8765) == expected


def test_is_port_available_busy_port_returns_false(busy_port: int) -> None:
    assert launcher.is_port_available(host="127.0.0.1", port=busy_port) is False


def test_is_port_available_free_port_returns_true() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]

    assert launcher.is_port_available(host="127.0.0.1", port=free_port) is True


def test_open_browser_when_ready_opens_once_after_server_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers: list[httpx.Response | Exception] = [
        httpx.ConnectError("down"),
        httpx.Response(503),
    ]
    answers.append(httpx.Response(200))
    opened: list[str] = []

    def fake_get(url: str, timeout: float) -> httpx.Response:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(webbrowser, "open", opened.append)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    launcher.open_browser_when_ready(url="http://127.0.0.1:8765")

    assert opened == ["http://127.0.0.1:8765"]


def test_open_browser_when_ready_server_never_answers_does_not_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []

    def fake_get(url: str, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(webbrowser, "open", opened.append)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    launcher.open_browser_when_ready(url="http://127.0.0.1:8765")

    assert opened == []


def test_run_server_busy_port_exits_1_without_starting(
    monkeypatch: pytest.MonkeyPatch, busy_port: int, caplog: pytest.LogCaptureFixture
) -> None:
    started: list[object] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(a))

    exit_code = launcher.run_server(
        config=Settings(web_host="127.0.0.1", web_port=busy_port), open_browser=False
    )

    assert exit_code == 1
    assert started == []
    assert f"Porta {busy_port} già occupata" in caplog.text


class InlineThread:
    """Runs the target on ``start()`` so the test needs no synchronisation."""

    def __init__(self, target: Any, args: tuple[Any, ...], daemon: bool) -> None:
        self.target, self.args = target, args

    def start(self) -> None:
        self.target(*self.args)


@pytest.mark.parametrize("open_browser", [True, False])
def test_run_server_free_port_starts_uvicorn_and_browser_watcher(
    monkeypatch: pytest.MonkeyPatch, open_browser: bool
) -> None:
    runs: list[dict[str, object]] = []
    watched: list[str] = []
    monkeypatch.setattr(launcher, "is_port_available", lambda host, port: True)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: runs.append(kw))
    monkeypatch.setattr(launcher, "open_browser_when_ready", watched.append)
    monkeypatch.setattr(threading, "Thread", InlineThread)

    exit_code = launcher.run_server(
        config=Settings(web_host="127.0.0.1", web_port=8765),
        open_browser=open_browser,
    )

    assert exit_code == 0
    assert runs == [{"host": "127.0.0.1", "port": 8765, "log_level": "info"}]
    assert watched == (["http://127.0.0.1:8765"] if open_browser else [])


def test_run_server_custom_port_accepts_same_port_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apps: list[Any] = []
    monkeypatch.setattr(launcher, "is_port_available", lambda host, port: True)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: apps.append(app))

    launcher.run_server(
        config=Settings(web_host="127.0.0.1", web_port=9000), open_browser=False
    )
    client = TestClient(apps[0], base_url="http://127.0.0.1:9000")
    same = client.post("/api/v1/system", headers={"Origin": "http://127.0.0.1:9000"})
    other = client.post("/api/v1/system", headers={"Origin": "http://127.0.0.1:8765"})

    assert same.status_code == 405  # reached routing: origin accepted
    assert other.status_code == 403

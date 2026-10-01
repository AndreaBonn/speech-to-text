import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.types import Message

from sbobina.settings import Settings
from sbobina.web import api_models, downloads
from sbobina.web.app import create_app
from sbobina.web.downloads import DownloadManager

BASE_URL = "http://127.0.0.1:8765"


def _immediate(
    *, repo_id: str, allow_patterns: list[str], dry_run: bool = False, **_: object
) -> list[Any] | str:
    return [] if dry_run else "/tmp/ignored"


def test_start_download_returns_202_then_conflicts_on_duplicate(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    client = TestClient(app, base_url=BASE_URL)
    hold = threading.Event()

    def fake_snapshot(
        *, repo_id: str, allow_patterns: list[str], dry_run: bool = False, **_: object
    ) -> list[Any] | str:
        if dry_run:
            return []
        hold.wait(timeout=5)
        return str(tmp_path)

    with patch.object(downloads, "snapshot_download", side_effect=fake_snapshot):
        first = client.post(
            "/api/v1/models/downloads", json={"source": "whisper", "name": "tiny"}
        )
        assert first.status_code == 202
        assert first.json()["data"] == {
            "source": "whisper",
            "name": "tiny",
            "status": "running",
            "completed": 0,
            "total": None,
            "fraction": None,
            "message": None,
        }
        second = client.post(
            "/api/v1/models/downloads", json={"source": "whisper", "name": "tiny"}
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "DOWNLOAD_IN_PROGRESS"
        hold.set()
        manager: DownloadManager = app.state.download_manager
        manager.join(source="whisper", name="tiny", timeout=5)


def test_start_download_rejects_unknown_whisper_model(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    client = TestClient(app, base_url=BASE_URL)
    response = client.post(
        "/api/v1/models/downloads", json={"source": "whisper", "name": "not-a-model"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_downloads_reports_completed_state(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    client = TestClient(app, base_url=BASE_URL)
    with patch.object(downloads, "snapshot_download", side_effect=_immediate):
        client.post(
            "/api/v1/models/downloads", json={"source": "whisper", "name": "tiny"}
        )
        manager: DownloadManager = app.state.download_manager
        manager.join(source="whisper", name="tiny", timeout=5)
    response = client.get("/api/v1/models/downloads")
    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "source": "whisper",
            "name": "tiny",
            "status": "done",
            "completed": 0,
            "total": None,
            "fraction": None,
            "message": None,
        }
    ]


def test_download_events_emits_progress_then_end_and_respects_disconnect() -> None:
    manager = DownloadManager(settings=Settings())
    hold = threading.Event()

    def fake_snapshot(
        *, repo_id: str, allow_patterns: list[str], dry_run: bool = False, **_: object
    ) -> list[Any] | str:
        if dry_run:
            return []
        hold.wait(timeout=5)
        return "/tmp/ignored"

    async def scenario() -> None:
        disconnected = False

        async def receive() -> Message:
            return {"type": "http.disconnect" if disconnected else "http.request"}

        request = Request(scope={"type": "http"}, receive=receive)
        stream = api_models._download_events(request=request, manager=manager)

        with patch.object(downloads, "snapshot_download", side_effect=fake_snapshot):
            manager.start(source="whisper", name="tiny")
            with anyio.fail_after(5):
                first = await anext(stream)
            assert "event: progress" in first
            assert '"status": "running"' in first
            hold.set()
            manager.join(source="whisper", name="tiny", timeout=5)
            with anyio.fail_after(5):
                second = await anext(stream)
            assert "event: progress" in second
            assert '"status": "done"' in second
            with anyio.fail_after(5):
                third = await anext(stream)
            assert "event: end" in third
            assert '"status": "done"' in third
            disconnected = True
            with pytest.raises(StopAsyncIteration), anyio.fail_after(5):
                await anext(stream)

    anyio.run(scenario)

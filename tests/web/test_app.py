from pathlib import Path
from unittest.mock import patch

import ollama
import pytest
from fastapi.testclient import TestClient

from sbobina import platform_info
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.errors import (
    AppError,
    JobNotCancellableError,
    NotFoundError,
    ValidationError,
)
from sbobina.web.job_models import JobConfig, JobStatus
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"


def test_system_returns_resolved_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = platform_info.PlatformInfo(
        system="linux",
        machine="x86_64",
        is_apple_silicon=False,
        cuda_devices=0,
        cuda_libs_available=False,
        cpu_compute_types=frozenset({"int8", "float32"}),
        cpu_count=4,
    )
    monkeypatch.setattr(platform_info, "detect_platform", lambda: info)
    config = Settings(device="auto", whisper_model="auto", compute_type="auto")
    app = create_app(settings=config, data_dir=tmp_path)
    with (
        patch.object(
            ollama.Client, "list", return_value=ollama.ListResponse(models=[])
        ),
        TestClient(app, base_url=BASE_URL) as client,
    ):
        response = client.get("/api/v1/system")
    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "os": "linux",
            "device": "cpu",
            "compute_type": "int8",
            "whisper_model": config.whisper_model_cpu,
            "reason": "Nessun percorso CUDA automatico disponibile",
            "cuda_libs_available": False,
            "ollama": {
                "status": "ready",
                "message": "Ollama è pronto.",
                "models": [],
            },
        }
    }
    assert app.state.job_store.jobs_dir == tmp_path / "jobs"
    assert not (tmp_path / "jobs").exists()


def test_host_middleware_rejects_untrusted_host(tmp_path: Path) -> None:
    client = TestClient(
        create_app(settings=Settings(), data_dir=tmp_path), base_url=BASE_URL
    )
    assert client.get("/missing", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/missing").status_code == 404


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_origin_middleware_checks_mutations(tmp_path: Path, host: str) -> None:
    config = Settings(web_host=host, web_port=9876)
    app = create_app(settings=config, data_dir=tmp_path)

    @app.api_route("/test", methods=["POST", "PUT", "PATCH", "DELETE", "GET"])
    def endpoint() -> dict[str, str]:
        return {"result": "ok"}

    url_host = f"[{host}]" if ":" in host else host
    origin = f"http://{url_host}:9876"
    client = TestClient(app, base_url=origin)
    for method in ["POST", "PUT", "PATCH", "DELETE"]:
        blocked = client.request(
            method, "/test", headers={"Origin": "https://evil.example"}
        )
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "FORBIDDEN"
        assert client.request(method, "/test", headers={"Origin": origin}).json() == {
            "result": "ok"
        }
        assert client.request(method, "/test").status_code == 200
    assert (
        client.get("/test", headers={"Origin": "https://evil.example"}).status_code
        == 200
    )


def test_request_validation_returns_all_field_details(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)

    @app.post("/validate")
    def validate(config: JobConfig) -> dict[str, int]:
        return {"beam_size": config.beam_size}

    client = TestClient(app, base_url=BASE_URL)
    response = client.post(
        "/validate",
        json={"beam_size": 0, "uncertain_threshold": 1.5, "whisper_model": "xl"},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert {detail["field"] for detail in error["details"]} == {
        "body.beam_size",
        "body.uncertain_threshold",
        "body.whisper_model",
    }
    assert all(detail["message"] for detail in error["details"])
    assert client.post("/validate", json={"beam_size": 3}).json() == {"beam_size": 3}


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (NotFoundError(entity="Job", id="missing"), 404, "NOT_FOUND"),
        (ValidationError(message="Valore non valido"), 422, "VALIDATION_ERROR"),
        (AppError(message="Internal path /secret"), 500, "INTERNAL_ERROR"),
        (JobNotCancellableError(job_id="abc"), 409, "JOB_NOT_CANCELLABLE"),
    ],
)
def test_domain_errors_use_envelope(
    tmp_path: Path, error: AppError, status: int, code: str
) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)

    @app.get("/error")
    def fail() -> None:
        raise error

    response = TestClient(app, base_url=BASE_URL).get("/error")
    assert response.status_code == status
    body = response.json()["error"]
    assert body["code"] == code
    assert body["message"] == (
        "Errore interno del server" if status == 500 else error.message
    )


@pytest.mark.parametrize(
    ("method", "path", "status_code", "code"),
    [
        ("GET", "/api/v1/nope", 404, "NOT_FOUND"),
        ("DELETE", "/api/v1/system", 405, "METHOD_NOT_ALLOWED"),
    ],
)
def test_http_errors_use_envelope(
    tmp_path: Path, method: str, path: str, status_code: int, code: str
) -> None:
    client = TestClient(
        create_app(settings=Settings(), data_dir=tmp_path), base_url=BASE_URL
    )

    response = client.request(method, path, headers={"Origin": BASE_URL})

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert "detail" not in response.json()


def test_lifespan_recovers_jobs_and_stops_supervisor(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    running = store.create(config=JobConfig())
    store.update(record=running.model_copy(update={"status": JobStatus.RUNNING}))
    app = create_app(settings=Settings(), data_dir=tmp_path)

    with TestClient(app, base_url=BASE_URL):
        supervisor = app.state.supervisor
        assert supervisor.is_running()
        recovered = store.get(job_id=str(running.id))

    assert recovered.status == JobStatus.INTERRUPTED
    assert recovered.error == {"code": "SERVER_RESTARTED"}
    assert not supervisor.is_running()


def test_lifespan_removes_import_staging_left_by_a_killed_import(
    tmp_path: Path,
) -> None:
    # F25: a kill or OOM between two renames leaves .import-* folders behind.
    staged = [
        tmp_path / name / ".import-00000000-0000-4000-8000-000000000001"
        for name in ("courses", "jobs")
    ]
    for directory in staged:
        directory.mkdir(parents=True)
        (directory / "partial.json").write_text(data="{}", encoding="utf-8")
    normal = tmp_path / "courses" / "11111111-1111-4111-8111-111111111111"
    normal.mkdir()
    (normal / "course.json").write_text(data="{}", encoding="utf-8")
    app = create_app(settings=Settings(), data_dir=tmp_path)

    with TestClient(app, base_url=BASE_URL):
        assert [path for path in staged if path.exists()] == []

    assert (normal / "course.json").read_text(encoding="utf-8") == "{}"

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sbobina import platform_info
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.errors import AppError, NotFoundError, ValidationError
from sbobina.web.job_models import JobConfig

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
    with TestClient(app, base_url=BASE_URL) as client:
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

    @app.api_route("/test", methods=["POST", "DELETE", "GET"])
    def endpoint() -> dict[str, str]:
        return {"result": "ok"}

    url_host = f"[{host}]" if ":" in host else host
    origin = f"http://{url_host}:9876"
    client = TestClient(app, base_url=origin)
    for method in ["POST", "DELETE"]:
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

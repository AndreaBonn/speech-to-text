from pathlib import Path

from fastapi.testclient import TestClient
from page_fixtures import BASE_URL

from sbobina.settings import Settings
from sbobina.web.app import create_app

VENDOR = Path(__file__).parents[2] / "src/sbobina/web/static/vendor/katex-0.19.0"


def test_katex_assets_are_served_locally(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        script = client.get("/static/vendor/katex-0.19.0/katex.min.js")
        font = client.get("/static/vendor/katex-0.19.0/fonts/KaTeX_Main-Regular.woff2")
        missing = client.get("/static/vendor/katex-0.19.0/fonts/KaTeX_Main-Regular.ttf")

    assert script.status_code == 200
    assert font.status_code == 200
    assert missing.status_code == 404


def test_katex_vendor_ships_woff2_only_with_both_licences() -> None:
    fonts = sorted(path.suffix for path in (VENDOR / "fonts").iterdir())

    assert fonts == [".woff2"] * 20
    assert (
        (VENDOR / "LICENSE").read_text(encoding="utf-8").startswith("The MIT License")
    )
    assert "Khan Academy" in (VENDOR / "LICENSE-fonts").read_text(encoding="utf-8")

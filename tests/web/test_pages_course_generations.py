"""C8: the generations list sits above the form, which a button opens."""

from pathlib import Path

from fastapi.testclient import TestClient
from page_fixtures import BASE_URL

from sbobina.settings import Settings
from sbobina.web.app import create_app


def test_generations_list_comes_before_the_form_and_its_button(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/corsi").text

    section = body.split('id="corsi-generations"')[1].split("</section>")[0]
    assert section.index('id="generations-list"') < section.index(
        'id="generations-new"'
    )
    assert section.index('id="generations-new"') < section.index(
        'id="generations-form"'
    )
    button = section.split('id="generations-new"')[1].split(">")[0]
    assert 'aria-controls="generations-form"' in button
    assert 'aria-expanded="false"' in button

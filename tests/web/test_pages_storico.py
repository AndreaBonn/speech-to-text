"""T1/T2: history filters, course column and bulk clean-up of attempts."""

from pathlib import Path

from fastapi.testclient import TestClient
from page_fixtures import BASE_URL

from sbobina.settings import Settings
from sbobina.web.app import create_app


def _storico(tmp_path: Path) -> str:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body: str = client.get("/storico").text
    return body


def test_history_has_status_filters_and_a_course_filter(tmp_path: Path) -> None:
    body = _storico(tmp_path=tmp_path)

    filters = body.split('id="storico-filters"')[1].split("</div>")[0]
    for value, label in (
        ("all", "Tutte"),
        ("done", "Completate"),
        ("unfinished", "Non completate"),
    ):
        assert f'data-filter="{value}"' in filters
        assert label in filters
    assert 'data-filter="all" aria-pressed="true"' in filters
    assert '<select id="storico-course"' in body


def test_history_table_shows_the_course_column(tmp_path: Path) -> None:
    body = _storico(tmp_path=tmp_path)

    head = body.split("<thead>")[1].split("</thead>")[0]
    assert (
        head.index(">Lezione</th>")
        < head.index(">Corso</th>")
        < head.index(">Data</th>")
    )


def test_history_offers_a_hidden_bulk_delete_of_attempts(tmp_path: Path) -> None:
    body = _storico(tmp_path=tmp_path)

    bulk = body.split('id="storico-bulk"')[1].split("</div>")[0]
    assert "hidden" in bulk.split(">")[0]
    assert 'id="storico-bulk-delete"' in bulk

"""Course detail layout: title, scoped search, section bar, summary, lessons."""

from pathlib import Path

from fastapi.testclient import TestClient
from page_fixtures import BASE_URL

from sbobina.settings import Settings
from sbobina.web.app import create_app

SECTIONS = (
    ("corsi-lessons", "Lezioni"),
    ("corsi-examcues", "Frasi da esame"),
    ("corsi-materials", "Materiali"),
    ("corsi-generations", "Esercitazioni"),
    ("corsi-chat", "Domande sul corso"),
)


def _corsi(tmp_path: Path) -> str:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body: str = client.get("/corsi").text
    return body


def test_course_title_is_the_page_heading_with_a_path_back(tmp_path: Path) -> None:
    """S1: the detail view retitles the page h1, no back button, no second title."""
    body = _corsi(tmp_path=tmp_path)

    assert '<h1 class="page-title" id="corsi-page-title">Corsi</h1>' in body
    crumbs = body.split('id="corsi-breadcrumbs"')[1].split("</nav>")[0]
    assert "hidden" in crumbs.split(">")[0]
    assert '<a href="/corsi" id="corsi-crumb-root">Corsi</a>' in crumbs
    assert 'id="corsi-detail-back"' not in body
    assert 'id="corsi-detail-title"' not in body


def test_course_detail_has_a_section_bar_linking_every_section(tmp_path: Path) -> None:
    """C1: one anchor per section, each pointing at an existing id."""
    body = _corsi(tmp_path=tmp_path)

    bar = body.split('id="corsi-sections"')[1].split("</nav>")[0]
    for section_id, label in SECTIONS:
        assert f'href="#{section_id}"' in bar
        assert f">{label}</a>" in bar
        assert f'id="{section_id}"' in body


def test_course_detail_has_summary_slot_and_no_duration_column(tmp_path: Path) -> None:
    """C10 and C4."""
    body = _corsi(tmp_path=tmp_path)

    assert 'id="corsi-summary"' in body
    lessons = body.split('id="corsi-lessons"')[1].split("</table>")[0]
    assert "Durata" not in lessons
    assert ">Lezione</th>" in lessons


def test_retrieval_state_keeps_its_text_slot_and_explains_itself(
    tmp_path: Path,
) -> None:
    """C7: the status text sits next to a toggletip saying what it changes."""
    body = _corsi(tmp_path=tmp_path)

    state = body.split('id="corsi-detail-retrieval"')[1].split("</div>")[0]
    assert 'id="corsi-detail-retrieval-text"' in state
    assert 'class="toggletip"' in state
    assert "parole diverse" in state

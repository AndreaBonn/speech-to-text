import json
import runpy
import subprocess
import sys
from pathlib import Path

from conftest import make_segment, make_transcript, make_word

from sbobina.models import save_transcript

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "exam_cues_gold.py"


def write_transcript(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    transcript = make_transcript(
        segments=[make_segment(words=[make_word(text=text, start=2.0)])]
    )
    save_transcript(transcript=transcript, path=path)


def run_gold(
    jobs: list[Path], output: Path, cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args=[
            sys.executable,
            str(SCRIPT),
            *map(str, jobs),
            "--output-dir",
            str(output),
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def test_collect_candidates_repeated_quotes_keep_detector_priority() -> None:
    transcript = make_transcript(
        segments=[
            make_segment(words=[make_word(text=text, start=start)])
            for text, start in [
                ("Ricordatevi il termine. Domanda aperta?", 1.0),
                ("RICORDATEVI   IL TERMINE! domanda   aperta.", 2.0),
                ("È importante. Nessun segnale.", 3.0),
            ]
        ]
    )

    rows = runpy.run_path(path_name=str(SCRIPT))["collect_candidates"](
        transcript=transcript, job_id="lecture"
    )

    assert [row["quote"] for row in rows] == [
        "Ricordatevi il termine",
        "È importante",
        "Domanda aperta",
    ]
    assert [row["predicted"] for row in rows] == ["strong", "weak", None]
    assert [row["source"] for row in rows] == ["detector", "detector", "wide_net"]
    assert [row["segment_index"] for row in rows] == [0, 2, 0]
    assert [row["start"] for row in rows] == [1.0, 3.0, 1.0]


def test_main_multiple_jobs_write_only_unique_output_files(tmp_path: Path) -> None:
    jobs = [tmp_path / "first", tmp_path / "second"]
    write_transcript(path=jobs[0] / "audio.json", text="Domanda aperta")
    write_transcript(path=jobs[0] / "audio.corretto.json", text="Segnatevelo")
    write_transcript(path=jobs[1] / "audio.json", text="Domanda aperta")
    before = set(tmp_path.rglob("*"))
    output = tmp_path / "evaluation"

    for _ in range(2):
        result = run_gold(jobs=jobs, output=output, cwd=tmp_path)
        assert Path(result.stdout.strip()).parent == output

    created = {path for path in tmp_path.rglob("*") if path.is_file()} - before
    assert len(created) == 2
    assert all(path.parent == output for path in created)
    for path in created:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert [(row["job_id"], row["quote"]) for row in rows] == [
            ("first", "Segnatevelo"),
            ("second", "Domanda aperta"),
        ]
        assert all(row["label"] == "" for row in rows)


def test_main_missing_transcript_reports_job_without_writing(tmp_path: Path) -> None:
    job = tmp_path / "missing"
    job.mkdir()
    output = tmp_path / "evaluation"

    result = subprocess.run(
        check=False,
        args=[sys.executable, str(SCRIPT), str(job), "--output-dir", str(output)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "missing" in result.stderr
    assert not output.exists()


def test_collect_candidates_no_signals_returns_empty_list() -> None:
    transcript = make_transcript(
        segments=[
            make_segment(words=[make_word(text="Una frase ordinaria.", start=0.0)])
        ]
    )

    rows = runpy.run_path(path_name=str(SCRIPT))["collect_candidates"](
        transcript=transcript, job_id="lecture"
    )

    assert rows == []

import json
import runpy
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from conftest import make_segment, make_transcript, make_word

from sbobina.models import save_transcript

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "eval_exam_cues.py"


def write_gold(path: Path, labels: list[str]) -> None:
    rows = [
        {
            "job_id": "lecture",
            "segment_index": index,
            "start": float(index),
            "quote": f"Manual example {index}",
            "predicted": "strong",
            "source": "detector",
            "label": label,
        }
        for index, label in enumerate(labels)
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def write_job(directory: Path, text: str, filename: str = "audio.json") -> None:
    directory.mkdir(exist_ok=True)
    transcript = make_transcript(
        segments=[make_segment(words=[make_word(text=text, start=0.0)])]
    )
    save_transcript(transcript=transcript, path=directory / filename)


def run_eval(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        check=False,
        args=[sys.executable, str(SCRIPT), *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def manual_report(tmp_path: Path) -> tuple[dict[str, Any], str]:
    gold = tmp_path / "gold.jsonl"
    write_gold(path=gold, labels=["strong", "strong", "strong", "none", ""])
    result = run_eval(arguments=[str(gold), "--json"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), result.stderr


def test_main_manual_gold_reports_precision_075(
    manual_report: tuple[dict[str, Any], str],
) -> None:
    report, _ = manual_report
    assert report["precision"]["strong"] == {"correct": 3, "total": 4, "value": 0.75}


def test_main_unpredicted_level_reports_undefined_precision(
    manual_report: tuple[dict[str, Any], str],
) -> None:
    report, _ = manual_report
    assert report["precision"]["strong"]["value"] == 0.75
    assert report["precision"]["weak"] == {"correct": 0, "total": 0, "value": None}


def test_main_manual_gold_counts_all_rows(
    manual_report: tuple[dict[str, Any], str],
) -> None:
    report, _ = manual_report
    assert report["counts"] == {
        "total": 5,
        "labeled": 4,
        "unlabeled": 1,
        "by_source": {"detector": 5},
        "by_label": {"strong": 3, "none": 1, "": 1},
    }


def test_main_manual_gold_groups_rows_by_job(
    manual_report: tuple[dict[str, Any], str],
) -> None:
    report, _ = manual_report
    assert report["by_job"]["lecture"]["counts"]["total"] == 5


def test_main_unlabeled_row_reports_exact_warning(
    manual_report: tuple[dict[str, Any], str],
) -> None:
    report, stderr = manual_report
    assert report["warnings"] == ["1 righe non etichettate escluse dalle metriche."]
    assert stderr == "1 righe non etichettate escluse dalle metriche.\n"


def test_parse_row_invalid_label_names_file_and_line(tmp_path: Path) -> None:
    gold = tmp_path / "invalid.jsonl"
    write_gold(path=gold, labels=["maybe"])
    parse_row = runpy.run_path(path_name=str(SCRIPT))["parse_row"]

    with pytest.raises(ValueError, match=r"invalid\.jsonl:1:.*label.*maybe"):
        parse_row(text=gold.read_text(), location=f"{gold}:1")


def test_aggregate_mixed_sources_reports_estimated_recall() -> None:
    rows = [
        {"job_id": job, "source": source, "predicted": predicted, "label": label}
        for job, source, predicted, label in [
            ("a", "detector", "strong", "weak"),
            ("a", "detector", "weak", "weak"),
            ("b", "wide_net", None, "strong"),
            ("b", "wide_net", None, "none"),
            ("b", "wide_net", None, ""),
        ]
    ]

    report = runpy.run_path(path_name=str(SCRIPT))["aggregate"](rows=rows)

    assert report["precision"]["strong"]["value"] == 0.0
    assert report["precision"]["weak"]["value"] == 1.0
    assert report["wide_net_recall"] == {
        "estimate": True,
        "detected": 2,
        "missed": 1,
        "total": 3,
        "value": pytest.approx(2 / 3),
    }
    assert report["counts"]["by_source"] == {"detector": 2, "wide_net": 3}
    assert report["counts"]["by_label"] == {"weak": 2, "strong": 1, "none": 1, "": 1}


@pytest.mark.parametrize(
    ("second", "overlap", "only_a", "only_b", "common", "common_count"),
    [
        (
            "SEGNATEVELO. Ricordatevi il termine",
            1.0,
            [],
            [],
            ["ricordatevi il termine", "segnatevelo"],
            2,
        ),
        (
            "Segnatevelo. All’esame torna",
            1 / 3,
            ["ricordatevi il termine"],
            ["all’esame torna"],
            ["segnatevelo"],
            1,
        ),
    ],
)
def test_main_duplicate_pair_reports_overlap_and_differences(
    tmp_path: Path,
    second: str,
    overlap: float,
    only_a: list[str],
    only_b: list[str],
    common: list[str],
    common_count: int,
) -> None:
    gold = tmp_path / "gold.jsonl"
    write_gold(path=gold, labels=["strong"])
    jobs = [tmp_path / "a", tmp_path / "b"]
    write_job(directory=jobs[0], text="Segnatevelo. Ricordatevi il termine")
    write_job(directory=jobs[1], text="Trascrizione originale senza segnali")
    write_job(directory=jobs[1], text=second, filename="audio.corretto.json")

    arguments = [str(gold), "--json", "--job-dirs", *map(str, jobs)]
    result = run_eval(
        arguments=[*arguments, "--duplicate-pair", "a", "b"], cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)

    assert report["stability"]["overlap"] == pytest.approx(overlap)
    assert report["stability"]["only_b"] == only_b
    assert report["stability"]["only_a"] == only_a
    assert report["stability"]["common"] == common
    assert report["stability"]["common_count"] == common_count


def test_main_job_dirs_reports_detector_latency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gold = tmp_path / "gold.jsonl"
    write_gold(path=gold, labels=["strong"])
    jobs = [tmp_path / "a", tmp_path / "b"]
    for directory in jobs:
        write_job(directory=directory, text="Segnatevelo")
    main = runpy.run_path(path_name=str(SCRIPT))["main"]
    ticks = iter([1.0, 1.125, 2.0, 2.25])
    monkeypatch.setattr(time, "perf_counter", lambda: next(ticks))

    main(argv=[str(gold), "--json", "--job-dirs", *map(str, jobs)])
    measured = json.loads(capsys.readouterr().out)["latency"]
    main(argv=[str(gold), "--json"])
    skipped = json.loads(capsys.readouterr().out)["latency"]

    assert measured == {
        "status": "measured",
        "by_job_ms": {"a": 125.0, "b": 250.0},
        "total_ms": 375.0,
        "scope": "find_exam_cues only; one call per job, no warm-up",
    }
    assert skipped == {
        "status": "skipped",
        "by_job_ms": {},
        "total_ms": None,
        "scope": "find_exam_cues only; one call per job, no warm-up",
    }


def test_main_duplicate_pair_without_transcripts_reports_error(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    write_gold(path=gold, labels=["strong"])

    result = subprocess.run(
        check=False,
        args=[sys.executable, str(SCRIPT), str(gold), "--duplicate-pair", "a", "b"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--job-dirs" in result.stderr


def test_main_empty_gold_reports_undefined_metrics_in_text(tmp_path: Path) -> None:
    gold = tmp_path / "empty.jsonl"
    gold.write_text("", encoding="utf-8")

    result = subprocess.run(
        args=[sys.executable, str(SCRIPT), str(gold)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Precisione strong: n/d (0/0)" in result.stdout
    assert "Recall stimato sulla rete larga: n/d (0/0)" in result.stdout
    assert "Latenza: non misurata" in result.stdout


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("label", None),
        ("label", []),
        ("source", "unknown"),
        ("predicted", None),
        ("quote", ""),
        ("job_id", 7),
        ("start", -1.0),
        ("start", float("nan")),
        ("segment_index", True),
    ],
)
def test_parse_row_invalid_fields_report_location(field: str, value: object) -> None:
    row = {
        "job_id": "a",
        "segment_index": 0,
        "start": 0.0,
        "quote": "Example",
        "source": "detector",
        "predicted": "strong",
        "label": "strong",
    }
    row[field] = value
    parse_row = runpy.run_path(path_name=str(SCRIPT))["parse_row"]

    with pytest.raises(ValueError, match=r"gold\.jsonl:2:"):
        parse_row(text=json.dumps(row), location="gold.jsonl:2")


def test_main_malformed_second_line_reports_file_and_line(tmp_path: Path) -> None:
    gold = tmp_path / "invalid.jsonl"
    write_gold(path=gold, labels=["strong"])
    gold.write_text(gold.read_text() + "\n{broken", encoding="utf-8")

    result = run_eval(arguments=[str(gold), "--json"], cwd=tmp_path)

    assert result.returncode == 1
    assert f"{gold}:2" in result.stderr
    assert result.stdout == ""


def test_main_multiple_gold_files_combines_counts_without_writes(
    tmp_path: Path,
) -> None:
    first, second = tmp_path / "first.jsonl", tmp_path / "second.jsonl"
    write_gold(path=first, labels=["strong", "none"])
    write_gold(path=second, labels=["strong"])
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    result = run_eval(arguments=[str(first), str(second), "--json"], cwd=tmp_path)
    report = json.loads(result.stdout)

    assert report["precision"]["strong"]["total"] == 3
    assert report["precision"]["strong"]["correct"] == 2
    assert {
        path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    } == before


def test_compare_strong_empty_sets_reports_undefined_overlap() -> None:
    report = runpy.run_path(path_name=str(SCRIPT))["compare_strong"](
        cues_a=(), cues_b=()
    )

    assert report["overlap"] is None
    assert report["common_count"] == 0
    assert report["only_a_count"] == 0
    assert report["only_b_count"] == 0


def test_main_redetect_scores_the_current_detector(tmp_path: Path) -> None:
    # The stored prediction says "none detected"; the transcript has a cue.
    gold = tmp_path / "gold.jsonl"
    row = {
        "job_id": "lecture",
        "segment_index": 0,
        "start": 0.0,
        "quote": "Segnatevelo",
        "predicted": None,
        "source": "wide_net",
        "label": "strong",
    }
    gold.write_text(json.dumps(row), encoding="utf-8")
    write_job(directory=tmp_path / "lecture", text="Segnatevelo")

    stored = json.loads(run_eval(arguments=[str(gold), "--json"], cwd=tmp_path).stdout)
    fresh = json.loads(
        run_eval(
            arguments=[
                str(gold),
                "--json",
                "--redetect",
                "--job-dirs",
                str(tmp_path / "lecture"),
            ],
            cwd=tmp_path,
        ).stdout
    )

    assert stored["precision"]["strong"]["total"] == 0
    assert fresh["precision"]["strong"] == {"correct": 1, "total": 1, "value": 1.0}
    assert fresh["unlabeled_detections"] == []


def test_main_redetect_without_job_dirs_is_an_error(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    write_gold(path=gold, labels=["strong"])

    result = run_eval(arguments=[str(gold), "--redetect"], cwd=tmp_path)

    assert result.returncode == 1
    assert "--redetect" in result.stderr

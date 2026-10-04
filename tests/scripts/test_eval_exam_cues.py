import json
import runpy
import subprocess
import sys
from pathlib import Path

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


def test_main_manual_gold_three_correct_reports_precision_075(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    write_gold(path=gold, labels=["strong", "strong", "strong", "none", ""])

    result = subprocess.run(
        args=[sys.executable, str(SCRIPT), str(gold), "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(result.stdout)

    assert report["precision"]["strong"] == {"correct": 3, "total": 4, "value": 0.75}
    assert report["precision"]["weak"]["value"] is None
    assert report["counts"]["total"] == 5
    assert report["counts"]["unlabeled"] == 1
    assert report["by_job"]["lecture"]["counts"]["total"] == 5
    assert report["latency"]["status"] == "skipped"
    assert report["warnings"]
    assert "1" in result.stderr


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
    ("second", "overlap", "only_b"),
    [
        ("SEGNATEVELO. Ricordatevi il termine", 1.0, []),
        ("Segnatevelo. All'esame torna", 1 / 3, ["all'esame torna"]),
    ],
)
def test_main_duplicate_pair_reports_overlap_and_differences(
    tmp_path: Path, second: str, overlap: float, only_b: list[str]
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
    assert report["stability"]["only_a"] == (
        [] if overlap == 1.0 else ["ricordatevi il termine"]
    )
    assert report["stability"]["common_count"] == (2 if overlap == 1.0 else 1)
    assert set(report["latency"]["by_job_ms"]) == {"a", "b"}
    assert all(value >= 0 for value in report["latency"]["by_job_ms"].values())


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

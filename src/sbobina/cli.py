import argparse
import logging
import sys
from collections.abc import Callable
from pathlib import Path

from sbobina.models import Transcript, load_transcript, save_transcript
from sbobina.render import RenderOptions, render_markdown
from sbobina.settings import settings
from sbobina.wer import compute_wer

logger = logging.getLogger("sbobina")

INPUT_FILE_ARGS = ("audio", "trascrizione", "riferimento", "ipotesi")


def parse_threshold(value: str) -> float:
    """Argparse type for ``--soglia``: a confidence in ``(0, 1]``."""
    try:
        threshold = float(value)
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"non è un numero: {value}") from err
    if not 0.0 < threshold <= 1.0:
        raise argparse.ArgumentTypeError(f"deve essere fra 0 (escluso) e 1: {value}")
    return threshold


def _render_options(threshold: float | None) -> RenderOptions:
    return RenderOptions(
        uncertain_threshold=threshold
        if threshold is not None
        else settings.uncertain_threshold,
        paragraph_gap_s=settings.paragraph_gap_s,
        paragraph_max_s=settings.paragraph_max_s,
    )


def _write_markdown(
    transcript: Transcript, json_path: Path, threshold: float | None
) -> Path:
    markdown_path = json_path.with_suffix(".md")
    markdown_path.write_text(
        render_markdown(transcript, _render_options(threshold)), encoding="utf-8"
    )
    return markdown_path


def cmd_trascrivi(args: argparse.Namespace) -> int:
    from sbobina.transcriber import transcribe_file  # heavy import only when needed

    audio_path: Path = args.audio
    output_dir: Path = args.output_dir or audio_path.parent
    if output_dir.exists() and not output_dir.is_dir():
        logger.error("La destinazione non è una cartella: %s", output_dir)
        return 1
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript = transcribe_file(audio_path, settings)
    json_path = output_dir / f"{audio_path.stem}.json"
    save_transcript(transcript, json_path)
    markdown_path = _write_markdown(transcript, json_path, args.soglia)
    logger.info("Scritti %s e %s", json_path, markdown_path)
    return 0


def cmd_rendi(args: argparse.Namespace) -> int:
    json_path: Path = args.trascrizione
    markdown_path = _write_markdown(load_transcript(json_path), json_path, args.soglia)
    logger.info("Scritto %s", markdown_path)
    return 0


def cmd_wer(args: argparse.Namespace) -> int:
    hypothesis_path: Path = args.ipotesi
    hypothesis = (
        load_transcript(hypothesis_path).text
        if hypothesis_path.suffix == ".json"
        else hypothesis_path.read_text(encoding="utf-8")
    )
    report = compute_wer(
        reference=args.riferimento.read_text(encoding="utf-8"), hypothesis=hypothesis
    )
    print(
        f"WER {report.wer:.2%} su {report.reference_words} parole: "
        f"{report.substitutions} sostituite, {report.deletions} mancanti, "
        f"{report.insertions} in più"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sbobina", description="Sbobinature di lezioni"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    trascrivi = commands.add_parser("trascrivi", help="Trascrive un file audio")
    trascrivi.add_argument("audio", type=Path)
    trascrivi.add_argument("-o", "--output-dir", type=Path, default=None)
    trascrivi.add_argument(
        "--soglia", type=parse_threshold, default=None, help="Soglia parole incerte"
    )
    trascrivi.set_defaults(handler=cmd_trascrivi)

    rendi = commands.add_parser(
        "rendi", help="Rigenera il .md da un .json senza ritrascrivere"
    )
    rendi.add_argument("trascrizione", type=Path)
    rendi.add_argument("--soglia", type=parse_threshold, default=None)
    rendi.set_defaults(handler=cmd_rendi)

    wer = commands.add_parser(
        "wer", help="Confronta con una trascrizione di riferimento"
    )
    wer.add_argument("riferimento", type=Path, help="Testo corretto (.txt)")
    wer.add_argument(
        "ipotesi", type=Path, help="Trascrizione da valutare (.json o .txt)"
    )
    wer.set_defaults(handler=cmd_wer)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = build_parser().parse_args(argv)
    inputs = [getattr(args, name) for name in INPUT_FILE_ARGS if hasattr(args, name)]
    missing = [path for path in inputs if not path.is_file()]
    if missing:
        logger.error("File non trovato: %s", ", ".join(str(path) for path in missing))
        return 1
    handler: Callable[[argparse.Namespace], int] = args.handler
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())

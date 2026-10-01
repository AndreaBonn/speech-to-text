from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from pathlib import Path

from sbobina import pipeline
from sbobina.models import load_transcript
from sbobina.render import format_timestamp
from sbobina.settings import Settings, settings
from sbobina.wer import compute_wer

logger = logging.getLogger("sbobina")

INPUT_FILE_ARGS = ("audio", "trascrizione", "riferimento", "ipotesi")
MIN_PORT, MAX_PORT = 1, 65535


def parse_port(value: str) -> int:
    """Argparse type for ``--port``: a TCP port in ``[1, 65535]``."""
    try:
        port = int(value)
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"non è un numero: {value}") from err
    if not MIN_PORT <= port <= MAX_PORT:
        raise argparse.ArgumentTypeError(
            f"deve essere fra {MIN_PORT} e {MAX_PORT}: {value}"
        )
    return port


def parse_threshold(value: str) -> float:
    """Argparse type for ``--soglia``: a confidence in ``(0, 1]``."""
    try:
        threshold = float(value)
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"non è un numero: {value}") from err
    if not 0.0 < threshold <= 1.0:
        raise argparse.ArgumentTypeError(f"deve essere fra 0 (escluso) e 1: {value}")
    return threshold


def _config_for(args: argparse.Namespace) -> Settings:
    """Apply the command-line overrides to the global settings."""
    options = vars(args)
    overrides = {
        "uncertain_threshold": options.get("soglia"),
        "ollama_model": options.get("modello"),
    }
    return settings.model_copy(
        update={key: value for key, value in overrides.items() if value is not None}
    )


def cmd_trascrivi(args: argparse.Namespace) -> int:
    audio_path: Path = args.audio
    output_dir: Path = args.output_dir or audio_path.parent
    if output_dir.exists() and not output_dir.is_dir():
        logger.error("La destinazione non è una cartella: %s", output_dir)
        return 1
    json_path = pipeline.transcribe_to_dir(
        audio_path, output_dir=output_dir, config=_config_for(args)
    )
    logger.info("Scritti %s e %s", json_path, json_path.with_suffix(".md"))
    return 0


def cmd_rendi(args: argparse.Namespace) -> int:
    json_path: Path = args.trascrizione
    markdown_path = pipeline.write_markdown(
        load_transcript(json_path), json_path=json_path, config=_config_for(args)
    )
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


def cmd_correggi(args: argparse.Namespace) -> int:
    json_path: Path = args.trascrizione
    config = _config_for(args)
    outcome = pipeline.correct_to_dir(
        json_path,
        config=config,
        subject=args.materia,
        on_progress=lambda done, total: logger.info(
            "Corretti %d paragrafi su %d", done, total
        ),
    )
    if outcome.corrected_json is not None:
        _, report_path = pipeline.corrected_paths(json_path)
        logger.info(
            "Scritti %s e %s", outcome.corrected_json.with_suffix(".md"), report_path
        )
    if not outcome.interrupted:
        return 0
    interrupted_at = outcome.result.interrupted_at
    assert interrupted_at is not None
    logger.error(
        "Ollama non raggiungibile o modello %s non scaricato: correzione interrotta a %s",
        config.ollama_model,
        format_timestamp(interrupted_at),
    )
    return 1


def cmd_web(args: argparse.Namespace) -> int:
    from sbobina.web.launcher import run_server  # lazy: other commands skip FastAPI

    config = settings
    if args.port is not None:
        config = settings.model_copy(update={"web_port": args.port})
    return run_server(config=config, open_browser=not args.no_browser)


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
    _add_correggi_parser(commands)
    _add_web_parser(commands)
    return parser


def _add_web_parser(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    web = commands.add_parser("web", help="Avvia l'interfaccia web locale")
    web.add_argument("--port", type=parse_port, default=None, help="Porta del server")
    web.add_argument("--no-browser", action="store_true", help="Non aprire il browser")
    web.set_defaults(handler=cmd_web)


def _add_correggi_parser(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    correggi = commands.add_parser(
        "correggi",
        help="Corregge le parole sentite male con un modello locale (Ollama)",
    )
    correggi.add_argument(
        "trascrizione", type=Path, help="Il .json prodotto da trascrivi"
    )
    correggi.add_argument("--materia", default=None, help='Es. "diritto privato"')
    correggi.add_argument("--modello", default=None, help="Modello Ollama da usare")
    correggi.add_argument("--soglia", type=parse_threshold, default=None)
    correggi.set_defaults(handler=cmd_correggi)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    # httpx logs every Ollama request at INFO, burying the progress lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)
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

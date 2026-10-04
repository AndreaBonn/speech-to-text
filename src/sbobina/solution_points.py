import re

from sbobina.generation_models import GenerationFormat

ORAL_POINT_SEPARATOR = " | "
# Unlike exam_cues.SENTENCE_SEPARATOR, a period followed by a digit or a
# lowercase word is an abbreviation ("art. 1418", "pag. iniziale"), not a
# sentence end: splitting there would make the judge cite half a point.
SOLUTION_SENTENCE_SEPARATOR = re.compile(r"[.!?]+(?=\s+(?![a-zà-öø-ÿ\d])|\s*$)")


def extract_solution_points(solution: str, format: GenerationFormat) -> tuple[str, ...]:
    if not solution.strip() or format not in (
        GenerationFormat.ORAL,
        GenerationFormat.OPEN,
    ):
        return ()
    parts = (
        solution.split(sep=ORAL_POINT_SEPARATOR)
        if format == GenerationFormat.ORAL
        else SOLUTION_SENTENCE_SEPARATOR.split(string=solution)
    )
    return tuple(point for part in parts if (point := part.strip()))

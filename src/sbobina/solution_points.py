import re

from sbobina.generation_models import GenerationFormat

ORAL_POINT_SEPARATOR = " | "
# Unlike exam_cues.SENTENCE_SEPARATOR, a period followed by a digit or a
# lowercase word is an abbreviation ("art. 1418", "pag. iniziale"), not a
# sentence end: splitting there would make the judge cite half a point.
SOLUTION_SENTENCE_SEPARATOR = re.compile(r"[.!?]+(?=\s+(?![a-zà-öø-ÿ\d])|\s*$)")
# List markers ("1.", "2)") separate items at the start or on a new line. Mid
# line ("X. 2. La") they also look like "par. 3) Il", so they count only in a
# solution that opens with a "1" marker and only before a capital letter.
LINE_MARKER = re.compile(r"(?:\A\s*|\n\s*)\d{1,2}[.)]\s+")
LIST_START = re.compile(r"\A\s*1[.)]\s+")
INLINE_MARKER = re.compile(r"(?<=[.!?;])\s+\d{1,2}[.)]\s+(?=[A-ZÀ-Ý])")


def _list_items(solution: str) -> list[str]:
    items = LINE_MARKER.split(string=solution)
    if not LIST_START.match(string=solution):
        return items
    return [part for item in items for part in INLINE_MARKER.split(string=item)]


def extract_solution_points(solution: str, format: GenerationFormat) -> tuple[str, ...]:
    if not solution.strip() or format not in (
        GenerationFormat.ORAL,
        GenerationFormat.OPEN,
    ):
        return ()
    # An oral outline written as prose (no " | ") is split like an open
    # solution: one point per sentence beats one point for the whole answer.
    parts = (
        solution.split(sep=ORAL_POINT_SEPARATOR)
        if format == GenerationFormat.ORAL and ORAL_POINT_SEPARATOR in solution
        else [
            sentence
            for item in _list_items(solution=solution)
            for sentence in SOLUTION_SENTENCE_SEPARATOR.split(string=item)
        ]
    )
    return tuple(point for part in parts if (point := part.strip()))

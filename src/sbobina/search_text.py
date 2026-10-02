import re
from dataclasses import dataclass

from sbobina.models import Transcript

MATCH_START = "\ue000"
MATCH_END = "\ue001"
MAX_TERMS = 10
MIN_WORD_LENGTH = 2
MIN_STEM_LENGTH = 5
FINAL_VOWELS = "aeiouàèéìòóùAEIOUÀÈÉÌÒÓÙ"
QUERY_TERMS = re.compile(r'"((?:[^"]|"")*)"|(\w+)')


@dataclass(frozen=True)
class Passage:
    segment_index: int
    start: float
    text: str


@dataclass(frozen=True)
class SnippetPart:
    text: str
    match: bool


def passages_from_transcript(transcript: Transcript) -> list[Passage]:
    return [
        Passage(segment_index=index, start=segment.start, text=segment.text)
        for index, segment in enumerate(transcript.segments)
        if segment.text
    ]


def build_match_query(raw: str) -> str | None:
    """Quote literal terms; see https://www.sqlite.org/fts5.html#fts5_strings."""
    terms = []
    for token in QUERY_TERMS.finditer(raw.replace("\x00", " ")):
        phrase, word = token.groups()
        if phrase is not None:
            text = phrase.replace('""', '"').strip()
            if re.search(r"\w", text):
                terms.append('"' + text.replace('"', '""') + '"')
        elif len(word) >= MIN_WORD_LENGTH:
            text = word.rstrip(FINAL_VOWELS) if len(word) >= MIN_STEM_LENGTH else word
            if text:
                terms.append(f'"{text}"*')
        if len(terms) == MAX_TERMS:
            break
    return " ".join(terms) or None


def snippet_parts(highlighted: str) -> list[SnippetPart]:
    parts: list[SnippetPart] = []
    is_match = False
    for text in re.split(f"([{MATCH_START}{MATCH_END}])", highlighted):
        if text in (MATCH_START, MATCH_END):
            is_match = text == MATCH_START
        elif text:
            parts.append(SnippetPart(text=text, match=is_match))
    return parts

from sbobina.models import Segment, Transcript, Word


def make_word(text: str, start: float, probability: float = 0.99) -> Word:
    return Word(start=start, end=start + 0.4, text=text, probability=probability)


def make_segment(words: list[Word]) -> Segment:
    return Segment(start=words[0].start, end=words[-1].end, words=tuple(words))


def make_transcript(segments: list[Segment]) -> Transcript:
    return Transcript(
        source="lezione.m4a",
        model="large-v3",
        language="it",
        duration=segments[-1].end,
        segments=tuple(segments),
    )

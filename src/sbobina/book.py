from sbobina.models import Transcript
from sbobina.render import RenderOptions, group_paragraphs


def book_paragraphs(transcript: Transcript, options: RenderOptions) -> list[str]:
    """Plain reading paragraphs: no timestamps, no uncertainty or correction marks.

    Paragraph boundaries are the reader's and the Markdown's, so the exported
    document breaks where the user saw it break while reviewing.
    """
    paragraphs = (
        "".join(word.text for segment in group for word in segment.words).split()
        for group in group_paragraphs(segments=transcript.segments, options=options)
    )
    return [" ".join(tokens) for tokens in paragraphs if tokens]


def render_book_text(title: str, paragraphs: list[str]) -> str:
    """Title, then paragraphs separated by one blank line; no hard wrapping."""
    return "\n\n".join([title, *paragraphs]) + "\n"

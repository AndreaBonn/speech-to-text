import html
import re
from dataclasses import dataclass, replace
from pathlib import Path

from pydantic import TypeAdapter

from sbobina.models import Transcript
from sbobina.render import RenderOptions, group_paragraphs
from sbobina.study_blocks import study_timestamp
from sbobina.study_citations import validate_item
from sbobina.study_files import atomic_write_pair
from sbobina.study_models import (
    ConceptItem,
    QuestionItem,
    Rejection,
    StudyChapter,
    StudyItem,
    StudyResult,
)
from sbobina.study_validation import validate_chapter

STUDY_ADAPTER = TypeAdapter(StudyResult)


@dataclass(frozen=True)
class LoadedStudy:
    result: StudyResult
    stale_dropped: int


def revalidate_study(result: StudyResult, transcript: Transcript) -> LoadedStudy:
    chapters = []
    stale_dropped = 0
    for original in result.chapters:
        chapter, counts = validate_chapter(
            chapter=original,
            segments=transcript.segments,
            allowed=frozenset(range(len(transcript.segments))),
        )
        stale_dropped += sum(counts.values())
        if chapter is not None:
            chapters.append(chapter)
    return LoadedStudy(
        result=replace(result, chapters=tuple(sorted(chapters, key=lambda c: c.start))),
        stale_dropped=stale_dropped,
    )


def load_study(path: Path, transcript: Transcript) -> LoadedStudy:
    """Revalidate saved quotes against the current transcript, counting stale items."""
    result = STUDY_ADAPTER.validate_json(path.read_text(encoding="utf-8"))
    return revalidate_study(result=result, transcript=transcript)


def _escape_markdown(text: str) -> str:
    return re.sub(
        r"([\\`*_{}\[\]()#+.!|>~-])",
        r"\\\1",
        html.escape(" ".join(text.split()), quote=False),
    )


def _item_text(item: StudyItem) -> str:
    if isinstance(item, ConceptItem):
        return f"{item.term}: {item.explanation}"
    if isinstance(item, QuestionItem):
        return item.question
    return item.text


def _render_item(
    item: StudyItem, transcript: Transcript, paragraphs: dict[int, int]
) -> list[str]:
    validated = validate_item(
        segments=transcript.segments,
        item=item,
        allowed=frozenset(range(len(transcript.segments))),
    )
    if isinstance(validated, Rejection):
        return []
    lines = [f"- {_escape_markdown(text=_item_text(item=item))}"]
    for citation, match in zip(item.citations, validated.citations, strict=True):
        paragraph = paragraphs[match.word_indices[0].segment_index]
        lines.append(
            f"  > §{paragraph} {study_timestamp(seconds=match.timestamp)}: "
            f"{_escape_markdown(text=citation.quote)}"
        )
    return lines


def _paragraph_numbers(
    transcript: Transcript, options: RenderOptions
) -> dict[int, int]:
    paragraphs = group_paragraphs(segments=transcript.segments, options=options)
    numbers = [
        number for number, group in enumerate(paragraphs, start=1) for _ in group
    ]
    return dict(enumerate(numbers))


def _render_chapter(
    chapter: StudyChapter, transcript: Transcript, paragraphs: dict[int, int]
) -> list[str]:
    title = _escape_markdown(text=chapter.title)
    lines = [f"## {title} ({study_timestamp(seconds=chapter.start)})", ""]
    for heading, items in (
        ("Riassunto", chapter.summary),
        ("Concetti", chapter.concepts),
        ("Domande di ripasso", chapter.questions),
    ):
        if not items:
            continue
        lines.extend([f"### {heading}", ""])
        for item in items:
            lines.extend(
                _render_item(item=item, transcript=transcript, paragraphs=paragraphs)
            )
        lines.append("")
    return lines


def render_study_markdown(
    result: StudyResult, transcript: Transcript, options: RenderOptions
) -> str:
    current = revalidate_study(result=result, transcript=transcript).result
    paragraphs = _paragraph_numbers(transcript=transcript, options=options)
    lines = ["# Materiali di studio", ""]
    for chapter in current.chapters:
        lines.extend(
            _render_chapter(
                chapter=chapter, transcript=transcript, paragraphs=paragraphs
            )
        )
    if current.failed_blocks:
        lines.extend(["## Blocchi non elaborati", ""])
        lines.extend(
            f"- {study_timestamp(seconds=b.start)} – {study_timestamp(seconds=b.end)}"
            for b in current.failed_blocks
        )
    return "\n".join(lines) + "\n"


def save_study(
    result: StudyResult, json_path: Path, transcript: Transcript, options: RenderOptions
) -> None:
    """Stage both outputs before replacing either destination in its own directory."""
    current = revalidate_study(result=result, transcript=transcript).result
    content = STUDY_ADAPTER.dump_json(current, indent=2).decode("utf-8") + "\n"
    markdown = render_study_markdown(
        result=current, transcript=transcript, options=options
    )
    atomic_write_pair(
        contents={json_path: content, json_path.with_suffix(".md"): markdown}
    )

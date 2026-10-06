"""LLM-response schema of open and oral exam questions (F41).

Split out of generation_models.py (300-line cap). Like every ``Proposed*``
class, these parse the raw reply and are never written to disk.
"""

from typing import Any

from pydantic import BaseModel, Field, model_validator

from sbobina.generation_models import ORAL_POINT_SEPARATOR, ProposedCitation


def _as_sentence(point: str) -> str:
    sentence = point[:1].upper() + point[1:]
    return sentence if sentence.endswith((".", "!", "?")) else f"{sentence}."


class ProposedTextQuestion(BaseModel):
    """An open question; the solution comes as a "punti" list (compito-v4).

    A free-text "soluzione" (older prompts) is still read. With one string,
    qwen wrote single-point solutions whatever the prompt said (F41); the
    points are joined into the stored solution so solution_points.py splits
    them back for the judge.
    """

    question: str = Field(alias="domanda")
    solution: str = Field(alias="soluzione")
    citations: list[ProposedCitation] = Field(alias="citazioni")

    @classmethod
    def join_points(cls, points: list[str]) -> str:
        return " ".join(_as_sentence(point=point) for point in points)

    @model_validator(mode="before")
    @classmethod
    def _solution_from_points(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("punti"), list):
            return data
        points = [
            point.strip()
            for point in data["punti"]
            if isinstance(point, str) and point.strip()
        ]
        return {**data, "soluzione": cls.join_points(points=points)} if points else data


class ProposedOralQuestion(ProposedTextQuestion):
    """An oral question: the points form an outline split on " | "."""

    @classmethod
    def join_points(cls, points: list[str]) -> str:
        # A separator inside a point would split it in two for the judge (A29);
        # a lone "|" stays, it is an absolute value in \(|q| < 1\).
        return ORAL_POINT_SEPARATOR.join(
            point.replace(ORAL_POINT_SEPARATOR, ", ") for point in points
        )


class TextQuestionResponse(BaseModel):
    questions: list[ProposedTextQuestion] = Field(alias="domande")


class OralQuestionResponse(BaseModel):
    questions: list[ProposedOralQuestion] = Field(alias="domande")

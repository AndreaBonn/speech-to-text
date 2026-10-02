import json
from dataclasses import dataclass, field

from sbobina.models import Segment, Transcript, Word
from sbobina.ollama_chat import ChatRequest

QUOTE = "la causa del contratto è illecita"


def transcript_fixture() -> Transcript:
    segments = tuple(
        Segment(
            start=start,
            end=start + len(text.split()),
            words=tuple(
                Word(
                    start=start + i,
                    end=start + i + 0.5,
                    text=" " + token,
                    probability=1.0,
                )
                for i, token in enumerate(text.split())
            ),
        )
        for start, text in ((0.0, "inizio della lezione"), (10.0, QUOTE))
    )
    return Transcript(
        source="audio.wav",
        model="whisper",
        language="it",
        duration=16.0,
        segments=segments,
    )


def response_fixture(quote: str = QUOTE, passage: str = "S1") -> str:
    citation = {"passaggio": passage, "testo": quote}
    return json.dumps(
        {
            "capitoli": [
                {
                    "titolo": "Contratto",
                    "inizio": 10,
                    "riassunto": [
                        {"testo": "La causa è illecita.", "citazioni": [citation]}
                    ],
                    "concetti": [
                        {
                            "termine": "causa",
                            "spiegazione": "Causa illecita",
                            "citazioni": [citation],
                        }
                    ],
                    "domande": [
                        {"domanda": "Com'è la causa?", "citazioni": [citation]}
                    ],
                }
            ]
        }
    )


@dataclass
class FakeChat:
    responses: list[str | Exception]
    requests: list[ChatRequest] = field(default_factory=list)

    def __call__(self, request: ChatRequest) -> str:
        self.requests.append(request)
        result = self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]
        if isinstance(result, Exception):
            raise result
        return result

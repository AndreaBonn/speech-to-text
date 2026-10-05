from typing import cast

import httpx
import ollama
import pytest

from sbobina.correction import CorrectorUnavailableError
from sbobina.ollama_vision import read_page_image

PNG_BYTES = b"\x89PNG\r\n\x1a\n fake"


class FakeClient:
    def __init__(self, content: str | None = None, error: Exception | None = None):
        self.content = content
        self.error = error
        self.arguments: dict[str, object] = {}

    def generate(self, **kwargs: object) -> ollama.GenerateResponse:
        self.arguments = kwargs
        if self.error is not None:
            raise self.error
        return ollama.GenerateResponse(response=self.content)


def test_read_page_image_returns_stripped_text() -> None:
    client = FakeClient(content="  Testo della pagina.  \n")
    text = read_page_image(
        client=cast(ollama.Client, client), model="qwen2.5vl:7b", png=PNG_BYTES
    )
    assert text == "Testo della pagina."
    assert client.arguments["model"] == "qwen2.5vl:7b"
    assert client.arguments["images"] == [PNG_BYTES]
    assert client.arguments["options"] == {"temperature": 0, "num_ctx": 4096}


def test_read_page_image_sends_the_ocr_prompt() -> None:
    client = FakeClient(content="testo")
    read_page_image(
        client=cast(ollama.Client, client), model="qwen2.5vl:7b", png=PNG_BYTES
    )
    assert "Trascrivi il testo di questa pagina" in str(client.arguments["prompt"])
    # T063: the default is ocr-v2, which asks for formulas between \( and \).
    assert "\\(" in str(client.arguments["prompt"])


def test_read_page_image_with_an_older_prompt_file_sends_it() -> None:
    client = FakeClient(content="testo")
    read_page_image(
        client=cast(ollama.Client, client),
        model="qwen2.5vl:7b",
        png=PNG_BYTES,
        prompt_file="ocr-v1.md",
    )
    prompt = str(client.arguments["prompt"])
    assert "Trascrivi il testo di questa pagina" in prompt
    assert "LaTeX" not in prompt


@pytest.mark.parametrize(
    "error",
    [
        ollama.ResponseError("missing", status_code=404),
        httpx.ReadError("reset"),
        ConnectionError("refused"),
    ],
)
def test_read_page_image_unreachable_raises_corrector_unavailable(
    error: Exception,
) -> None:
    client = FakeClient(error=error)
    with pytest.raises(CorrectorUnavailableError):
        read_page_image(
            client=cast(ollama.Client, client), model="qwen2.5vl:7b", png=PNG_BYTES
        )

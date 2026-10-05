"""Build the synthetic formula pages for the V10 OCR measure (T060).

    uv run --with pillow python scripts/math_pages.py data/eval/math

Each page of math_pages_content.py is typeset with pdflatex, rasterised with
pdftoppm, degraded like a scan (small rotation, blur, noise; fixed seed) and
saved as an image-only PDF, so the app has to OCR it. truth.json keeps the
original LaTeX of every formula, in page order.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from math_pages_content import PAGES, Page, Segment
from PIL import Image, ImageFilter

DPI = 200
SEED = 20261005
MAX_ROTATION_DEG = 0.6
BLUR_RADIUS = 0.6
NOISE_LEVEL = 18
PREAMBLE = r"""\documentclass[12pt,a4paper]{article}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb}
\usepackage[margin=2.5cm]{geometry}
\pagestyle{empty}
\begin{document}
"""


def segment_tex(segment: Segment) -> str:
    if isinstance(segment, str):
        return segment.replace("%", r"\%").replace("$", r"\$")
    kind, value = segment
    if kind == "i":
        return rf"\({value}\)"
    if kind == "d":
        return rf"\[{value}\]"
    return rf"\textit{{{value}}}"


def page_tex(page: Page) -> str:
    title, paragraphs = page
    body = "\n\n".join(
        "".join(segment_tex(s) for s in paragraph) for paragraph in paragraphs
    )
    return PREAMBLE + rf"\section*{{{title}}}" + "\n" + body + "\n\\end{document}\n"


def page_truth(page: Page) -> list[dict[str, object]]:
    return [
        {"latex": segment[1], "display": segment[0] == "d"}
        for paragraph in page[1]
        for segment in paragraph
        if isinstance(segment, tuple) and segment[0] in ("i", "d")
    ]


def degrade(image: Image.Image, rng: random.Random) -> Image.Image:
    gray = image.convert("L")
    angle = rng.uniform(-MAX_ROTATION_DEG, MAX_ROTATION_DEG)
    rotated = gray.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=255)
    blurred = rotated.filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS))
    noise = Image.effect_noise(blurred.size, NOISE_LEVEL)
    return Image.blend(blurred, noise, alpha=0.08)


def render_page(tex: str, workdir: Path, rng: random.Random) -> Image.Image:
    (workdir / "page.tex").write_text(tex, encoding="utf-8")
    subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "page.tex"],
        cwd=workdir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["pdftoppm", "-r", str(DPI), "-png", "-singlefile", "page.pdf", "page"],
        cwd=workdir,
        check=True,
    )
    with Image.open(workdir / "page.png") as image:
        return degrade(image=image, rng=rng)


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    truth = []
    for number, page in enumerate(PAGES, start=1):
        with TemporaryDirectory() as temporary:
            image = render_page(
                tex=page_tex(page=page), workdir=Path(temporary), rng=rng
            )
        name = f"pagina-{number:02d}"
        image.save(out / f"{name}.pdf", format="PDF", resolution=DPI)
        image.save(out / f"{name}.png")
        truth.append(
            {"page": name, "title": page[0], "formulas": page_truth(page=page)}
        )
    (out / "truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"{len(truth)} pagine, {sum(len(p['formulas']) for p in truth)} formule in {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(out=Path(sys.argv[1])))

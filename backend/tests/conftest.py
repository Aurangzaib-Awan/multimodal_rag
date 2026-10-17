import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _png(w: int, h: int) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), False)
    pix.set_rect(pix.irect, (200, 60, 60))
    return pix.tobytes("png")


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory) -> str:
    """Pages: 0 heading+text, 1 raster image, 2 tiny icon, 3 vector drawing, 4 blank, 5 scanned (full-page raster)."""
    doc = fitz.open()

    p = doc.new_page()
    p.insert_text((72, 80), "Introduction", fontsize=24)
    p.insert_text((72, 120), "Entropy measures uncertainty in a distribution. " * 2, fontsize=10)

    p = doc.new_page()
    p.insert_text((72, 80), "A photo follows.", fontsize=10)
    p.insert_image(fitz.Rect(72, 100, 272, 300), stream=_png(200, 200))

    p = doc.new_page()
    p.insert_text((72, 80), "An icon follows.", fontsize=10)
    p.insert_image(fitz.Rect(72, 100, 92, 120), stream=_png(20, 20))

    p = doc.new_page()
    p.insert_text((72, 60), "Fig", fontsize=10)
    for i in range(30):
        p.draw_line((72, 100 + i * 10), (72 + i * 12, 400))

    doc.new_page()

    p = doc.new_page()
    p.insert_image(p.rect, stream=_png(600, 800))

    path = tmp_path_factory.mktemp("pdf") / "sample.pdf"
    doc.save(path)
    return str(path)

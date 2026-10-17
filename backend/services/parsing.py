"""CPU-bound PDF parsing. Runs inside worker processes, so it must stay picklable and
must not import anything that opens Qdrant or loads models."""
import base64
import io
import re
from typing import Literal, TypedDict

import fitz
import pymupdf4llm
from PIL import Image

from config import FIGURE_DPI, MAX_IMAGE_SIDE, MIN_DRAWINGS, MIN_IMAGE_PX, SPARSE_TEXT_CHARS
from services.chunking import Chunk, split_markdown

PICTURE_PLACEHOLDER = re.compile(r"^\*{0,2}==>.*<==\*{0,2}$", re.MULTILINE)


class Visual(TypedDict):
    kind: Literal["image", "figure"]
    jpeg_b64: str
    xref: int | None


class PageResult(TypedDict):
    page_number: int
    chunks: list[Chunk]
    visuals: list[Visual]
    has_table: bool
    has_image: bool


def _to_jpeg_b64(img: Image.Image) -> str:
    img = img.convert("RGB")
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _raster_images(doc: fitz.Document, page: fitz.Page) -> list[Visual]:
    out, seen = [], set()
    for xref, _smask, w, h, *_ in page.get_images(full=True):
        if xref in seen or min(w, h) < MIN_IMAGE_PX:
            continue
        seen.add(xref)
        try:
            raw = doc.extract_image(xref)["image"]
            out.append({"kind": "image", "jpeg_b64": _to_jpeg_b64(Image.open(io.BytesIO(raw))), "xref": xref})
        except Exception as e:  # unsupported codec etc. — skip the image, keep the page
            print(f"warn: image xref {xref} on page {page.number + 1}: {e}")
    return out


def _render_page(page: fitz.Page) -> Visual:
    pix = page.get_pixmap(dpi=FIGURE_DPI)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return {"kind": "figure", "jpeg_b64": _to_jpeg_b64(img), "xref": None}


def _parse_page(doc: fitz.Document, page: fitz.Page, idx: int, markdown: str,
                section: str | None) -> tuple[PageResult, str | None]:
    chunks = split_markdown(PICTURE_PLACEHOLDER.sub("", markdown), section=section)
    if chunks:
        section = chunks[-1]["section"]
    has_table = any(c["type"] == "table" for c in chunks)
    visuals = _raster_images(doc, page)
    if (not visuals and not has_table
            and len(page.get_text().strip()) < SPARSE_TEXT_CHARS
            and len(page.get_drawings()) > MIN_DRAWINGS):
        visuals = [_render_page(page)]
    return {"page_number": idx + 1, "chunks": chunks, "visuals": visuals,
            "has_table": has_table, "has_image": bool(visuals)}, section


def parse_batch(path: str, pages: list[int]) -> list[PageResult]:
    """Parse 0-based `pages` of the PDF at `path`. Opens its own Document (never shared across processes)."""
    doc = fitz.open(path)
    try:
        md_pages = pymupdf4llm.to_markdown(doc, pages=pages, page_chunks=True, show_progress=False)
        results: list[PageResult] = []
        section = None
        for idx, md in zip(pages, md_pages):
            try:
                result, section = _parse_page(doc, doc[idx], idx, md["text"], section)
            except Exception as e:  # one damaged page must not lose the other 799
                print(f"warn: page {idx + 1} skipped: {e}")
                result = {"page_number": idx + 1, "chunks": [], "visuals": [], "has_table": False, "has_image": False}
            results.append(result)
        return results
    finally:
        doc.close()

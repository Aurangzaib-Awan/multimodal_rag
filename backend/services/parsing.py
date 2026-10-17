"""PDF parsing with PyMuPDF. Run it on the PYMUPDF thread, never on several threads at once."""
import base64
import io
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, TypedDict

import fitz
import pymupdf4llm
from PIL import Image

from config import (FIGURE_CAPTION_GAP, FIGURE_DPI, FIGURE_LABEL_CHARS, FIGURE_LABEL_GAP, FIGURE_PAD, MAX_IMAGE_SIDE, MIN_DRAWINGS,
                    FIGURE_JOIN_GAP, MIN_FIGURE_AREA, MIN_FIGURE_PATHS, MIN_IMAGE_PX, SPARSE_TEXT_CHARS)
from services.chunking import Chunk, split_markdown

PICTURE_PLACEHOLDER = re.compile(r"^\*{0,2}==>.*<==\*{0,2}$", re.MULTILINE)
# MuPDF is not thread-safe, so every PyMuPDF call goes through this one thread; the event loop stays free.
# (A process pool would need /dev/shm, which AWS Lambda does not have.)
PYMUPDF = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pymupdf")

CAPTION = re.compile(r"^\s*(fig(ure|\.)?|chart|diagram|plot|scheme)\s*\d", re.IGNORECASE)


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


def _render(page: fitz.Page, clip: fitz.Rect | None = None) -> Visual:
    pix = page.get_pixmap(dpi=FIGURE_DPI, clip=clip)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return {"kind": "figure", "jpeg_b64": _to_jpeg_b64(img), "xref": None}


def _gap(a: fitz.Rect, b: fitz.Rect) -> float:
    """Distance in points between two rectangles (0 when they touch or overlap)."""
    return max(b.x0 - a.x1, a.x0 - b.x1, b.y0 - a.y1, a.y0 - b.y1, 0)


def _without_lone_rules(page: fitz.Page, drawings: list[dict]) -> list[dict]:
    """Drop hairlines connected to nothing (footnote separators, header rules): they are page furniture and,
    with the loose join distance, would pull the footnote under a figure into its crop. Axes survive because
    they touch ticks, frames or data."""
    strict = page.cluster_drawings(drawings=drawings, x_tolerance=3, y_tolerance=3, final_filter=False)

    def lone_rule(d: dict) -> bool:
        r = d["rect"]
        if min(r.width, r.height) >= 1.5:
            return False
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        cluster = next(c for c in strict if c.x0 - 0.5 <= cx <= c.x1 + 0.5 and c.y0 - 0.5 <= cy <= c.y1 + 0.5)
        return sum(1 for o in drawings if cluster.x0 - 0.5 <= (o["rect"].x0 + o["rect"].x1) / 2 <= cluster.x1 + 0.5
                   and cluster.y0 - 0.5 <= (o["rect"].y0 + o["rect"].y1) / 2 <= cluster.y1 + 0.5) == 1

    return [d for d in drawings if not lone_rule(d)]


def _figure_regions(page: fitz.Page) -> list[fitz.Rect]:
    """Vector figures on the page: clusters of many connected drawing paths that are not a table.

    A figure's labels are text, not paths, so short text blocks touching the cluster and its
    "Figure N" caption are folded into the crop. Body paragraphs are long and stay out.
    """
    drawings = page.get_drawings()
    if len(drawings) < MIN_FIGURE_PATHS:
        return []
    drawings = _without_lone_rules(page, drawings)
    centers = [((d["rect"].x0 + d["rect"].x1) / 2, (d["rect"].y0 + d["rect"].y1) / 2) for d in drawings]
    tables, blocks, regions = None, None, []
    for r in page.cluster_drawings(drawings=drawings, x_tolerance=FIGURE_JOIN_GAP, y_tolerance=FIGURE_JOIN_GAP):
        paths = sum(1 for cx, cy in centers if r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1)
        if paths < MIN_FIGURE_PATHS or r.get_area() < MIN_FIGURE_AREA * page.rect.get_area():
            continue
        if tables is None:  # only paid for on pages that have a candidate
            tables = [fitz.Rect(t.bbox) for t in page.find_tables().tables]
            blocks = [(fitz.Rect(b[:4]), b[4]) for b in page.get_text("blocks") if b[6] == 0]
        if any((r & t).get_area() > 0.5 * r.get_area() for t in tables):
            continue  # ruled table, not a figure
        for _ in range(3):  # labels can chain: a label next to a label next to the drawing
            grown = fitz.Rect(r)
            for box, text in blocks:
                if len(text.strip()) < FIGURE_LABEL_CHARS and _gap(r, box) <= FIGURE_LABEL_GAP:
                    grown |= box
            if grown == r:
                break
            r = grown
        captions = [(_gap(r, box), box) for box, text in blocks if CAPTION.match(text) and _gap(r, box) <= FIGURE_CAPTION_GAP]
        if captions:
            r |= min(captions, key=lambda c: c[0])[1]
        regions.append((r + (-FIGURE_PAD, -FIGURE_PAD, FIGURE_PAD, FIGURE_PAD)) & page.rect)
    return regions


def _parse_page(doc: fitz.Document, page: fitz.Page, idx: int, markdown: str,
                section: str | None) -> tuple[PageResult, str | None]:
    chunks = split_markdown(PICTURE_PLACEHOLDER.sub("", markdown), section=section)
    if chunks:
        section = chunks[-1]["section"]
    has_table = any(c["type"] == "table" for c in chunks)
    visuals = _raster_images(doc, page) + [_render(page, r) for r in _figure_regions(page)]
    if (not visuals and not has_table  # fallback: a near-empty page with some drawings, but no clean cluster
            and len(page.get_text().strip()) < SPARSE_TEXT_CHARS
            and len(page.get_drawings()) > MIN_DRAWINGS):
        visuals = [_render(page)]
    return {"page_number": idx + 1, "chunks": chunks, "visuals": visuals,
            "has_table": has_table, "has_image": bool(visuals)}, section


def page_count(path: str) -> int:
    """Pages in the PDF at `path`; ValueError when it is not a readable PDF."""
    with fitz.open(path) as doc:
        if not doc.is_pdf or doc.page_count == 0:
            raise ValueError("not a readable PDF")
        return doc.page_count


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

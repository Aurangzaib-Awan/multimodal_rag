from pathlib import Path

from services.chunking import split_markdown
from services.parsing import parse_batch

TABLE_MD = """Some intro text.

Table 4.1: Radial layout.

|Subsystem|Technology|R_in|
|---|---|---|
|Beam pipe|Be|10|
|Main tracker|Drift chamber|345|
|ECAL|PbWO4|2050|

After the table."""


def test_split_keeps_table_whole():
    chunks = split_markdown(TABLE_MD)
    tables = [c for c in chunks if c["type"] == "table"]
    assert len(tables) == 1
    t = tables[0]["text"]
    assert "Table 4.1: Radial layout." in t
    assert all(row in t for row in ("Beam pipe", "Main tracker", "ECAL"))
    texts = " ".join(c["text"] for c in chunks if c["type"] == "text")
    assert "Some intro text." in texts and "After the table." in texts
    assert "Beam pipe" not in texts


def test_split_by_heading_sets_section():
    chunks = split_markdown("# A\nx\n## B\ny")
    assert [(c["section"], c["text"].splitlines()[-1]) for c in chunks] == [("A", "x"), ("B", "y")]


def test_long_section_splits_with_overlap():
    md = "# Long\n" + " ".join(f"word{i}" for i in range(700))  # ~4.5k chars
    chunks = split_markdown(md)
    assert len(chunks) >= 3
    assert all(len(c["text"]) <= 1500 for c in chunks)
    for a, b in zip(chunks, chunks[1:]):
        tail = a["text"][-150:]
        assert tail in b["text"]


def test_empty_markdown_gives_no_chunks():
    assert split_markdown("  \n\n ") == []


def _page(sample_pdf, idx):
    return parse_batch(sample_pdf, [idx])[0]


def test_raster_image_extracted(sample_pdf):
    r = _page(sample_pdf, 1)
    assert r["page_number"] == 2
    assert [v["kind"] for v in r["visuals"]] == ["image"]
    assert r["has_image"] is True


def test_small_icon_skipped(sample_pdf):
    r = _page(sample_pdf, 2)
    assert r["visuals"] == []


def test_vector_page_becomes_figure(sample_pdf):
    r = _page(sample_pdf, 3)
    assert [v["kind"] for v in r["visuals"]] == ["figure"]
    assert r["visuals"][0]["xref"] is None


def test_blank_page_no_visual(sample_pdf):
    r = _page(sample_pdf, 4)
    assert r["visuals"] == [] and r["chunks"] == []


def test_scanned_page_goes_to_vlm(sample_pdf):
    r = _page(sample_pdf, 5)
    assert len(r["visuals"]) == 1


def test_heading_text_chunk(sample_pdf):
    r = _page(sample_pdf, 0)
    assert any("Entropy" in c["text"] for c in r["chunks"])


def test_real_bookish_table_detected():
    pdf = Path(__file__).resolve().parent.parent / "test_table.pdf"
    r = parse_batch(str(pdf), [81])[0]
    assert r["has_table"] is True
    assert any(c["type"] == "table" and "Beam pipe" in c["text"] for c in r["chunks"])


def test_sentence_containing_omitted_is_kept(tmp_path):
    import fitz
    doc = fitz.open()
    doc.new_page().insert_text((72, 80), "The full proof is intentionally omitted here.", fontsize=11)
    path = str(tmp_path / "omit.pdf")
    doc.save(path)
    r = parse_batch(path, [0])[0]
    assert any("intentionally omitted" in c["text"] for c in r["chunks"])


def test_bad_page_does_not_fail_batch(sample_pdf, monkeypatch):
    from services import parsing
    real = parsing._raster_images

    def boom(doc, page):
        if page.number == 1:
            raise RuntimeError("corrupt page")
        return real(doc, page)

    monkeypatch.setattr(parsing, "_raster_images", boom)
    res = parse_batch(sample_pdf, [0, 1, 2])
    assert [r["page_number"] for r in res] == [1, 2, 3]
    assert res[1]["visuals"] == [] and res[1]["chunks"] == []
    assert res[0]["chunks"], "other pages still parsed"


# --- vector figures on pages that also carry body text -------------------------------------------

import base64  # noqa: E402
import io  # noqa: E402

import fitz  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BODY = ("Gradient descent updates the weights against the gradient of the loss. " * 14).strip()  # ~1000 chars


def _size(visual) -> tuple[int, int]:
    return Image.open(io.BytesIO(base64.b64decode(visual["jpeg_b64"]))).size


def _text_page(doc: fitz.Document) -> fitz.Page:
    page = doc.new_page()  # 612 x 792
    page.insert_textbox(fitz.Rect(72, 72, 540, 270), BODY, fontsize=10)
    return page


def _pdf_with(tmp_path, draw) -> str:
    doc = fitz.open()
    draw(_text_page(doc))
    path = str(tmp_path / "page.pdf")
    doc.save(path)
    return path


def _draw_boxes(page: fitz.Page) -> None:
    for row in range(5):  # 40 floating boxes 8pt apart (no connectors), ~290x140pt (~8% of the page), bottom at y=442
        for col in range(8):
            page.draw_rect(fitz.Rect(100 + col * 36, 300 + row * 30, 128 + col * 36, 322 + row * 30))


def _draw_figure(page: fitz.Page) -> None:
    _draw_boxes(page)
    page.insert_text((100, 470), "Figure 1: A grid of boxes.", fontsize=9)
    page.insert_textbox(fitz.Rect(72, 560, 540, 700), BODY, fontsize=10)


def test_figure_on_a_page_full_of_text_is_detected(tmp_path):
    path = _pdf_with(tmp_path, _draw_figure)
    r = parse_batch(path, [0])[0]
    assert [v["kind"] for v in r["visuals"]] == ["figure"]
    w, h = _size(r["visuals"][0])
    assert w < 1275 * 0.6 and h < 1650 * 0.3, "the crop must be the figure, not the whole page"


def test_figure_crop_includes_caption_but_not_body_text(tmp_path):
    from services.parsing import _figure_regions
    path = _pdf_with(tmp_path, _draw_figure)
    page = fitz.open(path)[0]
    (region,) = _figure_regions(page)
    caption = page.search_for("Figure 1")[0]
    assert region.contains(caption)
    assert region.y0 > 275 and region.y1 < 520, "body text above and below stays out of the crop"


def test_callout_box_and_few_lines_are_not_figures(tmp_path):
    def draw(page):
        page.draw_rect(fitz.Rect(344, 300, 557, 406), fill=(1, 0.8, 0.8), color=None)  # one big pink callout
        for i in range(8):  # a small ornament, under the path threshold
            page.draw_line((72, 450 + i * 6), (200, 450 + i * 6))
        page.insert_textbox(fitz.Rect(72, 520, 540, 700), BODY, fontsize=10)
    r = parse_batch(_pdf_with(tmp_path, draw), [0])[0]
    assert r["visuals"] == []


@pytest.mark.parametrize("page_idx,kinds", [(0, ["figure"]), (1, ["image"]), (2, []), (3, ["figure"])])
def test_real_test0_pdf(page_idx, kinds):
    pdf = ROOT / "test0.pdf"
    r = parse_batch(str(pdf), [page_idx])[0]
    assert [v["kind"] for v in r["visuals"]] == kinds


def test_real_test0_figure_crops_include_their_captions():
    from services.parsing import _figure_regions
    doc = fitz.open(ROOT / "test0.pdf")
    for idx, caption in ((0, "Figure 1"), (3, "Figure 3")):
        page = doc[idx]
        (region,) = _figure_regions(page)
        assert region.contains(page.search_for(caption)[0]), f"{caption} caption not in the crop"


@pytest.mark.parametrize("page_idx", [12, 13, 14])
def test_real_attention_visualizations_are_figures(page_idx):
    r = parse_batch(str(ROOT / "test1.pdf"), [page_idx])[0]
    assert [v["kind"] for v in r["visuals"]] == ["figure"]


@pytest.mark.parametrize("page_idx", [8, 9])
def test_real_ruled_tables_are_not_figures(page_idx):
    r = parse_batch(str(ROOT / "test1.pdf"), [page_idx])[0]
    assert r["has_table"] and r["visuals"] == []


def test_footnote_rule_under_a_figure_stays_out_of_the_crop(tmp_path):
    from services.parsing import _figure_regions

    def draw(page):
        _draw_boxes(page)
        page.draw_line((72, 450), (134, 450))  # footnote separator, 8pt under the figure
        page.insert_text((72, 462), "1 The following description is based on lecture notes.", fontsize=9)
    page = fitz.open(_pdf_with(tmp_path, draw))[0]
    (region,) = _figure_regions(page)
    footnote = page.search_for("The following description")[0]
    assert region.y1 <= footnote.y0 + 1, "the footnote leaked into the figure crop"

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

import uuid

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient, models

from routers import query as query_router
from services import retrieval, store
from services.embedding import embed_dense, embed_sparse
from services.retrieval import parse_query_filter


@pytest.mark.parametrize("q,page", [
    ("what is on page 5", 5), ("summarize the 5th page", 5), ("the third page please", 3),
    ("what is entropy", None),
])
def test_parse_filter_page_variants(q, page):
    assert parse_query_filter(q).page == page


@pytest.mark.parametrize("q,types", [
    ("show the table of subsystems", ["table"]),
    ("explain the diagram", ["image", "figure"]),
    ("what does the chart on page 2 show", ["image", "figure"]),
    ("what is entropy", None),
])
def test_parse_filter_types(q, types):
    assert parse_query_filter(q).types == types


def _add(items):
    texts = [t for t, _ in items]
    pts = [models.PointStruct(id=str(uuid.uuid4()), vector={"dense": d, "sparse": s},
                              payload={**pl, "text": t, "pages_total": 3})
           for d, s, (t, pl) in zip(embed_dense(texts), embed_sparse(texts), items)]
    store.upsert(pts)


@pytest.fixture
def filled():
    store.set_client(QdrantClient(location=":memory:"))
    store.reset_collection()
    _add([
        ("Entropy measures the uncertainty of a random variable.", {"type": "text", "page_number": 1, "section": "Info"}),
        ("A bar chart of training loss falling over epochs.", {"type": "figure", "page_number": 2, "section": None,
                                                             "image_base64": "AAAA"}),
        ("Gradient descent updates weights against the gradient.", {"type": "text", "page_number": 3, "section": "Opt"}),
    ])
    yield
    store.set_client(None)


def test_type_hint_boosts_but_never_hides_text(filled):
    _add([("The image classification model was trained for 90 epochs with SGD.",
           {"type": "text", "page_number": 3, "section": "Training"})])
    pts, flt = retrieval.retrieve("How was the image classification model trained?")
    assert flt.types == ["image", "figure"]
    assert any(p.payload["type"] == "text" and "90 epochs" in p.payload["text"] for p in pts)


def test_type_hint_ranks_matching_type_first(filled):
    pts, _ = retrieval.retrieve("show me the chart of training loss")
    assert pts[0].payload["type"] == "figure"


def test_type_hint_with_no_matching_type_still_answers(filled):
    pts, flt = retrieval.retrieve("show me the table about entropy")
    assert pts and pts[0].payload["page_number"] == 1


def test_page_filter_kept(filled):
    pts, flt = retrieval.retrieve("what is on page 3")
    assert flt.page == 3 and {p.payload["page_number"] for p in pts} == {3}


@pytest.fixture
def api(monkeypatch):
    async def fake_answer(q, points):
        return "stub answer [p.2]"
    monkeypatch.setattr(query_router, "generate_answer", fake_answer)
    from main import app
    with TestClient(app) as c:
        yield c


def test_images_only_for_visual_chunks(filled, api):
    body = api.post("/query", json={"question": "explain the chart about training loss"}).json()
    assert body["answer"] == "stub answer [p.2]"
    assert [i["page_number"] for i in body["images"]] == [2]
    assert body["images"][0]["image_base64"] == "AAAA"
    assert all("image_base64" not in s for s in body["sources"])


def test_page_out_of_range(filled, api):
    body = api.post("/query", json={"question": "what is on page 900"}).json()
    assert "3 pages" in body["answer"] and body["sources"] == []


def test_query_without_collection(api):
    store.set_client(QdrantClient(location=":memory:"))
    r = api.post("/query", json={"question": "anything"})
    store.set_client(None)
    assert r.status_code == 409


def test_document_info(filled, api):
    assert api.get("/document").json() == {"indexed": True, "filename": None, "pages_total": 3, "chunks": 3, "job": None}


def test_document_info_empty(api):
    store.set_client(QdrantClient(location=":memory:"))
    body = api.get("/document").json()
    store.set_client(None)
    assert body == {"indexed": False, "filename": None, "pages_total": None, "chunks": 0, "job": None}


def test_blank_question_rejected(api):
    assert api.post("/query", json={"question": "   "}).status_code == 422


def test_document_reports_running_job(api):
    from services import pipeline
    store.set_client(QdrantClient(location=":memory:"))
    job = pipeline.Job(filename="big.pdf", status="processing", pages_done=3, pages_total=800)
    pipeline.JOBS[job.id] = job
    try:
        body = api.get("/document").json()
    finally:
        pipeline.JOBS.pop(job.id)
        store.set_client(None)
    assert body["job"]["id"] == job.id and body["job"]["pages_total"] == 800
    assert body["indexed"] is False, "a half-built index must not look ready"

import uuid

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient, models

from routers import query as query_router
from services import retrieval, store
from services.embedding import embed_dense, embed_sparse
from services.retrieval import parse_query_filter

S = "11111111-1111-4111-8111-111111111111"  # test session id (X-Session-Id)
H = {"X-Session-Id": S}


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
    store.upsert(S, pts)


@pytest.fixture
def filled():
    store.set_client(QdrantClient(location=":memory:"))
    store.reset_collection(S)
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
    pts, flt = retrieval.retrieve(S, "How was the image classification model trained?")
    assert flt.types == ["image", "figure"]
    assert any(p.payload["type"] == "text" and "90 epochs" in p.payload["text"] for p in pts)


def test_type_hint_ranks_matching_type_first(filled):
    pts, _ = retrieval.retrieve(S, "show me the chart of training loss")
    assert pts[0].payload["type"] == "figure"


def test_type_hint_with_no_matching_type_still_answers(filled):
    pts, flt = retrieval.retrieve(S, "show me the table about entropy")
    assert pts and pts[0].payload["page_number"] == 1


def test_page_filter_kept(filled):
    pts, flt = retrieval.retrieve(S, "what is on page 3")
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
    body = api.post("/query", json={"question": "explain the chart about training loss"}, headers=H).json()
    assert body["answer"] == "stub answer [p.2]"
    assert [i["page_number"] for i in body["images"]] == [2]
    assert body["images"][0]["image_base64"] == "AAAA"
    assert all("image_base64" not in s for s in body["sources"])


def test_page_out_of_range(filled, api):
    body = api.post("/query", json={"question": "what is on page 900"}, headers=H).json()
    assert "3 pages" in body["answer"] and body["sources"] == []


def test_query_without_collection(api):
    store.set_client(QdrantClient(location=":memory:"))
    r = api.post("/query", json={"question": "anything"}, headers=H)
    store.set_client(None)
    assert r.status_code == 404 and "re-upload" in r.json()["detail"]


def test_document_info(filled, api):
    assert api.get("/document", headers=H).json() == {"indexed": True, "filename": None, "pages_total": 3, "chunks": 3, "job": None}


def test_document_info_empty(api):
    store.set_client(QdrantClient(location=":memory:"))
    body = api.get("/document", headers=H).json()
    store.set_client(None)
    assert body == {"indexed": False, "filename": None, "pages_total": None, "chunks": 0, "job": None}


def test_blank_question_rejected(api):
    assert api.post("/query", json={"question": "   "}, headers=H).status_code == 422


def test_document_reports_running_job(api):
    from services import pipeline
    store.set_client(QdrantClient(location=":memory:"))
    job = pipeline.Job(filename="big.pdf", session_id=S, status="processing", pages_done=3, pages_total=800)
    pipeline.JOBS[job.id] = job
    try:
        body = api.get("/document", headers=H).json()
    finally:
        pipeline.JOBS.pop(job.id)
        store.set_client(None)
    assert body["job"]["id"] == job.id and body["job"]["pages_total"] == 800
    assert body["indexed"] is False, "a half-built index must not look ready"


# --- relative pages and which images an answer shows -----------------------------------------------

@pytest.mark.parametrize("q,page", [
    ("show me what's on the last page", 9), ("summarize the final page", 9),
    ("what is on the second to last page", 8), ("the second last page", 8), ("penultimate page please", 8),
    ("what is on page 2", 2),
])
def test_relative_pages_use_the_page_count(q, page):
    assert parse_query_filter(q, pages_total=9).page == page


def test_last_page_without_a_page_count_is_no_filter():
    assert parse_query_filter("what is on the last page").page is None


@pytest.fixture
def answer_with(monkeypatch):
    def use(text):
        async def fake(q, points):
            return text
        monkeypatch.setattr(query_router, "generate_answer", fake)
    return use


def test_last_page_question_searches_only_the_last_page(filled, api, answer_with):
    answer_with("It covers gradient descent [p.3].")
    body = api.post("/query", json={"question": "show me what's on the last page"}, headers=H).json()
    assert body["filter"]["page"] == 3
    assert {s["page_number"] for s in body["sources"]} == {3}
    assert body["images"] == []


def test_images_appear_only_for_pages_the_answer_cites(filled, api, answer_with):
    answer_with("Entropy measures uncertainty [p.1].")
    body = api.post("/query", json={"question": "what is entropy and the training loss chart"}, headers=H).json()
    assert any(s["type"] == "figure" for s in body["sources"]), "the figure was retrieved"
    assert body["images"] == [], "but the answer never cited its page, so it is not shown"

    answer_with("Loss falls over epochs [p.2], unlike entropy [p.1].")
    body = api.post("/query", json={"question": "what is entropy and the training loss chart"}, headers=H).json()
    assert [i["page_number"] for i in body["images"]] == [2]


def test_busy_model_returns_503_with_a_clear_message(filled, api, monkeypatch):
    from services.generator import ModelBusy

    async def busy(q, points):
        raise ModelBusy()
    monkeypatch.setattr(query_router, "generate_answer", busy)
    r = api.post("/query", json={"question": "what is entropy"}, headers=H)
    assert r.status_code == 503 and "try again" in r.json()["detail"].lower()


# --- small chunks find the page, the whole page goes to the model ----------------------------------

@pytest.fixture
def long_page():
    """Page 5 holds one section split into three chunks; page 6 is unrelated."""
    store.set_client(QdrantClient(location=":memory:"))
    store.reset_collection(S)
    _add([
        ("Muscle spindles sense how long a muscle is.", {"type": "text", "page_number": 5, "section": "Spindles", "seq": 0}),
        ("They also report how fast the length changes.", {"type": "text", "page_number": 5, "section": "Spindles", "seq": 1}),
        ("Gamma motor neurons keep spindles sensitive.", {"type": "text", "page_number": 5, "section": "Spindles", "seq": 2}),
        ("A block diagram of the feedback loop.", {"type": "figure", "page_number": 5, "section": "Spindles", "seq": 1000,
                                                 "image_base64": "AAAA"}),
        ("Tendon organs measure force at the tendon.", {"type": "text", "page_number": 6, "section": "Tendons", "seq": 0}),
    ])
    yield
    store.set_client(None)


def _hit(page):
    return models.ScoredPoint(id=str(uuid.uuid4()), version=0, score=1.0, payload={"page_number": page})


def test_context_is_the_whole_page_in_reading_order(long_page):
    ctx = retrieval.page_context(S, [_hit(5)])
    assert [p.payload["text"] for p in ctx] == [
        "Muscle spindles sense how long a muscle is.",
        "They also report how fast the length changes.",
        "Gamma motor neurons keep spindles sensitive.",
        "A block diagram of the feedback loop.",
    ]
    assert all("image_base64" not in p.payload for p in ctx), "pictures are not sent to the text model"


def test_context_keeps_the_best_pages_only(long_page):
    ctx = retrieval.page_context(S, [_hit(6), _hit(5), _hit(6)], max_pages=1)
    assert {p.payload["page_number"] for p in ctx} == {6}


def test_the_model_gets_the_whole_page_not_just_the_hits(long_page, api, monkeypatch):
    seen = {}

    async def fake_answer(q, points):
        seen["texts"] = [p.payload["text"] for p in points]
        return "Spindles sense length and speed [p.5]."
    monkeypatch.setattr(query_router, "generate_answer", fake_answer)
    real_search = store.search
    monkeypatch.setattr(store, "search", lambda *a, **k: real_search(*a, **k)[:1])  # only the best match
    body = api.post("/query", json={"question": "what do gamma motor neurons do"}, headers=H).json()
    page5 = {"Muscle spindles sense how long a muscle is.", "They also report how fast the length changes.",
             "Gamma motor neurons keep spindles sensitive.", "A block diagram of the feedback loop."}
    assert page5 <= set(seen["texts"]), "every chunk of the matched page reaches the model"
    assert body["sources"], "the evidence list still shows the matched chunks"


# --- figure gallery ---------------------------------------------------------------------------------

def test_figures_lists_every_picture_in_page_order(filled, api):
    _add([("A photo of a microscope.", {"type": "image", "page_number": 1, "section": None, "seq": 1000,
                                        "image_base64": "BBBB"})])
    figs = api.get("/figures", headers=H).json()["figures"]
    assert [(f["page_number"], f["type"], f["image_base64"]) for f in figs] == [(1, "image", "BBBB"), (2, "figure", "AAAA")]
    assert figs[0]["caption"] == "A photo of a microscope."


def test_figures_for_a_session_without_a_document_is_empty(api):
    store.set_client(QdrantClient(location=":memory:"))
    body = api.get("/figures", headers=H).json()
    store.set_client(None)
    assert body == {"figures": []}

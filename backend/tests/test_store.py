import pytest
from qdrant_client import QdrantClient, models

from services import store


def _point(pid, page, ctype, dense, sparse_idx):
    return models.PointStruct(
        id=pid,
        vector={"dense": dense, "sparse": models.SparseVector(indices=[sparse_idx], values=[1.0])},
        payload={"page_number": page, "type": ctype, "text": f"p{page} {ctype}", "pages_total": 2},
    )


@pytest.fixture
def mem_store(monkeypatch):
    monkeypatch.setattr(store, "DENSE_SIZE", 2)
    store.set_client(QdrantClient(location=":memory:"))
    store.reset_collection()
    store.upsert([
        _point(1, 1, "text", [1.0, 0.0], 1),
        _point(2, 2, "table", [0.9, 0.1], 1),
        _point(3, 2, "figure", [0.0, 1.0], 2),
    ])
    yield store
    store.set_client(None)


def _sv(i):
    return models.SparseVector(indices=[i], values=[1.0])


def test_hybrid_search_filters_by_page(mem_store):
    flt = store.build_filter(page=2, types=None)
    pts = mem_store.search([1.0, 0.0], _sv(1), flt)
    assert {p.payload["page_number"] for p in pts} == {2}


def test_search_type_filter(mem_store):
    flt = store.build_filter(page=None, types=["figure", "image"])
    pts = mem_store.search([1.0, 0.0], _sv(1), flt)
    assert [p.id for p in pts] == [3]


def test_reset_recreates_empty(mem_store):
    assert mem_store.count() == 3
    mem_store.reset_collection()
    assert mem_store.count() == 0
    assert mem_store.has_collection()


def test_pages_total(mem_store):
    assert mem_store.pages_total() == 2

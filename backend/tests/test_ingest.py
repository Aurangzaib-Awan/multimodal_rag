import time

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from services import pipeline, store

S = "11111111-1111-4111-8111-111111111111"  # test session id (X-Session-Id)
H = {"X-Session-Id": S}


@pytest.fixture
def api(monkeypatch):
    store.set_client(QdrantClient(location=":memory:"))
    from main import app
    with TestClient(app) as c:
        yield c
    store.set_client(None)


def _wait(api, job_id, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        job = api.get(f"/ingest/{job_id}", headers=H).json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def _upload(api, path):
    with open(path, "rb") as f:
        return api.post("/ingest", files={"file": ("sample.pdf", f, "application/pdf")}, headers=H)


def test_ingest_job_completes_and_counts_chunks(api, sample_pdf, monkeypatch):
    async def fake_caption(b64, kind):
        return f"a {kind} caption"
    monkeypatch.setattr(pipeline, "caption", fake_caption)

    r = _upload(api, sample_pdf)
    assert r.status_code == 202
    job = _wait(api, r.json()["job_id"])
    assert job["status"] == "done", job
    assert job["pages_done"] == job["pages_total"] == 6
    # text pages 0,1,2,3 + image(p2) + figure(p4) + scanned(p6)
    assert job["chunks"] == store.count(S) >= 6
    assert job["visuals"] == 3


def test_caption_failure_does_not_fail_ingest(api, sample_pdf, monkeypatch):
    async def failing_caption(b64, kind):
        return None
    monkeypatch.setattr(pipeline, "caption", failing_caption)

    job = _wait(api, _upload(api, sample_pdf).json()["job_id"])
    assert job["status"] == "done"
    assert job["visuals"] == 0 and job["chunks"] >= 3


def test_ingest_rejects_corrupt_pdf(api):
    r = api.post("/ingest", files={"file": ("bad.pdf", b"not a pdf", "application/pdf")}, headers=H)
    assert r.status_code == 400
    assert "PDF" in r.json()["detail"]


def test_ingest_rejects_non_pdf_name(api):
    r = api.post("/ingest", files={"file": ("notes.txt", b"hello", "text/plain")}, headers=H)
    assert r.status_code == 400


def test_unknown_job_404(api):
    assert api.get("/ingest/nope", headers=H).status_code == 404


def test_replace_never_wipes_index_during_old_upsert(api, sample_pdf, monkeypatch):
    c = QdrantClient(location=":memory:")
    store.set_client(c)
    state = {"upserting": False, "overlap": False}
    real_upsert, real_delete = c.upsert, c.delete_collection

    def slow_upsert(*a, **k):
        state["upserting"] = True
        time.sleep(2)
        try:
            return real_upsert(*a, **k)
        finally:
            state["upserting"] = False

    def spy_delete(*a, **k):
        state["overlap"] |= state["upserting"]
        return real_delete(*a, **k)

    async def quick_caption(b64, kind):
        return "caption"

    monkeypatch.setattr(c, "upsert", slow_upsert)
    monkeypatch.setattr(c, "delete_collection", spy_delete)
    monkeypatch.setattr(pipeline, "caption", quick_caption)

    first = _upload(api, sample_pdf).json()["job_id"]
    end = time.time() + 30
    while not state["upserting"] and time.time() < end:
        time.sleep(0.05)
    assert state["upserting"], "first job never reached its upsert"
    second = _upload(api, sample_pdf).json()["job_id"]
    assert _wait(api, second)["status"] == "done"
    assert state["overlap"] is False, "index was wiped while the old job was still writing"
    assert api.get(f"/ingest/{first}", headers=H).json()["status"] == "error"

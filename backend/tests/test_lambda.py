"""Behavior that matters when the API runs on AWS Lambda."""
import asyncio
import multiprocessing.synchronize
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from services import pipeline, store


@pytest.fixture
def api():
    store.set_client(QdrantClient(location=":memory:"))
    from main import app
    with TestClient(app) as c:
        yield c
    store.set_client(None)


@pytest.fixture
def quick_caption(monkeypatch):
    async def fake(b64, kind):
        return f"a {kind} caption"
    monkeypatch.setattr(pipeline, "caption", fake)


def _upload(api, path, session):
    with open(path, "rb") as f:
        return api.post("/ingest", files={"file": ("sample.pdf", f, "application/pdf")},
                        headers={"X-Session-Id": session})


def test_app_starts_and_ingests_without_shared_memory(monkeypatch, sample_pdf, quick_caption):
    """Lambda has no /dev/shm, so any multiprocessing lock fails there. The app must not need one."""
    def no_shm(*a, **k):
        raise OSError(38, "Function not implemented")
    monkeypatch.setattr(multiprocessing.synchronize.SemLock, "__init__", no_shm)
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "rag")
    store.set_client(QdrantClient(location=":memory:"))
    from main import app
    with TestClient(app) as api:
        r = _upload(api, sample_pdf, str(uuid.uuid4()))
    store.set_client(None)
    assert r.status_code == 200 and r.json()["status"] == "done"


def test_ingest_is_synchronous_on_lambda(api, sample_pdf, quick_caption, monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "rag")
    s = str(uuid.uuid4())
    r = _upload(api, sample_pdf, s)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done" and body["chunks"] > 0 and body["pages_done"] == body["pages_total"] == 6
    assert api.get("/document", headers={"X-Session-Id": s}).json()["indexed"] is True


def test_failed_sync_ingest_returns_error_and_leaves_nothing(api, sample_pdf, quick_caption, monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "rag")

    def broken_upsert(collection, points):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(store, "upsert", broken_upsert)
    s = str(uuid.uuid4())
    r = _upload(api, sample_pdf, s)
    assert r.status_code == 500 and "disk on fire" in r.json()["detail"]
    assert not store.has_collection(s), "a half-built collection would answer from a partial document"


def test_failed_background_ingest_leaves_no_half_built_collection(api, sample_pdf, quick_caption, monkeypatch):
    calls = {"n": 0}
    real = store.upsert

    def upsert_then_break(collection, points):
        calls["n"] += 1
        if calls["n"] > 0:
            real(collection, points)
            raise RuntimeError("lost connection")
    monkeypatch.setattr(store, "upsert", upsert_then_break)
    s = str(uuid.uuid4())
    job_id = _upload(api, sample_pdf, s).json()["job_id"]
    import time
    for _ in range(300):
        job = api.get(f"/ingest/{job_id}", headers={"X-Session-Id": s}).json()
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert job["status"] == "error"
    assert api.post("/query", json={"question": "entropy"}, headers={"X-Session-Id": s}).status_code == 404


def test_new_upload_drops_the_old_collection_immediately(api, sample_pdf, quick_caption, monkeypatch):
    s = str(uuid.uuid4())
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "rag")
    assert _upload(api, sample_pdf, s).json()["status"] == "done"
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME")

    async def never_finishes(job, path):
        await asyncio.sleep(3600)
    monkeypatch.setattr("routers.ingest.run_job", never_finishes)
    assert _upload(api, sample_pdf, s).status_code == 202
    assert not store.has_collection(s), "the previous document must be gone as soon as a new one is accepted"


def test_all_pymupdf_work_runs_on_one_thread(api, sample_pdf, quick_caption, monkeypatch):
    """MuPDF is not thread-safe, so parsing is serialized on one dedicated thread."""
    seen = set()
    real = pipeline.parse_batch

    def spy(path, pages):
        seen.add(threading.current_thread().name)
        return real(path, pages)
    monkeypatch.setattr(pipeline, "parse_batch", spy)
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "rag")
    monkeypatch.setattr(pipeline, "PAGE_BATCH", 2)  # 6 pages -> 3 batches
    assert _upload(api, sample_pdf, str(uuid.uuid4())).json()["status"] == "done"
    assert len(seen) == 1 and next(iter(seen)).startswith("pymupdf")


# --- per-instance session cap: memory must not grow forever on a warm Lambda ---------------------

@pytest.fixture
def cap_two(monkeypatch):
    import routers.session as rs
    monkeypatch.setattr(rs, "MAX_SESSIONS", 2)
    monkeypatch.setattr(rs, "_recent", {})
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "rag")


def _ask(api, session):
    return api.post("/query", json={"question": "what is entropy"}, headers={"X-Session-Id": session})


def test_oldest_session_is_dropped_beyond_the_cap(api, sample_pdf, quick_caption, cap_two, monkeypatch):
    async def fake_answer(q, points):
        return "ok"
    monkeypatch.setattr("routers.query.generate_answer", fake_answer)
    a, b, c = (str(uuid.uuid4()) for _ in range(3))
    for s in (a, b, c):
        assert _upload(api, sample_pdf, s).json()["status"] == "done"
    assert not store.has_collection(a) and store.has_collection(b) and store.has_collection(c)
    assert _ask(api, a).status_code == 404
    assert not [j for j in pipeline.JOBS.values() if j.session_id == a], "dropped session's jobs stay in memory"


def test_asking_keeps_a_session_fresh(api, sample_pdf, quick_caption, cap_two, monkeypatch):
    async def fake_answer(q, points):
        return "ok"
    monkeypatch.setattr("routers.query.generate_answer", fake_answer)
    a, b, c = (str(uuid.uuid4()) for _ in range(3))
    _upload(api, sample_pdf, a)
    _upload(api, sample_pdf, b)
    assert _ask(api, a).status_code == 200  # a is now the most recently used
    _upload(api, sample_pdf, c)
    assert store.has_collection(a) and not store.has_collection(b)


def test_reuploading_does_not_pile_up_jobs(api, sample_pdf, quick_caption, cap_two):
    s = str(uuid.uuid4())
    for _ in range(3):
        _upload(api, sample_pdf, s)
    assert len([j for j in pipeline.JOBS.values() if j.session_id == s]) == 1

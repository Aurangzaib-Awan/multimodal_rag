import time
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


def H(session: str) -> dict:
    return {"X-Session-Id": session}


def _upload(api, path, session, name="sample.pdf"):
    with open(path, "rb") as f:
        return api.post("/ingest", files={"file": (name, f, "application/pdf")}, headers=H(session))


def _wait(api, job_id, session, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        job = api.get(f"/ingest/{job_id}", headers=H(session)).json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


@pytest.mark.parametrize("method,path,kwargs", [
    ("post", "/query", {"json": {"question": "hi"}}),
    ("get", "/document", {}),
    ("post", "/ingest", {"files": {"file": ("a.pdf", b"%PDF-1.4", "application/pdf")}}),
])
def test_missing_session_header_is_400(api, method, path, kwargs):
    r = getattr(api, method)(path, **kwargs)
    assert r.status_code == 400
    assert "X-Session-Id" in r.json()["detail"]


def test_malformed_session_header_is_400(api):
    r = api.post("/query", json={"question": "hi"}, headers=H("../../etc"))
    assert r.status_code == 400


def test_question_for_unknown_session_says_expired(api):
    r = api.post("/query", json={"question": "what is entropy"}, headers=H(str(uuid.uuid4())))
    assert r.status_code == 404
    assert "session expired" in r.json()["detail"].lower() and "re-upload" in r.json()["detail"].lower()


def test_sessions_are_isolated(api, sample_pdf, monkeypatch):
    async def fake_caption(b64, kind):
        return f"a {kind} caption"
    monkeypatch.setattr(pipeline, "caption", fake_caption)
    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    job = _wait(api, _upload(api, sample_pdf, a).json()["job_id"], a)
    assert job["status"] == "done"
    assert api.get("/document", headers=H(a)).json()["indexed"] is True
    assert api.get("/document", headers=H(b)).json()["indexed"] is False
    assert api.post("/query", json={"question": "entropy"}, headers=H(b)).status_code == 404
    assert api.get(f"/ingest/{job['id']}", headers=H(b)).status_code == 404, "another session can't read the job"


def test_upload_in_one_session_does_not_cancel_another(api, sample_pdf, monkeypatch):
    async def slow_caption(b64, kind):
        import asyncio
        await asyncio.sleep(3)
        return "caption"
    monkeypatch.setattr(pipeline, "caption", slow_caption)
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    job_a = _upload(api, sample_pdf, a).json()["job_id"]
    time.sleep(1)
    _upload(api, sample_pdf, b)
    assert _wait(api, job_a, a)["status"] == "done"


def test_upload_over_4_mb_is_rejected(api):
    big = b"%PDF-1.4\n" + b"0" * (4 * 1024 * 1024)
    r = api.post("/ingest", files={"file": ("big.pdf", big, "application/pdf")}, headers=H(str(uuid.uuid4())))
    assert r.status_code == 413
    assert "4 MB" in r.json()["detail"]


def test_cors_preflight_allows_session_header(api):
    r = api.options("/query", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-session-id",
    })
    assert r.status_code == 200
    assert "x-session-id" in r.headers["access-control-allow-headers"].lower()


def test_lambda_handler_is_exposed():
    from mangum import Mangum
    from main import handler
    assert isinstance(handler, Mangum)


def test_embedding_models_use_configured_cache_dir(monkeypatch):
    from services import embedding
    seen = {}

    class Fake:
        def __init__(self, model_name, cache_dir=None, **kw):
            seen[model_name] = cache_dir

    monkeypatch.setattr(embedding, "TextEmbedding", Fake)
    monkeypatch.setattr(embedding, "SparseTextEmbedding", Fake)
    monkeypatch.setattr(embedding, "MODEL_CACHE_DIR", "/opt/models-test")
    embedding._dense.cache_clear()
    embedding._sparse.cache_clear()
    try:
        embedding._dense()
        embedding._sparse()
    finally:
        embedding._dense.cache_clear()
        embedding._sparse.cache_clear()
    assert set(seen.values()) == {"/opt/models-test"} and len(seen) == 2

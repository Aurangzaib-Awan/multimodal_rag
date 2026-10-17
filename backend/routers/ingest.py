import asyncio
import os
import tempfile

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from config import MAX_UPLOAD_BYTES, on_lambda
from routers.session import Session
from services import store
from services.parsing import PYMUPDF, page_count
from services.pipeline import JOBS, Job, run_job

router = APIRouter(prefix="/ingest", tags=["Ingest"])


@router.post("", status_code=202)
async def ingest_document(response: Response, session: Session, file: UploadFile = File(...)):
    """Parse + index a PDF. Locally it runs in the background (202; poll GET /ingest/{job_id}).
    On AWS Lambda it finishes before replying (200 or 500), because Lambda freezes once a response is sent."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")

    fd, path = tempfile.mkstemp(suffix=".pdf")
    size = 0
    with os.fdopen(fd, "wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                break
            f.write(chunk)
    if size > MAX_UPLOAD_BYTES:
        os.remove(path)
        raise HTTPException(413, f"PDF is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB. Upload a smaller file.")
    try:
        await asyncio.get_running_loop().run_in_executor(PYMUPDF, page_count, path)
    except Exception:
        os.remove(path)
        raise HTTPException(400, "That file isn't a readable PDF.")

    # one document per session: stop the old ingest if it is still running, and drop the old document now
    for old in JOBS.values():
        if old.session_id == session and old.task and not old.task.done():
            old.task.cancel()
    await asyncio.to_thread(store.delete_collection, session)

    job = Job(filename=file.filename, session_id=session)
    JOBS[job.id] = job
    if on_lambda():
        await run_job(job, path)
        if job.status == "error":
            raise HTTPException(500, f"Indexing failed: {job.error}")
        response.status_code = 200
    else:
        job.task = asyncio.create_task(run_job(job, path))
    return {"job_id": job.id, **job.public()}


@router.get("/{job_id}")
async def job_status(job_id: str, session: Session):
    job = JOBS.get(job_id)
    if not job or job.session_id != session:
        raise HTTPException(404, "Unknown job.")
    return job.public()

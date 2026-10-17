import asyncio
import os
import tempfile

import fitz
from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from config import MAX_UPLOAD_BYTES
from routers.session import Session
from services.pipeline import JOBS, Job, run_job

router = APIRouter(prefix="/ingest", tags=["Ingest"])


@router.post("", status_code=202)
async def ingest_document(request: Request, session: Session, file: UploadFile = File(...)):
    """Start parsing + indexing a PDF in the background. Poll GET /ingest/{job_id} for progress."""
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
        with fitz.open(path) as doc:
            if doc.page_count == 0 or not doc.is_pdf:
                raise ValueError
    except Exception:
        os.remove(path)
        raise HTTPException(400, "That file isn't a readable PDF.")

    # one document per session: a new upload replaces that session's collection, so stop its running job
    for old in JOBS.values():
        if old.session_id == session and old.task and not old.task.done():
            old.task.cancel()

    job = Job(filename=file.filename, session_id=session)
    JOBS[job.id] = job
    job.task = asyncio.create_task(run_job(job, path, request.app.state.pool))
    return {"job_id": job.id}


@router.get("/{job_id}")
async def job_status(job_id: str, session: Session):
    job = JOBS.get(job_id)
    if not job or job.session_id != session:
        raise HTTPException(404, "Unknown job.")
    return job.public()

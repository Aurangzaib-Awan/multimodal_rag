import asyncio
import os
import tempfile

import fitz
from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from services.pipeline import JOBS, Job, run_job

router = APIRouter(prefix="/ingest", tags=["Ingest"])


@router.post("", status_code=202)
async def ingest_document(request: Request, file: UploadFile = File(...)):
    """Start parsing + indexing a PDF in the background. Poll GET /ingest/{job_id} for progress."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")

    fd, path = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
    try:
        with fitz.open(path) as doc:
            if doc.page_count == 0 or not doc.is_pdf:
                raise ValueError
    except Exception:
        os.remove(path)
        raise HTTPException(400, "That file isn't a readable PDF.")

    # one document at a time: a new upload replaces the collection, so stop any running job
    for old in JOBS.values():
        if old.task and not old.task.done():
            old.task.cancel()

    job = Job(filename=file.filename)
    JOBS[job.id] = job
    job.task = asyncio.create_task(run_job(job, path, request.app.state.pool))
    return {"job_id": job.id}


@router.get("/{job_id}")
async def job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job.")
    return job.public()

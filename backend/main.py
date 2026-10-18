import asyncio
import os
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum

from routers import ingest, query
from config import on_lambda
from routers.session import Session
from services import embedding, store
from services.pipeline import JOBS


app = FastAPI(title="Multimodal RAG API")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": str(exc)})


app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(query.router)


@app.get("/")
async def root():
    return {"message": "Welcome to the Multimodal RAG API"}


@app.get("/document")
async def document(session: Session):
    """What this session has indexed, so the UI can restore its state after a reload."""
    info = await asyncio.to_thread(store.document_info, session)
    running = [j for j in JOBS.values() if j.session_id == session and j.status in ("queued", "processing")]
    # while a job runs the index is half-built: not ready, and the UI resumes the job's progress
    return {**info, "indexed": info["indexed"] and not running, "job": running[-1].public() if running else None}


# AWS Lambda entry point. Local dev still runs `uvicorn main:app`.
handler = Mangum(app, lifespan="off")

if on_lambda():  # load the models during Lambda's init phase, not inside the first upload or question
    embedding.embed_dense(["warm up"])
    embedding.embed_sparse(["warm up"])

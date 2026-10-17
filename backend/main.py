import asyncio
import multiprocessing as mp
import os
import traceback
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import PARSE_WORKERS
from routers import ingest, query
from services import store
from services.pipeline import JOBS


@asynccontextmanager
async def lifespan(app: FastAPI):
    # spawn, not fork: the API process holds ONNX/HTTP threads that must not be forked
    app.state.pool = ProcessPoolExecutor(PARSE_WORKERS, mp_context=mp.get_context("spawn"))
    yield
    app.state.pool.shutdown(cancel_futures=True)


app = FastAPI(title="Multimodal RAG API", lifespan=lifespan)


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
async def document():
    """What is currently indexed, so the UI can restore its state after a reload."""
    info = await asyncio.to_thread(store.document_info)
    running = [j for j in JOBS.values() if j.status in ("queued", "processing")]
    # while a job runs the index is half-built: not ready, and the UI resumes the job's progress
    return {**info, "indexed": info["indexed"] and not running, "job": running[-1].public() if running else None}

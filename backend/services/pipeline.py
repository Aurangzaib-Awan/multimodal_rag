"""Ingest job: parse page batches in worker processes, caption visuals concurrently, embed, upsert.

Batches are pipelined: while the pool parses batch N+1, the event loop captions and embeds batch N.
"""
import asyncio
import os
import uuid
from concurrent.futures import Executor
from dataclasses import dataclass, field

import fitz
from qdrant_client import models

from config import PAGE_BATCH
from services import store
from services.embedding import embed_dense, embed_sparse
from services.parsing import PageResult, parse_batch
from services.vlm import caption


@dataclass
class Job:
    filename: str
    session_id: str  # also the Qdrant collection name
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "queued"  # queued | processing | done | error
    pages_done: int = 0
    pages_total: int = 0
    chunks: int = 0
    visuals: int = 0
    error: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)

    def public(self) -> dict:
        return {k: v for k, v in vars(self).items() if k != "task"}


JOBS: dict[str, Job] = {}


async def _points_for(pages: list[PageResult], job: Job, seen_xrefs: set[int]) -> list[models.PointStruct]:
    base = {"filename": job.filename, "pages_total": job.pages_total}
    items: list[tuple[str, dict]] = []  # (text to embed, payload)

    visuals = []
    for p in pages:
        meta = {**base, "page_number": p["page_number"], "page_has_table": p["has_table"],
                "page_has_image": p["has_image"]}
        for c in p["chunks"]:
            embed_text = f"{c['section']}\n{c['text']}" if c["section"] else c["text"]
            items.append((embed_text, {**meta, "type": c["type"], "section": c["section"], "text": c["text"]}))
        for v in p["visuals"]:
            if v["xref"] is not None:
                if v["xref"] in seen_xrefs:  # same logo on every page: caption once
                    continue
                seen_xrefs.add(v["xref"])
            section = p["chunks"][0]["section"] if p["chunks"] else None
            visuals.append((v, {**meta, "type": v["kind"], "section": section, "image_base64": v["jpeg_b64"]}))

    captions = await asyncio.gather(*(caption(v["jpeg_b64"], v["kind"]) for v, _ in visuals))
    for (v, payload), cap in zip(visuals, captions):
        if cap:
            items.append((cap, {**payload, "text": cap}))
            job.visuals += 1

    if not items:
        return []
    texts = [t for t, _ in items]
    dense = await asyncio.to_thread(embed_dense, texts)
    sparse = await asyncio.to_thread(embed_sparse, texts)
    return [models.PointStruct(id=str(uuid.uuid4()), vector={"dense": d, "sparse": s}, payload=pl)
            for d, s, (_, pl) in zip(dense, sparse, items)]


async def run_job(job: Job, path: str, pool: Executor) -> None:
    loop = asyncio.get_running_loop()
    try:
        with fitz.open(path) as doc:
            job.pages_total = doc.page_count
        job.status = "processing"
        await asyncio.to_thread(store.reset_collection, job.session_id)

        n = job.pages_total
        batches = [list(range(i, min(i + PAGE_BATCH, n))) for i in range(0, n, PAGE_BATCH)]
        futures = [loop.run_in_executor(pool, parse_batch, path, b) for b in batches]
        seen_xrefs: set[int] = set()
        try:
            for fut in asyncio.as_completed(futures):
                pages = await fut
                points = await _points_for(pages, job, seen_xrefs)
                await asyncio.to_thread(store.upsert, job.session_id, points)
                job.chunks += len(points)
                job.pages_done += len(pages)
        finally:
            for f in futures:  # on error/cancel, drop batches not yet started
                f.cancel()
        job.status = "done"
    except asyncio.CancelledError:
        job.status, job.error = "error", "Cancelled: a newer upload replaced this document."
        raise
    except Exception as e:
        job.status, job.error = "error", f"{type(e).__name__}: {e}"
    finally:
        os.remove(path)

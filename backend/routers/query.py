import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StringConstraints

from services import store
from services.generator import generate_answer
from services.retrieval import parse_query_filter, retrieve

router = APIRouter(prefix="/query", tags=["Query"])

VISUAL_TYPES = {"image", "figure"}


class QueryRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


@router.post("")
async def query_model(request: QueryRequest):
    """Page filter + content-type boost parsed from the question → hybrid dense+BM25 search (RRF) → Gemini."""
    q = request.question
    if not await asyncio.to_thread(lambda: store.has_collection() and store.count() > 0):
        raise HTTPException(409, "No document indexed yet. Upload a PDF first.")

    asked = parse_query_filter(q).page
    total = await asyncio.to_thread(store.pages_total)
    if asked is not None and total and not 1 <= asked <= total:
        return {"question": q, "answer": f"The document has {total} pages, so page {asked} doesn't exist.",
                "filter": {"page": asked, "types": None}, "sources": [], "images": []}

    points, flt = await asyncio.to_thread(retrieve, q)
    answer = await generate_answer(q, points)
    return {
        "question": q,
        "answer": answer,
        "filter": {"page": flt.page, "types": flt.types},
        "sources": [{"type": p.payload["type"], "page_number": p.payload["page_number"],
                     "section": p.payload.get("section"), "snippet": p.payload["text"][:240]} for p in points],
        "images": [{"type": p.payload["type"], "page_number": p.payload["page_number"],
                    "caption": p.payload["text"], "image_base64": p.payload["image_base64"]}
                   for p in points if p.payload["type"] in VISUAL_TYPES and p.payload.get("image_base64")],
    }

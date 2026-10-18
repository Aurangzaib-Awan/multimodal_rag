import asyncio
from functools import cache

from google import genai
from google.genai import errors, types
from qdrant_client import models

from config import GEMINI_API_KEY, LLM_MODEL, VLM_MODEL

SYSTEM = (
    "You answer questions about one PDF document using only the context excerpts provided. "
    "Excerpts may be text, markdown tables, or descriptions of images and figures. "
    "Cite pages inline like [p.12]. If the context does not contain the answer, say so plainly "
    "instead of guessing. Keep answers concise; use markdown lists or tables when they help."
)

RETRY_DELAYS = (1, 2)  # seconds before the 2nd and 3rd attempt; short, so a Lambda request stays well under its timeout
BUSY = {429, 500, 503}  # rate limited or overloaded: worth retrying


class ModelBusy(Exception):
    """Gemini stayed overloaded through every retry."""


@cache
def _client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set in backend/.env")
    return genai.Client(api_key=GEMINI_API_KEY)


async def generate_answer(question: str, points: list[models.ScoredPoint]) -> str:
    if not points:
        return "I couldn't find anything in the document related to that question."
    context = "\n\n".join(
        f"--- [p.{p.payload['page_number']} | {p.payload['type']}"
        f"{' | ' + p.payload['section'] if p.payload.get('section') else ''}] ---\n{p.payload['text']}"
        for p in points
    )
    # the last try uses the lighter model, which is served from a separate, usually less busy, capacity pool
    for attempt, model in enumerate((LLM_MODEL, LLM_MODEL, VLM_MODEL)):
        if attempt:
            await asyncio.sleep(RETRY_DELAYS[attempt - 1])
        try:
            r = await _client().aio.models.generate_content(
                model=model,
                contents=f"Context:\n{context}\n\nQuestion: {question}",
                config=types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0.1),
            )
            return (r.text or "").strip() or "The model returned no answer."
        except errors.APIError as e:
            if e.code not in BUSY:
                raise
    raise ModelBusy()

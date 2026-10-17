from functools import cache

from google import genai
from google.genai import types
from qdrant_client import models

from config import GEMINI_API_KEY, LLM_MODEL

SYSTEM = (
    "You answer questions about one PDF document using only the context excerpts provided. "
    "Excerpts may be text, markdown tables, or descriptions of images and figures. "
    "Cite pages inline like [p.12]. If the context does not contain the answer, say so plainly "
    "instead of guessing. Keep answers concise; use markdown lists or tables when they help."
)


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
    r = await _client().aio.models.generate_content(
        model=LLM_MODEL,
        contents=f"Context:\n{context}\n\nQuestion: {question}",
        config=types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0.1),
    )
    return (r.text or "").strip() or "The model returned no answer."

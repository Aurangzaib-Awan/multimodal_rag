"""Async VLM captions. Network-bound, so asyncio + a semaphore instead of threads."""
import asyncio
import base64
from functools import cache
from typing import Literal

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, VLM_CONCURRENCY, VLM_MODEL

PROMPTS = {
    "image": ("Describe this image from a document so it can be found by search. "
              "Transcribe any visible text, numbers and labels, then explain what it shows."),
    "figure": ("This is a rendered PDF page containing a vector graphic (chart, plot or diagram). "
               "Describe the graphic: its type, title, axes and units, legend, labelled parts, key values "
               "and the relationship or trend it shows. Transcribe visible text exactly."),
}

_sem: asyncio.Semaphore | None = None


@cache
def _client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set in backend/.env")
    return genai.Client(api_key=GEMINI_API_KEY)


async def caption(jpeg_b64: str, kind: Literal["image", "figure"]) -> str | None:
    """Caption one visual. Returns None after 3 failed attempts so one bad call never fails the ingest."""
    global _sem
    _sem = _sem or asyncio.Semaphore(VLM_CONCURRENCY)
    part = types.Part.from_bytes(data=base64.b64decode(jpeg_b64), mime_type="image/jpeg")
    async with _sem:
        for attempt in range(3):
            try:
                r = await _client().aio.models.generate_content(model=VLM_MODEL, contents=[part, PROMPTS[kind]])
                return (r.text or "").strip() or None
            except Exception as e:
                if attempt == 2:
                    print(f"warn: caption failed: {e}")
                    return None
                await asyncio.sleep(2 ** (attempt + 1))

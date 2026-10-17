"""Metadata pre-filter parsed from the question, then hybrid search."""
import re
from dataclasses import dataclass

from qdrant_client import models

from services import store
from services.embedding import embed_dense, embed_sparse

ORDINALS = {w: i for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth "
    "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth".split(), start=1)}
TABLE_WORDS = re.compile(r"\btables?\b")
VISUAL_WORDS = re.compile(r"\b(images?|pictures?|photos?|figures?|fig\.|diagrams?|graphs?|charts?|plots?|illustrations?)")


@dataclass
class QueryFilter:
    page: int | None = None
    types: list[str] | None = None


def _page(q: str) -> int | None:
    if m := re.search(r"\bpage\s+(?:no\.?\s*)?(\d+)\b", q):
        return int(m.group(1))
    if m := re.search(r"\b(\d+)(?:st|nd|rd|th)?\s+page\b", q):
        return int(m.group(1))
    for word, num in ORDINALS.items():
        if re.search(rf"\b{word}\s+page\b|\bpage\s+{word}\b", q):
            return num
    return None


def parse_query_filter(question: str) -> QueryFilter:
    q = question.lower()
    types = None
    if TABLE_WORDS.search(q):
        types = ["table"]
    elif VISUAL_WORDS.search(q):
        types = ["image", "figure"]
    return QueryFilter(page=_page(q), types=types)


def retrieve(collection: str, question: str) -> tuple[list[models.ScoredPoint], QueryFilter]:
    flt = parse_query_filter(question)
    dense = embed_dense([question], is_query=True)[0]
    sparse = embed_sparse([question], is_query=True)[0]
    hard = store.build_filter(flt.page, None)
    boost = store.build_filter(flt.page, flt.types) if flt.types else None
    return store.search(collection, dense, sparse, hard, boost), flt

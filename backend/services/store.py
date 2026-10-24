"""Qdrant access, in memory. One collection per session id; nothing survives the process."""
import threading
import warnings

from qdrant_client import QdrantClient, models

from config import DENSE_SIZE, TOP_K

_client: QdrantClient | None = None
# A cancelled job's write is already running in a thread and cannot be stopped; make a new job's wipe wait for it.
_write_lock = threading.Lock()


def set_client(client: QdrantClient | None) -> None:
    global _client
    _client = client


def client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(":memory:")
    return _client


def has_collection(collection: str) -> bool:
    return client().collection_exists(collection)


def reset_collection(collection: str) -> None:
    with _write_lock:
        _reset(collection)


def delete_collection(collection: str) -> None:
    with _write_lock:
        if client().collection_exists(collection):
            client().delete_collection(collection)


def _reset(collection: str) -> None:
    c = client()
    if c.collection_exists(collection):
        c.delete_collection(collection)
    c.create_collection(
        collection,
        vectors_config={"dense": models.VectorParams(size=DENSE_SIZE, distance=models.Distance.COSINE)},
        sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    with warnings.catch_warnings():  # in-memory mode ignores payload indexes and warns
        warnings.simplefilter("ignore")
        for field, schema in (("page_number", models.PayloadSchemaType.INTEGER),
                              ("type", models.PayloadSchemaType.KEYWORD)):
            c.create_payload_index(collection, field, schema)


def upsert(collection: str, points: list[models.PointStruct]) -> None:
    with _write_lock:
        for i in range(0, len(points), 64):
            client().upsert(collection, points[i:i + 64])


def count(collection: str) -> int:
    return client().count(collection).count


def pages_total(collection: str) -> int | None:
    return document_info(collection)["pages_total"]


def document_info(collection: str) -> dict:
    if not has_collection(collection):
        return {"indexed": False, "filename": None, "pages_total": None, "chunks": 0}
    pts, _ = client().scroll(collection, limit=1, with_payload=["filename", "pages_total"])
    p = pts[0].payload if pts else {}
    n = count(collection)
    return {"indexed": n > 0, "filename": p.get("filename"), "pages_total": p.get("pages_total"), "chunks": n}


def page_points(collection: str, pages: list[int]) -> list[models.Record]:
    """Every chunk on these pages (text, tables, figure captions), without the heavy image data."""
    flt = models.Filter(must=[models.FieldCondition(key="page_number", match=models.MatchAny(any=pages))])
    pts, _ = client().scroll(collection, scroll_filter=flt, limit=10_000,
                             with_payload=["page_number", "type", "section", "text", "seq"])
    return pts


def figures(collection: str) -> list[models.Record]:
    """Every image and figure of the document, in page order (for the gallery)."""
    if not has_collection(collection):
        return []
    flt = models.Filter(must=[models.FieldCondition(key="type", match=models.MatchAny(any=["image", "figure"]))])
    pts, _ = client().scroll(collection, scroll_filter=flt, limit=10_000,
                             with_payload=["page_number", "type", "text", "seq", "image_base64"])
    return sorted(pts, key=lambda p: (p.payload["page_number"], p.payload.get("seq", 0)))


def build_filter(page: int | None, types: list[str] | None) -> models.Filter | None:
    must = []
    if page is not None:
        must.append(models.FieldCondition(key="page_number", match=models.MatchValue(value=page)))
    if types:
        must.append(models.FieldCondition(key="type", match=models.MatchAny(any=types)))
    return models.Filter(must=must) if must else None


def search(collection: str, dense: list[float], sparse: models.SparseVector, flt: models.Filter | None,
           boost: models.Filter | None = None, limit: int = TOP_K) -> list[models.ScoredPoint]:
    """Hybrid search. `flt` is a hard filter. `boost` adds extra searches restricted to a preferred subset,
    so points inside it rank higher after RRF but nothing outside it is excluded."""
    prefetch = []
    for f in ([flt, boost] if boost else [flt]):
        prefetch += [models.Prefetch(query=dense, using="dense", filter=f, limit=limit * 2),
                     models.Prefetch(query=sparse, using="sparse", filter=f, limit=limit * 2)]
    return client().query_points(
        collection, prefetch=prefetch, query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit, with_payload=True,
    ).points

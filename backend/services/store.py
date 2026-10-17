"""Qdrant access. Embedded on-disk mode unless QDRANT_URL is set. Only the API process touches this."""
import threading
import warnings

from qdrant_client import QdrantClient, models

from config import COLLECTION, DENSE_SIZE, QDRANT_API_KEY, QDRANT_PATH, QDRANT_URL, TOP_K

_client: QdrantClient | None = None
# A cancelled job's write is already running in a thread and cannot be stopped; make a new job's wipe wait for it.
_write_lock = threading.Lock()


def set_client(client: QdrantClient | None) -> None:
    global _client
    _client = client


def client() -> QdrantClient:
    global _client
    if _client is None:
        _client = (QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60) if QDRANT_URL
                   else QdrantClient(path=QDRANT_PATH))
    return _client


def has_collection() -> bool:
    return client().collection_exists(COLLECTION)


def reset_collection() -> None:
    with _write_lock:
        _reset()


def _reset() -> None:
    c = client()
    if c.collection_exists(COLLECTION):
        c.delete_collection(COLLECTION)
    c.create_collection(
        COLLECTION,
        vectors_config={"dense": models.VectorParams(size=DENSE_SIZE, distance=models.Distance.COSINE)},
        sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    with warnings.catch_warnings():  # embedded mode ignores payload indexes and warns; server mode uses them
        warnings.simplefilter("ignore")
        for field, schema in (("page_number", models.PayloadSchemaType.INTEGER),
                              ("type", models.PayloadSchemaType.KEYWORD)):
            c.create_payload_index(COLLECTION, field, schema)


def upsert(points: list[models.PointStruct]) -> None:
    with _write_lock:
        for i in range(0, len(points), 64):
            client().upsert(COLLECTION, points[i:i + 64])


def count() -> int:
    return client().count(COLLECTION).count


def pages_total() -> int | None:
    return document_info()["pages_total"]


def document_info() -> dict:
    if not has_collection():
        return {"indexed": False, "filename": None, "pages_total": None, "chunks": 0}
    pts, _ = client().scroll(COLLECTION, limit=1, with_payload=["filename", "pages_total"])
    p = pts[0].payload if pts else {}
    n = count()
    return {"indexed": n > 0, "filename": p.get("filename"), "pages_total": p.get("pages_total"), "chunks": n}


def build_filter(page: int | None, types: list[str] | None) -> models.Filter | None:
    must = []
    if page is not None:
        must.append(models.FieldCondition(key="page_number", match=models.MatchValue(value=page)))
    if types:
        must.append(models.FieldCondition(key="type", match=models.MatchAny(any=types)))
    return models.Filter(must=must) if must else None


def search(dense: list[float], sparse: models.SparseVector, flt: models.Filter | None,
           boost: models.Filter | None = None, limit: int = TOP_K) -> list[models.ScoredPoint]:
    """Hybrid search. `flt` is a hard filter. `boost` adds extra searches restricted to a preferred subset,
    so points inside it rank higher after RRF but nothing outside it is excluded."""
    prefetch = []
    for f in ([flt, boost] if boost else [flt]):
        prefetch += [models.Prefetch(query=dense, using="dense", filter=f, limit=limit * 2),
                     models.Prefetch(query=sparse, using="sparse", filter=f, limit=limit * 2)]
    return client().query_points(
        COLLECTION, prefetch=prefetch, query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit, with_payload=True,
    ).points

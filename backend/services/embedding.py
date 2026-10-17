"""Local embeddings (fastembed / ONNX). Models load lazily, once per process."""
from functools import cache

from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client import models

from config import DENSE_MODEL, MODEL_CACHE_DIR, SPARSE_MODEL

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # bge v1.5 model card


@cache
def _dense() -> TextEmbedding:
    return TextEmbedding(DENSE_MODEL, cache_dir=MODEL_CACHE_DIR)


@cache
def _sparse() -> SparseTextEmbedding:
    return SparseTextEmbedding(SPARSE_MODEL, cache_dir=MODEL_CACHE_DIR)


def embed_dense(texts: list[str], is_query: bool = False) -> list[list[float]]:
    if is_query:
        texts = [QUERY_PREFIX + t for t in texts]
    return [v.tolist() for v in _dense().embed(texts, batch_size=32)]


def embed_sparse(texts: list[str], is_query: bool = False) -> list[models.SparseVector]:
    embed = _sparse().query_embed if is_query else _sparse().embed
    return [models.SparseVector(indices=e.indices.tolist(), values=e.values.tolist()) for e in embed(texts)]

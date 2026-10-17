import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Parsing
PAGE_BATCH = 16
PARSE_WORKERS = max(1, min(3, (os.cpu_count() or 2) - 1))
MAX_CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200
MIN_IMAGE_PX = 64           # skip icons / bullets smaller than this on either side
MAX_IMAGE_SIDE = 1280       # downscale before base64 + VLM
FIGURE_DPI = 150
SPARSE_TEXT_CHARS = 500     # vector-graph page: little text ...
MIN_DRAWINGS = 10           # ... but real drawing paths

# Models
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
VLM_MODEL = os.getenv("VLM_MODEL", "gemini-flash-lite-latest")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-flash-latest")
VLM_CONCURRENCY = 4
DENSE_MODEL = "BAAI/bge-base-en-v1.5"
DENSE_SIZE = 768
SPARSE_MODEL = "Qdrant/bm25"

# Qdrant: unset URL -> embedded on-disk mode
QDRANT_URL = os.getenv("QDRANT_URL") or None
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
QDRANT_PATH = str(BASE_DIR / "qdrant_data")
COLLECTION = "multimodal_docs"
TOP_K = 6

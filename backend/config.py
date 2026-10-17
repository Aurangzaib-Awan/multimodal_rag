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
SPARSE_TEXT_CHARS = 500     # fallback only: a near-empty page ...
MIN_DRAWINGS = 10           # ... with real drawing paths is rendered whole
MIN_FIGURE_PATHS = 15       # a drawing cluster this big is a figure; callouts, rules and ornaments are smaller
FIGURE_JOIN_GAP = 10        # paths this close (points) belong to one figure, so floating bars or dots still cluster
MIN_FIGURE_AREA = 0.05      # ... and must cover at least this share of the page
FIGURE_PAD = 10             # points of margin around the crop
FIGURE_CAPTION_GAP = 60     # a "Figure N" caption this close (points) is cropped in with its figure
FIGURE_LABEL_GAP = 8        # a short text block this close (points) to the drawing is one of its labels
FIGURE_LABEL_CHARS = 200    # text blocks shorter than this touching the figure are its labels, not body text

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

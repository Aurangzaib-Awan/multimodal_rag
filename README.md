# MultiRAG

Upload a PDF, then ask questions about its text, tables, images and charts. Answers cite pages, and the figures behind an answer come back with it.

## How it works

- **Parsing** (`backend/services/parsing.py`): runs in a process pool over 16-page batches, because PyMuPDF is CPU-bound and not thread-safe.
  - Text keeps its headings (from font size). Tables, including ones without ruled lines, become whole table chunks.
  - Raster images (icons under 64px skipped, repeated logos captioned once) and vector graphics (a page with little text, no table, no image and more than 10 drawing paths) are rendered and described by a vision model.
- **Captions and embeddings:** VLM calls run concurrently under asyncio, capped at 4 at once. Embeddings run locally with fastembed (bge-base dense, BM25 sparse).
- **Storage:** Qdrant payload per chunk: `page_number, type, section, text, filename, pages_total`, plus `image_base64` for images and figures.
- **Query** (`backend/services/retrieval.py`): a page mentioned in the question is a hard filter. Words like "table" or "chart" boost that content type without excluding the rest. Then hybrid dense + BM25 search with RRF, then Gemini answers with `[p.N]` citations.
- **Ingest is a background job**: `POST /ingest` returns a job id, `GET /ingest/{id}` reports progress, and `GET /document` tells a reloaded page what is indexed or still running.

## Run it

```bash
# backend (Python 3.12)
cd backend
python -m venv venv && venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # then set GEMINI_API_KEY
venv/bin/python -m uvicorn main:app --port 8000

# frontend
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

`backend/.env`:

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | image/figure captions and answers (required) |
| `QDRANT_URL`, `QDRANT_API_KEY` | optional. Unset = embedded Qdrant stored in `backend/qdrant_data` |
| `CORS_ORIGINS` | comma-separated, default `http://localhost:3000` |

### Using a Qdrant server (to browse the dashboard)

```bash
docker run -p 6333:6333 -v ./qdrant_storage:/qdrant/storage qdrant/qdrant
# then in backend/.env:  QDRANT_URL=http://localhost:6333
# dashboard: http://localhost:6333/dashboard
```

## Tests

```bash
cd backend && venv/bin/python -m pytest -q
cd frontend && npm run lint && npx tsc --noEmit
```

## Limits

- One document at a time. A new upload replaces the index.
- Embedded Qdrant allows one process on the folder, so run a single backend process.

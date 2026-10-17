# MultiRAG

Upload a PDF, then ask questions about its text, tables, images and charts. Answers cite pages, and the figures behind an answer come back with it.

## How it works

- **Parsing** (`backend/services/parsing.py`): 16-page batches run on one dedicated thread, because MuPDF is not thread-safe (and Lambda has no `/dev/shm` for a process pool). While one batch parses, the previous one is captioned and embedded.
  - Text keeps its headings (from font size). Tables, including ones without ruled lines, become whole table chunks.
  - Raster images (icons under 64px skipped, repeated logos captioned once) are extracted and described by a vision model.
  - Vector graphics are found by region, on any page, even one full of body text: connected drawing paths are clustered, and a cluster with at least 15 paths covering at least 5% of the page that is not a ruled table is a figure. It is cropped with its labels and its "Figure N" caption (not the body text around it) and described by the vision model. Lone separator rules and small callout boxes are ignored. Thresholds live in `backend/config.py`.
  - A near-empty page that has drawings but no clean cluster is still rendered whole as a fallback.
- **Captions and embeddings:** VLM calls run concurrently under asyncio, capped at 4 at once. Embeddings run locally with fastembed (bge-base dense, BM25 sparse).
- **Storage:** in-memory Qdrant, one collection per session (the `X-Session-Id` header, a UUID the frontend generates). Nothing persists: a restart, or a new Lambda instance, means re-uploading. Payload per chunk: `page_number, type, section, text, filename, pages_total`, plus `image_base64` for images and figures.
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
| `FASTEMBED_CACHE_PATH` | fastembed model folder. Default `/opt/models` (baked into the Lambda image); set a writable folder for local dev, e.g. `/tmp/fastembed_cache` |
| `CORS_ORIGINS` | comma-separated, default `http://localhost:3000` |

### Deploying to AWS Lambda

`main.handler` is the Lambda entry point (Mangum). `uvicorn main:app` keeps working locally.

- On Lambda (`AWS_LAMBDA_FUNCTION_NAME` is set) `POST /ingest` finishes the whole ingest before replying: 200 with the finished job, or 500 with the error. Lambda freezes the instance once a response is sent, so a background job would stall. Locally it stays a background job (202, poll `GET /ingest/{job_id}`).
- Ingesting `test0.pdf` takes about 25 s, close to API Gateway's 29 s default timeout. Use a Lambda Function URL (up to 15 min) or raise the timeout.
- Bake the fastembed models into the image at `/opt/models` (or set `FASTEMBED_CACHE_PATH`).

## Try it with the demo PDFs

Upload one of these from the UI, wait for the page map to fill in, then ask:

| File | What it is | Good questions |
|---|---|---|
| `test1.pdf` | "Attention Is All You Need" (Vaswani et al., 15 pages, 3 figures) | "Describe the figures and charts", "How is attention computed in the scaled dot-product figure?", "What is on page 5?" |
| `test0.pdf` | A Wikibooks chapter, "Anatomy of the Somatosensory System" (4 pages, 1 image) | "Summarize the first page", "Describe the image" |

`test1.pdf` is reproduced from the paper's Google-provided permission to reuse its tables and figures with attribution. `test0.pdf` comes from Wikibooks (Sensory Systems).

## Tests

```bash
cd backend && venv/bin/python -m pytest -q
cd frontend && npm run lint && npx tsc --noEmit
```

## Limits

- Every request needs an `X-Session-Id` header (a UUID); without it the API returns 400.
- One document per session. A new upload replaces that session's document.
- Uploads over 4 MB are rejected (413), and the frontend checks before uploading. Lambda caps requests at 6 MB, and the PDF arrives base64-encoded (+33%).
- A new upload deletes the session's previous document right away; a failed ingest deletes its half-built one.
- A question for a session with no collection returns 404 "Session expired, please re-upload your PDF."

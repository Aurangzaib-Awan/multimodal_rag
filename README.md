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
- **Query** (`backend/services/retrieval.py`): a page mentioned in the question is a hard filter. Words like "table" or "chart" boost that content type without excluding the rest. Then hybrid dense + BM25 search with RRF over small chunks. Gemini reads the whole page of the 3 best-matching pages (small chunks find the place, whole pages give the context) and answers with `[p.N]` citations; only images from pages the answer cites are returned.
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
| `LLM_MODEL` | answer model, default `gemini-flash-lite-latest` (fast); `gemini-flash-latest` is stronger but was often overloaded |
| `FASTEMBED_CACHE_PATH` | fastembed model folder. Default `/opt/models` (baked into the Lambda image); set a writable folder for local dev, e.g. `/tmp/fastembed_cache` |
| `CORS_ORIGINS` | comma-separated, default `http://localhost:3000` |

### Deploying to AWS Lambda

`main.handler` is the Lambda entry point (Mangum); `backend/Dockerfile` builds the image with both embedding models baked in at `/opt/models`. `uvicorn main:app` keeps working locally.

How it behaves on Lambda (`AWS_LAMBDA_FUNCTION_NAME` is set):

- `POST /ingest` finishes the whole ingest before replying: 200 with the finished job, or 500 with the error. Lambda freezes once a response is sent, so a background job would stall. Locally it stays a background job (202, poll `GET /ingest/{job_id}`).
- The models load during Lambda's init phase, not inside the first request. `test0.pdf` ingests in about 8 s once warm.
- One instance serves everything (reserved concurrency 1, below), so documents are never on "another instance". A second request that arrives while one is running gets 429 from AWS, and the UI says the server is busy.

Steps (replace `ACCOUNT`, `REGION`, the role and the key):

```bash
cd backend
docker buildx build --platform linux/amd64 --provenance=false -t multirag-api --load .

aws ecr create-repository --repository-name multirag-api
aws ecr get-login-password --region REGION | docker login --username AWS --password-stdin ACCOUNT.dkr.ecr.REGION.amazonaws.com
docker tag multirag-api:latest ACCOUNT.dkr.ecr.REGION.amazonaws.com/multirag-api:latest
docker push ACCOUNT.dkr.ecr.REGION.amazonaws.com/multirag-api:latest

aws lambda create-function --function-name multirag-api --package-type Image \
  --code ImageUri=ACCOUNT.dkr.ecr.REGION.amazonaws.com/multirag-api:latest \
  --role arn:aws:iam::ACCOUNT:role/YOUR_LAMBDA_ROLE \
  --memory-size 3008 --timeout 300 \
  --environment "Variables={GEMINI_API_KEY=your-key,CORS_ORIGINS=https://your-frontend.example}"

# one instance only: every session's in-memory document lives in the same place
aws lambda put-function-concurrency --function-name multirag-api --reserved-concurrent-executions 1

# public HTTPS endpoint, up to 15 min per request (API Gateway would cut ingest off at 29 s)
aws lambda create-function-url-config --function-name multirag-api --auth-type NONE
aws lambda add-permission --function-name multirag-api --statement-id public-url \
  --action lambda:InvokeFunctionUrl --principal "*" --function-url-auth-type NONE
```

- **Role:** any role with the `AWSLambdaBasicExecutionRole` policy (CloudWatch logs). The console's "create a new role" option makes one.
- **Memory 3008 MB:** measured about 1.1 GB after the first ingest plus about 15 MB per session (30 MB worst case), so the 50-session cap fits. More memory also means more CPU, and embedding is CPU-bound.
- **CORS:** leave the Function URL's own CORS setting off. The app already answers CORS from `CORS_ORIGINS`, and setting both sends duplicate headers that browsers reject.
- **Reserved concurrency 1 can fail on new AWS accounts.** AWS keeps at least 10 concurrent executions unreserved, and new accounts often have a total of only 10. If the command is refused, request a higher "Concurrent executions" quota in Service Quotas.
- **Frontend:** build it with `NEXT_PUBLIC_API_URL` set to the Function URL. A trailing slash is fine.
- **`--provenance=false`:** buildx otherwise adds build metadata that turns the image into a multi-entry index, which Lambda rejects.
- **Updating:** rebuild and push, then `aws lambda update-function-code --function-name multirag-api --image-uri ACCOUNT.dkr.ecr.REGION.amazonaws.com/multirag-api:latest`.

## Try it with the demo PDFs

Upload one of these from the UI, wait for the page map to fill in, then ask:

| File | What it is | Good questions |
|---|---|---|
| `test1.pdf` | "Attention Is All You Need" (Vaswani et al., 15 pages, 3 figures) | "Describe the figures and charts", "How is attention computed in the scaled dot-product figure?", "What is on page 5?" |
| `test0.pdf` | A Wikibooks chapter, "Anatomy of the Somatosensory System" (4 pages, 1 photo, 2 diagrams) | "Summarize the first page", "What is on the last page?", "Describe the figures" |

`test1.pdf` is reproduced from the paper's Google-provided permission to reuse its tables and figures with attribution. `test0.pdf` comes from Wikibooks (Sensory Systems).

## Tests

```bash
cd backend && venv/bin/python -m pytest -q
cd frontend && npm test && npm run lint && npx tsc --noEmit
```

## Limits

- Every request needs an `X-Session-Id` header (a UUID); without it the API returns 400.
- One document per session. A new upload replaces that session's document.
- Uploads over 4 MB are rejected (413), and the frontend checks before uploading. Lambda caps requests at 6 MB, and the PDF arrives base64-encoded (+33%).
- A new upload deletes the session's previous document right away; a failed ingest deletes its half-built one.
- Each instance keeps at most 50 sessions' documents in memory (`MAX_SESSIONS` in `backend/config.py`); the least recently used one is dropped, and that user sees "session expired".
- A question for a session with no collection returns 404 "Session expired, please re-upload your PDF."

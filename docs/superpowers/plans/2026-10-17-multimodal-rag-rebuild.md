# Multimodal RAG Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upload a PDF, parse it at runtime (headings, tables, images, vector graphics) and answer questions about any of it. The answer shows the images or figures behind it.

**Architecture:** A FastAPI backend parses page batches in a process pool. VLM and embedding calls fan out under asyncio with a concurrency cap. Points (page metadata, chunk text, dense and sparse vectors, base64 image) go to a local Qdrant. A query is first filtered on metadata parsed from the question (page, content type), then hybrid dense+BM25 search with RRF, then Gemini answers. A Next.js frontend handles upload with live progress, plus chat with cited sources and figures.

**Tech Stack:** Python 3.12, FastAPI, PyMuPDF 1.27 + pymupdf4llm 1.27, fastembed 0.8 (local dense + BM25), qdrant-client 1.17 (embedded or server), google-genai (Gemini), pytest; Next.js 16, React 19, Tailwind 4.

**Spec:** The user's chat request of 2026-10-17 (restated in "Decisions" below).

## Decisions and reasoning

### 1. Concurrency: processes for parsing, asyncio for network

The work has two parts with different bottlenecks:

| Stage | Bound by | Tool | Why |
|---|---|---|---|
| Layout parsing (pymupdf4llm, `fitz`) | CPU | `ProcessPoolExecutor`, page batches of 16 | PyMuPDF holds the GIL, and its docs say a `Document` must not be shared across threads. Threads would serialize on the GIL and risk crashes. Separate processes each open the file themselves and run truly in parallel. |
| VLM captions, LLM answer | Network latency | `asyncio` + `Semaphore(4)` on the async Gemini client | Hundreds of waits that each take seconds. Coroutines cost almost nothing per call, a semaphore gives one clear rate limit, and 429 retries with backoff fit in one place. A thread per request would buy nothing here. |
| Embedding (fastembed ONNX) | CPU, batched | One batched call in `asyncio.to_thread` | ONNX Runtime already uses every core inside one call. Parallelizing it again would only add contention. `to_thread` keeps the event loop responsive. |

Measured: one page takes about 1–2 s in pymupdf4llm layout mode. The 800-page Goodfellow PDF is roughly 15–25 min serially, and about a third of that with 3 workers. This machine has 4 cores and 7 GB RAM with about 1 GB free. Default `PARSE_WORKERS = min(3, os.cpu_count() - 1)` leaves a core for the API and the embedder.

### 2. Provider changes forced by today's environment (probed 2026-10-17)

- **HF Inference returns `402 Payment Required`** (no credits). Dense embeddings move to **local fastembed `BAAI/bge-base-en-v1.5` (768-d)**. bge-large (1024-d, ~1.3 GB) does not fit in free RAM. BM25 already runs in fastembed. As a bonus, the backend no longer needs `HF_TOKEN`.
- **Groq removed `llama-3.1-8b-instant` and `llama-4-scout`.** VLM captions and answers move to **Gemini** (`gemini-flash-lite-latest` for captions, `gemini-flash-latest` for answers), the key in `.env` works. `groq` is dropped from requirements.

### 3. Qdrant runs locally

The Docker socket is not accessible to this session, so the backend runs both ways:
- `QDRANT_URL` unset → embedded mode, `QdrantClient(path="backend/qdrant_data")`. No server needed.
- `QDRANT_URL=http://localhost:6333` → server mode. The README documents `docker run -p 6333:6333 -v ./qdrant_data_server:/qdrant/storage qdrant/qdrant` so the user can open the dashboard at `:6333/dashboard`.

Embedded mode allows one process per path, so only the API process may touch Qdrant. Parse workers never import the Qdrant module.

### 4. Parsing rules (per page)

1. **Text:** pymupdf4llm markdown keeps headings from font size (`#`, `##`) and bold/italic. The markdown is split into chunks at headings, max 1,500 chars, 200-char overlap. Each chunk keeps its nearest heading as `section`.
2. **Tables:** pymupdf4llm emits bookish tables without ruled lines as markdown pipes (verified on `test_table.pdf` p.82, Table 4.1). Runs of lines starting with `|` become a separate `table` chunk. The caption line directly above it, if one exists, is prepended. A table is never split mid-way.
3. **Images:** `page.get_images(full=True)` → `doc.extract_image(xref)`. Images under 64 px on either side (icons, bullets) are skipped, and xrefs repeated across pages (logos) are captioned only once. Each image is converted to JPEG, longest side at most 1,024 px, then captioned by the VLM.
4. **Vector graphics:** a page with **no raster image, no table, under 500 chars of text and more than 10 drawing paths** (`page.get_drawings()`) is rendered at 150 dpi and treated like an image (`type="figure"`). The drawings check stops blank or title-only pages from going to the VLM.

### 5. Metadata and retrieval

Payload on every point: `doc_id, filename, page_number, type ∈ {text, table, image, figure}, section, text, image_base64 (image/figure only), page_has_table, page_has_image`. Payload indexes go on `page_number`, `type` and `doc_id`.

Query flow:
1. Parse a filter from the question: page (the existing regex rules are kept), plus a type hint: "table" → `table`; "image/figure/diagram/graph/chart/plot" → `image, figure`.
2. Hybrid prefetch (dense + sparse, top 10 each) with that filter, then RRF top 6.
3. If the filtered search returns 0 points, retry without the type filter. The page filter is never dropped silently.
4. Gemini answers from the chunks, citing `[p.N]`. The response returns the answer, sources (type, page, section, snippet) and images for any `image`/`figure` chunk in the result.

### 6. Ingest is a background job

A long PDF takes minutes, and an HTTP request should not hang that long. `POST /ingest` saves the file, starts an asyncio task and returns `{job_id}` at once. `GET /ingest/{job_id}` returns `{status: queued|parsing|captioning|embedding|done|error, pages_done, pages_total, chunks, error}`. Jobs are held in an in-memory dict, because this is a one-user local app. Each upload replaces the previous document (existing behavior) by recreating the collection.

## Global Constraints

- Python deps live in `backend/venv`; Node deps in `frontend/node_modules`. No new runtime services are required.
- Secrets come only from `backend/.env`. Nothing secret goes to the frontend or into the repo.
- Frontend calls `NEXT_PUBLIC_API_URL`, default `http://localhost:8000`.
- Next.js 16 has breaking changes: read `frontend/node_modules/next/dist/docs/` before writing FE code (per `frontend/AGENTS.md`).
- Not a git repository: commit steps are skipped unless the user runs `git init`.

## Review Focus

1. **Scanned PDF (no text layer):** every page should go to the VLM as a `figure`. It must not be dropped as "sparse text with no drawings". Test `test_scanned_page_goes_to_vlm`: a page with no text, no drawings and one full-page raster image is captioned as an image.
2. **VLM rate limit (429) mid-ingest:** retry with backoff ×3, then store the chunk without a caption (skip it) and continue. The ingest must not fail. Test `test_caption_failure_does_not_fail_ingest`.
3. **Non-PDF or corrupt upload:** return 400 with a clear message, not a 500. Test `test_ingest_rejects_corrupt_pdf`.
4. **Question before any upload:** return 409 "No document indexed yet", not a Qdrant exception. Test `test_query_without_collection`.
5. **Page asked for is beyond the document:** "page 900" on 800 pages should get a plain "that page doesn't exist" answer, not an empty answer. Test `test_page_out_of_range`.

---

## File Structure

```
backend/
  config.py                  # env + constants (models, batch sizes, thresholds)
  main.py                    # app, CORS, routers (modified)
  routers/ingest.py          # POST /ingest, GET /ingest/{job_id} (rewritten)
  routers/query.py           # POST /query (rewritten; uses services.retrieval)
  services/parsing.py        # pure, picklable: parse_batch(path, pages) -> list[PageResult]   [runs in workers]
  services/chunking.py       # pure: split_markdown(md) -> list[Chunk]  (text/table split)
  services/vlm.py            # async caption(jpeg_b64, kind) with semaphore + retry
  services/embedding.py      # local fastembed dense + sparse, batched (rewritten)
  services/store.py          # Qdrant client, collection reset, upsert, hybrid search (replaces qdrant_client.py)
  services/pipeline.py       # orchestrates job: pool -> captions -> embed -> upsert, updates job status
  services/retrieval.py      # parse_query_filter(question) -> QueryFilter; search + fallback
  services/generator.py      # async Gemini answer (rewritten)
  tests/                     # pytest; fixtures build tiny PDFs with fitz at runtime
  requirements.txt           # drop groq/hf, add pytest
frontend/src/
  app/page.tsx, layout.tsx, globals.css   # rewritten via impeccable skill
  components/*                             # rewritten via impeccable skill
  lib/api.ts                               # typed fetch helpers + types matching backend JSON
```

Delete: `services/qdrant_client.py`, `services/image_captioning.py`, `services/pdf_processor.py` (logic moves into the new modules).

---

### Task 1: Pure parsing and chunking

**Files:** Create `backend/config.py`, `backend/services/chunking.py`, `backend/services/parsing.py`, `backend/tests/conftest.py`, `backend/tests/test_parsing.py`

**Interfaces — Produces:**
- `Chunk = TypedDict(type: Literal["text","table"], text: str, section: str | None)`
- `split_markdown(md: str, max_chars=1500, overlap=200) -> list[Chunk]`
- `PageResult = TypedDict(page_number: int, chunks: list[Chunk], visuals: list[Visual], has_table: bool, has_image: bool)`
- `Visual = TypedDict(kind: Literal["image","figure"], jpeg_b64: str, xref: int | None)`
- `parse_batch(path: str, pages: list[int]) -> list[PageResult]` (0-based page indices in, 1-based `page_number` out; top-level function so it pickles)

- [ ] **Step 1: Write failing tests** in `tests/test_parsing.py`, with fixtures in `conftest.py` that build PDFs with `fitz` (a heading page, a ruled-free text table, a page with a 200×200 raster, a page with a 20×20 icon, a page with 30 drawn lines and 1 word, a blank page):
  - `test_split_keeps_table_whole`: a 3-row pipe table gives exactly one `table` chunk containing all 3 rows, with its caption line prepended.
  - `test_split_by_heading_sets_section`: `"# A\nx\n## B\ny"` gives 2 text chunks with sections `"A"`, `"B"`.
  - `test_long_section_splits_with_overlap`: 4,000 chars gives ≥3 chunks, each ≤1,500 chars, and consecutive chunks share ≥150 chars.
  - `test_small_icon_skipped` / `test_raster_image_extracted`.
  - `test_vector_page_becomes_figure`: the drawn-lines page gives one `figure` visual.
  - `test_blank_page_no_visual`: the blank page gives no visuals and no chunks.
  - `test_scanned_page_goes_to_vlm` (Review Focus 1).
- [ ] **Step 2:** `venv/bin/pip install pytest && venv/bin/pytest tests/test_parsing.py -q` → FAIL (import errors).
- [ ] **Step 3: Implement** per Decisions §4. Image dedupe within a batch uses `xref`. Cross-batch dedupe happens in the pipeline (Task 3) by `xref`.
- [ ] **Step 4:** `venv/bin/pytest tests/test_parsing.py -q` → all pass. Also run `parse_batch("test_table.pdf", [81])` and check that a `table` chunk contains `"Beam pipe"`.

### Task 2: Embedding, VLM, store (I/O adapters)

**Files:** Rewrite `services/embedding.py`, create `services/vlm.py`, `services/store.py`; delete old `qdrant_client.py`, `image_captioning.py`; test `tests/test_store.py`

**Interfaces — Produces:**
- `embed_dense(texts: list[str], is_query=False) -> list[list[float]]` (bge-base: prefix `"Represent this sentence for searching relevant passages: "` for queries only, per the model card)
- `embed_sparse(texts: list[str]) -> list[models.SparseVector]`
- `async caption(jpeg_b64: str, kind: Literal["image","figure"]) -> str | None` (None after 3 failed tries; the figure prompt asks for axes, labels, values and relationships)
- `store.reset_collection() -> None`, `store.upsert(points: list[PointStruct]) -> None`, `store.search(dense, sparse, flt: models.Filter | None, limit=6) -> list[ScoredPoint]`, `store.has_collection() -> bool`
- `DENSE_SIZE = 768`

- [ ] **Step 1: Failing tests** (`tests/test_store.py`, using `QdrantClient(":memory:")` injected through `store.set_client`): `test_hybrid_search_filters_by_page`, `test_search_type_filter`, `test_reset_recreates_empty`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement.** Use one fastembed model instance per process, loaded lazily on first use. For `caption`, the async `genai.Client(...).aio.models.generate_content` sits under `asyncio.Semaphore(4)` with backoff of 2, 4, 8 s.
- [ ] **Step 4:** Tests pass. Then a smoke run: `embed_dense(["hi"])` has length 768, and `caption()` on a rendered page returns non-empty text.

### Task 3: Ingest pipeline + routes

**Files:** Create `services/pipeline.py`; rewrite `routers/ingest.py`; modify `main.py`; delete `services/pdf_processor.py`; test `tests/test_ingest.py`

**Interfaces:**
- Consumes `parse_batch`, `caption`, `embed_*`, `store.*`.
- Produces `JOBS: dict[str, Job]`, `Job = dataclass(id, filename, status, pages_done, pages_total, chunks, error)`, `async run_job(job: Job, path: str) -> None`.
- HTTP: `POST /ingest` (multipart `file`) → `202 {"job_id": str}`; `GET /ingest/{job_id}` → the Job as JSON; 404 for an unknown job id.

- [ ] **Step 1: Failing tests** (FastAPI `TestClient`, with `caption` monkeypatched to return a fixed caption or raise, and the store in memory): `test_ingest_job_completes_and_counts_chunks`, `test_caption_failure_does_not_fail_ingest` (RF 2), `test_ingest_rejects_corrupt_pdf` (RF 3; bytes `b"not a pdf"` with a .pdf name → 400).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement.** Validate with `fitz.open` before returning 202. Use `loop.run_in_executor(pool, parse_batch, path, batch)` per 16-page batch, updating `pages_done` as each batch completes. Caption with `asyncio.gather` per batch, embed per batch, upsert per batch, so memory stays bounded on the 800-page PDF. Delete the temp file in `finally`. The pool is created once at app startup (lifespan) and shut down on exit.
- [ ] **Step 4:** Tests pass.

### Task 4: Retrieval, generation, query route

**Files:** Create `services/retrieval.py`; rewrite `services/generator.py`, `routers/query.py`; test `tests/test_query.py`

**Interfaces:**
- `QueryFilter = dataclass(page: int | None, types: list[str] | None)`; `parse_query_filter(q: str) -> QueryFilter`
- `retrieve(q: str) -> tuple[list[ScoredPoint], QueryFilter]` (applies the fallback in Decisions §5.3)
- `async generate_answer(q: str, points) -> str`
- HTTP `POST /query {question}` → `{answer, filter: {page, types}, sources: [{type, page_number, section, snippet}], images: [{type, page_number, caption, image_base64}]}`

- [ ] **Step 1: Failing tests:** `test_parse_filter_page_variants` ("page 5", "5th page", "third page" → 5, 5, 3), `test_parse_filter_types` ("show the table" → `["table"]`, "explain the diagram" → `["image","figure"]`, "what is entropy" → None), `test_type_fallback_when_empty`, `test_query_without_collection` (RF 4 → 409), `test_page_out_of_range` (RF 5), `test_images_only_for_visual_chunks`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement.** The prompt tells the model to answer only from context, cite `[p.N]`, and say plainly when the answer isn't in the document.
- [ ] **Step 4:** `venv/bin/pytest -q` → the whole backend suite passes.

### Task 5: Frontend (impeccable skill)

**Files:** Create `frontend/src/lib/api.ts`; rewrite `src/app/page.tsx`, `layout.tsx`, `globals.css`, `src/components/*`

**Interfaces — Consumes:** the HTTP contracts in Tasks 3–4 exactly. `api.ts` exports `startIngest(file): Promise<{job_id}>`, `getJob(id): Promise<Job>`, `ask(question): Promise<QueryResponse>`, with TS types mirroring the JSON above.

- [ ] **Step 1:** Load the `impeccable` skill and follow its process (context gathering, design direction) before writing UI code. Read the Next 16 docs per AGENTS.md.
- [ ] **Step 2: Build.** It must have: drag-and-drop or click upload; live progress from polling `getJob` every 1 s (stage + pages done/total); the chat disabled until a document is indexed; answers rendered as markdown with `[p.N]` citations; source chips (type + page + section); figures and images as thumbnails that open a lightbox with their caption; and clear empty, error and loading states. It must work at 375 px width and in both light and dark themes.
- [ ] **Step 3:** `npm run build` and `npm run lint` → no errors.

### Task 6: Review + end-to-end verification

- [ ] **Step 1:** Run `ponytail:ponytail-review` over backend + frontend and fix the confirmed findings.
- [ ] **Step 2:** Start the backend (`venv/bin/uvicorn main:app --port 8000`) and the frontend (`npm run dev`). In the browser pane, upload `test1.pdf`, watch the progress reach done, then ask one question each about a table, an image and a page-specific fact. Confirm the answers cite pages and that the image question shows a thumbnail.
- [ ] **Step 3:** Update `backend/README.md` with setup steps, both Qdrant modes and the env vars.

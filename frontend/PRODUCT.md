# Product

> Facts below are inferred from the repo and the owner's brief (no interview round was run). Confirm or correct.

## What it is
A local, single-user multimodal RAG tool: attach one PDF, it is parsed at runtime (heading-aware text, bookish tables, raster images and vector graphics described by a VLM), then the user asks questions and gets answers cited by page, with the figures behind the answer shown inline.

## Users and job
- Primary: the developer/owner and reviewers evaluating the system, at a desk, working through long technical PDFs (textbooks, physics papers, ~10–800 pages).
- Job: ask a question, trust the answer by checking which page, table or figure it came from.

## Constraints
- One document at a time; uploading replaces the index.
- Ingest of a long PDF takes minutes; progress must be visible.
- Backend at NEXT_PUBLIC_API_URL (default http://localhost:8000).

## Platform
web (desktop first, must work at phone width)

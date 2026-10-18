import { apiBase, errorMessage } from "./errors";
import { newId } from "./uuid";

export const API_URL = apiBase(process.env.NEXT_PUBLIC_API_URL);

/** Matches the backend limit: Lambda caps requests at 6 MB and the PDF travels base64-encoded. */
export const MAX_UPLOAD_BYTES = 4 * 1024 * 1024;

const SESSION_KEY = "multirag-session";
let memorySession: string | null = null;

/** One id per browser tab (kept across reloads). The backend stores this tab's document under it. */
function sessionId(): string {
  try {
    let id = sessionStorage.getItem(SESSION_KEY);
    if (!id) {
      id = newId();
      sessionStorage.setItem(SESSION_KEY, id);
    }
    return id;
  } catch {
    return (memorySession ??= newId()); // storage blocked: keep it for this page load
  }
}

export type ChunkType = "text" | "table" | "image" | "figure";

export interface Job {
  id: string;
  filename: string;
  status: "queued" | "processing" | "done" | "error";
  pages_done: number;
  pages_total: number;
  chunks: number;
  visuals: number;
  error: string | null;
}

export interface DocumentInfo {
  indexed: boolean;
  filename: string | null;
  pages_total: number | null;
  chunks: number;
  job: Job | null; // set while an ingest is still running
}

export interface Source {
  type: ChunkType;
  page_number: number;
  section: string | null;
  snippet: string;
}

export interface Visual {
  type: "image" | "figure";
  page_number: number;
  caption: string;
  image_base64: string;
}

export interface QueryResponse {
  question: string;
  answer: string;
  filter: { page: number | null; types: ChunkType[] | null };
  sources: Source[];
  images: Visual[];
}

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { ...init?.headers, "X-Session-Id": sessionId() },
    });
  } catch {
    throw new ApiError(`Can't reach the API at ${API_URL}. Is the backend running?`);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(errorMessage(res.status, body), res.status);
  return body as T;
}

export const getDocument = () => call<DocumentInfo>("/document");

export function startIngest(file: File) {
  const form = new FormData();
  form.append("file", file);
  // locally the job runs in the background (status "queued"); on Lambda it comes back finished ("done")
  return call<Job & { job_id: string }>("/ingest", { method: "POST", body: form });
}

export const getJob = (id: string) => call<Job>(`/ingest/${id}`);

export const ask = (question: string) =>
  call<QueryResponse>("/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });

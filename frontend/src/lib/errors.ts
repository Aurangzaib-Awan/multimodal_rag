/** API base URL without a trailing slash (Lambda Function URLs end in "/", which would make "//document"). */
export function apiBase(url: string | undefined): string {
  return (url ?? "http://localhost:8000").replace(/\/+$/, "");
}

/** What to tell the user about a failed API response. */
export function errorMessage(status: number, body: { detail?: string; [key: string]: unknown }): string {
  // the backend runs as a single Lambda instance; AWS answers extra simultaneous requests with 429
  if (status === 429) return "The server is busy with another request. Please try again in a few seconds.";
  return body.detail ?? `Request failed (${status}).`;
}

"use client";

import { useRef, useState } from "react";
import { CircleAlert, FileText, FileUp, RefreshCw } from "lucide-react";
import PageMap from "./PageMap";

export type DocState =
  | { phase: "loading" }
  | { phase: "empty"; error?: string }
  | { phase: "uploading"; filename: string }
  | { phase: "processing"; filename: string; done: number; total: number; chunks: number }
  | { phase: "ready"; filename: string | null; total: number; chunks: number; visuals?: number }
  | { phase: "error"; filename: string; error: string };

interface Props {
  doc: DocState;
  cited: Set<number>;
  active: number | null;
  onFile: (file: File) => void;
  onPickPage: (page: number) => void;
}

export default function DocumentRail({ doc, cited, active, onFile, onPickPage }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const busy = doc.phase === "uploading" || doc.phase === "processing";

  const pick = () => input.current?.click();
  const drop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f && !busy) onFile(f);
  };

  return (
    <aside
      className="flex flex-col gap-3 md:gap-6 bg-rail text-rail-ink px-5 py-3 md:py-5 md:w-[320px] md:shrink-0 md:h-full md:overflow-y-auto"
      onDragOver={(e) => {
        e.preventDefault();
        if (!busy) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={drop}
    >
      <div className="flex items-baseline justify-between">
        <h1 className="text-[1.0625rem] font-semibold tracking-[-0.01em]">MultiRAG</h1>
        <span className="text-xs text-rail-ink-2">Ask your PDF</span>
      </div>

      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        className="sr-only"
        tabIndex={-1}
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) onFile(f);
        }}
      />

      {doc.phase === "loading" && <div className="h-28 rounded-xl bg-rail-2 animate-pulse" aria-label="Loading" />}

      {(doc.phase === "empty" || dragging) && (
        <button
          type="button"
          onClick={pick}
          disabled={busy}
          className={`group flex flex-col items-start gap-3 rounded-xl border border-dashed px-4 py-5 text-left transition-colors duration-200
            ${dragging ? "border-hl bg-rail-2" : "border-rail-line hover:border-rail-ink-2 hover:bg-rail-2/60"}`}
        >
          <FileUp className="size-5 text-hl" aria-hidden />
          <span>
            <span className="block text-sm font-medium">{dragging ? "Drop to index this PDF" : "Add a PDF"}</span>
            <span className="mt-1 block text-[0.8125rem] leading-snug text-rail-ink-2">
              Drop it here or click to browse. Text, tables, images and charts are all indexed.
            </span>
          </span>
        </button>
      )}

      {doc.phase === "empty" && doc.error && <Problem message={doc.error} />}

      {!dragging && doc.phase !== "empty" && doc.phase !== "loading" && (
        <section aria-labelledby="doc-title" className="flex flex-col gap-2 md:gap-4">
          <div className="flex items-start gap-3">
            <FileText className="mt-0.5 size-4 shrink-0 text-rail-ink-2" aria-hidden />
            <div className="min-w-0">
              <h2 id="doc-title" className="truncate text-sm font-medium" title={doc.filename ?? undefined}>
                {doc.filename ?? "Indexed document"}
              </h2>
              <p className="mt-0.5 text-[0.8125rem] text-rail-ink-2 tabular" aria-live="polite">
                <Status doc={doc} />
              </p>
            </div>
          </div>

          {doc.phase === "processing" && (
            <div className="h-1 overflow-hidden rounded-full bg-rail-ink/12" aria-hidden>
              <div
                className="h-full bg-hl transition-[width] duration-500 ease-out"
                style={{ width: `${doc.total ? (doc.done / doc.total) * 100 : 4}%` }}
              />
            </div>
          )}

          {(doc.phase === "processing" || doc.phase === "ready") && (
            <div className={`flex flex-col gap-2 ${doc.phase === "ready" ? "max-md:hidden" : ""}`}>
              <PageMap
                total={doc.total}
                done={doc.phase === "ready" ? doc.total : doc.done}
                cited={cited}
                active={active}
                onPick={doc.phase === "ready" ? onPickPage : undefined}
              />
              {doc.phase === "ready" && (
                <p className="text-xs text-rail-ink-2">
                  {cited.size ? (
                    <>
                      <span className="mr-1.5 inline-block size-2 rounded-[2px] bg-hl align-middle" aria-hidden />
                      Pages cited in the latest answer. Click any page to ask about it.
                    </>
                  ) : (
                    "Click a page to ask about it."
                  )}
                </p>
              )}
            </div>
          )}

          {doc.phase === "error" && <Problem message={doc.error} />}

          {!busy && (
            <button
              type="button"
              onClick={pick}
              className="inline-flex w-fit items-center gap-2 rounded-lg px-2.5 py-1.5 -ml-2.5 text-[0.8125rem] text-rail-ink-2 hover:bg-rail-2 hover:text-rail-ink transition-colors duration-150"
            >
              <RefreshCw className="size-3.5" aria-hidden />
              {doc.phase === "error" ? "Try another PDF" : "Replace with another PDF"}
            </button>
          )}
        </section>
      )}

      <p className="mt-auto hidden text-xs leading-relaxed text-rail-ink-2 md:block">
        One document at a time. Adding a new PDF replaces the current index.
      </p>
    </aside>
  );
}

function Status({ doc }: { doc: DocState }) {
  switch (doc.phase) {
    case "uploading":
      return <>Uploading…</>;
    case "processing":
      return doc.total ? (
        <>
          Reading pages {doc.done} of {doc.total} · {doc.chunks} passages
        </>
      ) : (
        <>Opening document…</>
      );
    case "ready":
      return (
        <>
          {doc.total} pages · {doc.chunks} passages indexed
        </>
      );
    case "error":
      return <>Indexing stopped</>;
    default:
      return null;
  }
}

function Problem({ message }: { message: string }) {
  return (
    <p role="alert" className="flex gap-2 rounded-lg bg-[#3a1714] px-3 py-2.5 text-[0.8125rem] leading-snug text-[#fecdca]">
      <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      {message}
    </p>
  );
}

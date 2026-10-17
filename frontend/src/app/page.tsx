"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import DocumentRail, { type DocState } from "@/components/DocumentRail";
import Conversation, { type Exchange } from "@/components/Conversation";
import FigureViewer from "@/components/FigureViewer";
import { ApiError, ask, getDocument, getJob, startIngest, type Visual } from "@/lib/api";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");

export default function Home() {
  const [doc, setDoc] = useState<DocState>({ phase: "loading" });
  const [jobId, setJobId] = useState<string | null>(null);
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [draft, setDraft] = useState("");
  const [active, setActive] = useState<number | null>(null);
  const [visual, setVisual] = useState<Visual | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const nextId = useRef(1);

  useEffect(() => {
    getDocument()
      .then((d) => {
        if (d.job) {
          // reloaded mid-ingest: pick the progress back up instead of showing a half-built index as ready
          setDoc({ phase: "processing", filename: d.job.filename, done: d.job.pages_done, total: d.job.pages_total, chunks: d.job.chunks });
          setJobId(d.job.id);
        } else {
          setDoc(d.indexed ? { phase: "ready", filename: d.filename, total: d.pages_total ?? 0, chunks: d.chunks } : { phase: "empty" });
        }
      })
      .catch((e) => setDoc({ phase: "empty", error: message(e) }));
  }, []);

  // Poll the ingest job until it finishes.
  useEffect(() => {
    if (!jobId) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const j = await getJob(jobId);
        if (stop) return;
        if (j.status === "done") {
          setDoc({ phase: "ready", filename: j.filename, total: j.pages_total, chunks: j.chunks, visuals: j.visuals });
          setJobId(null);
          return;
        }
        if (j.status === "error") {
          setDoc({ phase: "error", filename: j.filename, error: j.error ?? "Indexing failed." });
          setJobId(null);
          return;
        }
        setDoc({ phase: "processing", filename: j.filename, done: j.pages_done, total: j.pages_total, chunks: j.chunks });
      } catch (e) {
        if (stop) return;
        setDoc((d) => ({ phase: "error", filename: "filename" in d && d.filename ? d.filename : "PDF", error: message(e) }));
        setJobId(null);
        return;
      }
      timer = setTimeout(tick, 1000);
    };
    tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  const onFile = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setDoc({ phase: "empty", error: `"${file.name}" isn't a PDF. Choose a .pdf file.` });
      return;
    }
    setDoc({ phase: "uploading", filename: file.name });
    setExchanges([]);
    setActive(null);
    try {
      const { job_id } = await startIngest(file);
      setDoc({ phase: "processing", filename: file.name, done: 0, total: 0, chunks: 0 });
      setJobId(job_id);
    } catch (e) {
      setDoc({ phase: "error", filename: file.name, error: message(e) });
    }
  };

  const run = useCallback(async (id: number, question: string) => {
    try {
      const data = await ask(question);
      setExchanges((xs) => xs.map((x) => (x.id === id ? { ...x, status: "done", data } : x)));
    } catch (e) {
      setExchanges((xs) => xs.map((x) => (x.id === id ? { ...x, status: "error", error: message(e) } : x)));
    }
  }, []);

  const onAsk = (question: string) => {
    const id = nextId.current++;
    setExchanges((xs) => [...xs, { id, question, status: "pending" }]);
    setDraft("");
    setActive(null);
    run(id, question);
  };

  const onRetry = (ex: Exchange) => {
    setExchanges((xs) => xs.map((x) => (x.id === ex.id ? { ...x, status: "pending", error: undefined } : x)));
    run(ex.id, ex.question);
  };

  const cited = useMemo(() => {
    const last = [...exchanges].reverse().find((x) => x.status === "done");
    return new Set(last?.data?.sources.map((s) => s.page_number) ?? []);
  }, [exchanges]);

  const ready = doc.phase === "ready";
  const disabledReason =
    doc.phase === "processing" || doc.phase === "uploading" ? "Indexing… you can ask once it finishes" : "Add a PDF to start asking";

  return (
    <div className="flex h-dvh flex-col md:flex-row">
      <DocumentRail
        doc={doc}
        cited={cited}
        active={active}
        onFile={onFile}
        onPickPage={(page) => {
          setDraft(`What is on page ${page}?`);
          inputRef.current?.focus();
        }}
      />
      <Conversation
        exchanges={exchanges}
        ready={ready}
        loading={doc.phase === "loading"}
        disabledReason={disabledReason}
        draft={draft}
        setDraft={setDraft}
        onAsk={onAsk}
        onRetry={onRetry}
        active={active}
        onCite={(page) => setActive((a) => (a === page ? null : page))}
        onOpenVisual={setVisual}
        inputRef={inputRef}
      />
      <FigureViewer visual={visual} onClose={() => setVisual(null)} />
    </div>
  );
}

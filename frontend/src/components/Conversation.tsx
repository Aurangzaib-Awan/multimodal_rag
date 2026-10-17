"use client";

import { useEffect, useRef } from "react";
import { ArrowUp, ChartLine, CircleAlert, FileText, Table } from "lucide-react";
import type { QueryResponse, Visual } from "@/lib/api";
import Answer from "./Answer";

export interface Exchange {
  id: number;
  question: string;
  status: "pending" | "done" | "error";
  data?: QueryResponse;
  error?: string;
}

interface Props {
  exchanges: Exchange[];
  ready: boolean;
  loading: boolean;
  disabledReason: string;
  draft: string;
  setDraft: (s: string) => void;
  onAsk: (q: string) => void;
  onRetry: (ex: Exchange) => void;
  active: number | null;
  onCite: (page: number) => void;
  onOpenVisual: (v: Visual) => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}

const SUGGESTIONS = [
  "Summarize the first page",
  "What tables are in this document?",
  "Describe the figures and charts",
];

export default function Conversation({ inputRef, ...p }: Props) {
  const end = useRef<HTMLDivElement>(null);
  const pending = p.exchanges.some((e) => e.status === "pending");
  const lastStatus = p.exchanges.at(-1)?.status;

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [p.exchanges.length, lastStatus]);

  const submit = () => {
    const q = p.draft.trim();
    if (q && p.ready && !pending) p.onAsk(q);
  };

  return (
    <main className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-[760px] flex-col gap-12 px-5 py-10 md:px-8">
          {p.exchanges.length === 0 && !p.loading && <Intro ready={p.ready} onPick={(q) => p.onAsk(q)} />}

          {p.exchanges.map((ex) => (
            <article key={ex.id} className="flex flex-col gap-4" aria-busy={ex.status === "pending"}>
              <h2 className="text-[1.0625rem] font-semibold leading-snug tracking-[-0.01em] text-ink">{ex.question}</h2>
              {ex.status === "pending" && <Thinking />}
              {ex.status === "error" && (
                <div role="alert" className="flex items-start gap-3 rounded-xl bg-danger-wash px-4 py-3 text-sm text-danger">
                  <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <span className="flex-1">{ex.error}</span>
                  <button type="button" onClick={() => p.onRetry(ex)} className="font-medium underline underline-offset-2">
                    Retry
                  </button>
                </div>
              )}
              {ex.status === "done" && ex.data && (
                <Answer data={ex.data} active={p.active} onCite={p.onCite} onOpenVisual={p.onOpenVisual} />
              )}
            </article>
          ))}
          <div ref={end} />
        </div>
      </div>

      <div className="border-t border-line bg-ground/90 backdrop-blur-sm">
        <form
          className="mx-auto w-full max-w-[760px] px-5 py-4 md:px-8"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <div className="flex items-end gap-2 rounded-2xl bg-surface p-2 pl-4 shadow-[0_1px_2px_rgba(0,0,0,0.05),0_8px_24px_-12px_rgba(0,0,0,0.18)] focus-within:ring-2 focus-within:ring-[var(--focus)]">
            <label htmlFor="question" className="sr-only">
              Ask a question about the document
            </label>
            <textarea
              id="question"
              ref={inputRef}
              rows={1}
              value={p.draft}
              disabled={!p.ready}
              onChange={(e) => p.setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  submit();
                }
              }}
              placeholder={p.ready ? "Ask about a passage, a table, a figure, or a page…" : p.disabledReason}
              className="field-sizing-content max-h-40 min-h-[2.5rem] flex-1 resize-none bg-transparent py-2 text-[0.9375rem] leading-relaxed text-ink placeholder:text-ink-3 focus:outline-none disabled:cursor-not-allowed"
            />
            <button
              type="submit"
              disabled={!p.ready || pending || !p.draft.trim()}
              aria-label="Ask"
              className="grid size-10 shrink-0 place-items-center rounded-xl bg-rail text-rail-ink transition-colors duration-150 hover:bg-rail-2 disabled:bg-line disabled:text-ink-3 disabled:cursor-not-allowed"
            >
              <ArrowUp className="size-4" />
            </button>
          </div>
          <p className="mt-2 hidden text-xs text-ink-3 md:block">
            Enter to ask · Shift+Enter for a new line · Mention a page (&ldquo;page 12&rdquo;) or &ldquo;table&rdquo; / &ldquo;figure&rdquo; to narrow the search
          </p>
        </form>
      </div>
    </main>
  );
}

function Intro({ ready, onPick }: { ready: boolean; onPick: (q: string) => void }) {
  return (
    <section className="flex flex-col gap-8 pt-6 md:pt-16">
      <div className="flex flex-col gap-3">
        <h2 className="text-2xl font-semibold tracking-[-0.02em] text-balance">
          {ready ? "What do you want to know from this document?" : "Ask questions about any PDF, including its tables and figures"}
        </h2>
        <p className="max-w-[60ch] text-[0.9375rem] leading-relaxed text-ink-2">
          {ready
            ? "Every answer is cited by page. Click a citation to see the passage, table or figure it came from."
            : "Add a PDF on the left. It is read page by page, so nothing on the page is lost to plain-text extraction:"}
        </p>
      </div>

      {ready ? (
        <ul className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <li key={s}>
              <button
                type="button"
                onClick={() => onPick(s)}
                className="rounded-full bg-surface px-3.5 py-2 text-[0.8125rem] text-ink-2 shadow-[0_1px_2px_rgba(0,0,0,0.06)] hover:text-ink hover:shadow-[0_2px_8px_-2px_rgba(0,0,0,0.15)] transition-shadow duration-150"
              >
                {s}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <dl className="grid max-w-[60ch] gap-5 text-[0.9375rem]">
          {[
            { Icon: FileText, t: "Text, by section", d: "Headings are detected from font size, so answers know which section a passage belongs to." },
            { Icon: Table, t: "Tables, even without ruled lines", d: "Book-style tables are kept whole, rows and columns intact." },
            { Icon: ChartLine, t: "Images, charts and diagrams", d: "A vision model describes each one, and the picture comes back with the answer." },
          ].map(({ Icon, t, d }) => (
            <div key={t} className="flex gap-3">
              <Icon className="mt-0.5 size-4 shrink-0 text-ink-3" aria-hidden />
              <div>
                <dt className="font-medium">{t}</dt>
                <dd className="mt-0.5 text-ink-2 leading-relaxed">{d}</dd>
              </div>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

function Thinking() {
  return (
    <div className="flex max-w-[72ch] flex-col gap-2.5" aria-label="Finding the answer">
      {[92, 100, 74].map((w, i) => (
        <div key={i} className="h-3 rounded-full bg-line animate-pulse" style={{ width: `${w}%`, animationDelay: `${i * 120}ms` }} />
      ))}
      <p className="mt-1 text-xs text-ink-3">Searching the document…</p>
    </div>
  );
}

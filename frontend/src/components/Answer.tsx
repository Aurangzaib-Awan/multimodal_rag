"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { ChartLine, ChevronDown, FileText, Image as ImageIcon, Table } from "lucide-react";
import type { ChunkType, QueryResponse, Visual } from "@/lib/api";
import FigureShowcase from "./FigureShowcase";

const TYPE_META: Record<ChunkType, { label: string; Icon: typeof FileText }> = {
  text: { label: "Text", Icon: FileText },
  table: { label: "Table", Icon: Table },
  image: { label: "Image", Icon: ImageIcon },
  figure: { label: "Figure", Icon: ChartLine },
};

/** "[p.3]" / "[p.3, p.5]" → markdown links the renderer turns into citation tabs. */
function linkCitations(md: string) {
  return md.replace(/\[((?:\s*p\.?\s*\d+\s*,?)+)\]/gi, (_, inner: string) =>
    (inner.match(/\d+/g) ?? []).map((n) => `[p.${n}](#p-${n})`).join(" "),
  );
}

interface Props {
  data: QueryResponse;
  active: number | null;
  onCite: (page: number) => void;
  onOpenVisual: (v: Visual) => void;
}

export default function Answer({ data, active, onCite, onOpenVisual }: Props) {
  const [open, setOpen] = useState(false);
  const pages = [...new Set(data.sources.map((s) => s.page_number))].sort((a, b) => a - b);

  const cite = (page: number) => {
    setOpen(true);
    onCite(page);
  };

  return (
    <div className="flex flex-col gap-5">
      {(data.filter.page !== null || data.filter.types) && (
        <p className="text-xs text-ink-3">
          {data.filter.page !== null && <>Limited to page <span className="tabular">{data.filter.page}</span></>}
          {data.filter.page !== null && data.filter.types && " · "}
          {data.filter.types && <>Preferring {data.filter.types.map((t) => TYPE_META[t].label.toLowerCase() + "s").join(" and ")}</>}
        </p>
      )}

      {data.images.length > 0 && <FigureShowcase key={data.question} visuals={data.images} onOpen={onOpenVisual} />}

      <div className="prose-answer max-w-[72ch]">
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeKatex]}
          components={{
            a: ({ href, children }) => {
              const m = href?.match(/^#p-(\d+)$/);
              if (!m) return <a href={href} target="_blank" rel="noreferrer" className="underline underline-offset-2">{children}</a>;
              const page = Number(m[1]);
              return (
                <button
                  type="button"
                  onClick={() => cite(page)}
                  aria-label={`Show evidence from page ${page}`}
                  aria-pressed={active === page}
                  className={`mx-0.5 inline-flex translate-y-[-1px] items-center rounded-[4px] px-1.5 py-px font-mono text-[0.75rem] font-medium tabular text-hl-ink transition-colors duration-150
                    ${active === page ? "bg-hl" : "bg-hl/55 hover:bg-hl"}`}
                >
                  {children}
                </button>
              );
            },
          }}
        >
          {linkCitations(data.answer)}
        </ReactMarkdown>
      </div>

      {data.sources.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 -ml-2 text-[0.8125rem] font-medium text-ink-2 hover:bg-surface hover:text-ink transition-colors duration-150"
          >
            <ChevronDown className={`size-4 transition-transform duration-200 ${open ? "" : "-rotate-90"}`} aria-hidden />
            Evidence: {data.sources.length} passages from {pages.length === 1 ? "page" : "pages"}{" "}
            <span className="tabular">{pages.join(", ")}</span>
          </button>
          {open && (
            <ol className="mt-2 flex flex-col divide-y divide-line overflow-hidden rounded-xl bg-surface">
              {data.sources.map((s, i) => {
                const { Icon, label } = TYPE_META[s.type];
                const on = active === s.page_number;
                return (
                  <li key={i} className={`px-4 py-3 transition-colors duration-200 ${on ? "bg-hl-wash" : ""}`}>
                    <button type="button" onClick={() => onCite(s.page_number)} className="flex w-full flex-col gap-1 text-left">
                      <span className="flex items-center gap-2 text-xs text-ink-2">
                        <Icon className="size-3.5" aria-hidden />
                        <span className="font-medium text-ink">
                          {label} · p.<span className="tabular">{s.page_number}</span>
                        </span>
                        {s.section && <span className="truncate">{s.section}</span>}
                      </span>
                      <span className="line-clamp-3 text-[0.8125rem] leading-relaxed text-ink-2">{s.snippet}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}

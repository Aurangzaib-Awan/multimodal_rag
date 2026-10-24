"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { ChartLine, Image as ImageIcon, Maximize2, ScanEye } from "lucide-react";
import type { Visual } from "@/lib/api";

/** Vector diagrams are cropped out of the page by our own detection; say so, it is the multimodal part. */
export const figureLabel = (v: Pick<Visual, "type" | "page_number">) =>
  v.type === "figure" ? `Vector diagram · cropped from page ${v.page_number}` : `Image · page ${v.page_number}`;

const src = (v: Visual) => `data:image/jpeg;base64,${v.image_base64}`;

/** The pictures an answer used: the first one large, the rest as thumbnails that swap into the large slot. */
export default function FigureShowcase({ visuals, onOpen }: { visuals: Visual[]; onOpen: (v: Visual) => void }) {
  const [index, setIndex] = useState(0);
  const v = visuals[Math.min(index, visuals.length - 1)];
  const Icon = v.type === "figure" ? ChartLine : ImageIcon;

  return (
    <figure className="overflow-hidden rounded-2xl bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.06),0_8px_24px_-12px_rgba(0,0,0,0.25)]">
      <button
        type="button"
        onClick={() => onOpen(v)}
        aria-label={`Open ${figureLabel(v)} full size`}
        className="group relative block w-full bg-white"
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- base64 from the API */}
        <img src={src(v)} alt={figureLabel(v)} className="mx-auto max-h-[440px] w-auto max-w-full object-contain p-4" />
        <span className="absolute right-3 top-3 inline-flex items-center gap-1.5 rounded-lg bg-black/65 px-2.5 py-1.5 text-xs font-medium text-white opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100">
          <Maximize2 className="size-3.5" aria-hidden /> Full size
        </span>
      </button>

      <figcaption className="flex flex-col gap-3 border-t border-line px-4 py-3">
        <span className="flex items-center gap-2 text-xs font-medium text-ink-2">
          <Icon className="size-3.5" aria-hidden /> {figureLabel(v)}
        </span>

        {visuals.length > 1 && (
          <ul className="flex flex-wrap gap-2" aria-label="Other pictures used for this answer">
            {visuals.map((t, i) => (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => setIndex(i)}
                  aria-pressed={i === index}
                  aria-label={`Show ${figureLabel(t)}`}
                  className={`block overflow-hidden rounded-lg bg-white transition-shadow duration-150 ${
                    i === index ? "ring-2 ring-[var(--focus)]" : "ring-1 ring-line hover:ring-ink-3"
                  }`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- base64 from the API */}
                  <img src={src(t)} alt="" className="h-14 w-20 object-contain p-1" />
                </button>
              </li>
            ))}
          </ul>
        )}

        <details className="group/seen">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-[0.8125rem] font-medium text-ink-2 hover:text-ink">
            <ScanEye className="size-4" aria-hidden /> What the vision model saw
          </summary>
          <div className="prose-answer mt-2 max-h-72 overflow-y-auto text-[0.8125rem] text-ink-2">
            <ReactMarkdown>{v.caption}</ReactMarkdown>
          </div>
        </details>
      </figcaption>
    </figure>
  );
}

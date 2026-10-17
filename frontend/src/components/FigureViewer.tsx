"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import type { Visual } from "@/lib/api";

export default function FigureViewer({ visual, onClose }: { visual: Visual | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (visual && !d.open) d.showModal();
    if (!visual && d.open) d.close();
  }, [visual]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      aria-labelledby="figure-title"
      className="m-auto w-[min(1100px,calc(100vw-2rem))] max-h-[calc(100dvh-2rem)] rounded-2xl bg-surface p-0 text-ink shadow-[0_24px_64px_-12px_rgba(0,0,0,0.45)]"
    >
      {visual && (
        <div className="grid max-h-[calc(100dvh-2rem)] grid-rows-[auto_1fr] md:grid-cols-[1fr_340px] md:grid-rows-1">
          <div className="flex min-h-0 items-center justify-center bg-[#0c110e] p-4">
            {/* eslint-disable-next-line @next/next/no-img-element -- base64 from the API, nothing to optimize */}
            <img
              src={`data:image/jpeg;base64,${visual.image_base64}`}
              alt={`${visual.type === "figure" ? "Figure" : "Image"} from page ${visual.page_number}`}
              className="max-h-[60dvh] md:max-h-[calc(100dvh-4rem)] w-auto max-w-full object-contain"
            />
          </div>
          <div className="flex min-h-0 flex-col">
            <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
              <h2 id="figure-title" className="text-sm font-semibold">
                {visual.type === "figure" ? "Figure" : "Image"} · page <span className="tabular">{visual.page_number}</span>
              </h2>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="-mr-2 rounded-lg p-1.5 text-ink-2 hover:bg-ground hover:text-ink transition-colors duration-150"
              >
                <X className="size-4" />
              </button>
            </div>
            <div className="overflow-y-auto px-5 py-4">
              <p className="text-xs font-medium text-ink-3">What the vision model read from it</p>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-ink-2">{visual.caption}</p>
            </div>
          </div>
        </div>
      )}
    </dialog>
  );
}

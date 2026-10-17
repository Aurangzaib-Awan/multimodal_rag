"use client";

interface Props {
  total: number;
  done: number;
  cited: Set<number>;
  active: number | null;
  onPick?: (page: number) => void;
}

/** One cell per page. Fills while the document is parsed; cited pages light up in highlighter. */
export default function PageMap({ total, done, cited, active, onPick }: Props) {
  if (!total) return null;
  const cols = Math.min(total, 40);
  const tall = total <= 40;
  return (
    <div
      role="group"
      aria-label={`Page map, ${done} of ${total} pages indexed`}
      className="grid gap-[2px]"
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {Array.from({ length: total }, (_, i) => {
        const page = i + 1;
        const state = page === active ? "active" : cited.has(page) ? "cited" : i < done ? "done" : "pending";
        const cls = {
          pending: "bg-rail-ink/12",
          done: "bg-rail-ink/45 hover:bg-rail-ink/80",
          cited: "bg-hl/80 hover:bg-hl",
          active: "bg-hl ring-2 ring-hl ring-offset-1 ring-offset-rail",
        }[state];
        return (
          <button
            key={page}
            type="button"
            title={`Page ${page}`}
            aria-label={`Ask about page ${page}`}
            disabled={!onPick || i >= done}
            onClick={() => onPick?.(page)}
            className={`${tall ? "h-6" : "h-[7px]"} rounded-[2px] transition-colors duration-200 disabled:cursor-default ${cls}`}
          />
        );
      })}
    </div>
  );
}

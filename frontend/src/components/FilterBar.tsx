import { SlidersHorizontal, X } from "lucide-react";
import type { FacetValue } from "../types";

const LABELS: Record<string, string> = {
  company: "Company",
  research_source: "Source",
  report_kind: "Report",
  doc_type: "Type",
  research_area: "Area",
  year: "Year",
  quarter: "Quarter",
};

/**
 * Dynamic, ACL-aware data filters. Values come from VAIS metadata (availableFilters,
 * computed over the user's trimmed results), so chips only show what the user can see.
 */
export function FilterBar({
  available,
  selected,
  onToggle,
  onClear,
}: {
  available: Record<string, FacetValue[]>;
  selected: Record<string, string[]>;
  onToggle: (field: string, value: string) => void;
  onClear: () => void;
}) {
  // A field stays visible while it has ACTIVE selections even if the current result
  // set has no values for it (e.g. a filter combo that matches nothing) — otherwise the
  // card would unmount and the user would have no way to unselect the filter.
  const fields = Object.keys(LABELS).filter(
    (f) => (available[f]?.length ?? 0) > 0 || (selected[f]?.length ?? 0) > 0
  );
  const activeCount = Object.values(selected).reduce((n, v) => n + v.length, 0);
  if (!fields.length) return null;

  return (
    <div className="rounded-2xl border border-amgen-line bg-white p-3 shadow-card">
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-amgen-muted">
        <SlidersHorizontal size={14} /> Filters
        {activeCount > 0 && (
          <button
            onClick={onClear}
            className="ml-auto inline-flex items-center gap-1 rounded-full bg-amgen-surface px-2 py-0.5 text-[11px] font-medium normal-case text-amgen-blue"
          >
            Clear {activeCount} <X size={12} />
          </button>
        )}
      </div>
      <div className="flex flex-col gap-2">
        {fields.map((field) => (
          <div key={field} className="flex flex-wrap items-center gap-1.5">
            <span className="w-16 shrink-0 text-[11px] font-medium text-amgen-muted">
              {LABELS[field]}
            </span>
            {[
              ...(available[field] ?? []),
              // selected values missing from the current facet set still render (no
              // count) so they can always be toggled off
              ...(selected[field] ?? [])
                .filter((v) => !(available[field] ?? []).some((a) => a.value === v))
                .map((v) => ({ value: v, count: undefined as number | undefined })),
            ].map(({ value, count }) => {
              const on = selected[field]?.includes(value);
              return (
                <button
                  key={value}
                  onClick={() => onToggle(field, value)}
                  className={`rounded-full border px-2.5 py-1 text-xs transition ${
                    on
                      ? "border-amgen-blue bg-amgen-blue text-white"
                      : "border-amgen-line bg-white text-amgen-ink hover:border-amgen-blue"
                  }`}
                >
                  {value}
                  {count != null && (
                    <span className={on ? "text-white/70" : "text-amgen-muted"}> {count}</span>
                  )}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

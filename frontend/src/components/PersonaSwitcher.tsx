import { useState } from "react";
import { ChevronDown, UserRound, Check } from "lucide-react";
import type { Persona } from "../types";

/** User avatar + dropdown that switches the demo persona (drives X-Demo-User). */
export function PersonaSwitcher({
  personas,
  current,
  onChange,
  onLight = false,
}: {
  personas: Persona[];
  current?: Persona;
  onChange: (p: Persona) => void;
  onLight?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const btn = onLight
    ? "bg-amgen-blue text-white"
    : "bg-white/15 text-white hover:bg-white/25";
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition ${btn}`}
      >
        <span className="grid h-6 w-6 place-items-center rounded-full bg-white/25">
          <UserRound size={15} />
        </span>
        <span className="hidden sm:block max-w-[9rem] truncate">
          {current?.display_name ?? "Sign in"}
        </span>
        <ChevronDown size={15} />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-2 w-72 overflow-hidden rounded-2xl border border-amgen-line bg-white shadow-pill">
            <div className="px-4 py-2 text-xs font-semibold uppercase tracking-wide text-amgen-muted">
              Demo persona
            </div>
            {personas.map((p) => {
              const active = p.email === current?.email;
              return (
                <button
                  key={p.email}
                  onClick={() => {
                    onChange(p);
                    setOpen(false);
                  }}
                  className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-amgen-surface"
                >
                  <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-amgen-blue/10 text-amgen-blue">
                    <UserRound size={16} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1 text-sm font-semibold text-amgen-ink">
                      {p.display_name}
                      {active && <Check size={14} className="text-amgen-green" />}
                    </span>
                    <span className="block truncate text-xs text-amgen-muted">{p.email}</span>
                    <span className="mt-1 flex flex-wrap gap-1">
                      {p.groups.map((g) => (
                        <span
                          key={g}
                          className="rounded-full bg-amgen-teal/10 px-2 py-0.5 text-[10px] font-medium text-amgen-teal"
                        >
                          {g}
                        </span>
                      ))}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

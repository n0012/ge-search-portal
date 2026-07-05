import { useState } from "react";
import { Search, X, Sparkles } from "lucide-react";
import { Wordmark } from "./Logo";
import { PersonaSwitcher } from "./PersonaSwitcher";
import { useSuggestions } from "../useSuggestions";
import type { Persona } from "../types";

/** Compact on/off switch for auto-generating the AI answer on each search. */
function AiToggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={onToggle}
      title={on ? "AI answer on — generated for each search" : "AI answer off — search is faster; generate on demand"}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-xs font-medium transition ${
        on ? "border-amgen-blue/40 bg-amgen-blue/[0.06] text-amgen-blue" : "border-amgen-line text-amgen-muted hover:border-amgen-blue/40"
      }`}
    >
      <Sparkles size={13} />
      <span className="hidden sm:inline">AI answer</span>
      <span className={`relative h-4 w-7 rounded-full transition ${on ? "bg-amgen-blue" : "bg-amgen-line"}`}>
        <span className={`absolute top-0.5 h-3 w-3 rounded-full bg-white shadow transition-all ${on ? "left-3.5" : "left-0.5"}`} />
      </span>
    </button>
  );
}

/** Results-view top bar: wordmark + embedded search pill + persona switcher. */
export function Header({
  query,
  onSearch,
  personas,
  current,
  onPersona,
  onHome,
  onHow,
  aiOn,
  onToggleAi,
}: {
  query: string;
  onSearch: (q: string) => void;
  personas: Persona[];
  current?: Persona;
  onPersona: (p: Persona) => void;
  onHome?: () => void;
  onHow?: () => void;
  aiOn: boolean;
  onToggleAi: () => void;
}) {
  const [q, setQ] = useState(query);
  const { suggestions, onQueryChange } = useSuggestions(current?.email);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (q.trim()) onSearch(q.trim());
  };
  return (
    <header className="sticky top-0 z-30 border-b border-amgen-line bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
        <Wordmark onLight onHome={onHome} />
        <form onSubmit={submit} className="mx-auto flex max-w-2xl flex-1 items-center gap-2 rounded-full border border-amgen-line bg-white px-4 py-2 shadow-sm focus-within:border-amgen-blue">
          <input
            value={q}
            onChange={(e) => { setQ(e.target.value); onQueryChange(e.target.value); }}
            list="ge-suggest-header"
            autoComplete="off"
            className="flex-1 bg-transparent text-sm text-amgen-ink outline-none placeholder:text-amgen-muted"
            placeholder="Search…"
          />
          <datalist id="ge-suggest-header">
            {suggestions.map((s) => <option key={s} value={s} />)}
          </datalist>
          {q && (
            <button type="button" onClick={() => setQ("")} className="text-amgen-muted hover:text-amgen-ink">
              <X size={16} />
            </button>
          )}
          <span className="h-5 w-px bg-amgen-line" />
          <button type="submit" className="text-amgen-blue">
            <Search size={18} />
          </button>
        </form>
        <AiToggle on={aiOn} onToggle={onToggleAi} />
        <button onClick={onHow} className="hidden whitespace-nowrap text-xs font-medium text-amgen-muted hover:text-amgen-blue lg:block">
          How it works
        </button>
        <PersonaSwitcher personas={personas} current={current} onChange={onPersona} onLight />
      </div>
    </header>
  );
}

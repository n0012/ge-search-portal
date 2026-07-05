import { useState } from "react";
import { Search, ChevronDown } from "lucide-react";
import { Wordmark } from "./Logo";
import { HexEmblem } from "./HexEmblem";
import { SideDock } from "./SideDock";
import { PersonaSwitcher } from "./PersonaSwitcher";
import { useSuggestions } from "../useSuggestions";
import type { Persona } from "../types";

const SUGGESTIONS = [
  "What was Q4 operating income?",
  "How does AlphaFold predict protein structure?",
  "Amgen pipeline highlights",
  "clinical reasoning with LLMs",
];

export function HeroLanding({
  personas,
  current,
  onPersona,
  onSearch,
  onHome,
  onHow,
}: {
  personas: Persona[];
  current?: Persona;
  onPersona: (p: Persona) => void;
  onSearch: (q: string) => void;
  onHome?: () => void;
  onHow?: () => void;
}) {
  const [q, setQ] = useState("");
  const { suggestions, onQueryChange } = useSuggestions(current?.email);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (q.trim()) onSearch(q.trim());
  };
  return (
    <div className="relative min-h-screen overflow-hidden bg-white">
      {/* soft brand mesh background */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -left-32 -top-32 h-96 w-96 rounded-full bg-amgen-blue/10 blur-3xl" />
        <div className="absolute -right-24 top-40 h-96 w-96 rounded-full bg-amgen-teal/10 blur-3xl" />
        <div className="absolute bottom-0 left-1/3 h-80 w-80 rounded-full bg-amgen-green/10 blur-3xl" />
      </div>

      {/* top bar */}
      <header className="relative z-10 flex items-center justify-between px-6 py-5">
        <Wordmark onLight onHome={onHome} />
        <div className="flex items-center gap-3">
          <button
            onClick={onHow}
            className="hidden text-sm font-medium text-amgen-muted hover:text-amgen-blue md:block"
          >
            How it works
          </button>
          <PersonaSwitcher personas={personas} current={current} onChange={onPersona} onLight />
        </div>
      </header>

      <SideDock />

      {/* hero */}
      <main className="relative z-10 mx-auto flex max-w-3xl flex-col items-center px-6 pt-16 text-center md:pt-24">
        <HexEmblem />
        <h1 className="mt-5 text-4xl font-extrabold tracking-tight text-amgen-blue md:text-5xl">
          Find, Explore and Discover
        </h1>
        <p className="mt-3 text-amgen-muted">
          Secure, AI-assisted search across your enterprise content.
        </p>

        <form onSubmit={submit} className="mt-8 w-full">
          <div className="flex items-center gap-2 rounded-full border border-amgen-line bg-white px-5 py-3 shadow-hero focus-within:border-amgen-blue">
            <Search size={20} className="text-amgen-blue" />
            <input
              autoFocus
              value={q}
              onChange={(e) => { setQ(e.target.value); onQueryChange(e.target.value); }}
              placeholder="Search across Amgen, Alphabet & research…"
              list="ge-suggest-hero"
              autoComplete="off"
              className="flex-1 bg-transparent text-[15px] outline-none placeholder:text-amgen-muted"
            />
            <datalist id="ge-suggest-hero">
              {suggestions.map((s) => <option key={s} value={s} />)}
            </datalist>
            <button
              type="submit"
              className="rounded-full bg-amgen-blue px-4 py-1.5 text-sm font-semibold text-white hover:bg-amgen-blueDark"
            >
              Search
            </button>
          </div>
        </form>

        <div className="mt-5 flex flex-wrap justify-center gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => onSearch(s)}
              className="rounded-full border border-amgen-line bg-white px-3 py-1.5 text-xs text-amgen-muted transition hover:border-amgen-blue hover:text-amgen-blue"
            >
              {s}
            </button>
          ))}
        </div>
      </main>

      <ChevronDown
        className="absolute bottom-6 left-1/2 z-10 -translate-x-1/2 animate-floaty text-amgen-blue"
        size={26}
      />
    </div>
  );
}

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Sparkles, Send, ChevronDown, ChevronUp, Loader2, Globe } from "lucide-react";

export interface Turn {
  q: string;
  a: string;
}

/** Reusable collapsible Q&A box. The parent supplies `ask` — grounded on one document
 *  (ResultCard) or on the whole result set (AnswerCard). Optional `summarize` quick-action
 *  and an opt-in Google Search toggle (adds public web context for research). */
export function AskPanel({
  ask,
  title,
  placeholder,
  summarize,
  allowWebSearch = true,
  defaultOpen = false,
  onTurnsChange,
}: {
  ask: (question: string, opts: { useSearch: boolean }) => Promise<string>;
  title: string;
  placeholder: string;
  summarize?: { label: string; prompt: string };
  allowWebSearch?: boolean;
  defaultOpen?: boolean;
  onTurnsChange?: (turns: Turn[]) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [web, setWeb] = useState(false);
  const [err, setErr] = useState("");

  // surface the transcript to the parent (so the card's "Copy as Markdown" captures Q&A)
  useEffect(() => {
    onTurnsChange?.(turns);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turns]);

  async function run(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setErr("");
    setInput("");
    try {
      const a = await ask(q, { useSearch: web });
      setTurns((t) => [...t, { q, a: a || "_No answer for the documents you can access._" }]);
    } catch (e: any) {
      setErr(e?.message || "Could not get an answer.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 border-t border-amgen-line pt-2">
      <button
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-amgen-blue hover:bg-amgen-blue/[0.06]"
      >
        <Sparkles size={13} /> {title}
        {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>

      {open && (
        <div className="mt-2 space-y-3">
          {turns.map((t, i) => (
            <div key={i} className="space-y-1">
              <div className="text-xs font-semibold text-amgen-ink">{t.q}</div>
              <div className="prose-answer max-w-none rounded-lg bg-amgen-blue/[0.04] p-2.5 text-sm">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{t.a}</ReactMarkdown>
              </div>
            </div>
          ))}

          {busy && (
            <div className="flex items-center gap-2 text-xs text-amgen-muted">
              <Loader2 size={13} className="animate-spin" />
              {web ? "Searching the web & reading the documents… (this takes a bit longer)" : "Reading the documents…"}
            </div>
          )}
          {err && <div className="text-xs text-red-600">{err}</div>}

          <div className="flex flex-wrap items-center gap-2">
            {summarize && (
              <button
                onClick={() => run(summarize.prompt)}
                disabled={busy}
                className="shrink-0 rounded-lg border border-amgen-line px-2.5 py-1.5 text-xs font-medium text-amgen-muted hover:border-amgen-blue/40 hover:text-amgen-blue disabled:opacity-50"
              >
                {summarize.label}
              </button>
            )}
            {allowWebSearch && (
              <button
                type="button"
                onClick={() => setWeb((w) => !w)}
                title="Augment the answer with Google Search (adds public web context)"
                className={`inline-flex shrink-0 items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition ${
                  web ? "border-amgen-blue bg-amgen-blue text-white" : "border-amgen-line text-amgen-muted hover:border-amgen-blue/40 hover:text-amgen-blue"
                }`}
              >
                <Globe size={12} /> Web
              </button>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                run(input);
              }}
              className="flex flex-1 items-center gap-1.5 rounded-lg border border-amgen-line bg-white px-2.5 py-1 focus-within:border-amgen-blue"
            >
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={placeholder}
                className="flex-1 bg-transparent text-sm text-amgen-ink outline-none placeholder:text-amgen-muted"
              />
              <button type="submit" disabled={busy || !input.trim()} className="text-amgen-blue disabled:opacity-40">
                <Send size={15} />
              </button>
            </form>
          </div>
          {allowWebSearch && web && !busy && (
            <p className="flex items-center gap-1 text-[11px] text-amgen-muted">
              <Globe size={11} /> Web search is on — answers pull in public web results and take
              longer (typically ~30–45s extra).
            </p>
          )}
        </div>
      )}
    </div>
  );
}

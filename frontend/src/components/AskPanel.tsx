import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Sparkles, Send, ChevronDown, ChevronUp, Loader2 } from "lucide-react";

export interface Turn {
  q: string;
  a: string;
}

/** Reusable collapsible Q&A box. The parent supplies `ask` — grounded on one document
 *  (ResultCard) or on the whole result set (AnswerCard) via the GE engine assistant. Optional
 *  `summarize` quick-action. */
export function AskPanel({
  ask,
  title,
  placeholder,
  summarize,
  defaultOpen = false,
  onTurnsChange,
}: {
  ask: (question: string) => Promise<string>;
  title: string;
  placeholder: string;
  summarize?: { label: string; prompt: string };
  defaultOpen?: boolean;
  onTurnsChange?: (turns: Turn[]) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
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
      const a = await ask(q);
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
              <Loader2 size={13} className="animate-spin" /> Reading the documents…
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
        </div>
      )}
    </div>
  );
}

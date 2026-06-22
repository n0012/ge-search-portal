import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Sparkles, ExternalLink, Copy, Check } from "lucide-react";
import { AskPanel, type Turn } from "./AskPanel";
import type { Citation } from "../types";

/** The full card — answer + sources + any follow-up Q&A — as portable Markdown. */
function toMarkdown(summary: string, citations: Citation[], qa: Turn[]): string {
  let md = `## AI answer\n\n${summary || "_No answer generated._"}\n`;
  if (citations.length) {
    md += "\n### Sources\n" +
      citations.map((c) => `${c.index}. [${c.title}](${c.sourceUrl || ""})`).join("\n") + "\n";
  }
  if (qa.length) {
    md += "\n### Follow-up Q&A\n" +
      qa.map((t) => `**Q:** ${t.q}\n\n**A:** ${t.a}`).join("\n\n") + "\n";
  }
  return md;
}

function CopyMarkdown({ summary, citations, qa }: { summary: string; citations: Citation[]; qa: Turn[] }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(toMarkdown(summary, citations, qa));
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch { /* clipboard blocked — ignore */ }
      }}
      className="inline-flex items-center gap-1 text-xs text-amgen-muted hover:text-amgen-blue hover:underline"
      title="Copy the answer, sources, and any follow-up Q&A as Markdown"
    >
      {done ? <Check size={12} /> : <Copy size={12} />} {done ? "Copied" : "Copy as Markdown"}
    </button>
  );
}

/** AI answer card. Opt-in: idle (with a Generate button) → loading skeleton →
 *  markdown answer + citations. The answer is fetched separately from search so
 *  results stay fast; this card only shows an answer when explicitly requested
 *  (AI toggle on, or the user clicks "Generate AI answer"). */
export function AnswerCard({
  loading,
  summary,
  citations,
  requested,
  onGenerate,
  onAsk,
}: {
  loading: boolean;
  summary: string;
  citations: Citation[];
  requested: boolean;
  onGenerate: () => void;
  onAsk?: (question: string, opts: { useSearch: boolean }) => Promise<string>;
}) {
  const idle = !loading && !requested && !summary;
  const [qa, setQa] = useState<Turn[]>([]);

  return (
    <div className="rounded-2xl border border-amgen-blue/20 bg-gradient-to-br from-amgen-blue/[0.04] to-white p-5 shadow-card">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-full bg-amgen-blue/10 text-amgen-blue">
            <Sparkles size={16} className={loading ? "animate-pulse" : ""} />
          </span>
          <span className="text-sm font-semibold text-amgen-blue">
            {loading ? "Generating AI answer…" : "AI answer"}
          </span>
        </div>
        {!loading && !idle && (
          <div className="flex items-center gap-3">
            {(summary || qa.length > 0) && <CopyMarkdown summary={summary} citations={citations} qa={qa} />}
            <button
              onClick={onGenerate}
              className="text-xs text-amgen-muted hover:text-amgen-blue hover:underline"
            >
              Regenerate
            </button>
          </div>
        )}
      </div>

      {idle ? (
        <div className="flex flex-col items-start gap-2.5">
          <p className="text-sm text-amgen-muted">
            Get a synthesized, cited answer over the documents you can access.
          </p>
          <button
            onClick={onGenerate}
            className="inline-flex items-center gap-1.5 rounded-lg bg-amgen-blue px-3 py-1.5 text-sm font-medium text-white transition hover:bg-amgen-blue/90"
          >
            <Sparkles size={14} /> Generate AI answer
          </button>
        </div>
      ) : loading ? (
        <div className="space-y-2.5">
          <div className="skeleton h-3 w-[85%]" />
          <div className="skeleton h-3 w-[45%]" />
          <div className="skeleton h-3 w-[65%]" />
        </div>
      ) : (
        <>
          <div className="prose-answer max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {summary || "_No answer generated for the documents you can access._"}
            </ReactMarkdown>
          </div>
          {citations.length > 0 && (
            <div className="mt-4 border-t border-amgen-line pt-3">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-amgen-muted">
                Sources
              </div>
              <ol className="space-y-1">
                {citations.map((c) => (
                  <li key={c.index} className="flex items-start gap-2 text-sm">
                    <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded bg-amgen-blue/10 text-[11px] font-semibold text-amgen-blue">
                      {c.index}
                    </span>
                    <a
                      href={c.sourceUrl || "#"}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-amgen-blue hover:underline"
                    >
                      <span className="line-clamp-1">{c.title}</span>
                      <ExternalLink size={12} className="shrink-0" />
                    </a>
                  </li>
                ))}
              </ol>
            </div>
          )}
          {onAsk && (
            <AskPanel
              ask={onAsk}
              title="Ask about these documents"
              placeholder="Ask a follow-up about these results…"
              onTurnsChange={setQa}
            />
          )}
        </>
      )}
    </div>
  );
}

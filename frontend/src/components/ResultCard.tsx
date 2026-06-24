import { useState } from "react";
import type { ReactNode } from "react";
import { ThumbsUp, ThumbsDown, Flag, ExternalLink, ChevronRight, FileText } from "lucide-react";
import { docUrl } from "../api";
import { DocQA } from "./DocQA";
import type { SearchResult } from "../types";

const ENTITIES: Record<string, string> = {
  "&#39;": "'", "&quot;": '"', "&amp;": "&", "&nbsp;": " ", "&lt;": "<",
  "&gt;": ">", "&#34;": '"', "&#38;": "&",
};

/** Render a VAIS snippet: decode HTML entities, show <b> matches as bold, drop other tags. */
function renderSnippet(s: string): ReactNode[] {
  const decoded = s.replace(/&#?\w+;/g, (m) => ENTITIES[m] ?? " ");
  const nodes: ReactNode[] = [];
  let bold = false;
  decoded.split(/(<b>|<\/b>)/i).forEach((part, i) => {
    if (/^<b>$/i.test(part)) { bold = true; return; }
    if (/^<\/b>$/i.test(part)) { bold = false; return; }
    const text = part.replace(/<[^>]+>/g, "");          // strip any other stray tags
    if (!text) return;
    nodes.push(bold
      ? <strong key={i} className="font-semibold text-amgen-ink">{text}</strong>
      : <span key={i}>{text}</span>);
  });
  return nodes;
}

/** A single document result (cf. the Amgen mockup card). */
export function ResultCard({
  doc,
  userEmail,
  aiOn,
  searchId,
  showScore,
  onVote,
}: {
  doc: SearchResult;
  userEmail?: string;
  aiOn?: boolean;
  searchId?: string;
  showScore?: boolean;
  onVote?: (doc: SearchResult, vote: "up" | "down") => void;
}) {
  const [vote, setVote] = useState<"up" | "down" | null>(null);
  const cast = (v: "up" | "down") => {
    setVote(v);
    onVote?.(doc, v);
  };
  // imported GCS copy (ACL-checked signed URL); shown alongside the web source.
  const imported = doc.gcsUri ? docUrl(doc.documentId, userEmail) : "";
  const titleHref = doc.sourceUrl || imported || "#";
  const crumbs = [
    doc.company,
    doc.research_source,
    doc.venue,
    doc.research_area,
    doc.report_kind,
    doc.publish_date || doc.year,
  ].filter(Boolean) as string[];

  return (
    <div className="rounded-2xl border border-amgen-line bg-white p-4 shadow-card transition hover:border-amgen-blue/40">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="rounded bg-amgen-surface px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amgen-muted">
          {doc.doc_type?.replace(/_/g, " ") || doc.department || "Document"}
        </span>
        {showScore && typeof doc.rerankScore === "number" && (
          <span
            className="rounded bg-amgen-blue/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amgen-blue"
            title="Semantic re-rank relevance (Ranking API · semantic-ranker-default). Shown in demo mode."
          >
            relevance {doc.rerankScore.toFixed(2)}
          </span>
        )}
        <nav className="flex min-w-0 items-center gap-1 text-[11px] text-amgen-muted">
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <ChevronRight size={10} />}
              <span className="truncate">{c}</span>
            </span>
          ))}
        </nav>
      </div>

      <div className="flex items-start justify-between gap-3">
        <a
          href={titleHref}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-[15px] font-semibold text-amgen-blue hover:underline"
        >
          {doc.title}
          <ExternalLink size={13} className="shrink-0" />
        </a>
        <div className="flex shrink-0 items-center gap-1 text-amgen-muted">
          <button
            onClick={() => cast("up")}
            className={`rounded p-1 hover:bg-amgen-surface ${vote === "up" ? "text-amgen-green" : "hover:text-amgen-green"}`}
            title="Helpful"
          >
            <ThumbsUp size={14} />
          </button>
          <button
            onClick={() => cast("down")}
            className={`rounded p-1 hover:bg-amgen-surface ${vote === "down" ? "text-red-500" : ""}`}
            title="Not helpful"
          >
            <ThumbsDown size={14} />
          </button>
          <button className="rounded p-1 hover:bg-amgen-surface hover:text-red-500" title="Flag">
            <Flag size={14} />
          </button>
        </div>
      </div>

      {doc.snippet && (
        <p className="mt-1.5 line-clamp-3 text-sm leading-relaxed text-slate-600">
          {renderSnippet(doc.snippet)}
        </p>
      )}

      {/* provenance: original web source (if any) + the exact copy imported into VAIS */}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        {doc.sourceUrl ? (
          <a href={doc.sourceUrl} target="_blank" rel="noreferrer"
             className="inline-flex items-center gap-1 text-amgen-blue hover:underline">
            <ExternalLink size={11} /> Web source
          </a>
        ) : (
          <span className="text-amgen-muted/70">No web link</span>
        )}
        {imported && (
          <a href={imported} target="_blank" rel="noreferrer"
             className="inline-flex items-center gap-1 text-amgen-blue hover:underline"
             title="Open the exact file imported into Vertex AI Search (signed link)">
            <FileText size={11} /> Imported copy
          </a>
        )}
      </div>

      {aiOn && (
        <DocQA documentId={doc.documentId} userEmail={userEmail} searchId={searchId} />
      )}
    </div>
  );
}

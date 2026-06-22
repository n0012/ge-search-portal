import { ArrowLeft } from "lucide-react";
import { Wordmark } from "./Logo";

const SECTIONS = [
  {
    src: "/diagrams/arch-search.svg",
    title: "Core search — ACL-safe, query-time",
    body: "Every query is trimmed to what the signed-in user may see. VAIS filters on an indexed acl_groups field (the user's live Firestore groups), facets cascade, and a page-level Firestore re-check is the safety net. The AI answer is opt-in and grounded only on the trimmed set.",
  },
  {
    src: "/diagrams/arch-ai.svg",
    title: "AI summarization & document Q&A",
    body: "AI is opt-in (search stays fast and LLM-free by default). Three surfaces share one ACL-safe path that grounds Gemini only on the user's trimmed documents: summarize the whole result set (with citations), ask free-form follow-ups across the results, or ask/summarize a single document. Per request you can pick the model (Flash by default, failing over to Pro on overflow), use high thinking on Q&A, turn on Google Search grounding for research, or let Gemini read the docs' PDF pages (multimodal). Every turn is logged.",
  },
  {
    src: "/diagrams/arch-ingest.svg",
    title: "Catalog & document-processing pipeline",
    body: "A Firestore catalog collection is the single on-ramp. An idempotent reconcile job (Cloud Scheduler) loads only the delta into VAIS — staging content to GCS, importing/deleting in the index, seeding the ACL graph, and writing a BigQuery ledger. On import, Vertex AI Search runs its layout parser (text, tables, headings; OCR for scanned PDFs), splits documents into structure-preserving ~500-token chunks, and builds a hybrid semantic + keyword index (with acl_groups filterable). The same job handles the initial bulk load and ongoing incremental updates.",
  },
  {
    src: "/diagrams/arch-aws-sync.svg",
    title: "Syncing with AWS DynamoDB",
    body: "The catalog is the contract boundary. A DynamoDB-Streams → Lambda bridge (or a GCP-side boto3 poller) writes catalog records in the same shape; the reconcile job only ever reads Firestore — so the search app and ingest never depend on AWS credentials.",
  },
  {
    src: "/diagrams/arch-logging.svg",
    title: "Logging, analytics & feedback",
    body: "Every interaction is logged server-side (best-effort, never blocking the request) to BigQuery — searches, AI turns (with the model used, web-search flag and latency), feedback votes, and ingestion events — all joinable by a per-search correlation id. That powers tracking and optimization: relevance and zero-result queries, AI attach rate, model mix and failover, latency/cost, and ingestion health. Per-result 👍/👎 feedback also feeds VAIS user events (learn-to-rank), so the ranking improves with use. Ready-to-run queries live in sql/analytics.sql.",
  },
];

/** "How it works" — the architecture diagrams, rendered from /public/diagrams/*.svg. */
export function HowItWorks({ onHome }: { onHome?: () => void }) {
  return (
    <div className="min-h-screen bg-white">
      <header className="sticky top-0 z-30 border-b border-amgen-line bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center gap-4 px-4 py-3">
          <Wordmark onLight onHome={onHome} />
          <button
            onClick={onHome}
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-amgen-line px-3 py-1.5 text-sm text-amgen-muted hover:border-amgen-blue hover:text-amgen-blue"
          >
            <ArrowLeft size={15} /> Back to search
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-8">
        <h1 className="text-2xl font-extrabold tracking-tight text-amgen-blue">How it works</h1>
        <p className="mt-2 max-w-3xl text-sm text-amgen-muted">
          A custom front-end over Gemini Enterprise / Vertex AI Search, with per-user security
          trimming via an external Firestore permission graph — and a DynamoDB-ready, incremental
          ingestion pipeline.
        </p>

        <div className="mt-8 space-y-10">
          {SECTIONS.map((s) => (
            <section key={s.src}>
              <h2 className="text-lg font-bold text-amgen-ink">{s.title}</h2>
              <p className="mt-1 max-w-3xl text-sm text-amgen-muted">{s.body}</p>
              <div className="mt-3 overflow-hidden rounded-2xl border border-amgen-line bg-white shadow-card">
                <img src={s.src} alt={s.title} className="w-full" />
              </div>
            </section>
          ))}
        </div>
      </main>
    </div>
  );
}

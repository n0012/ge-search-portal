import { askDoc } from "../api";
import { AskPanel } from "./AskPanel";

/** Per-result AI panel: summarize or ask questions grounded on THIS document only
 *  (with optional Google Search grounding). */
export function DocQA({
  documentId,
  userEmail,
  model,
  searchId,
}: {
  documentId: string;
  userEmail?: string;
  model?: string;
  searchId?: string;
}) {
  return (
    <AskPanel
      title="Ask AI about this document"
      placeholder="Ask a question about this document…"
      summarize={{ label: "Summarize", prompt: "Summarize this document's key points in a few concise bullets." }}
      ask={(q, opts) => askDoc(documentId, q, userEmail, { model, useSearch: opts.useSearch, searchId })}
    />
  );
}

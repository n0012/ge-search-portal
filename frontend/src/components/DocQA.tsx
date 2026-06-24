import { askDoc } from "../api";
import { AskPanel } from "./AskPanel";

/** Per-result AI panel: summarize or ask questions grounded on THIS document only, via the
 *  Gemini Enterprise engine assistant (covered by the GE subscription, ACL-scoped to the doc). */
export function DocQA({
  documentId,
  userEmail,
  searchId,
}: {
  documentId: string;
  userEmail?: string;
  searchId?: string;
}) {
  return (
    <AskPanel
      title="Ask AI about this document"
      placeholder="Ask a question about this document…"
      summarize={{ label: "Summarize", prompt: "Summarize this document's key points in a few concise bullets." }}
      ask={(q) => askDoc(documentId, q, userEmail, { searchId })}
    />
  );
}

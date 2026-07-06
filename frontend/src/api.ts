import type { AiOpts, AnswerMeta, AppConfig, AnswerResponse, SearchResponse } from "./types";

// A Q&A turn's answer + provenance (assistant, estimated tokens, latency) + the assistant
// session to thread into the next turn so follow-ups keep conversational context.
export interface AskResult {
  answer: string;
  meta?: AnswerMeta;
  sessionId?: string;
}

// The demo persona is passed as X-Demo-User; in prod IAP supplies the identity.
function headers(user?: string): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (user) h["X-Demo-User"] = user;
  return h;
}

export async function getConfig(): Promise<AppConfig> {
  const r = await fetch("/api/config");
  if (!r.ok) throw new Error("config failed");
  return r.json();
}

export async function search(
  query: string,
  facets: Record<string, string[]>,
  user?: string
): Promise<SearchResponse> {
  const r = await fetch("/api/search", {
    method: "POST",
    headers: headers(user),
    body: JSON.stringify({ query, facets }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || "search failed");
  return r.json();
}

// Search-as-you-type suggestions (GE completionConfig). Best-effort; returns [] on error.
// Suggestions are query hints only — the search they trigger is still ACL-filtered.
export async function complete(q: string, user?: string): Promise<string[]> {
  try {
    const r = await fetch(`/api/complete?q=${encodeURIComponent(q)}`, { headers: headers(user) });
    if (!r.ok) return [];
    return (await r.json())?.suggestions ?? [];
  } catch {
    return [];
  }
}

// Deferred facet cascade: /api/search returns results immediately; this fetches the
// own-excluded recount for the ACTIVELY-filtered fields, which the UI merges into
// availableFilters (a field mapped to [] means: drop that chip group).
export async function fetchFacetPatch(
  query: string,
  facets: Record<string, string[]>,
  user?: string
): Promise<SearchResponse["availableFilters"]> {
  const r = await fetch("/api/facets", {
    method: "POST",
    headers: headers(user),
    body: JSON.stringify({ query, facets }),
  });
  if (!r.ok) throw new Error("facets failed");
  return (await r.json())?.availableFilters ?? {};
}

// Opt-in AI answer over the same ACL-trimmed set (re-derived server-side).
export async function generateAnswer(
  query: string,
  facets: Record<string, string[]>,
  user?: string,
  opts: AiOpts = {}
): Promise<AnswerResponse> {
  const r = await fetch("/api/answer", {
    method: "POST",
    headers: headers(user),
    body: JSON.stringify({ query, facets, ...opts }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || "answer failed");
  return r.json();
}

// Q&A / summarize grounded on ONE specific document (ACL-checked server-side).
export async function askDoc(
  documentId: string,
  question: string,
  user?: string,
  opts: AiOpts = {}
): Promise<AskResult> {
  const r = await fetch("/api/doc/qa", {
    method: "POST",
    headers: headers(user),
    body: JSON.stringify({ documentId, question, ...opts }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || "ask failed");
  const d = await r.json();
  return { answer: d?.answer ?? "", meta: d?.meta, sessionId: d?.sessionId };
}

// Q&A grounded on the WHOLE current result set (same ACL-trimmed docs as the search).
export async function askDocs(
  query: string,
  facets: Record<string, string[]>,
  question: string,
  user?: string,
  opts: AiOpts = {}
): Promise<AskResult> {
  const r = await fetch("/api/ask", {
    method: "POST",
    headers: headers(user),
    body: JSON.stringify({ query, facets, question, ...opts }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || "ask failed");
  const d = await r.json();
  return { answer: d?.answer ?? "", meta: d?.meta, sessionId: d?.sessionId };
}

// Link to the imported GCS copy (server 302s to a short-lived signed URL after an
// ACL check). In demo mode we pass the persona as ?u= since a navigation can't set
// the X-Demo-User header; prod ignores it (IAP supplies identity).
export function docUrl(documentId: string, user?: string): string {
  const u = user ? `?u=${encodeURIComponent(user)}` : "";
  return `/api/doc/${encodeURIComponent(documentId)}${u}`;
}

export function sendFeedback(
  query: string,
  documentId: string,
  title: string,
  vote: "up" | "down",
  user?: string,
  searchId?: string
): void {
  // fire-and-forget; logged to BigQuery server-side
  fetch("/api/feedback", {
    method: "POST",
    headers: headers(user),
    body: JSON.stringify({ query, documentId, title, vote, searchId }),
  }).catch(() => {});
}

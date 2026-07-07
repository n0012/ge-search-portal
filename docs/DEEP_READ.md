# Deep read — on-demand multimodal document Q&A (design + prerequisite)

**Status: designed, NOT implemented — blocked on a Gemini Enterprise Assistant
allowlist (see Prerequisite). Do not build against it until an eligible engine exists to
verify end-to-end.**

## What it is
An opt-in "deep read" on per-document Q&A: instead of grounding only on the extractive
text passages already in the index, the assistant does an **on-demand multimodal read of
the original file** (PDF pages, images, charts, complex tables) at question time.

## Why
The ingest **layout parser** captures text + OCRs images and extracts tables into chunks,
but it flattens complex/nested tables and does not *reason over* charts/figures. Roughly
**65% of the demo corpus is PDF** — exactly the content where a query-time multimodal pass
recovers meaning the import missed.

## Flow (per the streamAssist docs)
1. **Create a session** — `POST .../engines/{ENGINE}/sessions` → returns the session name.
2. **Upload the file** — `POST .../v1alpha/{session}:addContextFile` with
   `{fileName, mimeType, fileContents}` (`fileContents` = base64 ASCII). Returns
   `{session, fileId, tokenCount}`. Source bytes come from the imported GCS copy
   (`gcsdoc`/`content.uri`).
3. **Ask** — `POST .../assistants/{ASSISTANT}:streamAssist` with
   `{session, fileIds:[fileId], query:{text}}`. The assistant reads the file multimodally
   and answers, grounded on it.

## Cost model (the important part)
- The "Talk to Content" flow is **covered by the per-seat subscription** — it consumes the
  **pooled daily Assistant Query quota** (~160/day Standard, ~200/day Plus; Frontline has
  its own), **not** separate pay-as-you-go Vertex AI per-token billing.
- Each deep read = **one assistant query** against that daily pool. So it's *included*, but
  **bounded by the daily query limit** — plan adoption accordingly (not unlimited).

## Limits
- `addContextFile` inline upload: **50 MB** max. Files >50 MB use `UploadSessionFile`
  (up to 200 MB).
- Declare `mimeType` (`application/pdf`, `image/*`, `text/plain`).
- `fileContents` must be base64-encoded ASCII.
- Feature is **Preview** (Pre-GA terms; "as is", limited support).

## Prerequisite / gating (why it doesn't work today)
`sessions.addContextFile` is a **Gemini Enterprise Assistant (Agentspace)** method,
restricted behind the internal **`ASSISTANT_USER`** visibility label (applied via Tenant
Manager). It is **not** available on a plain Vertex AI Search engine.

Verified 2026-07-07 on `losiern-ge-portal1` (a trial `SEARCH_TIER_ENTERPRISE` +
`SEARCH_ADD_ON_LLM` engine): `addContextFile` returns **404 "Method not found"** on every
combination tried — including the **exact host + version the public docs specify**
(`global-discoveryengine.googleapis.com` + `v1`). Axes exhausted:

| Axis | Tried | Result |
|---|---|---|
| Host | `discoveryengine.googleapis.com`, `global-discoveryengine.googleapis.com` | all 404 |
| Version | `v1`, `v1alpha`, `v1beta` | all 404 |
| Resource | `sessions:addContextFile`, `assistants:addContextFile` | all 404 |
| Session source | `sessions.create`, `streamAssist` auto-create | all 404 |
| Body | with / without the `name` field | all 404 |

Plain `streamAssist` (grounded answers over the indexed corpus) works on the same engine —
only the file-context upload is gated. **The [public docs'][streamassist-doc] own verbatim
snippets fail on this engine**, which confirms the gating empirically and independently of
the internal `ASSISTANT_USER` source: even following the public docs exactly, the method
does not exist for this project.

Note: the `ASSISTANT_USER` label / allowlist requirement is **not documented publicly** —
the [public streamAssist doc][streamassist-doc] only marks the feature "Preview". The
gating is known solely from (a) this empirical 404 and (b) internal buganizer references.
The practical test for any project is simply to call `addContextFile` and see whether it
404s.

[streamassist-doc]: https://docs.cloud.google.com/gemini/enterprise/docs/get-answers-from-streamassist

**To unlock:** commercial onboarding to Gemini Enterprise Assistant via the **Google Cloud
Account Team / Sales Rep** (Cloud Support cannot process the allowlist). This is an
environment/edition change, not a code change.

## Implementation plan (once an allowlisted Assistant engine is available)
- **Backend** (`discovery.py` / `main.py`): add a session-create + `addContextFile` helper
  (bytes from `gcsdoc`), extend the assist path to pass `fileIds`, and add a `deep` branch
  to `/api/doc/qa` behind a config flag (`DEEP_READ`, default **off**). Fall back to the
  existing extractive-passage grounding when unavailable.
- **Frontend** (`DocQA` / `AskPanel`): a "Deep read (reads tables & images)" toggle that
  sends `deep: true`; surface "deep read · 1 assistant query" in the answer meta.
- **Verify** end-to-end on the allowlisted engine before shipping (no building against a
  404).

## References
- StreamAssist + file upload: https://docs.cloud.google.com/gemini/enterprise/docs/get-answers-from-streamassist

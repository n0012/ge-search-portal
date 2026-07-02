# GE Search Portal — Implementation Plan

A **generic, simple** custom web front-end that lets a customer (Amgen) search a
**Gemini Enterprise / Vertex AI Search data store** and get back ranked document
results plus an AI-generated answer with citations — **security-trimmed at query time
to only the documents the requesting user is permitted to see**, using an external
permission store (mirroring Amgen's per-document ACL DB).

It is a deliberately stripped-down reimagining of Jesus Chavez's
[`science-search-portal`](https://github.com/jchavezar/vertex-ai-samples/tree/main/semiautonomous-agents/science-search-portal),
which enforces ACLs via a SharePoint **federated** connector + Microsoft Entra ID /
MSAL login + a **Workload Identity Federation (WIF) + STS token-exchange** workaround.
We replace that with a simpler, customer-accurate model: an **external permission DB +
an app-side security trimmer** (WIF kept as a documented secondary approach).

---

## 1. Decision: New build, not a fork

**Recommendation: new build** in `ge-search-portal/`, copying only a
few load-bearing patterns from the reference.

| Reference carries… | We need… | Verdict |
|---|---|---|
| SharePoint federated connector → **5 entity data stores**, prefix-stripping fan-out | **1** ordinary VAIS data store | Delete |
| MSAL/Entra login + `X-Entra-Id-Token` header | Lightweight identity (IAP header / demo persona switch) | Replace |
| **WIF / STS token exchange** for per-user ACLs | Primary: external permission DB + app-side trimmer. WIF/native kept as documented **secondary** approach (§4.3) | Demote, keep in docs |
| ADK **Agent Engine** layer | Backend calls Discovery Engine directly | Delete |
| Reference React UI (just an Amgen logo) | Specific **"Intelligent Search"** look from slides 4 & 5 | Rebuild |
| `streamAssist` payload + response/citation parsing | Same idea, simpler API surface | Reuse (adapt) |
| Single-container Cloud Run packaging | Easy Cloud Run install | Reuse (simplify) |

A fork would mean deleting more than we keep; the desired UI plus the external-ACL model
is a near-total rewrite anyway. Clean build; reference repo kept read-only for snippets.

---

## 2. What Amgen wants (look & feel — slides 4 & 5)

Branded **"Intelligent Search"** portal, two views. Design tokens:

```js
brand = {
  primary:      '#3B48CC',  // royal blue — header, hero text, links
  primaryHover: '#2D37A4',
  accent:       '#10B981',  // emerald — highlights, hexagon emblem, stat numbers
  notice:       '#B5E742',  // lime — service-notice banner
  surface:      '#F3F4F6',  // grey — source-tab container
  skeleton:     '#E0E7FF',  // shimmer tint for the "Processing query…" state
}
```

**Landing / hero view (slide 5):** white canvas; top-left stacked `Intelligent`/`Search`
wordmark in royal blue; centered green roadmap ticker; royal-blue user button top-right;
hero cluster with emerald hexagon search emblem over a faint skyline graphic; headline
**"Find, Explore and Discover"**; subtitle "Over `N` documents from `M` sources." (numbers
emerald-bold); large elevated pill search bar; flat vector illustrations flanking;
floating left vertical icon dock; bouncing scroll chevron.

**Results view (slide 4):** royal-blue top header with stacked wordmark + embedded pill
search bar + user avatar; full-width lime **service-notice banner**; source-filter row
over a grey pill **source selector**; `Top Search Results` + `Export`; **AI answer card**
(indigo border, gradient, animated spinner + "Processing query…" + shimmer → rendered
markdown + inline citations); **document result cards** (`DOCUMENT` badge, breadcrumb,
blue title link, thumbs-up/down + flag, snippet + "Read More…"); right-edge vertical
**"Feedback"** tab.

> The **persona switcher** (to demo trimming as different users) lives in the top-right
> user menu. Source pills, export, feedback are static affordances in v1; only single-
> data-store search + security trimming are wired live.

---

## 3. Architecture

```
Browser (React SPA)  ── identity: IAP header in prod / persona switch in demo ──┐
   │  POST /api/search  { query }   (+ X-Demo-User in demo)                      │
   ▼                                                                            │
FastAPI  (single Cloud Run container; serves SPA + API; ADC service identity)   │
   │ 1. resolve requesting user ───────────────────────────────────────────────┘
   │ 2. user → groups            ─────────────►  Permission DB (Firestore)
   │ 3. RETRIEVE (no summary yet) ────────────►  Discovery Engine :search (over-fetch top N)
   │ 4. TRIM docs by ACL          ◄───────────  batched ACL lookup (doc_id → allowed principals)
   │ 5. GENERATE answer over ONLY authorized docs  (ACL-safe — see §4)
   ▼
{ summary, citations[], results[] }   ← all scoped to the user's permitted set
```

**Confirmed Discovery Engine facts** (REST, verified vs docs):
- `…/dataStores/{DS}/servingConfigs/default_search:search` works **directly on a data
  store — no separate Engine/App** — returning documents **and** an AI summary via
  `contentSearchSpec.summarySpec`. Summary handling is governed by §4 to stay ACL-safe.
- `:streamAnswer` streams an answer over SSE (optional, M7).
- Auth to Discovery Engine: Cloud Run runtime SA needs **`roles/discoveryengine.viewer`**.

Docs: REST ref https://docs.cloud.google.com/gemini/enterprise/docs/reference/rest ·
search method https://cloud.google.com/generative-ai-app-builder/docs/reference/rest/v1/projects.locations.collections.dataStores.servingConfigs/search ·
get-answers https://cloud.google.com/gemini/enterprise/docs/get-answers-from-streamassist ·
IAM https://cloud.google.com/generative-ai-app-builder/docs/access-control#discovery-engine-roles

---

## 4. Security trimming (per-user document ACLs) — core of this build

We document **two** approaches and **build the first**.

- **Approach 1 — Manual external-DB filtering (PRIMARY / implemented).** Authorization
  lives in an **external permission store** (Amgen uses AWS DocumentDB; we replicate with
  Firestore). The app trims results and grounds the answer itself. Mirrors what Amgen
  does today; this is what the demo wires live.
- **Approach 2 — WIF + native built-in ACLs (SECONDARY / documented).** Google enforces
  document-level ACLs server-side via federated end-user identity. What the reference
  implements; kept in the docs as the production-grade alternative.

### 4.1 The correctness rule (applies to Approach 1)
The Discovery Engine `:search` summary is generated server-side over the **top retrieved
docs before any app-side trim**. Displaying it would **leak content from documents the
user cannot see.** So Approach 1 is strictly **retrieve → trim → *then* generate** — we
never surface a summary computed over untrimmed results. (Approach 2 is inherently safe.)

### 4.2 Approach 1 — Manual external-DB filtering (PRIMARY, what we build)

**Permission model (the external DB).** A normalized RBAC graph — **three** Firestore
collections (`document` / `document_group` / `group_user`):
```
documents       : { document_id, title, department }   # mirror of indexed docs (optional, for admin/debug)
document_groups : { document_id, group_id }            # which group(s) a doc belongs to  (M:N edges)
group_users     : { group_id, user_id }                # which users belong to a group    (M:N edges)
```
A user may see a document iff some group **G** has an edge in **both** `document_groups`
(document_id↔G) **and** `group_users` (G↔user). At query time: resolve the user's groups
from `group_users`, then keep a retrieved doc iff its `document_groups` set intersects
them. `document_id` is the join key to Discovery Engine results — set deterministically at
ingest (§5) so edges line up exactly with indexed docs.

**Store.** `PermissionStore` interface, **Firestore-only** impl — GCP-native managed
NoSQL, the analog to Amgen's AWS DocumentDB; fast batched `where document_id in [...]`
lookups. (No SQLite. A real **Mongo/DocumentDB adapter** is a documented future swap.)

**Query-time flow — retrieve → trim → generate:**
1. **Resolve identity.** Prod: IAP header `X-Goog-Authenticated-User-Email`. Demo:
   persona switcher sends `X-Demo-User` (e.g. `riley.research@example.com` vs `dana.finance@example.com`).
2. **user → groups** via `group_users` (cache per request).
3. **Retrieve-only** `:search`, `summarySpec` **disabled**, **over-fetch** (≈5× display) to survive trimming.
4. **Trim:** one **batched** `document_groups` lookup for all returned `document_id`s; keep docs whose groups intersect the user's.
5. **Generate ACL-safe answer** via the **Gemini Enterprise engine assistant** —
   `engines/{ENGINE_ID}/assistants/{ASSISTANT_ID}:streamAssist` with
   `toolsSpec.vertexAiSearchSpec.filter: 'acl_groups: ANY(<user groups>)'` (+ active facets).
   Managed query understanding + retrieval + grounded generation + citations, server-side; the
   acl_groups predicate — the same one the search trim uses — keeps the ACL trim. (The original
   design used `id: ANY(<allowed ids>)`, but live verification showed `id` is not filterable on
   a GE engine: `:search` rejects it and the assistant tool silently fails to ground.)
   The SSE stream is consumed and assembled server-side into `{summary, citations}`.
   **Billing:** because the call hits the **GE engine** (not the data store / a non-GE engine),
   it's covered by the per-seat GE subscription — the same reason `:search` (step 3) targets the
   GE engine's serving config. Direct Vertex Gemini calls (vision over PDF pages) and the
   standalone Ranking API are avoided because they bill separately, outside the subscription.
6. **Return** trimmed `results[]` + ACL-safe `summary`/`citations[]`.

**Variant — filter injection (index-baked labels).** If group labels are baked into doc
metadata at ingest (filterable `acl_groups`), a single `:search` with
`filter: 'acl_groups: ANY(<user groups>)'` + `summarySpec` does retrieve+trim+summary
server-side. Most scalable, but puts ACLs in the index (what Amgen avoids). Middle ground.

### 4.3 Approach 2 — WIF + native built-in ACLs (SECONDARY, documented)

Google enforces document-level ACLs **server-side** using the end user's federated
identity — no app-side trimming, summary inherently ACL-safe. What `science-search-portal`
does. **Architecture:** (1) user signs in to corporate IdP (Entra/MSAL) → browser JWT;
(2) backend exchanges JWT via **STS token-exchange** against a GCP **Workforce Identity
Pool/Provider** (WIF) → short-lived GCP token representing the end user; (3) backend calls
Discovery Engine with that end-user credential; (4) each doc carries **`acl_info`** reader
principals (populated at ingest by the connector, e.g. SharePoint ACL sync), and DE
filters retrieval + generation to the caller's authorized set.
**Pros:** Google-enforced, leak-safe, no over-fetch, reuses corporate IdP, scales.
**Cons:** heavy setup (WIF, IdP app reg, MSAL/STS, ACL-syncing connector); ACLs must live
in/sync to the index. This is the complexity Amgen is avoiding — hence Approach 1 primary.
**Switch to it when:** ACLs change too fast to mirror externally, a connector already syncs
ACLs into the index, or platform-enforced per-user audit is required.

### 4.4 Data filters vs. access control (two layers)
Distinct from the ACL trim, the UI offers **data filters** (facets) so users refine
*within* what they're allowed to see. Best-practice design:
- **Source of truth = VAIS metadata** (`structData`), never Firestore. Firestore holds
  only the access graph; the index holds descriptive facets (`company`, `report_kind`,
  `research_source`, `research_area`, `doc_type`, `year`, …).
- **Dynamic + ACL-aware + leak-safe.** Available filter values/counts are computed from
  the user's **ACL-trimmed** result set for the current query — so chips show what the
  user *could* filter to, and counts never reveal documents they can't see. (Discovery
  Engine's native `facetSpecs` are ACL-unaware → we tally facets app-side instead.)
- **Compose safely.** Access control (RBAC) is enforced and not user-controllable;
  facet filters can only *narrow* within the permitted set, never widen it.
- **Flow** (`/api/search`): broad query-scoped retrieve → ACL trim → tally facets from
  the trimmed set (`availableFilters`) → apply the user's selected filters (in-memory
  for the demo's small corpus; push to the server-side DE `filter` for large corpora,
  with a separate ACL-trimmed facet pass) → generate over the final set.

### 4.5 Caveats (Approach 1)
- **Recall vs trimming:** post-retrieval trimming can drop visible count below page size.
  Mitigate with over-fetch (×5) + iterative paging. Filter-injection (§4.2 variant) avoids it.
- **Latency:** one batched DB read + (5a/5b) one generate hop. Streaming hides the gen hop.
- **No existence leak:** trim silently — do **not** surface "N hidden by access" counts.

---

## 5. Demo corpus, ingestion & ACL seeding

Stand up a realistic VAIS data store from **public** docs, attach metadata, and seed
Firestore ACLs so the **same query returns different results per user**. Follows
GoogleCloudPlatform/generative-ai `search/vais-building-blocks/ingesting_unstructured_documents_with_metadata.ipynb`.

### 5.1 Two content domains → two group roles
| Domain | Sources (public) | dept | Group | Demo user |
|---|---|---|---|---|
| **Finance** | Alphabet earnings-release PDFs **+ Amgen annual reports & quarterly earnings** (investor relations) | `finance` | `finance` | **dana.finance@example.com** |
| **Research** | **DeepMind** + **Google Health** publications (crawled → PDFs) | `research` | `research` | **riley.research@example.com** |

Effect: "What was Q4 operating income?" / an Amgen pipeline question answers for
`dana.finance@` (finance) only; a DeepMind/clinical-ML question answers for `riley.research@`
(research) only — trimming is obvious. (Optional: an `all-employees` group + shared docs.)

**Finance fetch** — (a) **Alphabet**: reuse
`a reference earnings-PDF notebook`'s `get_earnings_pdfs()` off
the Q4 CDN (`s206.q4cdn.com/479360582/files/doc_financials/`). (b) **Amgen**: pull from
`investors.amgen.com/financials/annual-reports` (annual reports / 10-Ks) and
`/financials/quarterly-earnings` (press releases, 10-Q, transcripts). Amgen IR runs on the
same **Q4 Inc** platform — resolve its `*.q4cdn.com/<id>/files/doc_financials/` base and
iterate, falling back to scraping `.pdf` hrefs off the IR pages. Tag `company` +
`report_kind` in metadata (§5.2) so finance docs segment by company and annual-vs-quarterly.

**Research fetch — crawl pipeline** over two public publication indexes:
- **DeepMind** `https://deepmind.google/research/publications/` — static HTML, **250 pubs /
  9 pages** (`/research/publications/page/{1..9}/`); each row links to a detail page
  `/research/publications/{id}/`.
- **Google Health** `https://health.google/publications/` — HCLS-relevant for Amgen.

Pipeline per source: (1) crawl the paginated index → collect detail-page URLs; (2) fetch
each detail page → parse **title, authors, year, venue, research area, abstract** + the
outbound paper link; (3) resolve to a real **full-text PDF** — arXiv → `arxiv.org/pdf/{id}`
or a direct `.pdf`; **skip (and log) paywalled/abstract-only** (Nature / SSRN / DOI),
since the actual PDF is required to be useful; (4) save `corpus/research/{source}/{id}.pdf`
and emit metadata. Cap at a configurable `N` (e.g. 30–50) for the demo; polite rate-limit.

**Amgen R&D (and any org's journal papers) via PubMed Central.** `amgen.com/science` is
JS-rendered with no scrapable PDFs, so Amgen research comes from **PubMed Central** by
affiliation (`Amgen[Affiliation] AND open access[filter]` — ~2,700 OA papers). The
reliable PDF route is **`https://europepmc.org/articles/PMC<id>?pdf=render`** (verified;
NCBI's own PDF host gates the blob behind an anti-bot interstitial), falling back through
`citation_pdf_url` → NCBI OA pdf/tgz (cf. `arundasan91/pubmed_pdf_downloader`). This
fetcher is **generic over affiliation**, so Google DeepMind / Google Health / Google
Research journal papers can be pulled the same way (`gdm-pmc` / `health-pmc` /
`google-pmc`) — useful for journal work (e.g. Nature Medicine) not posted to arXiv.

**Expanding sources (future).** [`openags/paper-search-mcp`](https://github.com/openags/paper-search-mcp)
implements the same OA-first fallback chain across 20+ sources (arXiv, bioRxiv, medRxiv,
PMC, Europe PMC, CORE, Zenodo, Unpaywall, …). If the arXiv + Europe PMC routes don't give
enough coverage for GDM/Health/preprints, that's the natural place to expand ingestion
(notably **Unpaywall DOI resolution** and **bioRxiv/medRxiv** preprints).

**Status: proven.** All research routes download real PDFs with rich metadata
(`title`, `publish_date`, `research_area`/theme, `venue`/journal, `authors`, `source_url`).
Finance (Alphabet/Amgen IR) PDF scraping is best-effort and not yet verified (JS pages).

### 5.2 Stage to GCS, metadata schema & ingestion
**Stage first.** Download every PDF, then `gsutil rsync` into
`gs://$BUCKET/corpus/<department>/<company-or-source>/…`. Staging in GCS (a) gives VAIS a
stable `content.uri`, and (b) gives us a **durable link back to the original file** from
both the file store and the search-result cards — alongside the original `source_url`.

**Unified metadata schema** (`structData`) segments the corpus along every axis you asked
for. One JSONL line per doc:
```json
{"id":"alphabet_2023_q4_earnings_release",
 "structData":{"title":"Alphabet 2023 Q4 Earnings Release","department":"finance",
   "company":"alphabet","doc_type":"earnings_release","report_kind":"quarterly",
   "year":"2023","quarter":"Q4","topic":["revenue","cloud"],
   "source_url":"https://abc.xyz/assets/.../2023Q4_alphabet_earnings_release.pdf"},
 "content":{"mimeType":"application/pdf","uri":"gs://$BUCKET/corpus/finance/alphabet/2023_q4_earnings_release.pdf"}}
{"id":"amgen_2023_annual_report",
 "structData":{"title":"Amgen 2023 Annual Report","department":"finance","company":"amgen",
   "doc_type":"annual_report","report_kind":"annual","year":"2023",
   "topic":["pipeline","financials"],"source_url":"https://investors.amgen.com/..."},
 "content":{"mimeType":"application/pdf","uri":"gs://$BUCKET/corpus/finance/amgen/2023_annual_report.pdf"}}
{"id":"deepmind_alphafold_2021",
 "structData":{"title":"Highly accurate protein structure prediction (AlphaFold)",
   "department":"research","research_source":"deepmind","doc_type":"research_paper",
   "research_area":"structural biology","year":"2021","venue":"Nature",
   "topic":["protein-folding","genomics"],"source_url":"https://www.nature.com/articles/s41586-021-03819-2"},
 "content":{"mimeType":"application/pdf","uri":"gs://$BUCKET/corpus/research/deepmind/alphafold_2021.pdf"}}
```
**Segmentation facets** — set **indexable + retrievable + dynamicFacetable** so they power
the slide-4 source selector + Filter(s) and can scope a query:
`company` (alphabet · amgen) · `report_kind` (annual · quarterly) · `department`
(finance · research) · `research_source` (deepmind · google-health · amgen) ·
`research_area` (Google Health themes / arXiv area) · `doc_type` · `publish_date` ·
`year`/`quarter` · `venue` (journal) · `topic`.

We control `id` (deterministic) → the **join key** to Firestore `document_groups`.
**ACLs stay external** (Approach 1); `structData` is descriptive/facet metadata only.
Both `source_url` and the GCS `content.uri` ride along so result cards **link back to the
original source and the stored copy**. Data store created `CONTENT_REQUIRED` + layout
chunking; import via `documents:import` `gcsSource` (REST, per the notebook).
*(Optionally also add `structData.acl_groups` to demo the filter-injection variant §4.2.)*

### 5.3 Demo users & permissions (files)
`seed/personas.yaml` — drives the persona switcher + `group_users` edges:
```yaml
users:
  - email: dana.finance@example.com
    display_name: Dana Whitfield
    title: Finance
    groups: [finance]
  - email: riley.research@example.com
    display_name: Riley Chen
    title: Research
    groups: [research]
  # - email: intern@example.com   # optional minimal-access persona
  #   groups: [all-employees]
```
`seed/acl_rules.yaml` — map doc metadata → group(s) (creates `document_groups` edges):
```yaml
by_department:
  finance:  [finance]
  research: [research]
# overrides: { "2023_Q4_earnings_release": [finance, exec] }
```

### 5.4 Setup scripts (`scripts/`, one-shot `setup_demo.sh`)
1. `01_fetch_corpus.py`  — Alphabet earnings (q4cdn) **+ Amgen IR (annual + quarterly)** → `corpus/finance/{company}/`; **crawl DeepMind + Google Health** → `corpus/research/{source}/`
2. `02_make_metadata.py` — walk `corpus/**.pdf` → `metadata.jsonl` (id, rich structData, `source_url`, content.uri)
3. `03_stage_import.py`  — `gsutil rsync corpus/ → gs://$BUCKET/corpus/`; create data store (`CONTENT_REQUIRED`, layout chunking, **facet field config**) + `documents:import`
4. `04_seed_acls.py`     — `personas.yaml` + `acl_rules.yaml` → Firestore `documents` + `document_groups` + `group_users` (keyed by the SAME ids)

`setup_demo.sh` runs 1–4; rerunnable (INCREMENTAL import; idempotent Firestore writes).

---

## 5.5 Document processing in VAIS (parser / OCR / multimodal)

Configured in `terraform/vais.tf` via `document_processing_config`:
- **Layout parser** (`default_parsing_config.layout_parsing_config`) — a layout-understanding
  model that extracts structure: titles, headings, paragraphs, **tables**, lists; OCRs
  text in elements/scanned pages. Chosen because it's Google's recommended parser for
  RAG/grounding and handles the dense financial tables + paper structure in our corpus.
- **Layout-based chunking** (`chunking_config.layout_based_chunking_config`, `chunk_size=500`,
  `include_ancestor_headings=true`) — splits into semantically coherent chunks that carry
  their heading context.

Ingestion pipeline inside VAIS: **parse (layout) → chunk → embed (Google text embeddings)
→ hybrid semantic + keyword index**. Answers ground on retrieved chunks.

Parser options (swappable per data store / per file type): **digital** (text layer, no OCR),
**OCR** (scanned/image-only PDFs), **layout** (ours — structure + tables + OCR).

**Multimodal reality / limits:** the semantic index is built on extracted **text** (incl.
OCR'd text and table cells). Figures/charts are *not* deeply understood — only text/captions
OCR'd from them — and `ANSWER_MODE=gemini` grounds on text snippets, not page images.
Future options: per-file-type **OCR override** for scans; passing PDF **pages as images to
Gemini** at answer time for true chart/figure reasoning (not wired today).

## 5.6 Ingestion at scale + per-document logging

The ingestion runs in the **`ge-search-ingest` Cloud Run Job** (`scripts/ingest_entrypoint.sh`
→ `01 fetch → 02 manifest → 03 stage+import → 04 ACL seed`). It is **not** per-document
end-to-end: downloads are per-doc, but the VAIS **load is a single bulk `documents:import`**
(VAIS parallelizes server-side) and Firestore writes are batched.

**Scale-out via Cloud Run Job task parallelism** (`terraform`: `ingest_task_count`,
`ingest_parallelism`; default 1):
- Each task gets `CLOUD_RUN_TASK_INDEX` / `CLOUD_RUN_TASK_COUNT`. `01` collects each source's
  candidate id list cheaply, then `shard()` takes a **disjoint stride slice** (`items[i::n]`)
  — union covers everything once, no overlap.
- Each task fetches **only its slice**, stages it, and imports its **own** manifest
  (`metadata-<task>.jsonl`) — safe because `documents:import` is INCREMENTAL and Firestore
  writes are idempotent, so **no cross-task barrier** is needed. `--limit` is per-task, so
  total ≈ `limit × task_count`.
- Today the slow part is sequential downloads; task parallelism scales that linearly. (A
  finer in-task thread pool is a possible future tweak.)

**Per-document logging:** `01` emits one **structured JSON line per document** (`dlog`:
`{log:"ingest_doc", task, action:"fetched"|"skip", source, document_id, bytes, title,
publish_date, …}`) to stdout → **Cloud Logging** (queryable in Logs Explorer).

**Per-document ingestion ledger (BigQuery `ge_search_logs.ingestion_log`).** Rather than a
Cloud Run Job *per document* (an anti-pattern: per-doc `documents:import` is slow/quota-heavy
and per-doc tasks add container overhead), we keep the efficient **bulk import** and record
each document's lifecycle to a durable ledger via `scripts/ingestlog.py` (`ilog`, best-effort,
lazy BigQuery — no-op locally so `01` stays stdlib-only). Stages per doc:
`download` (01 ok/skipped_no_pdf) → `staged` (03, uploaded to GCS) → `import` (03 ok/failed/
submitted — 03 polls the import LRO and reads the `errorConfig` GCS error file to flag
per-doc failures) → `acl` (04 ok/no_groups). Schema: `event_time, task, source,
document_id, stage, status, bytes, error`. The ingest SA gets `bigquery.dataEditor`; the job
sets `BQ_LOGGING=on`/`BQ_DATASET`. This gives a queryable, per-document "what downloaded /
made it into VAIS+Firestore / failed" view without abandoning the scalable bulk path.

## 5.7 Multimodal understanding & summarization (charts/tables/figures)

The VAIS semantic index is text-based, so it doesn't *understand* figures. We get
chart/table understanding at **answer time** without a vector index:

**VAIS retrieves the doc(s) → Gemini reads their pages during summarization.** When
`MULTIMODAL_ANSWERS=on`, `generate.py` attaches the top `MULTIMODAL_MAX_DOCS` retrieved
docs' **PDFs (by GCS uri)** to the Gemini request, so the model reads the actual pages —
charts, tables, figures included — and grounds the summary on them. Model:
`MULTIMODAL_MODEL` (default **`gemini-3.5-flash`** — GA, 1M-token context, native PDF/image
input). Off by default to keep the demo cheap/text-only.

Why this (not embeddings) for the common case:
- Embeddings can't be *read* by the LLM — they're for retrieval. Understanding a chart
  needs the **image/PDF** as model input.
- VAIS already found the relevant doc via text, so we just hand Gemini that doc — no
  rendering pipeline, no chunk→page mapping, no extra index. Latency stays low by capping
  to the top 1–2 docs.

**Constraints:** docs passed are already **ACL-trimmed** (post-trim list), so no leak;
flag-gated; bounded by `MULTIMODAL_MAX_DOCS` (and Gemini's 1M context) for latency/cost.

**Edge case → optional VS2 (documented, not built):** if an answer lives **only** in a
chart with *no* surrounding text, VAIS text retrieval can't find that page. Then add a
**Vector Search 2.0 / Agent Retrieval Collection** as a second, real-time channel:
server-side auto embeddings (`multimodal-embedding-001` for page images,
`gemini-embedding-2-preview` for text), hybrid search + rerank, **metadata-keyed by
`document_id`** so results pass the same ACL trim. Preferred over BigQuery vector search
for **real-time** latency (BQ is batch/analytics-grade). Confirm VS2 GA/region before
production. This is the only case that needs an extra index.

## 6. Tech stack

- **Backend:** FastAPI + Uvicorn, Python 3.12, `uv`; ADC via `google-auth`. Retrieval via
  `google-cloud-discoveryengine` (`SearchServiceClient`); ACL-safe answer via DE filter
  re-query (5a) or `google-genai` Vertex Gemini (5b). Permission store via
  `google-cloud-firestore` (Firestore-only). The single FastAPI process **also serves the
  built React static files** (no nginx/supervisord).
- **Frontend:** React 19 + TypeScript + Vite + Tailwind; `react-markdown`+`remark-gfm`;
  `lucide-react`; `framer-motion`. Persona switcher in the user menu. No MSAL/auth libs.
- **Packaging:** one multi-stage Dockerfile (node build → python slim), port `8080`,
  `CMD uvicorn`. `deploy.sh` → Artifact Registry + `gcloud run deploy`.

## 7. Proposed file tree

```
ge-search-portal/
├── PLAN.md  README.md  .env.example  Dockerfile  deploy.sh
├── seed/
│   ├── personas.yaml          # demo users → groups (dana.finance=finance, riley=research)
│   └── acl_rules.yaml         # department → group(s)
├── scripts/
│   ├── setup_demo.sh          # runs 01→04
│   ├── 01_fetch_corpus.py     # Alphabet + Amgen IR + crawl DeepMind/Health → PDFs
│   ├── 02_make_metadata.py    # → metadata.jsonl (rich structData + source_url)
│   ├── 03_stage_import.py     # gsutil rsync → GCS; create data store (+facets) + documents:import
│   └── 04_seed_acls.py        # → Firestore documents / document_groups / group_users
├── corpus/                    # PDFs (gitignored): finance/{alphabet,amgen}/  research/{deepmind,google-health}/
├── backend/
│   ├── pyproject.toml
│   ├── main.py                # FastAPI: /api/search, /api/me, /api/config, /healthz, SPA mount
│   ├── config.py
│   ├── discovery.py           # DE retrieve() + acl_safe_answer() (filter re-query path)
│   ├── permissions.py         # PermissionStore (documents/document_groups/group_users) + Firestore; trim()
│   ├── identity.py            # resolve user from IAP header / X-Demo-User
│   # (answers come from the GE engine assistant :streamAssist — see discovery.assist)
└── frontend/
    ├── package.json vite.config.ts tailwind.config.js tsconfig.json index.html
    └── src/
        ├── main.tsx App.tsx theme.ts api.ts
        └── components/
            ├── Header.tsx  HeroLanding.tsx  ResultsView.tsx
            ├── AnswerCard.tsx  ResultCard.tsx  SourceFilterBar.tsx
            ├── NoticeBanner.tsx  SideDock.tsx  FeedbackTab.tsx
            └── PersonaSwitcher.tsx
```

## 8. Backend contract

```
GET  /healthz        → 200 "ok"
GET  /api/me         → { user, groups }
GET  /api/config     → { dataStoreDisplayName, sources[], personas[], docCount? }
POST /api/search     → body {query, pageSize?, facets?{company?,report_kind?,research_source?,year?}}, header X-Demo-User / IAP
                       resp {summary, citations:[{title,sourceUrl,snippet,index}],
                             results:[{documentId,title,sourceUrl,gcsUri,snippet,
                                       company,department,doc_type,report_kind,year,breadcrumb}]}
                       # sourceUrl → original doc; gcsUri → stored copy (backend signs/proxies)
GET  /api/search/stream?q=…   → SSE streaming answer (optional, M7; ACL-safe gen only)
```

## 9. Configuration (`.env`)

```
PROJECT_ID=...               PROJECT_NUMBER=...
LOCATION=global              # data store location: global | us | eu
DATA_STORE_ID=ge-search-demo # created by scripts/03; reused by the app
GCS_BUCKET=gs://...-ge-search-corpus
# security trimmer (Approach 1 — manual external-DB filtering)
PERMISSION_BACKEND=firestore # firestore (DocumentDB adapter = future)
FIRESTORE_DATABASE=(default)
IDENTITY_SOURCE=demo         # demo (X-Demo-User) | iap (X-Goog-Authenticated-User-Email)
ENGINE_ID=ge-search-app      # GE engine; all :search + :streamAssist hit it (subscription-covered)
ASSISTANT_ID=default_assistant
# no Entra/MSAL/WIF/OAuth secrets — removed (Approach 2 only)
```

## 10. Deploy (Cloud Run)

```bash
RUNTIME_SA=ge-search-portal@$PROJECT_ID.iam.gserviceaccount.com
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$RUNTIME_SA" --role="roles/discoveryengine.viewer"
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$RUNTIME_SA" --role="roles/datastore.user"
# plus discoveryengine.assistants.assist (custom role) to call the GE engine assistant

gcloud run deploy ge-search-portal --source . --region $REGION --service-account $RUNTIME_SA \
  --allow-unauthenticated --port 8080 --memory 1Gi \
  --set-env-vars PROJECT_ID=...,PROJECT_NUMBER=...,LOCATION=global,DATA_STORE_ID=ge-search-demo,\
ENGINE_ID=ge-search-app,ASSISTANT_ID=default_assistant,PERMISSION_BACKEND=firestore,IDENTITY_SOURCE=iap
```
For real per-user identity, front with **IAP** (drop `--allow-unauthenticated`) so
`X-Goog-Authenticated-User-Email` is trustworthy; the demo persona switch is showcase-only.

## 11. Milestones

- **M0 — Scaffold:** dirs, `.env.example`, pyproject, vite+tailwind, brand tokens, `/healthz`.
- **M1 — Demo corpus & data store:** `scripts/` 01→03 — fetch Alphabet **+ Amgen** financials
  and **crawl DeepMind + Google Health** publications, **stage all PDFs to GCS**, build
  `metadata.jsonl` (rich facets + `source_url`), create the VAIS data store (with facet field
  config) + import. Verify in the GE/VAIS console.
- **M2 — Retrieval headless:** `discovery.retrieve()` + `POST /api/search` (no trim yet);
  `curl` returns docs + summary from the new data store.
- **M3 — Permission store + trimmer (Approach 1):** `04_seed_acls.py` → Firestore
  (`documents`/`document_groups`/`group_users`); `permissions.py` + `identity.py`; wire
  **retrieve → trim → ACL-safe generate** (§4.2); prove `dana.finance@`(finance) vs
  `riley.research@`(research) get different results/answers via `curl`.
- **M4 — Results view (slide 4):** Header, AnswerCard, ResultCard, NoticeBanner,
  SourceFilterBar (static), PersonaSwitcher.
- **M5 — Landing view (slide 5):** HeroLanding, SideDock, hero search → Results.
- **M6 — Containerize + deploy:** Dockerfile, `deploy.sh`, live on Cloud Run.
- **M7 (optional) — Streaming + logging:** SSE answer for the live "Processing query…"
  shimmer; feedback thumbs + queries → BigQuery (ties into the deck's logging workstream).

## 12. Open questions for Amgen / David

1. Confirm the **GCP project + location (global/us/eu)** to create the demo data store in.
2. **Permission store shape (prod):** what does Amgen's DocumentDB record per document
   (user ids, AD groups, labels?), and the **join key** to a DE doc (id, metadata, URI)?
3. Firestore as the DocumentDB analog OK for the demo, or point at a real Mongo/DocumentDB?
4. **Answer gen:** make doc `id`/an `acl` field **filterable** (enables clean all-in-DE 5a),
   or default to the Gemini path (5b)?
5. **Identity in prod:** IAP in front (recommended) so `X-Goog-Authenticated-User-Email` is trusted?
6. Add an `all-employees` group + a couple shared docs, or keep finance/research fully disjoint for the demo?
7. Streaming answers (M7) needed for the first demo, or is one-shot fine?
```

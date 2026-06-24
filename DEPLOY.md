# Deploy the GE Search Portal (turnkey)

Stand up the full demo in one command. Self-contained: this directory has everything
(Terraform, app, ingest, diagrams) and uses only relative paths.

## Prerequisites
- A **GCP project** with **billing enabled** and you as **Owner** (or Editor + Project IAM Admin).
- Local tools: **`gcloud`**, **`terraform`** (≥1.5). (Node/Python are only needed for local dev —
  the deploy builds the image in Cloud Build, not on your machine.)
- Authenticate once:
  ```bash
  gcloud auth login
  gcloud auth application-default login
  gcloud auth application-default set-quota-project YOUR_PROJECT_ID
  ```

## 1. (optional) Choose who can open the site
By default `deploy-all.sh` grants IAP access to the **gcloud account you deploy with**, so you
can open it immediately. To open it to a team/domain, copy the template and edit:
```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# set: iap_members = ["domain:your-domain.com"]   (or a group / specific users)
```

## 2. Deploy (one command)
```bash
bash deploy-all.sh YOUR_PROJECT_ID            # region defaults to us-central1
```
This runs three steps (override with `--steps infra,build,data`):
- **infra** — `terraform apply`: enables APIs, creates the GCS bucket, Firestore (Native),
  the VAIS data store (layout parsing), service accounts + IAM, BigQuery tables, the Cloud Run
  **service (IAP on)** + the ingest & reconcile **jobs** + Cloud Scheduler.
- **build** — Cloud Build → container image → deploys the service and both jobs.
- **data** — runs the `ge-search-ingest` job: fetch corpus (SEC EDGAR · arXiv · PubMed Central)
  → GCS → import into VAIS → seed ACLs → declare/sync `acl_groups`. (Import is async; results
  populate a few minutes later.)

When it finishes it prints the IAP-gated **Service URL**. Open it as an authorized user.

## 3. Verify
```bash
bash scripts/postdeploy_check.sh YOUR_PROJECT_ID
```
Checks the service is serving, IAP is gating (302), retrieval relevance, per-persona security
trim (no cross-domain leak), and that there are no error logs.

## Making a clean zip to hand off
Zip only tracked files (no local `.env`, state, `node_modules`, downloaded corpus):
```bash
git archive --format=zip --prefix=ge-search-portal/ -o ge-search-portal.zip HEAD:ge-search-portal
```

## Customize for your org
**Personas & groups** (who's in the switcher and what each can see) are plain seed files:
- `seed/personas.yaml` — demo users → groups (drives the persona switcher).
- `seed/acl_rules.yaml` — maps document metadata (`department`) → group(s), with optional
  per-document overrides. Define your own groups here.

Apply changes:
- Full (docs + personas): re-run the data step — `bash deploy-all.sh YOUR_PROJECT --steps data`.
- **Personas/groups only (no re-ingest):** run `scripts/04_seed_acls.py` directly — it seeds
  `users`/`group_users` from `personas.yaml` even with no corpus manifest present.

In **demo** mode these drive the persona switcher; in **iap** mode each signed-in user
filters via their own `group_users` (so for real use you'd seed your actual users/groups here).

**Corpus size & sources** are tfvars: `ingest_limit` (default 75 docs/sub-source) and
`edgar_forms` (default `10-K,10-Q,8-K`). Raise/lower for a richer or lighter demo corpus.

## Known one-time / environment notes
- **IAP consent screen (brand):** enabling IAP on Cloud Run may require the project's OAuth
  consent screen to exist. If `terraform apply` reports a missing IAP brand, create it once in
  the console (APIs & Services → OAuth consent screen, Internal) and re-run `--steps infra`.
- **All traffic must hit the GE engine (billing).** Discovery Engine billing is determined by the
  **engine you query**: calls to a **Gemini Enterprise engine's** serving config are covered by the
  per-seat GE subscription; calls to the **data store directly** (or a non-GE VAIS engine) bill
  standalone (SKU `93D6-7280-CF05`). So the app routes **both** `:search` and the assistant
  (`:streamAssist`) at the GE engine. Terraform creates `google_discovery_engine_chat_engine.engine`
  (`engine_id`, default `ge-search-app`) over the data store and sets `ENGINE_ID`/`ASSISTANT_ID` on
  the Cloud Run service. **`ENGINE_ID` must be a genuine GE engine** — verify after deploy that no
  `93D6-7280-CF05` charges accrue (see the billing check below). If a Terraform-created chat engine
  isn't billed as GE, create the app in the Gemini Enterprise/Agentspace console and set `engine_id`
  to it. Requires GE seats. IAM: the app SA's custom role adds `discoveryengine.assistants.assist`.
- **Answers are text-grounded (no separate Gemini billing).** The GE assistant grounds on indexed
  text/extractive segments — it does not do vision over raw PDF page images. We deliberately do
  **not** make direct Vertex Gemini calls (which would bill separately per token, outside the
  subscription), so every AI call stays covered. The standalone cross-encoder Ranking API is also
  **off by default** (`RERANK=off`) for the same reason.
- **Billing check (do this after deploy):** run a batch of searches + answers, then in Cloud
  Billing → Reports group by **SKU** and confirm **no `93D6-7280-CF05`** charges — i.e. traffic is
  attributed to the GE subscription, not standalone Vertex AI Search.
- **Demo vs real identity:** the demo runs `identity_source = "demo"` (persona switcher drives
  ACL). For real per-user filtering set `identity_source = "iap"` and seed real users into
  Firestore `group_users`. See README → "Identity & access".
- **Corpus reachability:** the ingest job fetches public docs from the internet; egress is on by
  default on Cloud Run. Counts are best-effort and logged to `ge_search_logs.ingestion_log`.
- **Re-installing on the SAME project:** a first install is clean. But if you `terraform destroy`
  and immediately reinstall, the VAIS data store deletes **asynchronously (can take hours)** and
  the same `data_store_id` can't be recreated until it finishes — set a new `data_store_id` in
  `terraform.tfvars` to reinstall right away. (Firestore is abandoned, not deleted, so it's fine.)

## Teardown
```bash
cd terraform && terraform destroy -var="project_id=YOUR_PROJECT_ID"
```

"""Runtime configuration, loaded from environment (Cloud Run --set-env-vars / .env)."""
import os


def _b(name, default):
    return os.environ.get(name, default)


PROJECT_ID = _b("PROJECT_ID", "")
PROJECT_NUMBER = _b("PROJECT_NUMBER", "")
LOCATION = _b("LOCATION", "global")               # global | us | eu
DATA_STORE_ID = _b("DATA_STORE_ID", "ge-search-demo")

# security trimmer
# IDENTITY_SOURCE decides WHOSE identity filters the data (RBAC). This is NOT the same as
# who can reach the site — that's the IAP allow-list (terraform var.iap_members).
#   demo = trust the persona switcher header (X-Demo-User), so a visitor can explore as any
#          seeded persona (David/Nick/Ravi). DEMOS ONLY — the client picks the identity, so
#          it must never gate real/sensitive data.
#   iap  = trust the IAP-signed header (X-Goog-Authenticated-User-Email): the real signed-in
#          user filters THEIR OWN data via their Firestore group_users. The persona switcher
#          / X-Demo-User / ?u= are ignored. Use this for any real deployment.
IDENTITY_SOURCE = _b("IDENTITY_SOURCE", "demo")    # demo | iap
FIRESTORE_DATABASE = _b("FIRESTORE_DATABASE", "(default)") or "(default)"  # literal "(default)"

# answer generation
ANSWER_MODE = _b("ANSWER_MODE", "gemini")          # gemini (5b) | de_filter (5a)
GEMINI_MODEL = _b("GEMINI_MODEL", "gemini-3.5-flash")
# failover when the docs are too big to fit flash's context -> a larger pro model.
# "" disables failover. Flash stays the default; pro is only used on overflow.
GEMINI_PRO_MODEL = _b("GEMINI_PRO_MODEL", "gemini-3.1-pro-preview")
# thinking depth ("high" | "low" | a budget int | "" = model default). Q&A (ask + per-doc)
# gets high thinking for better answers; the auto-summary stays default for speed.
ASK_THINKING = _b("ASK_THINKING", "high")
ANSWER_THINKING = _b("ANSWER_THINKING", "")

# multimodal answers: attach retrieved docs' PDFs so Gemini reads charts/tables/figures
MULTIMODAL_ANSWERS = _b("MULTIMODAL_ANSWERS", "off").lower() == "on"
MULTIMODAL_MODEL = _b("MULTIMODAL_MODEL", "") or "gemini-3.5-flash"  # GA, 1M ctx, reads PDFs
MULTIMODAL_MAX_DOCS = int(_b("MULTIMODAL_MAX_DOCS", "2"))

# retrieval tuning
PAGE_SIZE = int(_b("PAGE_SIZE", "10"))
OVERFETCH = int(_b("OVERFETCH", "5"))              # retrieve PAGE_SIZE*OVERFETCH, then trim
FACET_SAMPLE = int(_b("FACET_SAMPLE", "100"))     # breadth for computing dynamic facets
BOOST_RECENT_YEARS = _b("BOOST_RECENT_YEARS", "2024,2025,2026")  # ranking boost; "" disables

# Semantic re-ranking via the Discovery Engine Ranking API, applied to the ACL-trimmed
# results BEFORE the AI summary/answer — so both the shown results and what Gemini grounds
# on are ordered by a cross-encoder reranker. Best-effort: a failure/unavailable model is a
# no-op (native ranking stands). Overfetch RERANK_TOP_N, rerank, then show PAGE_SIZE.
RERANK = _b("RERANK", "on").lower() == "on"
RERANK_MODEL = _b("RERANK_MODEL", "") or "semantic-ranker-default@latest"
RERANK_TOP_N = int(_b("RERANK_TOP_N", "50"))

# BigQuery logging (searches + feedback)
BQ_LOGGING = _b("BQ_LOGGING", "on")               # on | off
BQ_DATASET = _b("BQ_DATASET", "ge_search_logs")

def answer_models():
    """Server-controlled allowlist of models the UI may pick for summarize/answer. Derived
    from the configured flash + pro models so clients can never request an arbitrary model."""
    models = [{"id": GEMINI_MODEL, "label": "Flash — fast & cheap", "default": True}]
    if GEMINI_PRO_MODEL and GEMINI_PRO_MODEL != GEMINI_MODEL:
        models.append({"id": GEMINI_PRO_MODEL, "label": "Pro — deeper reasoning"})
    return models


ANSWER_MODEL_IDS = {m["id"] for m in answer_models()}


DE_HOST = ("discoveryengine.googleapis.com" if LOCATION == "global"
           else f"{LOCATION}-discoveryengine.googleapis.com")
DATA_STORE_PATH = (f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/"
                   f"default_collection/dataStores/{DATA_STORE_ID}")
SERVING_CONFIG = f"{DATA_STORE_PATH}/servingConfigs/default_search"
SIGNED_URL_MINUTES = int(_b("SIGNED_URL_MINUTES", "30"))

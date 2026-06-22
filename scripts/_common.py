"""Shared ingest-side helpers: config, Discovery Engine REST session, Firestore client.

Kept tiny and dependency-lazy so pure modules (catalog_model) never need GCP. The
catalog/loader/reconcile scripts import this; the GCP clients are created on first use.
"""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def cfg(key, default=None):
    if key in os.environ:
        return os.environ[key]
    env = os.path.join(ROOT, ".env")
    if os.path.exists(env):
        for line in open(env):
            line = line.strip()
            if line.startswith(f"{key}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()
    return default


PROJECT = cfg("PROJECT_ID")
LOCATION = cfg("LOCATION", "global")
DATA_STORE_ID = cfg("DATA_STORE_ID", "ge-search-demo")
FIRESTORE_DATABASE = cfg("FIRESTORE_DATABASE", "(default)") or "(default)"
GCS_BUCKET = (cfg("GCS_BUCKET", "") or "").replace("gs://", "").rstrip("/")
DE_HOST = ("discoveryengine.googleapis.com" if LOCATION == "global"
           else f"{LOCATION}-discoveryengine.googleapis.com")
DATA_STORE_PATH = (f"projects/{PROJECT}/locations/{LOCATION}/collections/"
                   f"default_collection/dataStores/{DATA_STORE_ID}")
BRANCH = f"{DATA_STORE_PATH}/branches/default_branch"
HDR = {"X-Goog-User-Project": PROJECT}

_session = None
_fs = None


def de_session():
    global _session
    if _session is None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"])
        _session = AuthorizedSession(creds)
    return _session


def firestore_client():
    global _fs
    if _fs is None:
        from google.cloud import firestore
        _fs = firestore.Client(project=PROJECT, database=FIRESTORE_DATABASE)
    return _fs

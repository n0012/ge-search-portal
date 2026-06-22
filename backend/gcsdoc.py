"""Mint short-lived V4 signed URLs for imported GCS objects.

The app runs on Cloud Run with a keyless service account, so signing goes through the
IAM SignBlob API: the runtime SA must hold roles/iam.serviceAccountTokenCreator on
ITSELF (granted in terraform/iam.tf). We never expose the gs:// path or sign blindly —
callers ACL-check the user against the document first, then hand us the resolved uri.
"""
import datetime
import re

import google.auth
from google.auth.transport.requests import Request as _GReq
from google.cloud import storage

import config

_client = None


def _c():
    global _client
    if _client is None:
        _client = storage.Client(project=config.PROJECT_ID)
    return _client


def signed_url(gs_uri, minutes=None):
    """gs://bucket/obj -> time-limited HTTPS URL the browser can open directly.

    Returns None if the uri isn't a gs:// path, the object no longer exists, or
    signing fails. The existence check matters: generate_signed_url is an offline
    crypto op that never touches GCS, so without it a stale VAIS reference (object
    deleted but still indexed) would redirect the user to a raw GCS 404. We'd rather
    return None here and let the caller show a friendly "no longer available" page.
    """
    if not gs_uri or not gs_uri.startswith("gs://"):
        return None
    bucket, _, obj = gs_uri[len("gs://"):].partition("/")
    if not bucket or not obj:
        return None
    try:
        blob = _c().bucket(bucket).blob(obj)
        if not blob.exists():           # stale reference -> treat as gone
            return None
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(_GReq())  # populates token + service_account_email for IAM signing
        return blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=minutes or config.SIGNED_URL_MINUTES),
            method="GET",
            service_account_email=getattr(creds, "service_account_email", None),
            access_token=creds.token,
        )
    except Exception:
        return None


def read_text(gs_uri, max_chars=120000):
    """Plain-text contents of an imported object, for grounding single-doc Q&A.

    PDFs return "" — they're far better handled by attaching the file for multimodal
    reading. HTML (e.g. EDGAR filings) is stripped to text. Returns "" on any failure.
    """
    if not gs_uri or not gs_uri.startswith("gs://"):
        return ""
    bucket, _, obj = gs_uri[len("gs://"):].partition("/")
    if not bucket or not obj or obj.lower().endswith(".pdf"):
        return ""
    try:
        blob = _c().bucket(bucket).blob(obj)
        if not blob.exists():
            return ""
        txt = blob.download_as_bytes().decode("utf-8", "replace")
    except Exception:
        return ""
    if obj.lower().endswith((".htm", ".html")):
        txt = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", txt)
        txt = re.sub(r"(?s)<[^>]+>", " ", txt)
        txt = re.sub(r"&[a-z#0-9]+;", " ", txt)
        txt = re.sub(r"\s+", " ", txt)
    return txt[:max_chars]

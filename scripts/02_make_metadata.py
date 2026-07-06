#!/usr/bin/env python3
"""Turn ../_manifest.jsonl (from 01_fetch_corpus.py) into ../metadata.jsonl — the
Vertex AI Search import file (one JSON object per line):

  {"id": "...", "structData": {...facets...},
   "content": {"mimeType": "application/pdf", "uri": "gs://BUCKET/corpus/.../x.pdf"}}

Stdlib-only; no GCP needed. The GCS bucket comes from $GCS_BUCKET (or .env, or
--bucket). `id` is the join key to the Firestore ACL graph (04_seed_acls.py).

Usage
  python3 scripts/02_make_metadata.py
  python3 scripts/02_make_metadata.py --bucket gs://my-bucket
"""
import argparse
import json
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MANIFEST = os.path.join(ROOT, "_manifest.jsonl")
OUT = os.path.join(ROOT, "metadata.jsonl")
SEED = os.path.join(ROOT, "seed")

# structData carries descriptive/facet metadata only. `id` and `pdf` are not facets;
# everything else from the manifest becomes a structData field.
NON_FACET = {"id", "pdf"}

# research_source -> parent company, so the Company facet rolls research up alongside
# filings (DeepMind + Google Health are Alphabet). Only applied when `company` is absent.
SOURCE_COMPANY = {"deepmind": "alphabet", "google-health": "alphabet", "amgen": "amgen"}


def derive_company(struct):
    if not struct.get("company"):
        company = SOURCE_COMPANY.get(str(struct.get("research_source", "")).lower())
        if company:
            struct["company"] = company
    return struct


# quarter from a fiscal PERIOD-END month (authoritative, from EDGAR reportDate)
_Q_BY_END_MONTH = {3: "Q1", 6: "Q2", 9: "Q3", 12: "Q4"}
# quarter a 10-Q REPORTS, inferred from its FILING month (fallback when no period_end):
# filed Apr/May -> Q1, Jul/Aug -> Q2, Oct/Nov -> Q3 (Q4 is the annual 10-K)
_Q_BY_FILING_MONTH = {4: "Q1", 5: "Q1", 7: "Q2", 8: "Q2", 10: "Q3", 11: "Q3"}
# plain calendar quarter by month (for dated docs that aren't SEC filings)
_Q_BY_CAL_MONTH = {m: "Q%d" % ((m - 1) // 3 + 1) for m in range(1, 13)}
_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_MONTHS = ["", "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]


def _date_in(struct, *keys):
    """First YYYY-MM-DD found in the given fields (then the title)."""
    for k in keys + ("title",):
        m = _DATE_RE.search(str(struct.get(k, "") or ""))
        if m:
            return m.group(0)
    return ""


def derive_period(struct):
    """Add keyable time metadata so 'Q4 2025'-style queries/filters/ranking work — across
    BOTH SEC filings and research papers, with one shared vocabulary:
      year, quarter (Q1-Q4, or FY for annual filings), month, period ("Q2 2025" / "FY2024").

    Filings use the fiscal period: prefers the EDGAR period-of-report end date
    (`period_end`), else infers from the filing date + form. Research papers use the
    calendar quarter of their publish_date. The period is appended to synthetic filing
    titles (searchable + visible); real paper titles are left intact."""
    form = str(struct.get("doc_type", ""))

    if form in ("10-K", "10-Q", "8-K"):
        pend = struct.get("period_end") or ""
        src = pend or _date_in(struct)
        struct.pop("period_end", None)  # internal-only; never a facet
        if not src:
            return struct
        year, month = src[:4], int(src[5:7])
        quarter = None
        if form == "10-K":  # annual → full fiscal year (early-year filing reports prior year)
            year = pend[:4] if pend else (str(int(year) - 1) if month <= 4 else year)
            quarter = "FY"
        elif form == "10-Q":
            quarter = _Q_BY_END_MONTH.get(month) if pend else _Q_BY_FILING_MONTH.get(month)
        elif form == "8-K" and month in (1, 2):  # Jan/Feb earnings report prior-year Q4
            year, quarter = str(int(year) - 1), "Q4"
        struct["year"] = year
        if quarter:
            struct["quarter"] = quarter
            period = "FY%s" % year if quarter == "FY" else "%s FY%s" % (quarter, year)
            struct["period"] = period
            if period not in (struct.get("title") or ""):
                struct["title"] = "%s · %s" % (struct.get("title", "").strip(), period)
        return struct

    # Non-filing dated docs (research papers): calendar quarter/month/year from publish_date
    src = _date_in(struct, "publish_date")
    if src:
        year, month = src[:4], int(src[5:7])
        struct.setdefault("year", year)
        struct["quarter"] = _Q_BY_CAL_MONTH.get(month)
        struct["month"] = _MONTHS[month]
        struct["period"] = "%s %s" % (struct["quarter"], year)
    return struct


def load_acl_rules():
    """by_department + overrides from seed/acl_rules.yaml (same source 04_seed_acls.py
    uses), so the indexed acl_groups matches the Firestore graph. Best-effort: falls back
    to identity dept->group if pyyaml/the file is unavailable (keeps 02 runnable alone)."""
    try:
        import yaml
        r = yaml.safe_load(open(os.path.join(SEED, "acl_rules.yaml"))) or {}
        return r.get("by_department", {}), r.get("overrides", {})
    except Exception:
        return {"finance": ["finance"], "research": ["research"]}, {}


_BY_DEPT, _OVERRIDES = load_acl_rules()


def acl_groups_for(row, doc_id):
    """Indexed ACL key so VAIS can do the security trim server-side. Baked in at import
    time (not patched later) so the field is filterable from the first import."""
    return (_OVERRIDES.get(row.get("id")) or _OVERRIDES.get(doc_id)
            or _BY_DEPT.get(row.get("department"), []))


def load_env_bucket():
    bucket = os.environ.get("GCS_BUCKET")
    env = os.path.join(ROOT, ".env")
    if not bucket and os.path.exists(env):
        for line in open(env):
            line = line.strip()
            if line.startswith("GCS_BUCKET=") and "CHANGEME" not in line:
                bucket = line.split("=", 1)[1].strip()
    return bucket


def clean_id(raw):
    """Discovery Engine doc id: 1-63 chars of [a-zA-Z0-9_-]."""
    s = re.sub(r"[^A-Za-z0-9_-]", "_", raw)
    return s[:63].strip("_") or "doc"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default=load_env_bucket(),
                    help="GCS bucket root, e.g. gs://my-bucket (or set GCS_BUCKET)")
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--require-file", action="store_true",
                    help="skip rows whose local PDF is missing")
    args = ap.parse_args()

    if not args.bucket:
        ap.error("no GCS bucket: set GCS_BUCKET in .env or pass --bucket gs://...")
    bucket = args.bucket.rstrip("/")
    if not os.path.exists(args.manifest):
        ap.error(f"manifest not found: {args.manifest} (run 01_fetch_corpus.py first)")

    seen, written, skipped = set(), 0, 0
    with open(args.out, "w") as out:
        for line in open(args.manifest):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            pdf = row.get("pdf")
            if not pdf:
                skipped += 1
                continue
            if args.require_file and not os.path.exists(os.path.join(ROOT, pdf)):
                skipped += 1
                continue
            doc_id = clean_id(row["id"])
            if doc_id in seen:
                skipped += 1
                continue
            seen.add(doc_id)
            struct = {k: v for k, v in row.items() if k not in NON_FACET and v not in (None, "")}
            struct = derive_company(struct)
            struct = derive_period(struct)  # year/quarter/period for filings + papers
            acl = acl_groups_for(row, doc_id)
            if acl:
                struct["acl_groups"] = acl
            ext = os.path.splitext(pdf)[1].lower()
            mime = ("application/pdf" if ext == ".pdf"
                    else "text/html" if ext in (".htm", ".html")
                    else "application/octet-stream")
            out.write(json.dumps({
                "id": doc_id,
                "structData": struct,
                "content": {"mimeType": mime, "uri": f"{bucket}/{pdf}"},
            }) + "\n")
            written += 1

    print(f"wrote {written} docs to {args.out}  (skipped {skipped})")
    print(f"GCS content.uri base: {bucket}/corpus/...")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Fetch the demo corpus PDFs into ./corpus/{department}/{source}/.

Stdlib-only (urllib) so it runs anywhere with no pip installs.

We only keep documents we can actually get a full-text PDF for — that's the whole
point of the demo. Paywalled / abstract-only links (Nature, SSRN, bare DOI) are
logged and skipped.

Sources
  research:
    - deepmind      crawl deepmind.google/research/publications (paginate -> detail
                    page -> external link -> arXiv PDF)
    - google-health health.google/publications (single static page w/ embedded JSON
                    -> external links -> arXiv PDF), theme captured as research_area
  finance:
    - alphabet      Alphabet earnings PDFs (investor page .pdf hrefs)
    - amgen         Amgen IR annual reports + quarterly earnings

Each downloaded doc appends a row to ../_manifest.jsonl which 02_make_metadata.py
turns into the Vertex AI Search import JSONL.

Usage
  python scripts/01_fetch_corpus.py research --limit 12
  python scripts/01_fetch_corpus.py health --limit 8
  python scripts/01_fetch_corpus.py all --limit 30
"""
import argparse
import html as _html
import http.client
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from ingestlog import ilog  # per-document ledger (no-op unless BQ_LOGGING=on)

# Every network hop is best-effort; treat any of these as "skip this one".
NETERR = (OSError, urllib.error.URLError, http.client.HTTPException, ssl.SSLError)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORPUS = os.path.join(ROOT, "corpus")
MANIFEST = os.path.join(ROOT, "_manifest.jsonl")

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
CTX = ssl.create_default_context()

ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})")
PDF_HREF_RE = re.compile(r'href="([^"]+?\.pdf)"', re.I)

# Cloud Run Jobs set these per task; default to a single shard (local runs).
SHARD_INDEX = int(os.environ.get("CLOUD_RUN_TASK_INDEX", "0"))
SHARD_COUNT = int(os.environ.get("CLOUD_RUN_TASK_COUNT", "1"))


def shard(items):
    """This task's disjoint slice of a candidate list (deterministic stride slicing).

    With SHARD_COUNT tasks, task i processes items[i::SHARD_COUNT]; the union across
    tasks is the whole list with no overlap, so each Cloud Run task can fetch +
    import its slice independently (import is INCREMENTAL, Firestore writes are
    idempotent — no cross-task barrier needed).
    """
    items = list(items)
    return items[SHARD_INDEX::SHARD_COUNT] if SHARD_COUNT > 1 else items


def dlog(action, source, doc_id, **fields):
    """One structured JSON line per document → Cloud Logging (queryable / BQ-sinkable)."""
    rec = {"log": "ingest_doc", "task": SHARD_INDEX, "tasks": SHARD_COUNT,
           "action": action, "source": source, "document_id": doc_id}
    rec.update({k: v for k, v in fields.items() if v not in (None, "")})
    print(json.dumps(rec), flush=True)


def _open(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    return urllib.request.urlopen(req, timeout=30, context=CTX)


def get_text(url):
    with _open(url) as r:
        return r.read().decode("utf-8", "replace")


def get_text_ua(url, ua):
    """get_text with a custom User-Agent (SEC EDGAR requires a descriptive UA)."""
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
        return r.read().decode("utf-8", "replace")


def download_pdf(url, dest):
    """Download a URL to dest only if it's a real PDF. Returns byte size or None."""
    try:
        with _open(url) as r:
            data = r.read()
    except NETERR:
        return None
    if not data.startswith(b"%PDF"):
        return None
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return len(data)


def arxiv_meta(aid):
    """(title, publish_date YYYY-MM-DD) from arXiv — retry the API, then fall back to
    the abstract page so bulk runs don't degrade to 'arXiv:<id>' under rate limiting."""
    for attempt in range(3):
        try:
            text = get_text(f"http://export.arxiv.org/api/query?id_list={aid}")
            mt = re.search(r"<entry>.*?<title>(.*?)</title>", text, re.S)
            mp = re.search(r"<entry>.*?<published>(\d{4}-\d{2}-\d{2})", text, re.S)
            title = re.sub(r"\s+", " ", mt.group(1)).strip() if mt else ""
            published = mp.group(1) if mp else None
            if title and not title.lower().startswith("error"):
                return title, published
        except NETERR:
            pass
        time.sleep(1.5 * (attempt + 1))  # back off; arXiv API rate-limits bulk
    # fallback: the abstract page (og:title is the clean title)
    try:
        html = get_text(f"https://arxiv.org/abs/{aid}")
        m = (re.search(r'<meta property="og:title" content="([^"]+)"', html)
             or re.search(r"<title>(.*?)</title>", html, re.S))
        if m:
            t = re.sub(r"\s+", " ", _html.unescape(m.group(1))).strip()
            t = re.sub(r"^\[?\d{4}\.\d{4,5}\]?\s*", "", t)  # strip leading [id] if present
            if t:
                return t, None
    except NETERR:
        pass
    return f"arXiv:{aid}", None


_mf = None


def record(**row):
    global _mf
    if _mf is None:
        _mf = open(MANIFEST, "a")
    _mf.write(json.dumps(row) + "\n")
    _mf.flush()


# ---------------------------------------------------------------- research ----
def fetch_arxiv(aid, source, seen, research_area=None):
    if aid in seen:
        return False
    seen.add(aid)
    dest = os.path.join(CORPUS, "research", source, f"{aid}.pdf")
    if os.path.exists(dest):
        return False
    size = download_pdf(f"https://arxiv.org/pdf/{aid}", dest)
    if not size:
        dlog("skip", source, f"arXiv:{aid}", reason="no_full_text_pdf")
        ilog("download", source, f"arXiv:{aid}", "skipped_no_pdf")
        return False
    title, published = arxiv_meta(aid)
    row = dict(
        id=f"{source.replace('-', '_')}_{aid.replace('.', '_')}",
        department="research", research_source=source, doc_type="research_paper",
        arxiv_id=aid, title=title,
        publish_date=published, year=(published or "20" + aid[:2])[:4],
        research_area=research_area,
        source_url=f"https://arxiv.org/abs/{aid}",
        pdf=os.path.relpath(dest, ROOT),
    )
    record(**{k: v for k, v in row.items() if v})
    dlog("fetched", source, f"arXiv:{aid}", bytes=size, title=title,
         publish_date=published, research_area=research_area)
    ilog("download", source, row["id"], "ok", bytes_=size)
    return True


def crawl_deepmind(limit, seen):
    # Collect all candidate publication ids first (cheap), then this task fetches
    # detail pages only for its shard — no redundant detail fetches across tasks.
    pids = []
    for page in range(1, 10):
        idx = ("https://deepmind.google/research/publications/" if page == 1
               else f"https://deepmind.google/research/publications/page/{page}/")
        try:
            html = get_text(idx)
        except NETERR:
            break
        for pid in sorted(set(re.findall(r"/research/publications/(\d+)/", html)),
                          key=int, reverse=True):
            if pid not in pids:
                pids.append(pid)
    pids = shard(pids)
    got = 0
    for pid in pids:
        if got >= limit:
            break
        try:
            detail = get_text(f"https://deepmind.google/research/publications/{pid}/")
        except NETERR:
            continue
        m = ARXIV_RE.search(detail)
        if m and fetch_arxiv(m.group(1), "deepmind", seen):
            got += 1
        time.sleep(0.3)
    return got


def health_themes(html):
    """Map each arXiv id on the health index to its nearest preceding theme heading.

    The page groups publications under theme sections; we associate every arXiv id
    with the closest section heading that appears before it in the document.
    """
    headings = [(m.start(), _html.unescape(m.group(1)).strip()) for m in
                re.finditer(r'class="[^"]*expansion[^"]*"[^>]*>\s*<[^>]+>([^<]{3,40})', html)]
    headings = [(p, h) for p, h in headings if re.search(r"[A-Za-z]", h)]  # drop whitespace nodes
    area_of = {}
    for m in ARXIV_RE.finditer(html):
        aid = m.group(1)
        prior = [h for pos, h in headings if pos < m.start()]
        if aid not in area_of and prior:
            area_of[aid] = prior[-1]
    return area_of


def crawl_health(limit, seen):
    got = 0
    try:
        html = get_text("https://health.google/publications/")
    except NETERR:
        return 0
    area_of = health_themes(html)
    ids = shard(list(dict.fromkeys(ARXIV_RE.findall(html))))
    print(f"  google-health: {len(ids)} arXiv-linked papers (shard {SHARD_INDEX}/{SHARD_COUNT}), "
          f"{len(set(area_of.values()))} themes")
    for aid in ids:
        if got >= limit:
            break
        if fetch_arxiv(aid, "google-health", seen, research_area=area_of.get(aid)):
            got += 1
        time.sleep(0.3)
    return got


# --------------------------------------- Amgen research via PubMed Central ----
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_MONTHS = {m: f"{i:02d}" for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _json(url):
    try:
        return json.loads(get_text(url))
    except NETERR + (ValueError,):
        return None


def _tgz_pdf(url, dest):
    """Download a PMC OA .tar.gz package and extract the first PDF inside it."""
    import io
    import tarfile
    try:
        with _open(url) as r:
            blob = r.read()
        tf = tarfile.open(fileobj=io.BytesIO(blob))
    except NETERR + (tarfile.TarError, EOFError):
        return None
    for member in tf.getmembers():
        if member.name.lower().endswith(".pdf"):
            data = tf.extractfile(member).read()
            if data.startswith(b"%PDF"):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(data)
                return len(data)
    return None


def pmc_download(pmcid, dest):
    """Download an OA PDF for a PMC id, trying finders in order (cf.
    arundasan91/pubmed_pdf_downloader): Europe PMC's render endpoint first (the
    reliable one), then citation_pdf_url meta on the article page, then the NCBI
    OA-service pdf/tgz.

    NOTE: NCBI's own PDF host gates the blob behind an anti-bot interstitial, so we
    prefer https://europepmc.org/articles/PMC<id>?pdf=render which serves the OA PDF
    directly (verified). arXiv sources work everywhere.
    """
    # Europe PMC's render endpoint serves the OA PDF directly (most reliable).
    pdf_urls = [f"https://europepmc.org/articles/PMC{pmcid}?pdf=render"]
    tgz_urls = []
    try:
        art = get_text(f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/")
    except NETERR:
        art = ""
    m = (re.search(r'name="citation_pdf_url"\s+content="([^"]+)"', art)
         or re.search(r'content="([^"]+)"\s+name="citation_pdf_url"', art))
    if m:
        pdf_urls.append(m.group(1))
    try:
        oa = get_text(f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC{pmcid}")
    except NETERR:
        oa = ""
    mp = re.search(r'format="pdf"[^>]*href="([^"]+)"', oa)
    if mp:
        pdf_urls.append(mp.group(1).replace("ftp://ftp.ncbi.nlm.nih.gov", "https://ftp.ncbi.nlm.nih.gov"))
        pdf_urls.append(mp.group(1))  # raw ftp:// where egress allows it
    mt = re.search(r'format="tgz"[^>]*href="([^"]+)"', oa)
    if mt:
        tgz_urls.append(mt.group(1).replace("ftp://ftp.ncbi.nlm.nih.gov", "https://ftp.ncbi.nlm.nih.gov"))
        tgz_urls.append(mt.group(1))
    pdf_urls.append(f"https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC{pmcid}&blobtype=pdf")

    for url in pdf_urls:
        size = download_pdf(url, dest)
        if size:
            return size
    for url in tgz_urls:
        size = _tgz_pdf(url, dest)
        if size:
            return size
    return None


def pmc_summary(pmcid):
    d = _json(f"{EUTILS}/esummary.fcgi?db=pmc&id={pmcid}&retmode=json")
    r = (d or {}).get("result", {}).get(pmcid, {})
    title = r.get("title", f"PMC{pmcid}")
    journal = r.get("fulljournalname") or r.get("source")
    authors = ", ".join(a.get("name", "") for a in r.get("authors", [])[:3])
    parts = r.get("pubdate", "").split()       # e.g. "2026 Jun 17"
    date = None
    if parts and parts[0].isdigit():
        mo = _MONTHS.get(parts[1], "01") if len(parts) > 1 else "01"
        da = f"{int(parts[2]):02d}" if len(parts) > 2 and parts[2].isdigit() else "01"
        date = f"{parts[0]}-{mo}-{da}"
    return title, journal, authors, date


def fetch_pmc(affiliation, source, company, limit):
    """Fetch open-access PDFs for an organisation's papers via PubMed Central.

    Generic over `affiliation` — works for Amgen, Google DeepMind, Google Health,
    Google Research, etc. Captures journal-published work that isn't on arXiv.
    """
    term = urllib.parse.quote(f'{affiliation}[Affiliation] AND open access[filter]')
    d = _json(f"{EUTILS}/esearch.fcgi?db=pmc&term={term}&retmax={max(limit * 8, 40)}&retmode=json")
    ids = shard((d or {}).get("esearchresult", {}).get("idlist", []))
    print(f"  PubMed Central: {len(ids)} candidate '{affiliation}' OA papers "
          f"(shard {SHARD_INDEX}/{SHARD_COUNT})")
    got = 0
    for pmcid in ids:
        if got >= limit:
            break
        dest = os.path.join(CORPUS, "research", source, f"PMC{pmcid}.pdf")
        if os.path.exists(dest):
            continue
        size = pmc_download(pmcid, dest)
        time.sleep(0.34)
        if not size:
            dlog("skip", source, f"PMC{pmcid}", reason="no_oa_pdf")
            ilog("download", source, f"PMC{pmcid}", "skipped_no_pdf")
            continue
        title, journal, authors, date = pmc_summary(pmcid)
        row = dict(
            id=f"{source.replace('-', '_')}_pmc{pmcid}", department="research",
            research_source=source, company=company, doc_type="research_paper",
            title=title, venue=journal, authors=authors,
            publish_date=date, year=(date or "")[:4] or None,
            source_url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/",
            pdf=os.path.relpath(dest, ROOT),
        )
        record(**{k: v for k, v in row.items() if v})
        dlog("fetched", source, f"PMC{pmcid}", bytes=size, title=title,
             publish_date=date, venue=journal)
        ilog("download", source, row["id"], "ok", bytes_=size)
        got += 1
        time.sleep(0.34)
    return got


# Affiliation -> (source label, company) for the PMC route
PMC_ORGS = {
    "amgen-research": ("Amgen", "amgen", "amgen"),
    "gdm-pmc":        ("Google DeepMind", "deepmind-journals", "google"),
    "health-pmc":     ("Google Health", "google-health-journals", "google"),
    "google-pmc":     ("Google Research", "google-research", "google"),
}


# ----------------------------------------------------------------- finance ----
def scrape_pdfs(page_url, company, doc_type, report_kind, limit):
    """Best-effort: pull .pdf hrefs (incl. Q4 CDN) off an investor-relations page."""
    got = 0
    try:
        html = get_text(page_url)
    except NETERR:
        print(f"  could not load {page_url}")
        return 0
    hrefs = shard(list(dict.fromkeys(PDF_HREF_RE.findall(html))))
    print(f"  {company}: {len(hrefs)} .pdf links on {page_url} "
          f"(shard {SHARD_INDEX}/{SHARD_COUNT})")
    for href in hrefs:
        if got >= limit:
            break
        url = href if href.startswith("http") else urllib.parse.urljoin(page_url, href)
        name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(url.split("?")[0]))
        dest = os.path.join(CORPUS, "finance", company, name)
        if os.path.exists(dest):
            continue
        size = download_pdf(url, dest)
        if not size:
            continue
        ym = re.search(r"(20\d{2})", name)
        q = re.search(r"[Qq]([1-4])", name)
        row = dict(
            id=f"{company}_{os.path.splitext(name)[0]}".lower(),
            department="finance", company=company, doc_type=doc_type,
            report_kind=report_kind, title=name,
            year=ym.group(1) if ym else None,
            quarter=f"Q{q.group(1)}" if q else None,
            source_url=url, pdf=os.path.relpath(dest, ROOT),
        )
        record(**{k: v for k, v in row.items() if v})
        dlog("fetched", company, row["id"], bytes=size, title=name,
             year=row.get("year"), report_kind=report_kind)
        ilog("download", company, row["id"], "ok", bytes_=size)
        got += 1
        time.sleep(0.3)
    return got


# Finance via SEC EDGAR — authoritative + current 10-K/10-Q filings (HTML).
# SEC EDGAR asks for a descriptive User-Agent with a real contact. Set EDGAR_UA to your own
# (e.g. "yourapp you@yourorg.com") before a real fetch.
EDGAR_UA = os.environ.get("EDGAR_UA", "ge-search-portal contact@example.com")
EDGAR_CIKS = {"alphabet": "0001652044", "amgen": "0000318154"}


def download_file(url, dest, ua=UA, require_pdf=True):
    """Download any file (PDF or HTML). For PDFs, verify the %PDF magic."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=90, context=CTX) as r:
            data = r.read()
    except NETERR:
        return None
    if require_pdf and not data.startswith(b"%PDF"):
        return None
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return len(data)


# EDGAR form -> our report_kind label
EDGAR_KIND = {"10-K": "annual", "10-Q": "quarterly", "8-K": "current"}


def fetch_edgar(company, cik, limit, forms=None):
    """Recent filings for a company from SEC EDGAR (primary HTML doc). `forms` defaults to
    10-K/10-Q; set EDGAR_FORMS (e.g. "8-K") to pull earnings / current reports too."""
    forms = forms or tuple(f.strip() for f in
                           os.environ.get("EDGAR_FORMS", "10-K,10-Q").split(",") if f.strip())
    try:
        j = json.loads(get_text_ua(f"https://data.sec.gov/submissions/CIK{cik}.json", EDGAR_UA))
    except NETERR + (ValueError,):
        j = {}
    rec = (j.get("filings", {}) or {}).get("recent", {}) or {}
    allforms, accs = rec.get("form", []), rec.get("accessionNumber", [])
    prims, dates = rec.get("primaryDocument", []), rec.get("filingDate", [])
    cands = [(allforms[i], accs[i], prims[i], dates[i]) for i in range(len(allforms))
             if allforms[i] in forms and prims[i].lower().endswith((".htm", ".html"))]
    cands = shard(cands)
    got = 0
    for form, acc, prim, date in cands:
        if got >= limit:
            break
        did = re.sub(r"[^a-z0-9_-]", "_", f"{company}_{form}_{date}".lower())[:63]
        dest = os.path.join(CORPUS, "finance", company, did + os.path.splitext(prim)[1])
        if os.path.exists(dest):
            continue
        url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc.replace('-', '')}/{prim}"
        size = download_file(url, dest, ua=EDGAR_UA, require_pdf=False)
        if not size:
            ilog("download", company, did, "skipped")
            continue
        row = dict(id=did, department="finance", company=company, doc_type=form,
                   report_kind=EDGAR_KIND.get(form, "filing"),
                   title=f"{company.title()} {form} {date}", year=date[:4],
                   source_url=url, pdf=os.path.relpath(dest, ROOT))
        record(**{k: v for k, v in row.items() if v})
        dlog("fetched", company, did, bytes=size, year=date[:4], doc_type=form)
        ilog("download", company, did, "ok", bytes_=size)
        got += 1
        time.sleep(0.3)
    print(f"  {company}: {got} EDGAR filings")
    return got


def fetch_alphabet(limit):
    return fetch_edgar("alphabet", EDGAR_CIKS["alphabet"], limit)


def fetch_amgen(limit):
    return fetch_edgar("amgen", EDGAR_CIKS["amgen"], limit)


# -------------------------------------------------------------------- main ----
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", choices=["research", "deepmind", "health",
                                       "amgen-research", "gdm-pmc", "health-pmc",
                                       "google-pmc", "finance", "alphabet",
                                       "amgen", "all"])
    ap.add_argument("--limit", type=int, default=15, help="max docs per sub-source")
    args = ap.parse_args()
    seen, totals = set(), {}
    if SHARD_COUNT > 1:
        print(f"== ingest shard {SHARD_INDEX} of {SHARD_COUNT} (limit {args.limit}/sub-source) ==")

    if args.source in ("research", "deepmind", "all"):
        print("DeepMind publications -> arXiv PDFs:")
        totals["deepmind"] = crawl_deepmind(args.limit, seen)
    if args.source in ("research", "health", "all"):
        print("Google Health publications -> arXiv PDFs:")
        totals["google-health"] = crawl_health(args.limit, seen)
    if args.source in ("research", "amgen-research", "all"):
        print("Amgen open-access research (PubMed Central) -> PDFs:")
        aff, src, co = PMC_ORGS["amgen-research"]
        totals["amgen-research"] = fetch_pmc(aff, src, co, args.limit)
    if args.source in ("gdm-pmc", "health-pmc", "google-pmc"):  # opt-in extras
        aff, src, co = PMC_ORGS[args.source]
        print(f"{aff} journal research (PubMed Central) -> PDFs:")
        totals[args.source] = fetch_pmc(aff, src, co, args.limit)
    if args.source in ("finance", "alphabet", "all"):
        print("Alphabet earnings PDFs:")
        totals["alphabet"] = fetch_alphabet(args.limit)
    if args.source in ("finance", "amgen", "all"):
        print("Amgen IR PDFs:")
        totals["amgen"] = fetch_amgen(args.limit)

    print("\nDownloaded:", ", ".join(f"{k}={v}" for k, v in totals.items()))
    print(f"Manifest: {MANIFEST}")


if __name__ == "__main__":
    main()

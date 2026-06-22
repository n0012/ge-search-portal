#!/usr/bin/env python3
"""Repair arXiv titles that fell back to 'arXiv:<id>' during a rate-limited ingest.

Re-resolves titles from the arXiv API (batched, gentle) and patches them in place into
the VAIS data store (structData.title) and Firestore (documents.title) — no PDF re-download.

Env: PROJECT_ID, LOCATION, DATA_STORE_ID, FIRESTORE_DATABASE.
"""
import json
import os
import re
import time
import urllib.request

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def cfg(k, d=None):
    if k in os.environ:
        return os.environ[k]
    env = os.path.join(ROOT, ".env")
    if os.path.exists(env):
        for line in open(env):
            line = line.strip()
            if line.startswith(f"{k}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()
    return d


PROJECT = cfg("PROJECT_ID")
LOCATION = cfg("LOCATION", "global")
DS = cfg("DATA_STORE_ID", "ge-search-demo")
DB = cfg("FIRESTORE_DATABASE", "(default)")
HOST = "discoveryengine.googleapis.com" if LOCATION == "global" else f"{LOCATION}-discoveryengine.googleapis.com"
BASE = (f"https://{HOST}/v1/projects/{PROJECT}/locations/{LOCATION}/collections/"
        f"default_collection/dataStores/{DS}/branches/default_branch")
_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
SESS = AuthorizedSession(_creds)
HDR = {"X-Goog-User-Project": PROJECT}


def list_docs():
    docs, token = [], ""
    while True:
        url = f"{BASE}/documents?pageSize=200" + (f"&pageToken={token}" if token else "")
        r = SESS.get(url, headers=HDR, timeout=60)
        r.raise_for_status()
        j = r.json()
        docs += j.get("documents", [])
        token = j.get("nextPageToken")
        if not token:
            return docs


def arxiv_titles(ids):
    out = {}
    for i in range(0, len(ids), 40):
        batch = ids[i:i + 40]
        try:
            url = f"http://export.arxiv.org/api/query?id_list={','.join(batch)}&max_results=40"
            txt = urllib.request.urlopen(url, timeout=40).read().decode("utf-8", "replace")
        except Exception:
            time.sleep(2)
            continue
        for m in re.finditer(r"<entry>(.*?)</entry>", txt, re.S):
            e = m.group(1)
            mi = re.search(r"arxiv\.org/abs/(\d{4}\.\d{4,5})", e)
            mt = re.search(r"<title>(.*?)</title>", e, re.S)
            if mi and mt:
                out[mi.group(1)] = re.sub(r"\s+", " ", mt.group(1)).strip()
        time.sleep(1.5)
    return out


def main():
    docs = list_docs()
    need = [d for d in docs
            if (d.get("structData", {}) or {}).get("title", "").startswith("arXiv:")
            and (d.get("structData", {}) or {}).get("arxiv_id")]
    print(f"{len(docs)} docs total; {len(need)} with unresolved arXiv titles")
    if not need:
        print("nothing to fix.")
        return
    titles = arxiv_titles(sorted({d["structData"]["arxiv_id"] for d in need}))
    db = firestore.Client(project=PROJECT, database=DB)
    fixed = 0
    for d in need:
        new = titles.get(d["structData"]["arxiv_id"])
        if not new:
            continue
        sd = dict(d["structData"])
        sd["title"] = new
        r = SESS.patch(f"https://{HOST}/v1/{d['name']}?updateMask=structData",
                       headers=HDR, json={"structData": sd}, timeout=30)
        if r.status_code == 200:
            db.collection("documents").document(d["id"]).set({"title": new}, merge=True)
            fixed += 1
        else:
            print(f"  patch failed [{r.status_code}] {d['id']}: {r.text[:120]}")
    print(f"fixed {fixed} titles")


if __name__ == "__main__":
    main()

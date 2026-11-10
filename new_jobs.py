#!/usr/bin/env python3
"""Daily feed of new jobs from Greenhouse, Lever and Ashby career boards, written to CSV.

Two sources:
  public  Reads each board's public JSON endpoint directly. Free, standard library only.
          Supports Greenhouse, Lever and Ashby.
  apify   Runs the fecklesspleb/ats-jobs-scraper Actor through the Apify API
          (run-sync-get-dataset-items). Adds Workday, Workable, Recruitee and Teamtailor,
          salary parsing and the Actor's own only-new-jobs state. Needs APIFY_TOKEN.

Both sources produce the same columns. Every job gets a stable key, uid = "ats:board:id",
and a job is new when its uid is not already in data/jobs.csv. Job URLs are not used as the
key because Greenhouse URLs often point at the company's own careers domain and can change.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USER_AGENT = os.environ.get(
    "JOBS_FEED_USER_AGENT",
    "ats-new-jobs-feed/1.0 (+https://github.com/fecklesspleb/ats-new-jobs-feed)",
)
APIFY_ACTOR = "fecklesspleb~ats-jobs-scraper"
APIFY_BASE = "https://api.apify.com/v2"
COLUMNS = [
    "uid", "ats", "board", "company", "title", "location", "workplace",
    "posted_at", "salary", "url", "first_seen",
]
SUPPORTED_PUBLIC = ("greenhouse", "lever", "ashby")


# ---------------------------------------------------------------- board parsing

def parse_board(entry: str) -> tuple[str, str]:
    """Turn 'greenhouse:airbnb' or a board URL into (ats, board). Raises ValueError otherwise."""
    entry = entry.strip()
    m = re.match(r"^(greenhouse|lever|ashby):([A-Za-z0-9_.\-]+)$", entry, re.I)
    if m:
        return m.group(1).lower(), m.group(2)
    u = urllib.parse.urlparse(entry if "://" in entry else "https://" + entry)
    host = (u.hostname or "").lower()
    parts = [p for p in u.path.split("/") if p]
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io") and parts:
        return "greenhouse", parts[0]
    if host in ("jobs.lever.co", "jobs.eu.lever.co") and parts:
        return "lever", parts[0]
    if host == "jobs.ashbyhq.com" and parts:
        return "ashby", parts[0]
    raise ValueError(
        f"{entry!r}: use greenhouse:<board>, lever:<site>, ashby:<board> or a board URL "
        "(other ATSs need --source apify)"
    )


def read_companies(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for ln in lines:
        ln = re.split(r"(?:^|\s)#", ln, maxsplit=1)[0].strip()  # drop comments, keep URL fragments
        if ln:
            out.append(ln)
    return out


# ---------------------------------------------------------------- HTTP

def http_json(url: str, *, data: bytes | None = None, headers: dict | None = None, timeout: float = 30):
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------------------------------------------------------------- public endpoints

def _ms_to_iso(ms) -> str | None:
    if not isinstance(ms, (int, float)):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def greenhouse_jobs(board: str, fetch=http_json) -> list[dict]:
    data = fetch(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs")
    out = []
    for j in data.get("jobs", []):
        out.append({
            "uid": f"greenhouse:{board.lower()}:{j['id']}", "ats": "greenhouse", "board": board,
            "company": j.get("company_name") or board, "title": (j.get("title") or "").strip(),
            "location": (j.get("location") or {}).get("name"), "workplace": None,
            "posted_at": j.get("first_published") or j.get("updated_at"),
            "salary": None, "url": j.get("absolute_url"),
        })
    return out


def lever_jobs(site: str, fetch=http_json) -> list[dict]:
    data = fetch(f"https://api.lever.co/v0/postings/{site}?mode=json")
    if not isinstance(data, list):  # unknown site: {"ok": false, "error": "Document not found"}
        raise ValueError(f"lever:{site}: {data}")
    out = []
    for j in data:
        cats = j.get("categories") or {}
        out.append({
            "uid": f"lever:{site}:{j['id']}", "ats": "lever", "board": site,
            "company": site, "title": (j.get("text") or "").strip(),
            "location": cats.get("location"), "workplace": j.get("workplaceType"),
            "posted_at": _ms_to_iso(j.get("createdAt")), "salary": None, "url": j.get("hostedUrl"),
        })
    return out


def ashby_jobs(board: str, fetch=http_json) -> list[dict]:
    data = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        comp = (j.get("compensation") or {}).get("compensationTierSummary")
        out.append({
            "uid": f"ashby:{board.lower()}:{j['id']}", "ats": "ashby", "board": board,
            "company": board, "title": (j.get("title") or "").strip(),
            "location": j.get("location"), "workplace": (j.get("workplaceType") or "").lower() or None,
            "posted_at": j.get("publishedAt"), "salary": comp, "url": j.get("jobUrl"),
        })
    return out


READERS = {"greenhouse": greenhouse_jobs, "lever": lever_jobs, "ashby": ashby_jobs}


def fetch_public(companies: list[str], fetch=http_json, pause: float = 1.0) -> tuple[list[dict], list[str]]:
    jobs, errors = [], []
    for i, entry in enumerate(companies):
        try:
            ats, board = parse_board(entry)
            jobs.extend(READERS[ats](board, fetch=fetch))
        except (ValueError, KeyError, urllib.error.URLError, json.JSONDecodeError) as e:
            errors.append(f"{entry}: {e}")
        if pause and i < len(companies) - 1:
            time.sleep(pause)  # one board at a time; Lever's robots.txt asks for Crawl-delay: 1
    return jobs, errors


# ---------------------------------------------------------------- Apify Actor

def is_job_item(item: dict) -> bool:
    """The Actor also writes free records to the dataset: unresolved boards, expired jobs and
    status messages. Keep only real job records."""
    if item.get("type") == "status":
        return False
    if item.get("status") not in (None, "active"):
        return False
    return bool(item.get("url") and item.get("title") and item.get("uid"))


def from_actor_item(item: dict) -> dict:
    return {
        "uid": item["uid"], "ats": item.get("ats"), "board": item.get("companySlug"),
        "company": item.get("companyName") or item.get("companySlug"),
        "title": (item.get("title") or "").strip(), "location": item.get("location"),
        "workplace": item.get("workArrangement"), "posted_at": item.get("postedAt"),
        "salary": item.get("salaryText"), "url": item.get("url"),
    }


def actor_input(companies, keywords, only_new=True, state_store="ats-new-jobs-feed", max_jobs=500) -> dict:
    body = {
        "companies": companies,
        "includeDescription": False,
        "onlyNewJobs": only_new,
        "stateStoreName": state_store,
        "maxTotalJobs": max_jobs,
    }
    if keywords:
        body["keywords"] = keywords
    return body


def run_actor(body: dict, token: str, max_usd: float, actor: str = APIFY_ACTOR, fetch=http_json) -> list[dict]:
    qs = urllib.parse.urlencode({"maxTotalChargeUsd": max_usd, "timeout": 280, "clean": "true"})
    url = f"{APIFY_BASE}/actors/{actor}/run-sync-get-dataset-items?{qs}"
    items = fetch(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=320,
    )
    if not isinstance(items, list):
        raise RuntimeError(f"Unexpected Apify response: {str(items)[:300]}")
    return items


# ---------------------------------------------------------------- dedupe and CSV

def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {row["uid"] for row in csv.DictReader(f) if row.get("uid")}


def keep_keywords(jobs: list[dict], keywords: list[str]) -> list[dict]:
    if not keywords:
        return jobs
    kws = [k.lower() for k in keywords]
    return [j for j in jobs if any(k in j["title"].lower() for k in kws)]


def select_new(jobs: list[dict], seen: set[str], today: str) -> list[dict]:
    new, batch = [], set()
    for j in jobs:
        if j["uid"] in seen or j["uid"] in batch:
            continue
        batch.add(j["uid"])
        new.append({**j, "first_seen": today})
    return new


def write_csv(path: Path, rows: list[dict], append: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    mode = "a" if append and exists else "w"
    with path.open(mode, newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if mode == "w":
            w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- CLI

def main(argv=None, fetch=http_json, now=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--source", choices=["public", "apify"], default=os.environ.get("JOBS_SOURCE", "public"))
    p.add_argument("--companies-file", default="companies.txt", type=Path)
    p.add_argument("--keyword", action="append", default=[], help="keep titles containing any of these (repeatable)")
    p.add_argument("--out-dir", default="data", type=Path)
    p.add_argument("--max-usd", type=float, default=float(os.environ.get("APIFY_MAX_USD", "0.50")),
                   help="apify only: hard cap on what one run can charge (default 0.50)")
    p.add_argument("--max-jobs", type=int, default=500, help="apify only: stop after this many jobs")
    p.add_argument("--dry-run", action="store_true", help="print what would be requested and exit")
    a = p.parse_args(argv)

    companies = read_companies(a.companies_file)
    if not companies:
        print("No companies listed in", a.companies_file, file=sys.stderr)
        return 2
    today = (now or datetime.now(timezone.utc)).date().isoformat()

    if a.source == "apify":
        body = actor_input(companies, a.keyword, max_jobs=a.max_jobs)
        if a.dry_run:
            print(json.dumps({"actor": APIFY_ACTOR, "maxTotalChargeUsd": a.max_usd, "input": body}, indent=2))
            return 0
        token = os.environ.get("APIFY_TOKEN")
        if not token:
            print("Set APIFY_TOKEN (Apify Console > Settings > API & Integrations).", file=sys.stderr)
            return 2
        try:
            items = run_actor(body, token, a.max_usd, fetch=fetch)
        except urllib.error.HTTPError as e:
            if e.code == 408:
                print("The run took longer than the 300 s sync limit. List fewer boards per run "
                      "or switch to the asynchronous run endpoint.", file=sys.stderr)
            else:
                print(f"Apify API error {e.code}: {e.read()[:300]!r}", file=sys.stderr)
            return 1
        skipped = [i for i in items if not is_job_item(i)]
        for i in skipped:
            if i.get("status") == "unresolved" or i.get("type") == "status":
                print(f"note: {i.get('input') or ''} {i.get('reason') or i.get('message') or i.get('status')}", file=sys.stderr)
        jobs = [from_actor_item(i) for i in items if is_job_item(i)]
        errors = []
    else:
        if a.dry_run:
            for c in companies:
                try:
                    print(parse_board(c))
                except ValueError as e:
                    print("skip:", e)
            return 0
        jobs, errors = fetch_public(companies, fetch=fetch)
        jobs = keep_keywords(jobs, a.keyword)
        for e in errors:
            print("error:", e, file=sys.stderr)

    all_path, new_path = a.out_dir / "jobs.csv", a.out_dir / "new_jobs.csv"
    new = select_new(jobs, load_seen(all_path), today)
    write_csv(all_path, new, append=True)
    write_csv(new_path, new, append=False)
    print(f"{len(jobs)} jobs read, {len(new)} new, written to {new_path}")
    return 1 if errors and not jobs else 0


if __name__ == "__main__":
    sys.exit(main())

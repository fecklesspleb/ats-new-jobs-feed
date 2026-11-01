"""Checks two n8n executions, the requests the mock server received and the CSV written.
Usage: check_run.py OUT1.json REQUESTS.jsonl CSV_DIR OUT2.json"""
import csv
import glob
import json
import sys

out, log, csv_dir, out2 = sys.argv[1:5]


def load(path):
    raw = open(path).read()
    return json.JSONDecoder().raw_decode(raw[raw.index("{"):])[0]


data = load(out)
run = data["data"]["resultData"]["runData"] if "data" in data else data["resultData"]["runData"]
err = data.get("data", data)["resultData"].get("error")
assert not err, err
rows = [i["json"] for i in run["Shape job row"][0]["data"]["main"][0]]
kept = len(run["Keep job records"][0]["data"]["main"][0])
got = len(run["Run ATS Jobs Scraper"][0]["data"]["main"][0])
req = [json.loads(l) for l in open(log)]
assert len(req) == 2, req
r = req[0]
assert r["path"].startswith("/v2/acts/fecklesspleb~ats-jobs-scraper/run-sync-get-dataset-items?"), r["path"]
assert "maxTotalChargeUsd=0.5" in r["path"] and "timeout=280" in r["path"], r["path"]
assert r["auth"] == "Bearer test-token"
b = r["body"]
assert b["onlyNewJobs"] is True and b["includeDescription"] is False and b["maxTotalJobs"] == 500
assert b["companies"][2] == "ashby:ramp" and b["keywords"] == ["engineer", "developer"], b
assert got == 5 and kept == 2, (got, kept)
assert [x["Job ID"] for x in rows] == ["ashby:ramp:34413f8d-26bf-4bbc-8ade-eb309a0e2245", "workday:nvidia:JR2001996"]
assert rows[1]["Company"] == "NVIDIA USA"
assert set(rows[0]) == {"Job ID", "Company", "Title", "Location", "Work arrangement", "Posted", "Salary", "URL", "ATS", "First seen"}
kept_new = len(run["Skip jobs already saved"][0]["data"]["main"][0])
assert kept_new == 2, kept_new
files = sorted(glob.glob(csv_dir + "/new_jobs_*.csv"))
assert len(files) == 1, files
with open(files[0], newline="", encoding="utf-8-sig") as f:  # n8n writes a UTF-8 BOM
    csv_rows = list(csv.DictReader(f))
    assert csv_rows and "Job ID" in csv_rows[0], (files[0], open(files[0], "rb").read()[:300])
assert [x["Job ID"] for x in csv_rows] == [x["Job ID"] for x in rows], csv_rows
d2 = load(out2)
r2 = d2.get("data", d2)["resultData"]
assert not r2.get("error"), r2.get("error")
run2 = r2["runData"]
assert len(run2["Skip jobs already saved"][0]["data"]["main"][0]) == 0
assert "Write CSV file" not in run2, "run 2 should not write a file"
print("PASS: HTTP node got", got, "records, filter kept", kept, "; run 1 wrote", files[0].rsplit("/", 1)[1],
      "with", len(csv_rows), "rows; run 2 (same mock data) kept 0 and wrote no file")
for x in rows:
    print(" ", json.dumps(x, ensure_ascii=False))
print("request:", r["path"])
print("body:", json.dumps(b))

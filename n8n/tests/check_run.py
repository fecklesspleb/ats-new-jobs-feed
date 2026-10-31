"""Checks the n8n execution output and the request the mock server received."""
import json
import sys

out, log = sys.argv[1], sys.argv[2]
raw = open(out).read()
data = json.loads(raw[raw.index("{"):])
run = data["data"]["resultData"]["runData"] if "data" in data else data["resultData"]["runData"]
err = data.get("data", data)["resultData"].get("error")
assert not err, err
rows = [i["json"] for i in run["Shape job row"][0]["data"]["main"][0]]
kept = len(run["Keep job records"][0]["data"]["main"][0])
got = len(run["Run ATS Jobs Scraper"][0]["data"]["main"][0])
req = [json.loads(l) for l in open(log)]
assert len(req) == 1, req
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
print("PASS: HTTP node got", got, "records, filter kept", kept)
for x in rows:
    print(" ", json.dumps(x, ensure_ascii=False))
print("request:", r["path"])
print("body:", json.dumps(b))

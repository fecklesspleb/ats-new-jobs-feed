"""Builds ats-new-jobs-to-csv.n8n.json. Edit here, then run: python3 build.py"""
import json
import uuid

NS = uuid.UUID("6f1c2a52-0b7e-4a8e-9a43-3f2f5d1b7c11")


def nid(name):
    return str(uuid.uuid5(NS, name))


ACTOR_URL = "https://api.apify.com/v2/actors/fecklesspleb~ats-jobs-scraper/run-sync-get-dataset-items"

MAIN_NOTE = """### How it works
For job seekers, recruiters and researchers who track hiring at specific companies. Every morning at 8 the workflow asks the Apify Actor fecklesspleb/ats-jobs-scraper for jobs on the career boards you list (Greenhouse, Lever, Ashby, Workday, Workable, Recruitee, Teamtailor). Monitoring mode (onlyNewJobs) returns only jobs it has not returned before. A filter drops the Actor's free status records, **Skip jobs already saved** drops any Job ID this workflow has written before, and the new jobs are saved as a CSV file named `new_jobs_YYYY-MM-DD_HHmmss.csv`. The file needs no credential. A run with no new jobs writes no file.

### Setup
1. Copy your Apify API token from Apify Console > Settings > API & Integrations. In n8n create a **Header Auth** credential: Name `Authorization`, Value `Bearer ` followed by your token. Select it in **Run ATS Jobs Scraper**.
2. In **Search settings**, set `companies` (board URLs or `ats:slug`), `keywords` (title words), `maxUsd` (spending cap per run) and `outputFolder`. n8n 2.x writes files only inside allowed folders: `/home/node/.n8n-files` is the default in the official Docker image; elsewhere use a folder listed in `N8N_RESTRICT_FILE_ACCESS_TO`.
3. Click **Execute workflow**, open the CSV, then activate.

Disclosure: fecklesspleb built this template and the paid Actor it calls ($0.002 per job returned). `maxUsd` is sent as `maxTotalChargeUsd`, which stops the run at your cap. Runs longer than 300 seconds return HTTP 408 to n8n while continuing on Apify, so keep each workflow to a few dozen boards. Built on n8n 2.45.4.

### Customization
You can replace the two file nodes with Google Sheets, a database or a webhook node; only the CSV output is tested. Use a different `stateStoreName` for each separate search."""


def sticky(name, content, x, y, w, h, color=None):
    p = {"content": content, "height": h, "width": w}
    if color is not None:
        p["color"] = color
    return {"parameters": p, "id": nid(name), "name": name, "type": "n8n-nodes-base.stickyNote",
            "typeVersion": 1, "position": [x, y]}


def assignment(name, value, typ):
    return {"id": nid("a-" + name), "name": name, "value": value, "type": typ}


nodes = [
    sticky("Main note", MAIN_NOTE, -620, -260, 520, 860),
    sticky("Section: settings", "## Schedule and settings\nChange the run time, boards, keywords and spending cap here.",
           -60, -60, 460, 360, 7),
    sticky("Section: scrape", "## Fetch new jobs from Apify\nOne API call per run. maxTotalChargeUsd stops spending at your cap.",
           420, -60, 460, 360, 7),
    sticky("Section: new", "## Keep only new jobs\nDrops status records, then any Job ID this workflow saved in an earlier run.",
           900, -60, 680, 360, 7),
    sticky("Section: csv", "## Save as CSV\nOne dated file per run with new jobs. No credential needed.",
           1600, -60, 480, 360, 7),
    {
        "parameters": {"rule": {"interval": [{"triggerAtHour": 8}]}},
        "id": nid("Every morning at 8"), "name": "Every morning at 8",
        "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [0, 100],
    },
    {
        "parameters": {
            "assignments": {"assignments": [
                assignment("companies", '["https://boards.greenhouse.io/airbnb", "https://jobs.lever.co/spotify", "ashby:ramp"]', "array"),
                assignment("keywords", '["engineer", "developer"]', "array"),
                assignment("stateStoreName", "n8n-new-jobs", "string"),
                assignment("maxUsd", "0.5", "number"),
                assignment("outputFolder", "/home/node/.n8n-files", "string"),
            ]},
            "options": {},
        },
        "id": nid("Search settings"), "name": "Search settings",
        "type": "n8n-nodes-base.set", "typeVersion": 3.4, "position": [200, 100],
    },
    {
        "parameters": {
            "method": "POST",
            "url": ACTOR_URL,
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
            "sendQuery": True,
            "queryParameters": {"parameters": [
                {"name": "maxTotalChargeUsd", "value": "={{ $json.maxUsd }}"},
                {"name": "timeout", "value": "280"},
                {"name": "clean", "value": "true"},
            ]},
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify({ companies: $json.companies, keywords: $json.keywords, onlyNewJobs: true, stateStoreName: $json.stateStoreName, includeDescription: false, maxTotalJobs: 500 }) }}",
            "options": {"timeout": 320000},
        },
        "id": nid("Run ATS Jobs Scraper"), "name": "Run ATS Jobs Scraper",
        "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [560, 100],
    },
    {
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                "conditions": [{
                    "id": nid("c-is-job"),
                    "leftValue": "={{ !$json.type && ($json.status === undefined || $json.status === null || $json.status === 'active') && !!$json.uid && !!$json.url }}",
                    "rightValue": "",
                    "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                }],
                "combinator": "and",
            },
            "looseTypeValidation": True,
            "options": {},
        },
        "id": nid("Keep job records"), "name": "Keep job records",
        "type": "n8n-nodes-base.filter", "typeVersion": 2.2, "position": [960, 100],
    },
    {
        "parameters": {
            "assignments": {"assignments": [
                assignment("Job ID", "={{ $json.uid }}", "string"),
                assignment("Company", "={{ $json.companyName || $json.companySlug }}", "string"),
                assignment("Title", "={{ $json.title }}", "string"),
                assignment("Location", "={{ ($json.locations || [$json.location]).filter(Boolean).join('; ') }}", "string"),
                assignment("Work arrangement", "={{ $json.workArrangement || '' }}", "string"),
                assignment("Posted", "={{ $json.postedAt ? String($json.postedAt).slice(0, 10) : '' }}", "string"),
                assignment("Salary", "={{ $json.salaryText || '' }}", "string"),
                assignment("URL", "={{ $json.url }}", "string"),
                assignment("ATS", "={{ $json.ats }}", "string"),
                assignment("First seen", "={{ $json.firstSeenAt ? String($json.firstSeenAt).slice(0, 10) : $now.toISODate() }}", "string"),
            ]},
            "options": {},
        },
        "id": nid("Shape job row"), "name": "Shape job row",
        "type": "n8n-nodes-base.set", "typeVersion": 3.4, "position": [1180, 100],
    },
    {
        "parameters": {
            "operation": "removeItemsSeenInPreviousExecutions",
            "dedupeValue": "={{ $json['Job ID'] }}",
            "options": {"scope": "workflow", "historySize": 10000},
        },
        "id": nid("Skip jobs already saved"), "name": "Skip jobs already saved",
        "type": "n8n-nodes-base.removeDuplicates", "typeVersion": 2, "position": [1400, 100],
    },
    {
        "parameters": {"operation": "csv", "options": {"headerRow": True}},
        "id": nid("Convert to CSV"), "name": "Convert to CSV",
        "type": "n8n-nodes-base.convertToFile", "typeVersion": 1.1, "position": [1700, 100],
    },
    {
        "parameters": {
            "operation": "write",
            "fileName": "={{ $('Search settings').first().json.outputFolder.replace(/\\/$/, '') }}/new_jobs_{{ $now.toFormat('yyyy-MM-dd_HHmmss') }}.csv",
            "options": {},
        },
        "id": nid("Write CSV file"), "name": "Write CSV file",
        "type": "n8n-nodes-base.readWriteFile", "typeVersion": 1, "position": [1920, 100],
    },
]

chain = ["Every morning at 8", "Search settings", "Run ATS Jobs Scraper", "Keep job records",
         "Shape job row", "Skip jobs already saved", "Convert to CSV", "Write CSV file"]
connections = {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(chain, chain[1:])}

wf = {
    "name": "Daily new jobs from Greenhouse, Lever, Ashby and Workday boards to a CSV file",
    "nodes": nodes,
    "connections": connections,
    "pinData": {},
    "settings": {"executionOrder": "v1"},
    "meta": {"templateCredsSetupCompleted": False},
    "tags": [],
}

if __name__ == "__main__":
    with open("ats-new-jobs-to-csv.n8n.json", "w", encoding="utf-8") as f:
        json.dump(wf, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("wrote ats-new-jobs-to-csv.n8n.json,", len(nodes), "nodes")

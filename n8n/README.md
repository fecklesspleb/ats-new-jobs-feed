# n8n: daily new jobs from company career boards to Google Sheets

An n8n workflow that runs once a day, asks the [ATS Jobs Scraper](https://apify.com/fecklesspleb/ats-jobs-scraper) Actor on Apify for jobs it has not returned before, and upserts them into a Google Sheet keyed on Job ID. Disclosure: I built and sell usage of that Actor.

File: `ats-new-jobs-to-google-sheets.n8n.json` (import it with **Workflows > Import from file**).

## Flow

1. **Every morning at 8** (Schedule Trigger).
2. **Search settings** (Edit Fields): `companies`, `keywords`, `stateStoreName`, `maxUsd`.
3. **Run ATS Jobs Scraper** (HTTP Request): `POST https://api.apify.com/v2/acts/fecklesspleb~ats-jobs-scraper/run-sync-get-dataset-items?maxTotalChargeUsd=<maxUsd>&timeout=280&clean=true` with the body `{companies, keywords, onlyNewJobs: true, stateStoreName, includeDescription: false, maxTotalJobs: 500}`. The response is a JSON array, which n8n turns into one item per record.
4. **Keep job records** (Filter): drops the Actor's free non-job records (boards that could not be resolved, status messages) and keeps records with a `uid` and `url`.
5. **Shape job row** (Edit Fields): Job ID, Company, Title, Location, Work arrangement, Posted, Salary, URL, ATS, First seen.
6. **Append or update job rows** (Google Sheets): matches on the Job ID column.

It uses only built-in n8n nodes, so it works on n8n Cloud and self-hosted n8n without community nodes.

## Setup

1. **Apify token.** Apify Console > Settings > API & Integrations. In n8n create a **Header Auth** credential named `Apify API`: Name `Authorization`, Value `Bearer <your token>`. Select it in **Run ATS Jobs Scraper**.
2. **Sheet.** Create a Google Sheet with this header row: `Job ID, Company, Title, Location, Work arrangement, Posted, Salary, URL, ATS, First seen`. Connect your Google Sheets credential in **Append or update job rows** and pick the document and tab.
3. **Settings.** In **Search settings**, list board URLs or `ats:slug` entries. Greenhouse, Lever, Ashby, Workable, Recruitee, Teamtailor, Polymer and HireHive boards work by URL or slug; Workday needs the full career site URL, for example `https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite`. Keywords match job titles, case-insensitive.
4. Run it once with **Execute workflow**, check the sheet, then activate it.

## Cost

The Actor charges $0.002 per job returned. There is no separate start fee in its pricing, and records about boards that could not be resolved are free. `maxUsd` (sent as `maxTotalChargeUsd`) caps each run; the default $0.50 covers 250 jobs. With `onlyNewJobs` on, the first run returns everything that matches and later runs return only jobs not returned before, so a day with 10 new matching jobs costs $0.02. Jobs left out because a run hit the cap are not marked as returned, so the next run picks them up.

## Limits

- The sync endpoint waits up to 300 seconds. A longer run returns HTTP 408 to n8n and keeps running on Apify; list fewer boards per workflow if that happens.
- Use a different `stateStoreName` for each separate search. Two workflows sharing one store name would split the new jobs between them.

## Tests

`tests/run_local_n8n.sh` imports the workflow into a throwaway local n8n (tested with n8n 2.45.4), builds a test copy (manual trigger, a local mock of the Apify endpoint, Google Sheets replaced by No Op) and executes it. `tests/check_run.py` asserts the request path, cost cap, auth header and body, that 5 records in (2 jobs, 1 unresolved board, 1 expired job, 1 status message) become 2 rows, and the row columns. No Apify credit is used.

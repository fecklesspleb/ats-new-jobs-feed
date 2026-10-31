# ats-new-jobs-feed

A small Python script and a GitHub Actions schedule that check company career boards once a day and write **only the jobs you have not seen before** to CSV.

- `data/new_jobs.csv`: jobs first seen on the latest run (overwritten each run).
- `data/jobs.csv`: every job ever seen, one row per job (appended).

Jobs are deduplicated by a stable key, `uid = ats:board:id` (for example `greenhouse:airbnb:7532824`). The job URL is not used as the key because Greenhouse URLs often point at the company's own careers site and can change when the company redesigns it.

## Two ways to get the jobs

| Source | What it reads | Cost | Needs |
|---|---|---|---|
| `public` (default) | The public JSON job-board endpoints of Greenhouse, Lever and Ashby | Free | Nothing |
| `apify` | The [ATS Jobs Scraper](https://apify.com/fecklesspleb/ats-jobs-scraper) Actor on Apify, through one `run-sync-get-dataset-items` API call | $0.002 per job returned | An Apify API token |

The `public` source uses only the Python standard library and these endpoints:

```
https://boards-api.greenhouse.io/v1/boards/{board}/jobs
https://api.lever.co/v0/postings/{site}?mode=json
https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true
```

It waits one second between boards (Lever's robots.txt asks for `Crawl-delay: 1`) and sends a User-Agent that names this project. Unlisted Ashby jobs (`isListed: false`) are skipped.

The `apify` source adds Workday, Workable, Recruitee, Teamtailor, Polymer and HireHive boards, parsed salary fields and a `workArrangement` value. It also keeps its own "already returned" state on Apify (`onlyNewJobs`), so a daily run is charged only for jobs it has not returned before. Disclosure: I built and sell usage of that Actor.

Both sources write the same columns:

`uid, ats, board, company, title, location, workplace, posted_at, salary, url, first_seen`

## Run it locally

Python 3.9 or newer, no packages to install.

```bash
git clone https://github.com/fecklesspleb/ats-new-jobs-feed
cd ats-new-jobs-feed
python3 new_jobs.py --keyword engineer
python3 new_jobs.py --keyword engineer   # second run: 0 new
```

On October 31, 2026 the three sample boards listed 462 jobs (Airbnb 202 on Greenhouse, Spotify 89 on Lever, Ramp 171 on Ashby). The first run above wrote 128 jobs with "engineer" in the title; the second run, minutes later, wrote 0.

Edit `companies.txt` to choose boards. One per line, either `ats:board` or a board URL:

```
greenhouse:airbnb
https://jobs.lever.co/spotify
ashby:ramp
https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite   # apify source only
```

To find a company's board name, open its careers page and look for a link to `boards.greenhouse.io/<board>`, `job-boards.greenhouse.io/<board>`, `jobs.lever.co/<site>` or `jobs.ashbyhq.com/<board>`.

Options:

```
--source public|apify     default public (or env JOBS_SOURCE)
--keyword WORD            keep titles containing WORD, case-insensitive; repeatable
--companies-file PATH     default companies.txt
--out-dir PATH            default data
--max-usd 0.50            apify only: hard cap on what one run can charge (or env APIFY_MAX_USD)
--max-jobs 500            apify only: stop after this many jobs
--dry-run                 print the parsed boards (public) or the Actor request (apify) and exit, no network
```

To use the Actor:

```bash
export APIFY_TOKEN=...   # Apify Console > Settings > API & Integrations
python3 new_jobs.py --source apify --keyword engineer --dry-run   # check the request first
python3 new_jobs.py --source apify --keyword engineer
```

The token is sent in the `Authorization` header, never in the URL. The run is capped with `maxTotalChargeUsd`, and the Actor stops cleanly when the next job would go over the cap.

## Run it every day with GitHub Actions

`.github/workflows/new-jobs.yml` runs at 11:17 UTC every day (and on demand from the Actions tab). It runs the offline tests, runs `new_jobs.py`, and commits `data/jobs.csv` and `data/new_jobs.csv` when they change.

1. Fork or copy this repository.
2. Edit `companies.txt`.
3. Optional, under Settings > Secrets and variables > Actions:
   - Variable `KEYWORDS`, comma separated, for example `engineer, data scientist`.
   - To use the Actor: variable `JOBS_SOURCE` = `apify`, secret `APIFY_TOKEN`, and optionally variable `APIFY_MAX_USD`.
4. Open the Actions tab, enable workflows if asked, and run **New jobs feed** once by hand.

GitHub disables scheduled workflows in public repositories after 60 days with no repository activity, and scheduled workflows are off by default in a fork. The workflow commits only when the CSVs change (a day with new jobs, or the first quiet day after one), so a quiet watch list can switch itself off; check the Actions tab now and then.

## What a run costs

`public` source: nothing. The script makes one request per board, and GitHub Actions minutes are free for public repositories on standard runners.

`apify` source: the Actor's price is $0.002 per job returned (pay per event, event `job`). There is no separate start fee in its pricing, and records about boards that could not be read are free.

| Run | Jobs returned | Charge |
|---|---|---|
| First run, the three sample boards, keyword `engineer` | about 128 | about $0.26 |
| First run, the three sample boards, no keyword | 462 listed, stopped at the $0.50 default cap | $0.50 (250 jobs) |
| A later daily run with 10 new matching jobs | 10 | $0.02 |

The job counts come from the boards' public endpoints on October 31, 2026; your counts will differ. When a run stops at the cap, the jobs it did not return are not marked as seen, so the next run picks them up.

If you only need one ATS, the [Greenhouse](https://apify.com/fecklesspleb/greenhouse-jobs-scraper), [Lever](https://apify.com/fecklesspleb/lever-jobs-scraper) and [Ashby](https://apify.com/fecklesspleb/ashby-jobs-scraper) Actors cost $0.001 per job. This script calls the multi-ATS Actor.

## n8n version

`n8n/` holds the same idea as an n8n workflow: a schedule, one HTTP Request to the Actor, a filter, and an upsert into Google Sheets keyed on Job ID. See `n8n/README.md`.

## Tests

```bash
python3 -m unittest discover -s tests -v          # offline, uses saved responses in tests/fixtures
LIVE=1 python3 -m unittest tests.test_new_jobs.LivePublic -v   # also reads the three public boards
```

The offline tests never touch the network or Apify. They check board parsing, filtering, dedupe across two runs, the exact Apify request (URL, cost cap, header, body fields against the Actor's input schema), that the Actor's non-job records (unresolved boards, expired jobs, status messages) are dropped, and the 408 timeout path.

## Limits

- Greenhouse and Ashby return a board's full list in one response (Airbnb's Greenhouse board is about 155 KB; Ramp's Ashby board is about 3 MB with descriptions). Lever supports `limit` and `skip`; this script reads each Lever site in one request.
- A Lever site that does not exist returns 404; one that exists with no openings returns `[]`.
- The Apify sync endpoint waits at most 300 seconds. If a run takes longer you get HTTP 408 (the run keeps going on Apify); list fewer boards per run.
- Only boards you list are checked. This is not a search engine across companies.

## License

MIT

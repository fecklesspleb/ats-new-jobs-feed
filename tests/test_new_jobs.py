"""Offline tests. No network, no Apify credit: every HTTP call is answered from tests/fixtures.

The Greenhouse, Lever and Ashby fixtures are trimmed copies of real public responses (Oct 31, 2026).
apify_items.json holds the two sample records from the ats-jobs-scraper README (build 1.0.14) plus
one record of each free, non-job kind the Actor can write: unresolved, expired and status.

Set LIVE=1 to also run one test against the real public endpoints (still free).
"""
import csv
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import io
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import new_jobs  # noqa: E402

FX = ROOT / "tests" / "fixtures"
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


class FakeHTTP:
    """Stands in for new_jobs.http_json and records each call."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, data=None, headers=None, timeout=30):
        self.calls.append({"url": url, "data": data, "headers": headers or {}})
        if "boards-api.greenhouse.io" in url:
            return load("greenhouse_airbnb.json")
        if "api.lever.co" in url:
            if "/nope" in url:
                return {"ok": False, "error": "Document not found"}
            return load("lever_spotify.json")
        if "api.ashbyhq.com" in url:
            return load("ashby_ramp.json")
        if "api.apify.com" in url:
            return load("apify_items.json")
        raise AssertionError("unexpected URL " + url)


class Workdir:
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "companies.txt").write_text(
            "# comment\ngreenhouse:airbnb\nhttps://jobs.lever.co/spotify\nashby:ramp\n", encoding="utf-8")
        return d

    def __exit__(self, *exc):
        self.tmp.cleanup()


def rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class ReadCompanies(unittest.TestCase):
    def test_comments(self):
        with Workdir() as d:
            f = d / "c.txt"
            f.write_text("# full line\n\nashby:ramp   # inline note\n  https://jobs.lever.co/spotify\n", encoding="utf-8")
            self.assertEqual(new_jobs.read_companies(f), ["ashby:ramp", "https://jobs.lever.co/spotify"])


class ParseBoard(unittest.TestCase):
    def test_prefixes_and_urls(self):
        P = new_jobs.parse_board
        self.assertEqual(P("greenhouse:airbnb"), ("greenhouse", "airbnb"))
        self.assertEqual(P("https://boards.greenhouse.io/airbnb"), ("greenhouse", "airbnb"))
        self.assertEqual(P("https://job-boards.greenhouse.io/airbnb/jobs/123"), ("greenhouse", "airbnb"))
        self.assertEqual(P("jobs.lever.co/spotify"), ("lever", "spotify"))
        self.assertEqual(P("https://jobs.ashbyhq.com/ramp"), ("ashby", "ramp"))

    def test_rejects_unsupported(self):
        with self.assertRaises(ValueError):
            new_jobs.parse_board("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite")


class PublicSource(unittest.TestCase):
    def test_first_run_writes_all_then_second_run_writes_none(self):
        fake = FakeHTTP()
        with Workdir() as d:
            new_jobs.time.sleep = lambda s: None
            args = ["--source", "public", "--companies-file", str(d / "companies.txt"), "--out-dir", str(d / "data")]
            self.assertEqual(new_jobs.main(args, fetch=fake, now=NOW), 0)
            first = rows(d / "data" / "new_jobs.csv")
            self.assertEqual(len(first), 9)  # 3 per fixture
            self.assertEqual(len({r["uid"] for r in first}), 9)
            self.assertEqual(first[0]["first_seen"], "2026-10-31")
            # Lever: same title three times, three different IDs -> three rows
            lever_titles = [r["title"] for r in first if r["ats"] == "lever"]
            self.assertEqual(len(lever_titles), 3)
            # Ashby title has a leading space in the API; it is stripped
            self.assertTrue(all(not r["title"].startswith(" ") for r in first))
            # Ashby salary summary is kept
            self.assertTrue(any(r["salary"] for r in first if r["ats"] == "ashby"))

            self.assertEqual(new_jobs.main(args, fetch=fake, now=NOW), 0)
            self.assertEqual(rows(d / "data" / "new_jobs.csv"), [])
            self.assertEqual(len(rows(d / "data" / "jobs.csv")), 9)

    def test_keyword_filter(self):
        fake = FakeHTTP()
        with Workdir() as d:
            new_jobs.time.sleep = lambda s: None
            args = ["--companies-file", str(d / "companies.txt"), "--out-dir", str(d / "data"), "--keyword", "ENGINEER"]
            new_jobs.main(args, fetch=fake, now=NOW)
            titles = [r["title"] for r in rows(d / "data" / "new_jobs.csv")]
            self.assertTrue(titles)
            self.assertTrue(all("engineer" in t.lower() for t in titles))

    def test_unknown_lever_site_is_an_error_not_a_crash(self):
        fake = FakeHTTP()
        jobs, errors = new_jobs.fetch_public(["lever:nope", "ashby:ramp"], fetch=fake, pause=0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(jobs), 3)

    def test_unlisted_ashby_jobs_are_skipped(self):
        data = load("ashby_ramp.json")
        data["jobs"][0]["isListed"] = False
        jobs = new_jobs.ashby_jobs("ramp", fetch=lambda url: data)
        self.assertEqual(len(jobs), 2)


class ApifySource(unittest.TestCase):
    def test_request_shape_and_filtering(self):
        fake = FakeHTTP()
        with Workdir() as d:
            os.environ["APIFY_TOKEN"] = "test-token"
            args = ["--source", "apify", "--companies-file", str(d / "companies.txt"),
                    "--out-dir", str(d / "data"), "--keyword", "engineer", "--max-usd", "0.25"]
            self.assertEqual(new_jobs.main(args, fetch=fake, now=NOW), 0)
            call = fake.calls[0]
            self.assertIn("/actors/fecklesspleb~ats-jobs-scraper/run-sync-get-dataset-items?", call["url"])
            self.assertIn("maxTotalChargeUsd=0.25", call["url"])
            self.assertEqual(call["headers"]["Authorization"], "Bearer test-token")
            self.assertNotIn("test-token", call["url"])
            body = json.loads(call["data"])
            self.assertEqual(body["companies"], ["greenhouse:airbnb", "https://jobs.lever.co/spotify", "ashby:ramp"])
            self.assertEqual(body["keywords"], ["engineer"])
            self.assertTrue(body["onlyNewJobs"])
            self.assertFalse(body["includeDescription"])
            out = rows(d / "data" / "new_jobs.csv")
            # 5 records in the fixture, 2 are jobs; unresolved, expired and status records are dropped
            self.assertEqual([r["uid"] for r in out],
                             ["ashby:ramp:34413f8d-26bf-4bbc-8ade-eb309a0e2245", "workday:nvidia:JR2001996"])
            # Workday records carry companyName (there is no "company" field)
            self.assertEqual(out[1]["company"], "NVIDIA USA")
            self.assertEqual(out[0]["salary"], "$211.4K – $290.6K • Offers Equity")

    def test_input_fields_exist_in_actor_schema(self):
        schema = load("ats_jobs_scraper_input_schema.json")
        body = new_jobs.actor_input(["ashby:ramp"], ["engineer"])
        self.assertEqual(set(body) - set(schema["properties"]), set())

    def test_missing_token(self):
        with Workdir() as d:
            os.environ.pop("APIFY_TOKEN", None)
            rc = new_jobs.main(["--source", "apify", "--companies-file", str(d / "companies.txt")], fetch=FakeHTTP())
            self.assertEqual(rc, 2)

    def test_sync_timeout_message(self):
        def boom(*a, **k):
            raise urllib.error.HTTPError("u", 408, "Request Timeout", {}, io.BytesIO(b""))
        with Workdir() as d:
            os.environ["APIFY_TOKEN"] = "t"
            rc = new_jobs.main(["--source", "apify", "--companies-file", str(d / "companies.txt"),
                                "--out-dir", str(d / "data")], fetch=boom)
            self.assertEqual(rc, 1)
            self.assertFalse((d / "data" / "jobs.csv").exists())


@unittest.skipUnless(os.environ.get("LIVE") == "1", "set LIVE=1 to hit the public endpoints")
class LivePublic(unittest.TestCase):
    def test_live_boards(self):
        jobs, errors = new_jobs.fetch_public(["greenhouse:airbnb", "lever:spotify", "ashby:ramp"])
        self.assertEqual(errors, [])
        by_ats = {a: sum(1 for j in jobs if j["ats"] == a) for a in ("greenhouse", "lever", "ashby")}
        print("\nlive job counts:", by_ats)
        self.assertTrue(all(by_ats.values()))
        self.assertEqual(len({j["uid"] for j in jobs}), len(jobs))


if __name__ == "__main__":
    unittest.main(verbosity=2)

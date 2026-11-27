"""Monthly: rebuild data/boards.json from the SimplifyJobs new-grad list and Common Crawl.

    python -m jobfinder.discover               # full rebuild (2 most recent crawls)
    python -m jobfinder.discover --crawls 1    # faster
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from pathlib import Path

import httpx

from .filters import location_class
from .models import Board
from .run import SIMPLIFY_URL
from .sources import USER_AGENT, list_board, make_client, make_limits
from .urls import parse_ats_url

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "boards.json"
CC_COLLINFO = "https://index.commoncrawl.org/collinfo.json"
CC_QUERIES = [
    ("boards.greenhouse.io/*", "prefix"), ("job-boards.greenhouse.io/*", "prefix"), ("jobs.lever.co/*", "prefix"),
    ("jobs.ashbyhq.com/*", "prefix"), ("apply.workable.com/*", "prefix"), ("myworkdayjobs.com", "domain"),
    ("icims.com", "domain"), ("oraclecloud.com", "domain"),
]
MAX_CC_PAGES = 60          # per query; oraclecloud.com is mostly non-careers pages
SKIP_ATS = {"amazon", "apple", "microsoft", "google", "tiktok", "ibm"}   # read directly (bigtech.py)


def add(boards: dict, ats: str, token: str | None, name: str, tier: str) -> None:
    if not token or ats in SKIP_ATS:
        return
    key = (ats, token)
    if key not in boards:
        boards[key] = Board(ats=ats, token=token, name=name, tier=tier)
    elif tier == "newgrad":
        boards[key].tier = "newgrad"
        boards[key].name = boards[key].name or name


async def from_simplify(client: httpx.AsyncClient, boards: dict) -> int:
    listings = (await client.get(SIMPLIFY_URL, timeout=120)).json()
    n = 0
    for x in listings:
        parsed = parse_ats_url(x.get("url") or "")
        if parsed:
            add(boards, parsed[0], parsed[1], x.get("company_name") or "", "newgrad")
            n += 1
    return n


async def _cc_get(client, url, params, tries=5):
    for i in range(tries):
        try:
            r = await client.get(url, params=params, timeout=180)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
        except httpx.HTTPError:
            pass
        await asyncio.sleep(10 * (i + 1))   # Common Crawl asks clients to back off on 503s
    return None


async def from_common_crawl(client: httpx.AsyncClient, boards: dict, crawls: int) -> int:
    indexes = [c["id"] for c in (await client.get(CC_COLLINFO, timeout=60)).json()[:crawls]]
    n = 0
    for idx in indexes:
        api = f"https://index.commoncrawl.org/{idx}-index"
        for url, match in CC_QUERIES:
            base = {"url": url, "output": "json", "fl": "url"}
            if match == "domain":
                base["matchType"] = "domain"
            r = await _cc_get(client, api, {**base, "showNumPages": "true"})
            pages = (r.json().get("pages", 0) if r else 0)
            for page in range(min(pages, MAX_CC_PAGES)):
                r = await _cc_get(client, api, {**base, "page": str(page)})
                if not r:
                    continue
                for line in r.text.splitlines():
                    try:
                        u = json.loads(line)["url"]
                    except (ValueError, KeyError):
                        continue
                    parsed = parse_ats_url(u)
                    if parsed:
                        add(boards, parsed[0], parsed[1], "", "broad")
                        n += 1
            print(f"  {idx} {url}: {pages} pages, {len(boards)} boards so far")
    return n


async def probe(boards: list[Board], concurrency: int) -> list[Board]:
    """Keep boards that respond with jobs, and (except Workday) have at least one non-foreign job."""
    keep = []
    async with make_client() as client:
        limits = make_limits(concurrency)
        results = await asyncio.gather(*(list_board(client, b, limits, max_pages=1) for b in boards))
    for b, jobs in zip(boards, results):
        if not jobs:
            continue
        if b.ats not in ("workday", "icims", "oraclecloud") and not any(j.country_hint == "US" or location_class(j.location) != "non-US" for j in jobs):
            continue
        if not b.name:
            b.name = jobs[0].company if jobs[0].company != b.token else ""
        keep.append(b)
    return keep


async def main_async(args) -> None:
    t0 = time.time()
    boards: dict = {}
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        print(f"SimplifyJobs links: {await from_simplify(client, boards)}  -> {len(boards)} boards")
        if args.crawls:
            print(f"Common Crawl links: {await from_common_crawl(client, boards, args.crawls)}  -> {len(boards)} boards")
    found = list(boards.values())
    print("found by ATS:", dict(Counter(b.ats for b in found)))
    live = await probe(found, args.concurrency)
    live.sort(key=lambda b: (b.tier != "newgrad", b.ats, b.token.lower()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps([b.to_dict() for b in live], indent=0))
    print("live by ATS:", dict(Counter(b.ats for b in live)), "| by tier:", dict(Counter(b.tier for b in live)))
    print(f"wrote {len(live)} boards to {OUT} in {time.time() - t0:.0f}s")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--crawls", type=int, default=2, help="how many recent Common Crawl indexes to sweep (0 = skip)")
    p.add_argument("--concurrency", type=int, default=32)
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()

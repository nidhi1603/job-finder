"""Keep data/boards.json (the company job boards the hourly run reads) up to date.

Boards come from the SimplifyJobs new-grad list (every run) and Common Crawl (re-swept every 30 days, saved to
data/candidates.json). Each board is then "probed" once to see if it is live with US jobs; results are saved to
data/probes.json and re-checked every 45 days. Probing stops at the time budget and the next run continues where
it left off, so a run never loses its work to GitHub's time limit.

    python -m jobfinder.discover                    # daily: new-grad list + probe whatever is due
    python -m jobfinder.discover --recrawl          # also re-sweep Common Crawl now
    python -m jobfinder.discover --budget-min 30    # stop probing after 30 minutes in all
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .filters import location_class
from .models import Board
from .run import SIMPLIFY_URL
from .sources import USER_AGENT, list_board, make_client, make_limits
from .urls import parse_ats_url

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "boards.json"
CANDIDATES = ROOT / "data" / "candidates.json"   # every board Common Crawl turned up (not yet checked)
PROBES = ROOT / "data" / "probes.json"           # "ats|token" -> [checked on, live 1/0, company name]
RECRAWL_DAYS = 30
REPROBE_DAYS = 45
CHUNK = 300                                       # boards probed between progress saves
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
        results = await asyncio.gather(*(list_board(client, b, limits, max_pages=1) for b in boards), return_exceptions=True)
    for b, jobs in zip(boards, results):
        if not jobs or isinstance(jobs, BaseException):
            continue
        if b.ats not in ("workday", "icims", "oraclecloud") and not any(j.country_hint == "US" or location_class(j.location) != "non-US" for j in jobs):
            continue
        if not b.name:
            b.name = jobs[0].company if jobs[0].company != b.token else ""
        keep.append(b)
    return keep


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_since(day: str | None) -> float:
    if not day:
        return 1e9
    return (datetime.now(timezone.utc) - datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)).days


def _dump(path: Path, obj) -> None:
    """One entry per line, sorted, so daily commits only add small diffs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, dict):
        body = ",\n".join(f"{json.dumps(k)}:{json.dumps(v, separators=(',', ':'))}" for k, v in sorted(obj.items()))
        path.write_text("{\n" + body + "\n}\n")
    else:
        path.write_text(json.dumps(obj, indent=0) + "\n")


def _pkey(b: Board) -> str:
    return f"{b.ats}|{b.token}"


def write_boards(boards: dict, probes: dict) -> list[Board]:
    live = []
    for b in boards.values():
        p = probes.get(_pkey(b))
        if p and p[1]:
            b.name = b.name or p[2]
            live.append(b)
    live.sort(key=lambda b: (b.tier != "newgrad", b.ats, b.token.lower()))
    _dump(OUT, [b.to_dict() for b in live])
    return live


async def main_async(args) -> None:
    t0 = time.time()
    deadline = t0 + args.budget_min * 60
    boards: dict = {}
    cand = json.loads(CANDIDATES.read_text()) if CANDIDATES.exists() else {}
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        print(f"SimplifyJobs links: {await from_simplify(client, boards)}  -> {len(boards)} boards")
        if args.crawls and (args.recrawl or _days_since(cand.get("date")) >= RECRAWL_DAYS):
            crawled: dict = {}
            print(f"Common Crawl links: {await from_common_crawl(client, crawled, args.crawls)}  -> {len(crawled)} boards")
            cand = {"date": _today(), "boards": sorted(f"{b.ats}|{b.token}" for b in crawled.values())}
            _dump(CANDIDATES, cand)
    for k in cand.get("boards", []):
        ats, token = k.split("|", 1)
        add(boards, ats, token, "", "broad")
    print("boards by ATS:", dict(Counter(b.ats for b in boards.values())))

    probes = json.loads(PROBES.read_text()) if PROBES.exists() else {}
    due = [b for b in boards.values() if _days_since((probes.get(_pkey(b)) or [None])[0]) >= REPROBE_DAYS]
    # new-grad boards first, then never-checked boards, then the longest-unchecked
    due.sort(key=lambda b: (b.tier != "newgrad", _pkey(b) in probes, (probes.get(_pkey(b)) or [""])[0]))
    print(f"{len(due)} boards due for a check")
    done = 0
    for i in range(0, len(due), CHUNK):
        if time.time() > deadline:
            print(f"time budget reached; {len(due) - done} boards left for the next run")
            break
        chunk = due[i:i + CHUNK]
        live = {_pkey(b) for b in await probe(chunk, args.concurrency)}
        for b in chunk:
            probes[_pkey(b)] = [_today(), int(_pkey(b) in live), b.name or ""]
        done += len(chunk)
        _dump(PROBES, probes)
        print(f"  checked {done}/{len(due)} ({sum(1 for b in chunk if _pkey(b) in live)} live in this batch) at {time.time() - t0:.0f}s")
    live = write_boards(boards, probes)
    print("live by ATS:", dict(Counter(b.ats for b in live)), "| by tier:", dict(Counter(b.tier for b in live)))
    print(f"wrote {len(live)} boards to {OUT} in {time.time() - t0:.0f}s")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--crawls", type=int, default=2, help="how many recent Common Crawl indexes to sweep (0 = skip)")
    p.add_argument("--recrawl", action="store_true", help="re-sweep Common Crawl even if the saved sweep is recent")
    p.add_argument("--budget-min", type=float, default=300, help="stop probing after this many minutes in all")
    p.add_argument("--concurrency", type=int, default=32)
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()

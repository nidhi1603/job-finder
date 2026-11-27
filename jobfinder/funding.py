"""Daily: find startups that raised money in the last 6 months, and their job boards.

    python -m jobfinder.funding                 # update data/funded.json
    python -m jobfinder.funding --sec-days 3    # smaller SEC backfill (testing)

Sources (all free):
  - Y Combinator's company directory: companies from batches whose Demo Day falls in the window.
  - SEC Form D filings: US companies reporting a sale of securities (an investor round), tech and
    health-tech industries, $1M+ sold. SEC asks automated clients to identify themselves, so this
    source runs only when SEC_CONTACT (an email) is set.
  - TechCrunch funding headlines ("X raises $20M Series A").

Each company is matched to a job board once (website careers links first, then guessed board
names on Greenhouse/Lever/Ashby/Workable). Unmatched companies are retried every 21 days.
"""
from __future__ import annotations

import argparse
import asyncio
import html as htmllib
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from .models import Board
from .sources import USER_AGENT, _request
from .urls import parse_ats_url

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "funded.json"
WINDOW_DAYS = 182
RECHECK_DAYS = 21
BIG_ATS = {"amazon", "apple", "microsoft", "google", "tiktok", "ibm"}

# ------------------------------------------------------------------ helpers

_LEGAL = re.compile(r"[,.]?\s+(inc|incorporated|corp|corporation|llc|l\.l\.c|ltd|limited|co|company|pbc|plc)\.?$", re.I)
_SOFT = re.compile(r"\s+(technologies|technology|labs|ai|hq|software|systems|health|bio|therapeutics)$", re.I)


def clean_name(name: str) -> str:
    n = re.sub(r"\s+\(CIK.*$", "", htmllib.unescape(name)).strip()
    for _ in range(2):
        n = _LEGAL.sub("", n).strip()
    return n


def key_of(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", clean_name(name).lower())


def money(amount: float) -> str:
    return f"${amount / 1e9:.1f}B" if amount >= 1e9 else f"${amount / 1e6:.0f}M" if amount >= 1e6 else f"${amount / 1e3:.0f}K"


# ------------------------------------------------------------------ Y Combinator

_DEMO_MONTH = {"W": 3, "X": 6, "P": 6, "S": 9, "F": 12}   # X/P = spring batch


def yc_batches(today: date, start: date) -> list[tuple[str, date]]:
    out = []
    for yy in range(today.year - 2001, today.year - 1999 + 1):
        for season, month in _DEMO_MONTH.items():
            demo = date(2000 + yy, month, 15)
            if start <= demo <= today + timedelta(days=200):
                out.append((f"{season}{yy:02d}", demo))
    return out


async def from_yc(client: httpx.AsyncClient, today: date, start: date) -> list[dict]:
    found = []
    for batch, demo in yc_batches(today, start):
        url = f"https://api.ycombinator.com/v0.1/companies?batch={batch}"
        while url:
            r = await _request(client, "GET", url)
            if r is None or r.status_code != 200:
                break
            d = r.json()
            for c in d.get("companies") or []:
                if c.get("status") not in (None, "Active"):
                    continue
                regions = " ".join(c.get("regions") or []) + " " + " ".join(c.get("locations") or [])
                if "United States" not in regions and "America / Canada" not in regions and "Remote" not in regions:
                    continue
                found.append({"name": c.get("name") or "", "website": c.get("website") or "", "source": "yc", "yc_slug": c.get("slug") or "",
                              "raised": f"Y Combinator {batch}", "date": min(demo, today).isoformat()})
            url = d.get("nextPage")
    return found


# ------------------------------------------------------------------ SEC Form D

FUND_NAME = re.compile(
    r"\b(fund|funds|l\.?p\.?|llp|partners|capital|holdings?|ventures?|investors?|investments?|properties|property|realty|"
    r"real estate|reit|trust|spv|series|portfolio|opportunit\w*|income|equity|credit|lending|homes?|apartments?|land|"
    r"acquisitions?|master|feeder|offshore|onshore|co-?invest\w*|syndicate|management|advisors?|asset|assets|energy|"
    r"oil|gas|mining|minerals|solar|wind|hotel|church|school|foundation|dst|mortgage|loan|notes)\b", re.I)
KEEP_INDUSTRY = re.compile(r"technology|computers|telecommunications|biotechnology|other health care|business services|other banking", re.I)
EFTS = "https://efts.sec.gov/LATEST/search-index"


def _tag(xml: str, name: str) -> str:
    m = re.search(rf"<{name}>(.*?)</{name}>", xml, re.S)
    return htmllib.unescape(m.group(1).strip()) if m else ""


async def from_sec(client: httpx.AsyncClient, contact: str, since: date, today: date) -> list[dict]:
    hdr = {"User-Agent": f"personal-job-finder {contact}", "Accept": "application/json"}
    found, filings = [], []
    day = since
    while day <= today:                                   # weekly chunks (EFTS caps a query at 10,000 hits)
        end = min(day + timedelta(days=6), today)
        offset = 0
        while True:
            r = await _request(client, "GET", f"{EFTS}?forms=D&dateRange=custom&startdt={day}&enddt={end}&from={offset}", headers=hdr)
            await asyncio.sleep(0.15)
            if r is None or r.status_code != 200:
                break
            hits = r.json().get("hits", {}).get("hits") or []
            for h in hits:
                s = h.get("_source") or {}
                name = (s.get("display_names") or [""])[0]
                if s.get("form") != "D" or not name or FUND_NAME.search(clean_name(name)):
                    continue
                if not set(s.get("biz_states") or []) - {""}:
                    continue
                filings.append((h["_id"], (s.get("ciks") or ["0"])[0], name, s.get("file_date") or str(end)))
            offset += len(hits)
            if len(hits) < 100 or offset >= 9900:
                break
        day = end + timedelta(days=1)
    print(f"  SEC: {len(filings)} operating-company filings to inspect")
    for fid, cik, name, filed in filings:
        adsh, _, doc = fid.partition(":")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh.replace('-', '')}/{doc or 'primary_doc.xml'}"
        r = await _request(client, "GET", url, headers={**hdr, "Accept": "application/xml"})
        await asyncio.sleep(0.15)                       # stay well under SEC's 10 requests/second
        if r is None or r.status_code != 200:
            continue
        xml = r.text
        industry = _tag(xml, "industryGroupType")
        if _tag(xml, "investmentFundType") or not KEEP_INDUSTRY.search(industry):
            continue
        try:
            sold = float(_tag(xml, "totalAmountSold") or 0)
        except ValueError:
            sold = 0
        if sold < 1_000_000:
            continue
        found.append({"name": clean_name(_tag(xml, "entityName") or name), "website": "", "source": "sec",
                      "raised": f"{money(sold)} raised (SEC Form D, {industry})", "date": filed})
    return found


# ------------------------------------------------------------------ TechCrunch headlines

TC_FEEDS = ["https://techcrunch.com/category/venture/feed/", "https://techcrunch.com/tag/funding/feed/"]
RAISE = re.compile(   # company name is case-sensitive (capitalised words right before the verb); the rest isn't
    r"(?P<name>[A-Z][\w.&'’-]*(?:\s+[A-Z][\w.&'’-]*){0,3})\s+(?i:raises|secures|lands|closes|nabs|bags|announces|gets|snags)\b"
    r"[^$]{0,40}\$(?P<amt>[\d.]+)\s?(?P<unit>[MBK]|(?i:million|billion))\b(?P<rest>.*)")
ROUND = re.compile(r"\b(pre-seed|seed|series [a-h])\b", re.I)


async def from_techcrunch(client: httpx.AsyncClient, start: date) -> list[dict]:
    found = []
    for feed in TC_FEEDS:
        r = await _request(client, "GET", feed, headers={"Accept": "application/rss+xml, text/xml"})
        if r is None or r.status_code != 200:
            continue
        for item in re.findall(r"<item>(.*?)</item>", r.text, re.S):
            title = htmllib.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", _tag(item, "title")))
            m = RAISE.search(title)
            if not m:
                continue
            try:
                pub = datetime.strptime(_tag(item, "pubDate")[:16], "%a, %d %b %Y").date()
            except ValueError:
                pub = date.today()
            if pub < start:
                continue
            rnd = ROUND.search(title)
            unit = m.group("unit")[0].upper()
            found.append({"name": m.group("name").strip(), "website": "", "source": "techcrunch",
                          "raised": f"${m.group('amt')}{unit}{' ' + rnd.group(1).title() if rnd else ''} (TechCrunch)",
                          "date": pub.isoformat()})
    return found


# ------------------------------------------------------------------ match companies to job boards

def _slugs(name: str) -> tuple[list[str], list[str]]:
    """(strict slugs from the full name, loose slugs with words like 'Labs'/'AI' removed)."""
    full = clean_name(name).lower()
    loose = _SOFT.sub("", full)
    strict = {re.sub(r"[^a-z0-9]", "", full), re.sub(r"[^a-z0-9]+", "-", full).strip("-")}
    looser = {re.sub(r"[^a-z0-9]", "", loose), re.sub(r"[^a-z0-9]+", "-", loose).strip("-")} - strict
    return [s for s in strict if len(s) >= 3], [s for s in looser if len(s) >= 6]


def _same(a: str, b: str) -> bool:
    a, b = key_of(a), key_of(b)
    return bool(a and b and (a in b or b in a))


async def _probe(client, ats: str, slug: str, name: str, verify_name: bool) -> bool:
    urls = {"greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
            "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=1",
            "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
            "workable": f"https://apply.workable.com/api/v1/widget/accounts/{slug}"}
    r = await _request(client, "GET", urls[ats])
    if r is None or r.status_code != 200:
        return False
    try:
        d = r.json()
    except ValueError:
        return False
    if ats == "greenhouse":
        jobs = d.get("jobs") or []
        return bool(jobs) and (not verify_name or _same(jobs[0].get("company_name") or "", name))
    if ats == "lever":
        return isinstance(d, list) and bool(d)
    if ats == "ashby":
        return bool(d.get("jobs"))
    return bool(d.get("jobs")) and (not verify_name or _same(d.get("name") or "", name))


async def find_boards(client, company: dict) -> list[list[str]]:
    boards: dict[tuple, None] = {}
    site = company.get("website") or ""
    if site:
        base = site if site.startswith("http") else "https://" + site
        for path in ("", "/careers", "/jobs"):
            r = await _request(client, "GET", base.rstrip("/") + path, headers={"Accept": "text/html"})
            if r is None or r.status_code != 200:
                continue
            for href in set(re.findall(r'href=["\']([^"\']+)["\']', r.text)) | set(re.findall(r'https://[^\s"\'<>]+', r.text)):
                p = parse_ats_url(href)
                if p and p[1] and p[0] not in BIG_ATS:
                    boards[(p[0], p[1])] = None
            if boards:
                break
    if not boards and company.get("yc_slug"):
        boards[("ycjobs", company["yc_slug"])] = None     # YC startups list jobs on ycombinator.com
    elif not boards:
        # Guess the board name from the company name. Only exact full-name guesses, and one-word names
        # need 8+ letters: short common words ("Current", "Harbor") belong to other companies' boards.
        strict, _ = _slugs(company["name"])
        name = clean_name(company["name"])
        if " " in name.strip() or len(key_of(name)) >= 8:
            for ats in ("ashby", "greenhouse", "lever", "workable"):
                for slug in strict:
                    if await _probe(client, ats, slug, company["name"], verify_name=ats in ("greenhouse", "workable")):
                        boards[(ats, slug)] = None
                        break
    return [list(b) for b in boards]


# ------------------------------------------------------------------ data file

def load() -> dict:
    if OUT.exists():
        return json.loads(OUT.read_text())
    return {"meta": {}, "companies": {}}


def funded_boards() -> tuple[list[Board], dict[tuple[str, str], str]]:
    """Boards of recently funded companies for the hourly run, plus a funding label per board."""
    data, boards, labels = load(), [], {}
    cutoff = (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()
    for c in data["companies"].values():
        if c["date"] < cutoff:
            continue
        for ats, token in c.get("boards") or []:
            boards.append(Board(ats=ats, token=token, name=c["name"], tier="funded"))
            labels[(ats, token)] = f"{c['raised']} · {c['date'][:7]}"
    return boards, labels


async def main_async(args) -> None:
    t0 = time.time()
    today = date.today()
    start = today - timedelta(days=WINDOW_DAYS)
    data = load()
    companies: dict = data["companies"]
    found: list[dict] = []
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
                                 timeout=httpx.Timeout(20.0, connect=8.0), follow_redirects=True) as client:
        yc = await from_yc(client, today, start)
        print(f"Y Combinator: {len(yc)} US companies in batches with Demo Day since {start}")
        tc = await from_techcrunch(client, start)
        print(f"TechCrunch: {len(tc)} funding headlines")
        found += yc + tc
        contact = os.environ.get("SEC_CONTACT", "").strip()
        if contact:
            last = data["meta"].get("sec_last")
            since = max(start, date.fromisoformat(last) - timedelta(days=2)) if last else start
            if args.sec_days:
                since = today - timedelta(days=args.sec_days)
            sec = await from_sec(client, contact, since, today)
            print(f"SEC Form D: {len(sec)} tech/health-tech raises of $1M+ since {since}")
            found += sec
            if not args.sec_days:                       # a short test run must not skip the 6-month backfill
                data["meta"]["sec_last"] = today.isoformat()
        else:
            print("SEC Form D skipped (SEC_CONTACT not set)")

        for f in found:
            k = key_of(f["name"])
            if not k or len(k) < 3:
                continue
            old = companies.get(k)
            if old is None or f["date"] > old["date"]:
                companies[k] = {**(old or {}), **{x: f[x] for x in ("name", "source", "raised", "date") if x in f},
                                **({"yc_slug": f["yc_slug"]} if f.get("yc_slug") else {}),
                                "website": f["website"] or (old or {}).get("website", "")}

        cutoff = start.isoformat()
        for k in [k for k, c in companies.items() if c["date"] < cutoff]:
            del companies[k]
        recheck = (today - timedelta(days=RECHECK_DAYS)).isoformat()
        todo = [c for c in companies.values() if "checked" not in c or (not c.get("boards") and c["checked"] < recheck)]
        if args.limit:
            todo = todo[: args.limit]
        print(f"matching {len(todo)} companies to job boards ...")
        sem = asyncio.Semaphore(16)

        async def resolve(c):
            async with sem:
                try:
                    c["boards"] = await find_boards(client, c)
                except Exception:
                    c["boards"] = c.get("boards") or []
                c["checked"] = today.isoformat()
        await asyncio.gather(*(resolve(c) for c in todo))

    data["meta"]["updated"] = today.isoformat()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=0, sort_keys=True))
    with_boards = sum(1 for c in companies.values() if c.get("boards"))
    print(f"{len(companies)} funded companies in window, {with_boards} with job boards -> {OUT} ({time.time() - t0:.0f}s)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sec-days", type=int, default=0, help="only look back N days in SEC filings (testing)")
    p.add_argument("--limit", type=int, default=0, help="match at most N companies to boards this run (testing)")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()

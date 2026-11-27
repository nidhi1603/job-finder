"""Readers for the public job feeds of five applicant tracking systems.

Each reader turns one Board into a list of Job objects. Readers never raise on a bad
board: a dead or blocked board just returns [] so one company can't break a run.
"""
from __future__ import annotations

import asyncio
import logging
import random

import httpx

from .models import Board, Job
from .text import from_epoch_ms, html_to_text, now_utc, parse_iso, parse_workday_posted

log = logging.getLogger(__name__)

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 personal-job-finder")
WORKDAY_MAX_PAGES = 25      # 20 jobs a page, newest first
WORKDAY_MAX_AGE_DAYS = 15


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(25.0, connect=10.0),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        limits=httpx.Limits(max_connections=48, max_keepalive_connections=24),
        follow_redirects=True,
    )


async def _request(client: httpx.AsyncClient, method: str, url: str, **kw) -> httpx.Response | None:
    for attempt in range(3):
        try:
            r = await client.request(method, url, **kw)
        except (httpx.TransportError, httpx.TimeoutException) as e:
            log.debug("transport error %s %s", url, e)
            await asyncio.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            retry_after = r.headers.get("retry-after", "")
            wait = float(retry_after) if retry_after.isdigit() else 2.0 * (attempt + 1) + random.random()
            await asyncio.sleep(min(wait, 20))
            continue
        return r
    return None


async def _get_json(client, url, **kw):
    r = await _request(client, "GET", url, **kw)
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def _country_hint(code_or_name: str | None) -> str | None:
    if not code_or_name:
        return None
    v = code_or_name.strip().lower()
    if v in ("us", "usa", "united states", "united states of america", "u.s.", "u.s.a."):
        return "US"
    return "non-US"


# ---------------------------------------------------------------- Greenhouse
GH_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


async def greenhouse_list(client, board: Board) -> list[Job]:
    data = await _get_json(client, GH_API.format(token=board.token))
    if not data:
        return []
    jobs = data.get("jobs") or []
    out = []
    for j in jobs:
        first = j.get("first_published")
        out.append(Job(
            ats="greenhouse", board=board.token, job_id=str(j.get("id")),
            company=j.get("company_name") or board.name or board.token,
            title=j.get("title") or "", location=(j.get("location") or {}).get("name") or "",
            url=j.get("absolute_url") or "", posted_at=parse_iso(first or j.get("updated_at")),
            posted_exact=bool(first), needs_detail=True, board_size=len(jobs),
        ))
    return out


async def greenhouse_detail(client, job: Job) -> None:
    data = await _get_json(client, GH_API.format(token=job.board) + f"/{job.job_id}")
    if data:
        job.text = html_to_text(data.get("content") or "")


# ---------------------------------------------------------------- Lever
LEVER_API = "https://api.lever.co/v0/postings/{token}?mode=json"


async def lever_list(client, board: Board) -> list[Job]:
    data = await _get_json(client, LEVER_API.format(token=board.token))
    if not isinstance(data, list):
        return []
    out = []
    for p in data:
        cats = p.get("categories") or {}
        parts = [p.get("descriptionPlain") or html_to_text(p.get("description") or "")]
        for lst in p.get("lists") or []:
            parts.append(lst.get("text") or "")
            parts.append(html_to_text(lst.get("content") or ""))
        parts.append(p.get("additionalPlain") or "")
        locs = cats.get("allLocations") or [cats.get("location") or ""]
        out.append(Job(
            ats="lever", board=board.token, job_id=p.get("id") or "",
            company=board.name or board.token, title=p.get("text") or "",
            location=" | ".join(x for x in locs if x), url=p.get("hostedUrl") or "",
            posted_at=from_epoch_ms(p.get("createdAt")), country_hint=_country_hint(p.get("country")),
            employment_type=cats.get("commitment") or "", text="\n".join(x for x in parts if x),
            board_size=len(data),
        ))
    return out


# ---------------------------------------------------------------- Ashby
ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{token}"


async def ashby_list(client, board: Board) -> list[Job]:
    data = await _get_json(client, ASHBY_API.format(token=board.token))
    if not data:
        return []
    jobs = [j for j in data.get("jobs") or [] if j.get("isListed", True)]
    out = []
    for j in jobs:
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        locs = [j.get("location") or ""] + [s.get("location") or "" for s in j.get("secondaryLocations") or []]
        out.append(Job(
            ats="ashby", board=board.token, job_id=j.get("id") or "",
            company=board.name or board.token, title=j.get("title") or "",
            location=" | ".join(x for x in locs if x), url=j.get("jobUrl") or "",
            posted_at=parse_iso(j.get("publishedAt")), country_hint=_country_hint(addr.get("addressCountry")),
            employment_type=j.get("employmentType") or "",
            text=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml") or ""),
            board_size=len(jobs),
        ))
    return out


# ---------------------------------------------------------------- Workable
WORKABLE_API = "https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"


async def workable_list(client, board: Board) -> list[Job]:
    data = await _get_json(client, WORKABLE_API.format(token=board.token))
    if not data:
        return []
    jobs = data.get("jobs") or []
    out = []
    for j in jobs:
        locs = j.get("locations") or [{"country": j.get("country"), "city": j.get("city"), "region": j.get("state")}]
        loc_txt = " | ".join(", ".join(x for x in (l.get("city"), l.get("region"), l.get("country")) if x) for l in locs)
        codes = {(l.get("countryCode") or l.get("country") or "") for l in locs}
        hint = "US" if any(_country_hint(c) == "US" for c in codes if c) else (_country_hint(next(iter(codes), None)) if codes - {""} else None)
        text = "\n".join(html_to_text(j.get(k) or "") for k in ("description", "requirements", "benefits"))
        out.append(Job(
            ats="workable", board=board.token, job_id=j.get("shortcode") or "",
            company=data.get("name") or board.name or board.token, title=j.get("title") or "",
            location=loc_txt + (" | Remote" if j.get("telecommuting") else ""), url=j.get("url") or j.get("shortlink") or "",
            posted_at=parse_iso(j.get("published_on") or j.get("created_at")), posted_exact=True,
            country_hint=hint, employment_type=j.get("employment_type") or "", text=text, board_size=len(jobs),
        ))
    return out


# ---------------------------------------------------------------- Workday
async def workday_list(client, board: Board, window_days: int = WORKDAY_MAX_AGE_DAYS,
                       max_pages: int = WORKDAY_MAX_PAGES) -> list[Job]:
    """Newest-first pages; stops at the first page with nothing posted inside window_days.

    Hourly runs pass a 1-2 day window (only what's new since the last run), so a big
    company costs a page or two instead of 25.
    """
    host, tenant, site = board.token.split("|")
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    public = f"https://{host}/recruiting/{tenant}/{site}" if "myworkdaysite" in host else f"https://{host}/{site}"
    now = now_utc()
    out: list[Job] = []
    total = None
    for page in range(max_pages):
        body = {"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": ""}
        r = await _request(client, "POST", api, json=body, headers={"Content-Type": "application/json"})
        await asyncio.sleep(WORKDAY_DELAY)
        if r is None or r.status_code != 200:
            break
        try:
            d = r.json()
        except ValueError:
            break
        total = d.get("total") or total
        posts = d.get("jobPostings") or []
        if not posts:
            break
        page_has_fresh = False
        for p in posts:
            path = p.get("externalPath") or ""
            posted, days = parse_workday_posted(p.get("postedOn") or "", now)
            if days is None or days <= window_days:
                page_has_fresh = True
            out.append(Job(
                ats="workday", board=board.token, job_id=path, company=board.name or tenant,
                title=p.get("title") or "", location=p.get("locationsText") or "",
                url=public + path, posted_at=posted, posted_exact=False,
                needs_detail=True, detail_ref=path,
            ))
        if not page_has_fresh or (total and (page + 1) * 20 >= total):
            break
    for j in out:
        j.board_size = total or len(out)
    return out


async def workday_detail(client, job: Job) -> None:
    host, tenant, site = job.board.split("|")
    data = await _get_json(client, f"https://{host}/wday/cxs/{tenant}/{site}{job.detail_ref}")
    if not data:
        return
    info = data.get("jobPostingInfo") or {}
    job.text = html_to_text(info.get("jobDescription") or "")
    start = parse_iso(info.get("startDate"))
    if start:
        job.posted_at, job.posted_exact = start, True
    country = (info.get("country") or {}).get("descriptor")
    if country:
        job.country_hint = _country_hint(country)
    extra = info.get("additionalLocations") or []
    if info.get("location"):
        job.location = " | ".join([info["location"], *extra])
    job.employment_type = info.get("timeType") or job.employment_type


LISTERS = {
    "greenhouse": greenhouse_list,
    "lever": lever_list,
    "ashby": ashby_list,
    "workable": workable_list,
}
DETAILERS = {"greenhouse": greenhouse_detail, "workday": workday_detail}

# Workday serves every company from shared infrastructure and answers bursts with HTTP 429,
# so it gets its own small lane: a few companies at a time, a pause after every request.
WORKDAY_CONCURRENCY = 4
WORKDAY_DELAY = 0.4


def make_limits(concurrency: int = 32) -> dict[str, asyncio.Semaphore]:
    return {"default": asyncio.Semaphore(concurrency), "workday": asyncio.Semaphore(WORKDAY_CONCURRENCY)}


async def list_board(client, board: Board, limits: dict, window_days: int = WORKDAY_MAX_AGE_DAYS,
                     max_pages: int | None = None) -> list[Job]:
    sem = limits["workday" if board.ats == "workday" else "default"]
    async with sem:
        try:
            if board.ats == "workday":
                return await workday_list(client, board, window_days, max_pages or WORKDAY_MAX_PAGES)
            return await LISTERS[board.ats](client, board)
        except Exception as e:  # one broken board must not stop the run
            log.debug("board %s:%s failed: %s", board.ats, board.token, e)
            return []


async def fetch_detail(client, job: Job, limits: dict) -> None:
    fn = DETAILERS.get(job.ats)
    if not fn:
        return
    async with limits["workday" if job.ats == "workday" else "default"]:
        try:
            await fn(client, job)
        except Exception as e:
            log.debug("detail %s failed: %s", job.key, e)
        if job.ats == "workday":
            await asyncio.sleep(WORKDAY_DELAY)

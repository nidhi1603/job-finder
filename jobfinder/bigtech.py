"""Readers for big-company career sites and two enterprise ATSes (Oracle Recruiting Cloud, iCIMS).

All of these list newest jobs first, so each reader pages until it reaches jobs older than
`window_days` (15 on a catch-up run, ~2 on hourly runs) or `max_pages`.
Meta is deliberately absent: metacareers.com blocks automated access.
"""
from __future__ import annotations

import asyncio
import html as htmllib
import json
import re
from datetime import datetime, timedelta, timezone

from .models import Board, Job
from .text import html_to_text, now_utc, parse_iso

PAGE_DELAY = 0.3

# Single-company boards checked every run. token is what each reader needs.
BIGTECH_BOARDS = [
    Board("amazon", "amazon", "Amazon", "bigtech"),
    Board("apple", "apple", "Apple", "bigtech"),
    Board("microsoft", "microsoft.com", "Microsoft", "bigtech"),
    Board("google", "google", "Google", "bigtech"),
    Board("tiktok", "tiktok", "TikTok", "bigtech"),
    Board("ibm", "ibm", "IBM", "bigtech"),
    Board("oraclecloud", "eeho.fa.us2.oraclecloud.com|CX_45001", "Oracle", "bigtech"),
    Board("oraclecloud", "jpmc.fa.oraclecloud.com|CX_1001", "JPMorgan Chase", "bigtech"),
]


def _old(posted: datetime | None, now: datetime, window_days: int) -> bool:
    return bool(posted and (now - posted) > timedelta(days=window_days))


def _section(title: str, body_html: str) -> str:
    body = html_to_text(body_html or "")
    return f"{title}:\n{body}" if body else ""


async def _get_json(client, url, **kw):
    from .sources import _request
    r = await _request(client, "GET", url, **kw)
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


async def _post_json(client, url, body, headers=None):
    from .sources import _request
    r = await _request(client, "POST", url, json=body, headers={"Content-Type": "application/json", **(headers or {})})
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


# ---------------------------------------------------------------- Amazon
AMAZON_CATEGORIES = ["software-development", "machine-learning-science", "data-science", "research-science", "business-intelligence"]


async def amazon_list(client, board: Board, window_days: int, max_pages: int) -> list[Job]:
    now, out = now_utc(), []
    cats = "".join(f"&category%5B%5D={c}" for c in AMAZON_CATEGORIES)
    for page in range(max_pages):
        d = await _get_json(client, "https://www.amazon.jobs/en/search.json?base_query=&loc_query=United%20States"
                                    f"&country=USA&result_limit=100&offset={page * 100}&sort=recent{cats}")
        await asyncio.sleep(PAGE_DELAY)
        jobs = (d or {}).get("jobs") or []
        if not jobs:
            break
        page_fresh = False
        for j in jobs:
            try:
                posted = datetime.strptime(j.get("posted_date", ""), "%B %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                posted = None
            page_fresh |= not _old(posted, now, window_days)
            text = "\n".join(x for x in (html_to_text(j.get("description") or ""),
                                          _section("Basic Qualifications", j.get("basic_qualifications")),
                                          _section("Preferred Qualifications", j.get("preferred_qualifications"))) if x)
            out.append(Job(
                ats="amazon", board="amazon", job_id=str(j.get("id_icims") or j.get("id")), company="Amazon",
                title=j.get("title") or "", location=j.get("normalized_location") or j.get("location") or "",
                url="https://www.amazon.jobs" + (j.get("job_path") or ""), posted_at=posted, country_hint="US",
                employment_type="Intern" if j.get("is_intern") else (j.get("job_schedule_type") or ""), text=text,
                board_size=d.get("hits") or 0,
            ))
        if not page_fresh:
            break
    return out


# ---------------------------------------------------------------- Apple
async def apple_list(client, board: Board, window_days: int, max_pages: int) -> list[Job]:
    from .sources import _request
    r = await _request(client, "GET", "https://jobs.apple.com/api/v1/CSRFToken")
    token = r.headers.get("x-apple-csrf-token") if r is not None else None
    if not token:
        return []
    hdr = {"x-apple-csrf-token": token}
    now, out = now_utc(), []
    for page in range(1, max_pages + 1):
        body = {"query": "", "filters": {"locations": ["postLocation-USA"]}, "page": page, "locale": "en-us",
                "sort": "newest", "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"}}
        d = await _post_json(client, "https://jobs.apple.com/api/v1/search", body, hdr)
        await asyncio.sleep(PAGE_DELAY)
        res = (d or {}).get("res") or {}
        rows = res.get("searchResults") or []
        if not rows:
            break
        page_fresh = False
        for j in rows:
            posted = parse_iso(j.get("postDateInGMT"))
            page_fresh |= not _old(posted, now, window_days)
            locs = j.get("locations") or []
            loc = " | ".join(", ".join(x for x in (l.get("city"), l.get("stateProvince"), l.get("countryName")) if x) for l in locs)
            out.append(Job(
                ats="apple", board="apple", job_id=str(j.get("positionId") or j.get("id")), company="Apple",
                title=j.get("postingTitle") or "", location=loc or "United States",
                url=f"https://jobs.apple.com/en-us/details/{j.get('positionId')}/{j.get('transformedPostingTitle') or ''}",
                posted_at=posted, country_hint="US", text=j.get("jobSummary") or "", needs_detail=True,
                detail_ref=token, board_size=res.get("totalRecords") or 0,
            ))
        if not page_fresh:
            break
    return out


async def apple_detail(client, job: Job) -> None:
    d = await _get_json(client, f"https://jobs.apple.com/api/v1/jobDetails/{job.job_id}?locale=en-us",
                        headers={"x-apple-csrf-token": job.detail_ref})
    r = (d or {}).get("res") or {}
    if r:
        job.text = "\n".join(x for x in (html_to_text(r.get("jobSummary") or ""), html_to_text(r.get("description") or ""),
                                          _section("Minimum Qualifications", r.get("minimumQualifications")),
                                          _section("Preferred Qualifications", r.get("preferredQualifications"))) if x)


# ---------------------------------------------------------------- Microsoft (Eightfold)
MS_API = "https://apply.careers.microsoft.com/api/pcsx"


MS_QUERIES = ["software engineer", "machine learning", "data scientist", "applied scientist", "research", "AI engineer", "data analyst"]


async def microsoft_list(client, board: Board, window_days: int, max_pages: int) -> list[Job]:
    """Eightfold returns 10 jobs a page, so search the target families separately instead of paging everything."""
    from urllib.parse import quote
    out, seen = [], set()
    for q in MS_QUERIES:
        for job in await _microsoft_query(client, board, quote(q), window_days, min(max_pages, 15)):
            if job.job_id not in seen:
                seen.add(job.job_id)
                out.append(job)
    return out


async def _microsoft_query(client, board: Board, query: str, window_days: int, max_pages: int) -> list[Job]:
    now, out, start = now_utc(), [], 0
    for _ in range(max_pages):
        d = await _get_json(client, f"{MS_API}/search?domain={board.token}&query={query}&location=United%20States&start={start}&sort_by=timestamp")
        await asyncio.sleep(PAGE_DELAY)
        data = (d or {}).get("data") or {}
        rows = data.get("positions") or []
        if not rows:
            break
        page_fresh = False
        for p in rows:
            posted = datetime.fromtimestamp(int(p["postedTs"]), tz=timezone.utc) if p.get("postedTs") else None
            page_fresh |= not _old(posted, now, window_days)
            out.append(Job(
                ats="microsoft", board=board.token, job_id=str(p.get("displayJobId") or p.get("id")), company="Microsoft",
                title=p.get("name") or "", location=" | ".join(p.get("standardizedLocations") or p.get("locations") or []),
                url=f"https://apply.careers.microsoft.com/careers/job/{p.get('id')}", posted_at=posted,
                country_hint="US" if any("United States" in x or x.endswith(", US") for x in (p.get("locations") or []) + (p.get("standardizedLocations") or [])) else None,
                needs_detail=True, detail_ref=str(p.get("id")), board_size=data.get("count") or 0,
            ))
        start += len(rows)
        if not page_fresh:
            break
    return out


async def microsoft_detail(client, job: Job) -> None:
    d = await _get_json(client, f"{MS_API}/position_details?position_id={job.detail_ref}&domain={job.board}&hl=en")
    data = (d or {}).get("data") or {}
    if data:
        job.text = html_to_text(data.get("jobDescription") or "")


# ---------------------------------------------------------------- Google (early-career roles)
GOOGLE_RESULTS = ("https://www.google.com/about/careers/applications/jobs/results"
                  "?location=United%20States&target_level=EARLY&sort_by=date")
_GOOGLE_DATA = re.compile(r"AF_initDataCallback\(\{key: 'ds:1'.*?data:(\[.*?\]), sideChannel", re.S)


async def google_list(client, board: Board, window_days: int, max_pages: int) -> list[Job]:
    from .sources import _request
    now, out = now_utc(), []
    for page in range(1, max_pages + 1):
        r = await _request(client, "GET", GOOGLE_RESULTS + (f"&page={page}" if page > 1 else ""), headers={"Accept": "text/html"})
        await asyncio.sleep(PAGE_DELAY)
        m = _GOOGLE_DATA.search(r.text) if r is not None and r.status_code == 200 else None
        if not m:
            break
        try:
            data = json.loads(m.group(1))
        except ValueError:
            break
        rows = data[0] or []
        if not rows:
            break
        page_fresh = False
        for j in rows:
            ts = j[12][0] if len(j) > 12 and isinstance(j[12], list) and j[12] else None
            posted = datetime.fromtimestamp(ts, tz=timezone.utc) if isinstance(ts, int) else None
            page_fresh |= not _old(posted, now, window_days)
            locs = [l[0] for l in (j[9] or []) if l]
            def part(i):
                v = j[i] if len(j) > i else None
                return v[1] if isinstance(v, list) and len(v) > 1 and isinstance(v[1], str) else ""
            text = "\n".join(x for x in (html_to_text(part(10)), html_to_text(part(3)), html_to_text(part(4))) if x)
            slug = re.sub(r"[^a-z0-9]+", "-", (j[1] or "").lower()).strip("-")
            out.append(Job(
                ats="google", board="google", job_id=str(j[0]), company="Google", title=j[1] or "",
                location=" | ".join(locs), url=f"https://www.google.com/about/careers/applications/jobs/results/{j[0]}-{slug}",
                posted_at=posted, country_hint="US", text=text, board_size=data[2] if len(data) > 2 and isinstance(data[2], int) else 0,
            ))
        if not page_fresh or len(rows) < 20:
            break
    return out


# ---------------------------------------------------------------- TikTok
TIKTOK_API = "https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts"
TIKTOK_KEYWORDS = ["software engineer", "machine learning", "data scientist", "research scientist", "graduate", "AI engineer"]


def _country(city: dict | None) -> str:
    while city and city.get("parent"):
        city = city["parent"]
    return (city or {}).get("en_name") or ""


async def tiktok_list(client, board: Board, window_days: int, max_pages: int) -> list[Job]:
    """TikTok's feed has no posting date; the job's first-seen time stands in for it."""
    out, seen = [], set()
    for kw in TIKTOK_KEYWORDS:
        for page in range(min(max_pages, 3)):
            body = {"recruitment_id_list": [], "job_category_id_list": [], "subject_id_list": [], "location_code_list": [],
                    "keyword": kw, "limit": 50, "offset": page * 50}
            d = await _post_json(client, TIKTOK_API, body, {"website-path": "tiktok"})
            await asyncio.sleep(PAGE_DELAY)
            rows = ((d or {}).get("data") or {}).get("job_post_list") or []
            for j in rows:
                if j.get("id") in seen:
                    continue
                seen.add(j.get("id"))
                country = _country(j.get("city_info"))
                if country and "United States" not in country:
                    continue
                city = (j.get("city_info") or {}).get("en_name") or ""
                out.append(Job(
                    ats="tiktok", board="tiktok", job_id=str(j.get("id")), company="TikTok", title=j.get("title") or "",
                    location=f"{city}, United States" if city else "United States", url=f"https://lifeattiktok.com/search/{j.get('id')}",
                    posted_at=None, posted_exact=False, country_hint="US",
                    text=f"{j.get('description') or ''}\n{j.get('requirement') or ''}", board_size=500,
                ))
            if len(rows) < 50:
                break
    return out


# ---------------------------------------------------------------- IBM
async def ibm_list(client, board: Board, window_days: int, max_pages: int) -> list[Job]:
    """IBM's API gives only a short description (job pages are bot-protected), so jobs carry a flag."""
    now, out = now_utc(), []
    for page in range(max_pages):
        body = {"appId": "careers", "scopes": ["careers2"], "query": {"bool": {"must": []}},
                "post_filter": {"bool": {"must": [{"term": {"field_keyword_05": "United States"}}]}},
                "size": 100, "from": page * 100, "sort": [{"dcdate": "desc"}], "lang": "zz", "sm": {"query": "", "lang": "zz"},
                "_source": ["title", "url", "description", "dcdate", "field_keyword_18", "field_keyword_19"]}
        d = await _post_json(client, "https://www-api.ibm.com/search/api/v2", body)
        await asyncio.sleep(PAGE_DELAY)
        hits = ((d or {}).get("hits") or {}).get("hits") or []
        if not hits:
            break
        total = (d["hits"].get("total") or {}).get("value", 0)
        page_fresh = False
        for h in hits:
            s = h.get("_source") or {}
            posted = parse_iso(s.get("dcdate"))
            page_fresh |= not _old(posted, now, window_days)
            m = re.search(r"jobId=(\d+)", s.get("url") or "")
            out.append(Job(
                ats="ibm", board="ibm", job_id=m.group(1) if m else h.get("_id", ""), company="IBM", title=s.get("title") or "",
                location=f"{s.get('field_keyword_19') or ''}, United States", url=s.get("url") or "", posted_at=posted,
                country_hint="US", employment_type=s.get("field_keyword_18") or "", text=s.get("description") or "", board_size=total,
            ))
        if not page_fresh:
            break
    return out


# ---------------------------------------------------------------- Oracle Recruiting Cloud (Oracle, JPMorgan, ...)
async def oraclecloud_list(client, board: Board, window_days: int, max_pages: int) -> list[Job]:
    host, site = board.token.split("|")
    api = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    # Each Oracle site has its own id for the "United States" location facet; look it up first.
    f = await _get_json(client, f"{api}?onlyData=true&expand=requisitionList&finder=findReqs;siteNumber={site},facetsList=LOCATIONS,limit=1")
    facets = (((f or {}).get("items") or [{}])[0].get("locationsFacet")) or []
    us = next((x.get("Id") for x in facets if (x.get("Name") or "").strip() == "United States"), None)
    us_filter = f",selectedLocationsFacet={us}" if us else ""
    now, out = now_utc(), []
    for page in range(max_pages):
        d = await _get_json(client, f"{api}?onlyData=true&expand=requisitionList.secondaryLocations"
                                    f"&finder=findReqs;siteNumber={site},limit=25,offset={page * 25},sortBy=POSTING_DATES_DESC{us_filter}")
        await asyncio.sleep(0.4)
        items = (d or {}).get("items") or []
        reqs = items[0].get("requisitionList") or [] if items else []
        if not reqs:
            break
        total = items[0].get("TotalJobsCount") or 0
        page_fresh = False
        for r in reqs:
            posted = parse_iso(r.get("PostedDate"))
            page_fresh |= not _old(posted, now, window_days)
            locs = [r.get("PrimaryLocation") or ""] + [s.get("Name") or "" for s in r.get("secondaryLocations") or []]
            out.append(Job(
                ats="oraclecloud", board=board.token, job_id=str(r.get("Id")), company=board.name or host.split(".")[0],
                title=r.get("Title") or "", location=" | ".join(x for x in locs if x),
                url=f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{r.get('Id')}", posted_at=posted,
                country_hint="US" if r.get("PrimaryLocationCountry") == "US" else ("non-US" if r.get("PrimaryLocationCountry") else None),
                text=r.get("ShortDescriptionStr") or "", needs_detail=True, board_size=total,
            ))
        if not page_fresh or (page + 1) * 25 >= total:
            break
    return out


async def oraclecloud_detail(client, job: Job) -> None:
    host, site = job.board.split("|")
    d = await _get_json(client, f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
                                f"?expand=all&onlyData=true&finder=ById;Id=%22{job.job_id}%22,siteNumber={site}")
    items = (d or {}).get("items") or []
    if items:
        it = items[0]
        job.text = "\n".join(x for x in (html_to_text(it.get("ExternalDescriptionStr") or ""),
                                          _section("Qualifications", it.get("ExternalQualificationsStr"))) if x)


# ---------------------------------------------------------------- iCIMS (many companies)
_ICIMS_CARD = re.compile(r'<a[^>]+href="(https://[^"]+?/jobs/(\d+)/[^"?]+/job)[^"]*"[^>]*>\s*(?:<span[^>]*>[^<]*</span>\s*)?<h3[^>]*>(.*?)</h3>', re.S)
_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


async def icims_list(client, board: Board, window_days: int, max_pages: int) -> list[Job]:
    """iCIMS list pages show title only (newest IDs first); date, location and text come from each job page."""
    from .sources import _request
    out, seen = [], set()
    for page in range(max_pages):
        r = await _request(client, "GET", f"https://{board.token}/jobs/search?ss=1&in_iframe=1&pr={page}", headers={"Accept": "text/html"})
        await asyncio.sleep(0.4)
        if r is None or r.status_code != 200:
            break
        cards = _ICIMS_CARD.findall(r.text)
        new = [c for c in cards if c[1] not in seen]
        if not new:
            break
        for url, jid, title_html in new:
            seen.add(jid)
            out.append(Job(
                ats="icims", board=board.token, job_id=jid, company=board.name or board.token.split(".")[0],
                title=htmllib.unescape(re.sub(r"<[^>]+>", "", title_html)).strip(), location="", url=url,
                posted_at=None, needs_detail=True,
            ))
    for j in out:
        j.board_size = len(out)
    return out


async def icims_detail(client, job: Job) -> None:
    from .sources import _request
    r = await _request(client, "GET", job.url + "?in_iframe=1", headers={"Accept": "text/html"})
    if r is None or r.status_code != 200:
        return
    for raw in _LD.findall(r.text):
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get("@type") != "JobPosting":
            continue
        job.text = html_to_text(d.get("description") or "")
        job.posted_at = parse_iso(d.get("datePosted"))
        locs = d.get("jobLocation") or []
        locs = locs if isinstance(locs, list) else [locs]
        parts, countries = [], set()
        for l in locs:
            a = (l or {}).get("address") or {}
            parts.append(", ".join(x for x in (a.get("addressLocality"), a.get("addressRegion"), a.get("addressCountry")) if x))
            if a.get("addressCountry"):
                countries.add(a["addressCountry"])
        job.location = " | ".join(p for p in parts if p)
        if countries:
            job.country_hint = "US" if countries & {"US", "USA", "United States"} else "non-US"
        org = (d.get("hiringOrganization") or {}).get("name")
        if org:
            job.company = org
        return


# ---------------------------------------------------------------- Y Combinator startups (Work at a Startup)
_DATA_PAGE = re.compile(r'data-page="([^"]+)"')
_REL = re.compile(r"(\d+|a|an)\s+(minute|hour|day|week|month|year)s?", re.I)
_UNIT_DAYS = {"minute": 1 / 1440, "hour": 1 / 24, "day": 1, "week": 7, "month": 30, "year": 365}


def _relative(label: str, now: datetime) -> datetime | None:
    """'about 1 month' / '3 days' / 'about 2 hours' -> approximate datetime."""
    m = _REL.search(label or "")
    if not m:
        return now if "less than" in (label or "") else None
    n = 1 if m.group(1).lower() in ("a", "an") else int(m.group(1))
    return now - timedelta(days=n * _UNIT_DAYS[m.group(2).lower()])


def _yc_text(j: dict) -> str:
    visa = j.get("visa") or ""
    visa_line = ("Visa sponsorship is not available (US citizen/visa only)." if "only" in visa.lower()
                 else "Visa sponsorship is available." if "sponsor" in visa.lower() else "")
    return "\n".join(x for x in (
        f"Minimum experience: {j['minExperience']} of experience" if j.get("minExperience") and j["minExperience"] != "Any (new grads ok)"
        else "New grads ok" if j.get("minExperience") else "",
        visa_line, f"Salary: {j['salaryRange']}" if j.get("salaryRange") else "", j.get("description") or "") if x)


async def ycjobs_list(client, board: Board, window_days: int, max_pages: int) -> list[Job]:
    from .sources import _request
    r = await _request(client, "GET", f"https://www.ycombinator.com/companies/{board.token}/jobs", headers={"Accept": "text/html"})
    m = _DATA_PAGE.search(r.text) if r is not None and r.status_code == 200 else None
    if not m:
        return []
    props = json.loads(htmllib.unescape(m.group(1))).get("props") or {}
    now, out = now_utc(), []
    posts = props.get("jobPostings") or []
    for j in posts:
        out.append(Job(
            ats="ycjobs", board=board.token, job_id=str(j.get("id")), company=j.get("companyName") or board.name,
            title=j.get("title") or "", location=j.get("location") or "", url="https://www.ycombinator.com" + (j.get("url") or ""),
            posted_at=_relative(j.get("createdAt") or "", now), posted_exact=False, employment_type=j.get("type") or "",
            text=_yc_text(j), needs_detail=True, detail_ref=j.get("url") or "", board_size=len(posts),
        ))
    return out


async def ycjobs_detail(client, job: Job) -> None:
    from .sources import _request
    r = await _request(client, "GET", "https://www.ycombinator.com" + job.detail_ref, headers={"Accept": "text/html"})
    m = _DATA_PAGE.search(r.text) if r is not None and r.status_code == 200 else None
    if m:
        j = (json.loads(htmllib.unescape(m.group(1))).get("props") or {}).get("job") or {}
        if j:
            job.text = _yc_text(j)


PAGED_LISTERS = {
    "ycjobs": ycjobs_list,
    "amazon": amazon_list, "apple": apple_list, "microsoft": microsoft_list, "google": google_list,
    "tiktok": tiktok_list, "ibm": ibm_list, "oraclecloud": oraclecloud_list, "icims": icims_list,
}
BIG_DETAILERS = {"ycjobs": ycjobs_detail, "apple": apple_detail, "microsoft": microsoft_detail, "oraclecloud": oraclecloud_detail, "icims": icims_detail}

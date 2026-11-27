"""Your job tracker: a private Google Sheet that a small Apps Script web app (tracker/Code.gs) writes to.

Two secrets connect it: SHEET_URL (the web app's .../exec link) and SHEET_SECRET (the same value as SECRET
in the script). Nothing about you is stored in this repo: rows live only in your sheet.
"""
from __future__ import annotations

import os

import httpx

from .models import Job
from .scoring import crowd_label, fit_band

GROUP = {0: "Strong", 1: "Good", 2: "Other"}
CHUNK = 150                      # rows per request, well inside Apps Script's time limit


def configured() -> bool:
    return bool(os.environ.get("SHEET_URL", "").strip() and os.environ.get("SHEET_SECRET", "").strip())


def group_of(job: Job) -> str:
    return "Funded" if job.funding else GROUP[fit_band(job)]


def job_row(j: Job) -> dict:
    flags = []
    if j.funding:
        flags.append("💰 " + j.funding)
    flags += [f"★ {b}" for b in j.boosts[:1]]
    if j.min_yoe:
        flags.append(f"asks {j.min_yoe}+ yrs")
    flags += j.flags
    return {
        "key": j.key, "company": j.company, "title": j.title, "url": j.url, "location": j.location[:250],
        "posted": j.posted_at.strftime("%Y-%m-%d") if j.posted_at else "",
        "fit": j.fit, "group": group_of(j),
        "matched": ", ".join(j.matched), "missing": ", ".join(j.missing[:12]),
        "flags": " · ".join(flags), "crowd": crowd_label(j.crowd),
    }


def _post(payload: dict, timeout: float = 180) -> dict | None:
    try:
        r = httpx.post(os.environ["SHEET_URL"].strip(), json={**payload, "secret": os.environ["SHEET_SECRET"].strip()},
                       follow_redirects=True, timeout=timeout)   # Apps Script answers with a redirect
        d = r.json()
    except Exception as e:      # network error, or Google returned an HTML error page
        print(f"tracker sheet unreachable: {type(e).__name__}: {str(e)[:200]}")
        return None
    if not d.get("ok"):
        print(f"tracker sheet error: {d.get('error')}")
        return None
    return d


def add_jobs(jobs: list[Job]) -> dict | None:
    """Adds the jobs the sheet doesn't have yet. Returns {added, url, annotations: {key: note}}, or None if it failed.

    annotations holds notes such as "You applied here Nov 28" for companies you already applied to.
    """
    out = {"added": 0, "annotations": {}, "url": ""}
    rows = [job_row(j) for j in jobs]
    for i in range(0, max(len(rows), 1), CHUNK):
        d = _post({"action": "add", "jobs": rows[i:i + CHUNK]})
        if d is None:
            return None
        out["added"] += d.get("added", 0)
        out["annotations"].update(d.get("annotations") or {})
        out["url"] = d.get("url") or out["url"]
    return out


def summary(since_iso: str) -> dict | None:
    """Rows found since `since_iso` (with their current Status) and application counts, for the morning email."""
    return _post({"action": "summary", "since": since_iso})

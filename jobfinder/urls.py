"""Recognise ATS job/board URLs: (ats, board_token, job_id)."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

_LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")


def parse_ats_url(url: str) -> tuple[str, str | None, str | None] | None:
    try:
        u = urlparse(url.strip())
    except ValueError:
        return None
    host = (u.netloc or "").lower().split(":")[0]
    parts = [unquote(p) for p in u.path.split("/") if p]
    q = parse_qs(u.query)

    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io", "boards-api.greenhouse.io"):
        if parts and parts[0] == "embed":
            tok = (q.get("for") or [None])[0]
            jid = (q.get("token") or [None])[0]
            return ("greenhouse", tok.lower() if tok else None, jid) if tok else None
        if parts and parts[0] == "v1" and len(parts) > 2:
            parts = parts[2:]
        if not parts:
            return None
        jid = parts[2] if len(parts) > 2 and parts[1] == "jobs" and parts[2].isdigit() else None
        return ("greenhouse", parts[0].lower(), jid)
    if "gh_jid" in q:
        return ("greenhouse", None, q["gh_jid"][0])

    if host == "jobs.lever.co" and parts:
        jid = parts[1] if len(parts) > 1 and re.fullmatch(r"[0-9a-f-]{36}", parts[1]) else None
        return ("lever", parts[0].lower(), jid)

    if host == "jobs.ashbyhq.com" and parts:
        jid = parts[1] if len(parts) > 1 and re.fullmatch(r"[0-9a-f-]{36}", parts[1]) else None
        return ("ashby", parts[0], jid)

    if host == "apply.workable.com" and parts:
        if parts[0] == "j":
            return ("workable", None, parts[1] if len(parts) > 1 else None)
        if parts[0] in ("api", "careers"):
            return None
        jid = parts[2] if len(parts) > 2 and parts[1] == "j" else None
        return ("workable", parts[0].lower(), jid)

    if host.endswith(".myworkdayjobs.com") and parts:
        tenant = host.split(".")[0]
        if _LOCALE.match(parts[0]):
            parts = parts[1:]
        if not parts or parts[0] in ("wday", "login"):
            return None
        site = parts[0]
        jid = None
        if "job" in parts:
            i = parts.index("job")
            jid = "/" + "/".join(parts[i:])
            jid = re.sub(r"/apply(/.*)?$", "", jid)
        return ("workday", f"{host}|{tenant}|{site}", jid)

    if host.endswith(".icims.com") and host not in ("www.icims.com", "icims.com") and not host.startswith(("community.", "developer.")):
        m = re.search(r"/jobs/(\d+)", u.path)
        return ("icims", host, m.group(1) if m else None)

    if re.fullmatch(r"[a-z0-9-]+\.fa(\.[a-z0-9-]+)?\.oraclecloud\.com", host) and "CandidateExperience" in u.path:
        m = re.search(r"/sites/([A-Za-z0-9_]+)", u.path)
        if m:
            j = re.search(r"/job/(\d+)", u.path)
            return ("oraclecloud", f"{host}|{m.group(1)}", j.group(1) if j else None)
        return None

    # Big-company sites (used to spot their jobs on the SimplifyJobs list)
    if host.endswith("amazon.jobs"):
        m = re.search(r"/jobs/(\d+)", u.path)
        return ("amazon", "amazon", m.group(1) if m else None)
    if host == "jobs.apple.com":
        m = re.search(r"/details/(\d+)", u.path)
        return ("apple", "apple", m.group(1) if m else None)
    if host.endswith("careers.microsoft.com"):
        m = re.search(r"/job/(\d+)", u.path)
        return ("microsoft", "microsoft.com", m.group(1) if m else None)
    if host in ("www.google.com", "careers.google.com") and "careers" in u.path:
        m = re.search(r"/results/(\d+)", u.path)
        return ("google", "google", m.group(1) if m else None)
    if host.endswith("lifeattiktok.com"):
        m = re.search(r"/search/(\d+)", u.path)
        return ("tiktok", "tiktok", m.group(1) if m else None)

    if re.fullmatch(r"wd\d+\.myworkdaysite\.com", host) and len(parts) >= 3 and parts[0] == "recruiting":
        tenant, site = parts[1], parts[2]
        jid = None
        if "job" in parts:
            i = parts.index("job")
            jid = re.sub(r"/apply(/.*)?$", "", "/" + "/".join(parts[i:]))
        return ("workday", f"{host}|{tenant}|{site}", jid)
    return None


def match_id(ats: str, token: str | None, job_id: str | None) -> str | None:
    """ID used to spot the same job on the SimplifyJobs list (board token may be missing there)."""
    if not job_id:
        return None
    if ats == "workday" and token:
        return f"workday:{token.split('|')[1]}:{job_id.lower()}"
    return f"{ats}:{job_id.lower()}"

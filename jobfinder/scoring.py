"""Fit score (keyword match against your skills) and crowding estimate."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from .filters import split_sections
from .models import Job
from .skills import detect

ROOT = Path(__file__).resolve().parent.parent


# Knowing the left side implies the right side (TypeScript means you can read and write JavaScript, etc.).
IMPLIED = {
    "TypeScript": {"JavaScript"}, "React": {"JavaScript"}, "Next.js": {"JavaScript", "React"}, "Node.js": {"JavaScript"},
    "FastAPI": {"REST APIs"}, "Flask": {"REST APIs"}, "Django": {"REST APIs"},
    "PostgreSQL": {"SQL"}, "MySQL": {"SQL"}, "LoRA/QLoRA": {"Fine-tuning"},
    "LangChain": {"LLMs"}, "LangGraph": {"LLMs"}, "LlamaIndex": {"LLMs"},
}
# Words that appear in almost every posting ("security", "monitoring", "systems design"); they say little
# about fit, so they don't count toward the score either way.
NON_SCORING = {"Security", "Observability", "System Design"}


def with_implied(skills: set[str]) -> set[str]:
    out = set(skills)
    for s in skills:
        out |= IMPLIED.get(s, set())
    return out


def load_profile() -> set[str]:
    """Your skills: PROFILE_SKILLS env/secret (comma-separated), else profile.local.json."""
    raw = os.environ.get("PROFILE_SKILLS", "").strip()
    if raw:
        return with_implied({s.strip() for s in raw.split(",") if s.strip()})
    local = ROOT / "profile.local.json"
    if local.exists():
        return with_implied(set(json.loads(local.read_text())["skills"]))
    raise SystemExit("No profile: set PROFILE_SKILLS or create profile.local.json (python -m jobfinder.profile <resume>)")


def score_fit(job: Job, profile: set[str]) -> None:
    required, preferred = split_sections(job.text or "")
    req = detect(required) - NON_SCORING
    pref = detect(preferred) - req - NON_SCORING
    if not req and not pref:
        job.fit = None
        return
    hit_req, hit_pref = req & profile, pref & profile
    hits, total = 2 * len(hit_req) + len(hit_pref), 2 * len(req) + len(pref)
    job.fit = round(100 * hits / total)
    job.fit_rank = 100 * hits / (total + 4)      # 2/2 skills ranks below 9/10 skills
    job.skills_total = len(req) + len(pref)
    job.matched = sorted(hit_req) + sorted(hit_pref)
    job.missing = sorted(req - profile) + sorted(pref - profile)


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def score_crowd(job: Job, now: datetime, on_simplify: bool, reposted: bool) -> None:
    """0 = quiet, 100 = crowded. Heuristic, not a measured applicant count."""
    score, why = 0, []
    if job.posted_at:
        hours = (now - job.posted_at).total_seconds() / 3600
        for limit, pts in ((6, 0), (24, 10), (72, 25), (168, 40)):
            if hours <= limit:
                score += pts
                break
        else:
            score += 55
        if hours > 24:
            why.append(f"{int(hours // 24)}d old")
    size = job.board_size
    for limit, pts in ((20, 0), (100, 10), (500, 20)):
        if size < limit:
            score += pts
            break
    else:
        score += 30
    if size >= 100:
        why.append(f"big company ({size} open jobs)")
    if on_simplify:
        score += 25
        why.append("on SimplifyJobs new-grad list")
    if reposted:
        score += 10
        why.append("reposted")
    job.crowd = min(score, 100)
    job.crowd_reasons = why


def crowd_label(score: int) -> str:
    return "Low" if score < 30 else "Medium" if score < 55 else "High"


# ------------------------------------------------------------------ email order
BANDS = ["Strong fit", "Good fit", "Other matches"]


def fit_band(job: Job) -> int:
    """0 = strong (70%+ with at least 4 skills detected), 1 = good (50%+ with at least 3), 2 = everything else.

    The skill minimums stop a posting that names one skill you have from showing as a 100% fit."""
    if job.fit is None:
        return 2
    if job.fit >= 70 and job.skills_total >= 4:
        return 0
    if job.fit >= 50 and job.skills_total >= 3:
        return 1
    return 2


def order_jobs(jobs: list[Job]) -> list[Job]:
    """Recently funded startups first; then best fit band; inside each group the newest posting first."""
    return sorted(jobs, key=lambda j: (0 if j.funding else 1, fit_band(j), -(j.posted_at.timestamp() if j.posted_at else 0)))

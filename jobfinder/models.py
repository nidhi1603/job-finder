"""Data shapes shared by every module."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Board:
    """One company job board on one applicant tracking system (ATS)."""
    ats: str            # greenhouse | lever | ashby | workable | workday
    token: str          # board slug; for workday "host|tenant|site"
    name: str = ""      # company name if known
    tier: str = "broad"  # newgrad (from the SimplifyJobs list) | broad (web-crawl sweep)

    def to_dict(self) -> dict:
        return {"ats": self.ats, "token": self.token, "name": self.name, "tier": self.tier}


@dataclass
class Job:
    ats: str
    board: str
    job_id: str
    company: str
    title: str
    location: str
    url: str
    posted_at: datetime | None
    posted_exact: bool = True          # False when the ATS only gives "Posted 3 Days Ago"
    country_hint: str | None = None    # "US", "non-US" or None when the feed doesn't say
    employment_type: str = ""
    text: str = ""                     # plain-text job description
    needs_detail: bool = False         # description must be fetched separately
    detail_ref: str = ""
    board_size: int = 0                # open jobs on the board (company-size stand-in)

    # filled in by filters / scoring
    family: str = ""
    flags: list[str] = field(default_factory=list)
    boosts: list[str] = field(default_factory=list)
    min_yoe: int | None = None
    fit: int | None = None
    fit_rank: float = -1.0             # fit shrunk toward 0 when few skills were detected (for sorting)
    skills_total: int = 0
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    funding: str = ""                 # e.g. "$20M Series A (TechCrunch) · 2026-10" for recently funded startups
    crowd: int = 0
    crowd_reasons: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.ats}:{self.board}:{self.job_id}"

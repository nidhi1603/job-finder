"""What has already been evaluated or emailed (data/seen.json, saved to the "state" branch by the workflow).

Stores only job keys, dates and a status code: no scores, no profile data.
Status: e = emailed, s = added to the tracker sheet, f:<reason> = dropped by a rule, l = below the fit floor.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .models import Job
from .scoring import norm_title
from .text import parse_iso

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "seen.json"
KEEP_JOBS_DAYS = 21
KEEP_TITLES_DAYS = 90


class State:
    def __init__(self, jobs: dict | None = None, titles: dict | None = None, meta: dict | None = None):
        self.jobs: dict[str, list] = jobs or {}
        self.titles: dict[str, str] = titles or {}
        self.meta: dict = meta or {}
        self._titles_at_start = set(self.titles)

    @classmethod
    def load(cls) -> "State":
        if not PATH.exists():
            return cls()
        d = json.loads(PATH.read_text())
        return cls(d.get("jobs"), d.get("titles"), d.get("meta"))

    def is_empty(self) -> bool:
        return not self.jobs

    def __contains__(self, key: str) -> bool:
        return key in self.jobs

    @staticmethod
    def title_key(job: Job) -> str:
        return f"{job.ats}:{job.board}|{norm_title(job.title)}"

    def was_reposted(self, job: Job) -> bool:
        """Same company + same title seen in an earlier run under a different job id."""
        return self.title_key(job) in self._titles_at_start

    def mark(self, job: Job, status: str, now: datetime) -> None:
        self.jobs[job.key] = [now.strftime("%Y-%m-%dT%H:%MZ"), status]
        self.titles.setdefault(self.title_key(job), now.strftime("%Y-%m-%d"))

    def save(self, now: datetime) -> None:
        job_cut, title_cut = now - timedelta(days=KEEP_JOBS_DAYS), now - timedelta(days=KEEP_TITLES_DAYS)
        self.jobs = {k: v for k, v in self.jobs.items() if (parse_iso(v[0]) or now) >= job_cut}
        self.titles = {k: v for k, v in self.titles.items() if (parse_iso(v) or now) >= title_cut}
        self.meta["last_run"] = now.strftime("%Y-%m-%dT%H:%MZ")
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps({"meta": self.meta, "jobs": self.jobs, "titles": self.titles},
                                   separators=(",", ":"), sort_keys=True))

"""Hard rules (drop), flags (show) and boosts (rank higher)."""
from __future__ import annotations

import re
from datetime import datetime

from . import rules as R
from .models import Job

# ------------------------------------------------------------------ title & location


def title_family(title: str) -> str | None:
    if R.EXCLUDE_TITLE.search(title):
        return None
    for name, rx in R.TITLE_FAMILIES.items():
        if rx.search(title):
            return name
    return None


def is_intern(job: Job) -> bool:
    return bool(R.INTERN_TITLE.search(job.title) or re.search(r"intern", job.employment_type, re.I))


def location_class(location: str) -> str:
    """'US', 'non-US' or 'unknown' from a location string."""
    if R.US_STRONG.search(location) or R.US_TOKEN.search(location):
        return "US"            # multi-location jobs that include a US city are kept
    if R.NON_US_LOCATION.search(location) or R.CA_PROVINCE_ABBR.search(location):
        return "non-US"
    if R.US_ABBR_STRICT.search(location):
        return "US"
    return "unknown"


def job_location_class(job: Job) -> str:
    if job.country_hint == "US":
        return "US"
    cls = location_class(job.location)
    if cls == "unknown" and job.country_hint == "non-US":
        return "non-US"
    return cls


def mentions_us(text: str) -> bool:
    return bool(R.US_STRONG.search(text) or R.US_TOKEN.search(text) or R.US_ABBR_STRICT.search(text))


def prefilter(job: Job, now: datetime) -> str | None:
    """Cheap checks on list data. Returns a drop reason or None."""
    fam = title_family(job.title)
    if not fam:
        return "title"
    job.family = fam
    if R.SENIOR_TITLE.search(job.title):
        return "senior-title"
    if job_location_class(job) == "non-US":
        return "non-us"
    if job.posted_at and (now - job.posted_at).days > R.MAX_AGE_DAYS:
        return "too-old"
    return None


# ------------------------------------------------------------------ sections & years of experience


def split_sections(text: str) -> tuple[str, str]:
    """Return (required_text, preferred_text). Without headings, everything counts as required."""
    req, pref, kind, saw_req = [], [], "other", False
    for line in text.split("\n"):
        stripped = line.strip(" -•*:")
        bullet = line.lstrip().startswith(("-", "•", "*", "·"))
        is_heading = (not bullet and len(stripped) <= 80 and not re.search(r"\d", stripped)
                      and (line.rstrip().endswith(":") or len(stripped.split()) <= 5))
        if is_heading and R.PREFERRED_HDR.search(stripped):
            kind = "pref"
            continue
        if is_heading and R.REQUIRED_HDR.search(stripped):
            kind, saw_req = "req", True
            continue
        (pref if kind == "pref" else req).append(line)
    required = "\n".join(req)
    return (required if saw_req or req else text), "\n".join(pref)


_NUM = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_YOE = re.compile(
    rf"{_NUM}\s*\+?\s*(?:(?:-|–|—|to)\s*{_NUM}\s*\+?\s*)?(?:plus\s+)?(?:years?|yrs?)(?:'s)?\b"
    rf"(?![\s-]*(?:degree|program|college|university|old|bachelor|undergrad))", re.I)
_EXPERIENCE_AFTER = re.compile(r"experien|industry|professional|hands[- ]on|in (?:a |the )?(?:software|data|machine|ml|research)", re.I)


def _n(v: str) -> int:
    return int(v) if v.isdigit() else _WORDS[v.lower()]


def min_years_required(required_text: str) -> int | None:
    """Largest 'minimum years of experience' stated in the required section.

    Within one sentence, alternatives ("BS + 3 years or MS + 1 year") take the smallest;
    across sentences the strictest requirement wins.
    """
    best = None
    for sentence in re.split(r"\n+|(?<=[.;])\s+", required_text):
        mins = []
        for m in _YOE.finditer(sentence):
            after = sentence[m.end(): m.end() + 90]
            if not _EXPERIENCE_AFTER.search(after) and not _EXPERIENCE_AFTER.search(sentence[max(0, m.start() - 40): m.start()]):
                continue
            low = _n(m.group(1))
            if low > 20:
                continue
            mins.append(low)
        if mins:
            s = min(mins)
            best = s if best is None else max(best, s)
    return best


# ------------------------------------------------------------------ rules that need the description


def phd_only(title: str, required_text: str) -> bool:
    """A PhD is required (in the title or a non-'preferred' requirement) with no other degree route."""
    needs_phd = bool(R.PHD.search(title)) or any(
        R.PHD.search(s) and not R.NOT_REQUIRED_WORDS.search(s)
        for s in re.split(r"\n+|(?<=[.;])\s+", required_text))
    return needs_phd and not R.NON_PHD_ROUTE.search(title + "\n" + required_text)


def charges_candidates(text: str) -> bool:
    """The posting asks the candidate to pay a fee, deposit or bond (unless it says it doesn't)."""
    for m in R.FEE_TERMS.finditer(text):
        before = text[max(0, m.start() - 60): m.start()]
        if not R.FEE_NEGATION.search(before) and not re.match(r"\s*(?:is|are)?\s*(?:waived|covered|paid) by", text[m.end(): m.end() + 30], re.I):
            return True
    return False


def detail_rules(job: Job) -> str | None:
    text = job.text or ""
    if job_location_class(job) == "unknown" and not mentions_us(job.location + "\n" + text):
        return "location-unclear"
    if charges_candidates(text):
        return "charges-candidates"
    if R.CLEARANCE.search(text):
        return "clearance"
    if R.CITIZENSHIP.search(text):
        return "citizenship"
    if R.ENROLLED.search(text) and not R.RECENT_GRAD.search(text):
        return "enrolled-student"
    if is_intern(job) and not R.RECENT_GRAD.search(text):
        return "intern-no-recent-grads"
    required, _ = split_sections(text)
    if phd_only(job.title, required):
        return "phd-only"
    job.min_yoe = min_years_required(job.title + "\n" + required)   # titles like 'Data Scientist (3-5 years experience)'
    if job.min_yoe is not None and job.min_yoe > R.MAX_MIN_YOE:
        return "yoe"
    return None


def annotate(job: Job) -> None:
    text = job.text or ""
    if R.NO_SPONSOR.search(text):
        job.flags.append("No sponsorship")
    elif R.SPONSORS.search(text):
        job.flags.append("Sponsors visas")
    required, _ = split_sections(text)
    degrees = [name for name, rx in R.DEGREE if rx.search(required)]
    if degrees:
        job.flags.append("Degree: " + "/".join(reversed(degrees)))
    if is_intern(job):
        job.flags.append("Internship (accepts recent grads)")
    if R.AGENCY.search(text):
        job.flags.append("Agency (hiring for a client)")
    if R.TRAINING_PLACEMENT.search(text):
        job.flags.append("Training & placement program: check for fees")
    m = R.BOOST.search(job.title + "\n" + text)
    if m:
        job.boosts.append(m.group(0).strip())
